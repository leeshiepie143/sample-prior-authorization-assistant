"""
Policy metadata management for the Knowledge Base system.

This module handles metadata schema, indexing, and organization
of policy documents by payor, service type, and clinical area.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Set
from enum import Enum

from common.models import serialize_model, deserialize_model
from common.exceptions import DataValidationError
from common.validators import MedicalCodeValidator
from common.logging_config import get_logger
from common.utils import safe_json_dumps, safe_json_loads

logger = get_logger(__name__)


class PolicyType(Enum):
    """Types of policy documents"""
    MEDICAL_NECESSITY = "medical_necessity"
    COVERAGE_DETERMINATION = "coverage_determination"
    PRIOR_AUTHORIZATION = "prior_authorization"
    CLINICAL_GUIDELINE = "clinical_guideline"
    FORMULARY = "formulary"


class ClinicalArea(Enum):
    """Clinical specialty areas"""
    CARDIOLOGY = "cardiology"
    ORTHOPEDICS = "orthopedics"
    RADIOLOGY = "radiology"
    ONCOLOGY = "oncology"
    NEUROLOGY = "neurology"
    GASTROENTEROLOGY = "gastroenterology"
    PULMONOLOGY = "pulmonology"
    ENDOCRINOLOGY = "endocrinology"
    DERMATOLOGY = "dermatology"
    GENERAL_MEDICINE = "general_medicine"


@dataclass
class PolicyMetadata:
    """Metadata for policy documents in the knowledge base"""
    
    policy_id: str
    payor: str
    policy_title: str
    policy_type: PolicyType
    clinical_area: ClinicalArea
    effective_date: date
    expiration_date: Optional[date]
    version: str
    document_path: str
    
    # Medical codes covered by this policy
    cpt_codes: List[str] = field(default_factory=list)
    icd_codes: List[str] = field(default_factory=list)
    service_categories: List[str] = field(default_factory=list)
    
    # Policy characteristics
    requires_prior_auth: bool = True
    urgency_levels: List[str] = field(default_factory=lambda: ["routine", "urgent", "emergent"])
    age_restrictions: Optional[Dict[str, Any]] = None
    gender_restrictions: Optional[List[str]] = None
    
    # Document metadata
    file_size_bytes: int = 0
    page_count: int = 0
    language: str = "en"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Indexing metadata
    keywords: List[str] = field(default_factory=list)
    summary: str = ""
    
    def __post_init__(self):
        """Validate metadata after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate policy metadata"""
        
        # Validate required fields
        if not self.policy_id or not self.payor or not self.policy_title:
            raise DataValidationError("Policy ID, payor, and title are required")
        
        # Validate payor name
        if not MedicalCodeValidator.validate_payor_name(self.payor):
            logger.warning("Unrecognized payor name", payor=self.payor)
        
        # Validate medical codes
        invalid_cpts = MedicalCodeValidator.validate_cpt_codes(self.cpt_codes)
        if invalid_cpts:
            raise DataValidationError(f"Invalid CPT codes: {invalid_cpts}")
        
        invalid_icds = MedicalCodeValidator.validate_icd_codes(self.icd_codes)
        if invalid_icds:
            raise DataValidationError(f"Invalid ICD codes: {invalid_icds}")
        
        # Validate dates
        if self.expiration_date and self.effective_date >= self.expiration_date:
            raise DataValidationError("Effective date must be before expiration date")
        
        # Validate version format
        if not self.version or not self.version.replace('.', '').replace('-', '').isalnum():
            raise DataValidationError("Invalid version format")
    
    def is_active(self, check_date: date = None) -> bool:
        """Check if policy is currently active"""
        if check_date is None:
            check_date = date.today()
        
        if check_date < self.effective_date:
            return False
        
        if self.expiration_date and check_date >= self.expiration_date:
            return False
        
        return True
    
    def covers_service(self, cpt_code: str = None, icd_code: str = None, 
                      service_category: str = None) -> bool:
        """Check if policy covers a specific service"""
        
        if cpt_code and cpt_code in self.cpt_codes:
            return True
        
        if icd_code and icd_code in self.icd_codes:
            return True
        
        if service_category and service_category.lower() in [cat.lower() for cat in self.service_categories]:
            return True
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'policy_id': self.policy_id,
            'payor': self.payor,
            'policy_title': self.policy_title,
            'policy_type': self.policy_type.value,
            'clinical_area': self.clinical_area.value,
            'effective_date': self.effective_date.isoformat(),
            'expiration_date': self.expiration_date.isoformat() if self.expiration_date else None,
            'version': self.version,
            'document_path': self.document_path,
            'cpt_codes': self.cpt_codes,
            'icd_codes': self.icd_codes,
            'service_categories': self.service_categories,
            'requires_prior_auth': self.requires_prior_auth,
            'urgency_levels': self.urgency_levels,
            'age_restrictions': self.age_restrictions,
            'gender_restrictions': self.gender_restrictions,
            'file_size_bytes': self.file_size_bytes,
            'page_count': self.page_count,
            'language': self.language,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'keywords': self.keywords,
            'summary': self.summary
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PolicyMetadata':
        """Create from dictionary"""
        
        # Convert string dates back to date objects
        effective_date = date.fromisoformat(data['effective_date'])
        expiration_date = date.fromisoformat(data['expiration_date']) if data.get('expiration_date') else None
        created_at = datetime.fromisoformat(data['created_at'])
        updated_at = datetime.fromisoformat(data['updated_at'])
        
        return cls(
            policy_id=data['policy_id'],
            payor=data['payor'],
            policy_title=data['policy_title'],
            policy_type=PolicyType(data['policy_type']),
            clinical_area=ClinicalArea(data['clinical_area']),
            effective_date=effective_date,
            expiration_date=expiration_date,
            version=data['version'],
            document_path=data['document_path'],
            cpt_codes=data.get('cpt_codes', []),
            icd_codes=data.get('icd_codes', []),
            service_categories=data.get('service_categories', []),
            requires_prior_auth=data.get('requires_prior_auth', True),
            urgency_levels=data.get('urgency_levels', ["routine", "urgent", "emergent"]),
            age_restrictions=data.get('age_restrictions'),
            gender_restrictions=data.get('gender_restrictions'),
            file_size_bytes=data.get('file_size_bytes', 0),
            page_count=data.get('page_count', 0),
            language=data.get('language', 'en'),
            created_at=created_at,
            updated_at=updated_at,
            keywords=data.get('keywords', []),
            summary=data.get('summary', '')
        )


class PolicyMetadataManager:
    """Manages policy metadata indexing and organization"""
    
    def __init__(self):
        self.metadata_cache: Dict[str, PolicyMetadata] = {}
    
    def create_policy_metadata(self, policy_data: Dict[str, Any]) -> PolicyMetadata:
        """Create policy metadata from policy document data"""
        
        # Extract basic information
        policy_id = policy_data.get('policy_id') or f"policy_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        payor = policy_data.get('payor', '').strip()
        title = policy_data.get('title', policy_data.get('policy_title', '')).strip()
        
        # Determine policy type
        policy_type = self._determine_policy_type(policy_data)
        
        # Determine clinical area
        clinical_area = self._determine_clinical_area(policy_data)
        
        # Extract dates
        effective_date = self._parse_date(policy_data.get('effective_date'))
        expiration_date = self._parse_date(policy_data.get('expiration_date'))
        
        # Extract medical codes
        cpt_codes = self._extract_cpt_codes(policy_data)
        icd_codes = self._extract_icd_codes(policy_data)
        
        # Extract service categories
        service_categories = self._extract_service_categories(policy_data)
        
        # Generate keywords
        keywords = self._generate_keywords(policy_data)
        
        # Create summary
        summary = self._create_summary(policy_data)
        
        metadata = PolicyMetadata(
            policy_id=policy_id,
            payor=MedicalCodeValidator.normalize_payor_name(payor),
            policy_title=title,
            policy_type=policy_type,
            clinical_area=clinical_area,
            effective_date=effective_date or date.today(),
            expiration_date=expiration_date,
            version=policy_data.get('version', '1.0'),
            document_path=policy_data.get('document_path', ''),
            cpt_codes=cpt_codes,
            icd_codes=icd_codes,
            service_categories=service_categories,
            requires_prior_auth=policy_data.get('requires_prior_auth', True),
            urgency_levels=policy_data.get('urgency_levels', ["routine", "urgent", "emergent"]),
            age_restrictions=policy_data.get('age_restrictions'),
            gender_restrictions=policy_data.get('gender_restrictions'),
            file_size_bytes=policy_data.get('file_size_bytes', 0),
            page_count=policy_data.get('page_count', 0),
            keywords=keywords,
            summary=summary
        )
        
        # Cache the metadata
        self.metadata_cache[policy_id] = metadata
        
        logger.info("Policy metadata created",
                   policy_id=policy_id,
                   payor=payor,
                   clinical_area=clinical_area.value)
        
        return metadata
    
    def _determine_policy_type(self, policy_data: Dict[str, Any]) -> PolicyType:
        """Determine policy type from document content"""
        
        content = str(policy_data).lower()
        
        if 'medical necessity' in content:
            return PolicyType.MEDICAL_NECESSITY
        elif 'coverage determination' in content:
            return PolicyType.COVERAGE_DETERMINATION
        elif 'prior authorization' in content or 'preauthorization' in content:
            return PolicyType.PRIOR_AUTHORIZATION
        elif 'clinical guideline' in content or 'clinical criteria' in content:
            return PolicyType.CLINICAL_GUIDELINE
        elif 'formulary' in content or 'drug list' in content:
            return PolicyType.FORMULARY
        else:
            return PolicyType.MEDICAL_NECESSITY  # Default
    
    def _determine_clinical_area(self, policy_data: Dict[str, Any]) -> ClinicalArea:
        """Determine clinical area from document content"""
        
        content = str(policy_data).lower()
        
        # Clinical area keywords
        area_keywords = {
            ClinicalArea.CARDIOLOGY: ['cardiac', 'heart', 'cardiovascular', 'coronary', 'echocardiogram', 'catheterization'],
            ClinicalArea.ORTHOPEDICS: ['orthopedic', 'bone', 'joint', 'fracture', 'arthroscopy', 'spine'],
            ClinicalArea.RADIOLOGY: ['imaging', 'mri', 'ct scan', 'x-ray', 'ultrasound', 'mammography'],
            ClinicalArea.ONCOLOGY: ['cancer', 'oncology', 'chemotherapy', 'radiation', 'tumor', 'malignant'],
            ClinicalArea.NEUROLOGY: ['neurological', 'brain', 'nervous system', 'seizure', 'stroke'],
            ClinicalArea.GASTROENTEROLOGY: ['gastro', 'digestive', 'endoscopy', 'colonoscopy', 'liver'],
            ClinicalArea.PULMONOLOGY: ['pulmonary', 'lung', 'respiratory', 'breathing', 'copd'],
            ClinicalArea.ENDOCRINOLOGY: ['diabetes', 'thyroid', 'hormone', 'endocrine', 'insulin'],
            ClinicalArea.DERMATOLOGY: ['skin', 'dermatology', 'dermatitis', 'melanoma', 'rash']
        }
        
        for area, keywords in area_keywords.items():
            if any(keyword in content for keyword in keywords):
                return area
        
        return ClinicalArea.GENERAL_MEDICINE  # Default
    
    def _parse_date(self, date_str: Any) -> Optional[date]:
        """Parse date from various formats"""
        if not date_str:
            return None
        
        if isinstance(date_str, date):
            return date_str
        
        if isinstance(date_str, datetime):
            return date_str.date()
        
        if isinstance(date_str, str):
            try:
                return date.fromisoformat(date_str)
            except ValueError:
                try:
                    return datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        return datetime.strptime(date_str, '%m/%d/%Y').date()
                    except ValueError:
                        logger.warning("Could not parse date", date_str=date_str)
                        return None
        
        return None
    
    def _extract_cpt_codes(self, policy_data: Dict[str, Any]) -> List[str]:
        """Extract CPT codes from policy data"""
        
        cpt_codes = set()
        
        # Check explicit CPT codes field
        if 'cpt_codes' in policy_data:
            codes = policy_data['cpt_codes']
            if isinstance(codes, list):
                cpt_codes.update(codes)
            elif isinstance(codes, str):
                cpt_codes.update(codes.split(','))
        
        # Extract from content using regex
        content = str(policy_data)
        import re
        cpt_pattern = re.compile(r'\b(\d{5}(?:-[A-Z0-9]{2})?)\b')
        matches = cpt_pattern.findall(content)
        
        for match in matches:
            if MedicalCodeValidator.validate_cpt_code(match):
                cpt_codes.add(match)
        
        return list(cpt_codes)
    
    def _extract_icd_codes(self, policy_data: Dict[str, Any]) -> List[str]:
        """Extract ICD codes from policy data"""
        
        icd_codes = set()
        
        # Check explicit ICD codes field
        if 'icd_codes' in policy_data:
            codes = policy_data['icd_codes']
            if isinstance(codes, list):
                icd_codes.update(codes)
            elif isinstance(codes, str):
                icd_codes.update(codes.split(','))
        
        # Extract from content using regex
        content = str(policy_data)
        import re
        icd_pattern = re.compile(r'\b([A-Z]\d{2}(?:\.[A-Z0-9]{1,4})?)\b')
        matches = icd_pattern.findall(content)
        
        for match in matches:
            if MedicalCodeValidator.validate_icd_code(match):
                icd_codes.add(match)
        
        return list(icd_codes)
    
    def _extract_service_categories(self, policy_data: Dict[str, Any]) -> List[str]:
        """Extract service categories from policy data"""
        
        categories = set()
        
        # Check explicit service categories
        if 'service_categories' in policy_data:
            cats = policy_data['service_categories']
            if isinstance(cats, list):
                categories.update(cats)
            elif isinstance(cats, str):
                categories.update(cats.split(','))
        
        # Infer from content
        content = str(policy_data).lower()
        
        category_keywords = {
            'diagnostic': ['diagnostic', 'diagnosis', 'test', 'screening', 'examination'],
            'therapeutic': ['therapeutic', 'treatment', 'therapy', 'intervention'],
            'surgical': ['surgical', 'surgery', 'procedure', 'operation'],
            'imaging': ['imaging', 'radiology', 'scan', 'x-ray', 'mri', 'ct'],
            'laboratory': ['laboratory', 'lab', 'blood test', 'pathology'],
            'preventive': ['preventive', 'prevention', 'screening', 'wellness']
        }
        
        for category, keywords in category_keywords.items():
            if any(keyword in content for keyword in keywords):
                categories.add(category)
        
        return list(categories)
    
    def _generate_keywords(self, policy_data: Dict[str, Any]) -> List[str]:
        """Generate keywords for search indexing"""
        
        keywords = set()
        
        # Add payor name
        payor = policy_data.get('payor', '')
        if payor:
            keywords.add(payor.lower())
        
        # Add policy title words
        title = policy_data.get('title', policy_data.get('policy_title', ''))
        if title:
            title_words = [word.lower().strip('.,!?') for word in title.split() if len(word) > 3]
            keywords.update(title_words)
        
        # Add medical codes
        keywords.update(policy_data.get('cpt_codes', []))
        keywords.update(policy_data.get('icd_codes', []))
        
        # Add service categories
        keywords.update(policy_data.get('service_categories', []))
        
        # Add clinical terms from content
        content = str(policy_data).lower()
        clinical_terms = [
            'medical necessity', 'prior authorization', 'coverage', 'criteria',
            'diagnosis', 'treatment', 'procedure', 'therapy', 'medication'
        ]
        
        for term in clinical_terms:
            if term in content:
                keywords.add(term)
        
        return list(keywords)
    
    def _create_summary(self, policy_data: Dict[str, Any]) -> str:
        """Create a summary of the policy"""
        
        payor = policy_data.get('payor', 'Unknown Payor')
        title = policy_data.get('title', policy_data.get('policy_title', 'Policy'))
        
        summary_parts = [f"{payor} policy for {title}"]
        
        # Add coverage information
        cpt_codes = policy_data.get('cpt_codes', [])
        if cpt_codes:
            summary_parts.append(f"Covers CPT codes: {', '.join(cpt_codes[:5])}")
            if len(cpt_codes) > 5:
                summary_parts[-1] += f" and {len(cpt_codes) - 5} more"
        
        # Add service categories
        categories = policy_data.get('service_categories', [])
        if categories:
            summary_parts.append(f"Service categories: {', '.join(categories)}")
        
        return '. '.join(summary_parts)
    
    def get_metadata_by_payor(self, payor: str) -> List[PolicyMetadata]:
        """Get all metadata for a specific payor"""
        return [
            metadata for metadata in self.metadata_cache.values()
            if metadata.payor.lower() == payor.lower()
        ]
    
    def get_metadata_by_clinical_area(self, clinical_area: ClinicalArea) -> List[PolicyMetadata]:
        """Get all metadata for a specific clinical area"""
        return [
            metadata for metadata in self.metadata_cache.values()
            if metadata.clinical_area == clinical_area
        ]
    
    def search_metadata(self, query: str, payor: str = None, 
                       clinical_area: ClinicalArea = None) -> List[PolicyMetadata]:
        """Search metadata by query terms"""
        
        query_lower = query.lower()
        results = []
        
        for metadata in self.metadata_cache.values():
            # Filter by payor if specified
            if payor and metadata.payor.lower() != payor.lower():
                continue
            
            # Filter by clinical area if specified
            if clinical_area and metadata.clinical_area != clinical_area:
                continue
            
            # Check if query matches keywords, title, or summary
            if (query_lower in metadata.policy_title.lower() or
                query_lower in metadata.summary.lower() or
                any(query_lower in keyword.lower() for keyword in metadata.keywords)):
                results.append(metadata)
        
        return results

