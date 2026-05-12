"""
Core data models for the Prior Authorization Application.

This module defines all the data structures used throughout the system,
including extracted data, patient information, assessment results, and
clinical evidence models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from enum import Enum
import json
import re
from dataclasses_json import dataclass_json


class ComplianceStatus(Enum):
    """Compliance status for medical necessity criteria"""
    MET = "met"
    NOT_MET = "not_met"
    PARTIALLY_MET = "partially_met"


class DocumentFormat(Enum):
    """Document format types"""
    PDF = "PDF"
    FHIR_JSON = "FHIR_JSON"
    X12_278_JSON = "X12_278_JSON"
    X12_275_JSON = "X12_275_JSON"
    UNKNOWN = "UNKNOWN"


class ProcessingStatus(Enum):
    """Processing status for document workflow"""
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    SELECTING_POLICY = "selecting_policy"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceType(Enum):
    """Types of clinical evidence"""
    LAB_RESULT = "lab_result"
    IMAGING = "imaging"
    CLINICAL_NOTE = "clinical_note"
    PROCEDURE_NOTE = "procedure_note"
    DIAGNOSTIC_REPORT = "diagnostic_report"
    MEDICATION_HISTORY = "medication_history"


@dataclass_json
@dataclass
class PatientInfo:
    """Patient demographic and clinical information"""
    patient_id: str  # Anonymized identifier
    age_range: str  # Age range for privacy (e.g., "60-70")
    gender: str
    primary_diagnosis: str
    comorbidities: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate patient information"""
        if not self.patient_id:
            raise ValueError("Patient ID is required")
        if self.gender not in ["male", "female", "other", "unknown"]:
            raise ValueError("Invalid gender value")
    



@dataclass_json
@dataclass
class ClinicalEvidence:
    """Clinical evidence extracted from medical records"""
    evidence_id: str
    source_document: str
    evidence_type: EvidenceType
    content: str
    confidence_score: float
    page_reference: Optional[int] = None
    extracted_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate clinical evidence"""
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError("Confidence score must be between 0.0 and 1.0")
        if not self.content.strip():
            raise ValueError("Evidence content cannot be empty")


@dataclass_json
@dataclass
class ExtractedData:
    """Data extracted from prior authorization documents"""
    document_id: str
    cpt_codes: List[str]
    icd_codes: List[str]
    service_type: str
    payor_name: str
    plan_type: str
    patient_info: PatientInfo
    extraction_confidence: float
    raw_text: str
    coverage_state: Optional[str] = None  # 2-letter lowercase state code from insurance coverage
    structured_fields: Dict[str, Any] = field(default_factory=dict)
    extracted_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate extracted data"""
        self._validate_medical_codes()
        if not (0.0 <= self.extraction_confidence <= 1.0):
            raise ValueError("Extraction confidence must be between 0.0 and 1.0")
        if not self.payor_name.strip():
            raise ValueError("Payor name is required")
    

    
    def _validate_medical_codes(self):
        """Validate CPT and ICD code formats"""
        # CPT code validation (5 digits, optionally with modifiers)
        cpt_pattern = re.compile(r'^\d{5}(-\w{2})?$')
        for cpt in self.cpt_codes:
            if not cpt_pattern.match(cpt):
                raise ValueError(f"Invalid CPT code format: {cpt}")
        
        # ICD-10 code validation (basic format check)
        icd_pattern = re.compile(r'^[A-Z]\d{2}(\.\d{1,4})?$')
        for icd in self.icd_codes:
            if not icd_pattern.match(icd):
                raise ValueError(f"Invalid ICD-10 code format: {icd}")


@dataclass_json
@dataclass
class ClinicalCriterion:
    """Clinical criterion from policy requirements"""
    criterion_id: str
    description: str
    required_evidence: List[str]
    clinical_indicators: List[str]
    exclusion_criteria: List[str] = field(default_factory=list)
    priority: str = "standard"  # "critical", "standard", "optional"
    
    def __post_init__(self):
        """Validate clinical criterion"""
        if not self.description.strip():
            raise ValueError("Criterion description is required")
        if self.priority not in ["critical", "standard", "optional"]:
            raise ValueError("Priority must be critical, standard, or optional")
    



@dataclass_json
@dataclass
class SelectedPolicy:
    """Policy selected for prior authorization assessment"""
    policy_id: str
    payor: str
    policy_title: str
    effective_date: str
    relevance_score: float
    applicable_criteria: List[ClinicalCriterion]
    policy_version: str = "1.0"
    policy_metadata: Dict[str, Any] = field(default_factory=dict)
    selected_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate selected policy"""
        if not (0.0 <= self.relevance_score <= 1.0):
            raise ValueError("Relevance score must be between 0.0 and 1.0")
        if not self.applicable_criteria:
            raise ValueError("At least one applicable criterion is required")
    



@dataclass_json
@dataclass
class CriterionAssessment:
    """Assessment result for a single clinical criterion"""
    criterion_id: str
    status: ComplianceStatus
    supporting_evidence: List[str]
    confidence_score: float
    clinical_rationale: str
    gaps_identified: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    assessed_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate criterion assessment"""
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError("Confidence score must be between 0.0 and 1.0")
        if not self.clinical_rationale.strip():
            raise ValueError("Clinical rationale is required")


@dataclass_json
@dataclass
class GapAnalysis:
    """Analysis of documentation gaps and recommendations"""
    missing_evidence: List[str]
    critical_gaps: List[str]
    recommendations: List[str]
    priority_actions: List[str]
    estimated_approval_likelihood: float
    
    def __post_init__(self):
        """Validate gap analysis"""
        if not (0.0 <= self.estimated_approval_likelihood <= 1.0):
            raise ValueError("Approval likelihood must be between 0.0 and 1.0")


@dataclass_json
@dataclass
class AssessmentResult:
    """Complete assessment result for prior authorization request"""
    assessment_id: str
    document_id: str
    overall_compliance: str  # "compliant", "non_compliant", "partially_compliant"
    criteria_results: List[CriterionAssessment]
    gap_analysis: GapAnalysis
    recommendations: List[str]
    approval_likelihood: float
    processing_time_seconds: float
    assessed_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate assessment result"""
        valid_compliance = ["compliant", "non_compliant", "partially_compliant"]
        if self.overall_compliance not in valid_compliance:
            raise ValueError(f"Overall compliance must be one of: {valid_compliance}")
        if not (0.0 <= self.approval_likelihood <= 1.0):
            raise ValueError("Approval likelihood must be between 0.0 and 1.0")
        if not self.criteria_results:
            raise ValueError("At least one criterion result is required")


@dataclass_json
@dataclass
class ProcessingState:
    """Processing state for document workflow tracking"""
    document_id: str
    status: ProcessingStatus
    current_step: str
    progress_percentage: int
    error_details: Optional[str] = None
    step_results: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate processing state"""
        if not (0 <= self.progress_percentage <= 100):
            raise ValueError("Progress percentage must be between 0 and 100")
    
    def update_progress(self, step: str, percentage: int, result: Any = None):
        """Update processing progress"""
        self.current_step = step
        self.progress_percentage = percentage
        self.updated_at = datetime.utcnow()
        if result is not None:
            self.step_results[step] = result
    
    def mark_failed(self, error: str):
        """Mark processing as failed"""
        self.status = ProcessingStatus.FAILED
        self.error_details = error
        self.updated_at = datetime.utcnow()


# Utility functions for model serialization
def serialize_model(model: Any) -> str:
    """Serialize a dataclass model to JSON string"""
    if hasattr(model, 'to_json'):
        return model.to_json()
    return json.dumps(model, default=str)


def deserialize_model(json_str: str, model_class: type) -> Any:
    """Deserialize JSON string to dataclass model"""
    if hasattr(model_class, 'from_json'):
        return model_class.from_json(json_str)
    data = json.loads(json_str)
    return model_class(**data)
