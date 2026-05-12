"""
FHIR Data Extractor for Prior Authorization.

This module extracts medical data from FHIR JSON bundles following
the Da Vinci Prior Authorization standards.
"""

import json
import base64
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

from common.models import ExtractedData, PatientInfo
from common.exceptions import DocumentParsingException
from common.logging_config import get_logger
from common.utils import anonymize_patient_id, create_age_range
from common.validators import MedicalCodeValidator

logger = get_logger(__name__)


@dataclass
class FHIRPatientInfo:
    """Internal model for FHIR Patient resource"""
    name: Optional[str] = None
    mrn: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None


@dataclass
class FHIRCoverageInfo:
    """Internal model for FHIR Coverage resource"""
    payor: Optional[str] = None
    plan_type: Optional[str] = None
    plan_name: Optional[str] = None
    state: Optional[str] = None
    member_id: Optional[str] = None
    group_number: Optional[str] = None


@dataclass
class FHIRServiceInfo:
    """Internal model for FHIR Claim/Service resource"""
    cpt_code: Optional[str] = None
    cpt_description: Optional[str] = None
    service_type: Optional[str] = None
    diagnosis_codes: Optional[List[str]] = None
    diagnosis_descriptions: Optional[List[str]] = None
    procedure_date: Optional[str] = None
    provider: Optional[str] = None
    drug_category: Optional[str] = None
    generic_drug_name: Optional[str] = None
    all_cpt_codes: Optional[List[str]] = None
    all_hcpcs_codes: Optional[List[str]] = None  # HCPCS codes (K, G, E codes, etc.)
    all_rxnorm_codes: Optional[List[str]] = None  # RxNorm codes for medications
    all_cpt_descriptions: Optional[List[str]] = None
    all_hcpcs_descriptions: Optional[List[str]] = None
    all_rxnorm_descriptions: Optional[List[str]] = None
    session_counts: Optional[Dict[str, int]] = None
    treatment_duration_days: Optional[int] = None
    treatment_start_date: Optional[str] = None
    treatment_end_date: Optional[str] = None
    service_location: Optional[str] = None
    supporting_info: Optional[List[str]] = None


@dataclass
class FHIRDocumentContent:
    """Internal model for decoded DocumentReference content"""
    title: Optional[str] = None
    content_type: Optional[str] = None
    decoded_text: Optional[str] = None
    size: Optional[int] = None
    creation_date: Optional[str] = None


class FHIRParsingException(DocumentParsingException):
    """Raised when FHIR parsing fails"""
    def __init__(self, message: str, document_id: str = None, resource_type: str = None):
        super().__init__(
            f"FHIR parsing failed: {message}" + 
            (f" (resource: {resource_type})" if resource_type else ""),
            document_id=document_id
        )


class FHIRDataExtractor:
    """Extracts medical data from FHIR JSON bundles"""
    
    # US State code mapping for normalization
    STATE_CODES = {
        'alabama': 'al', 'alaska': 'ak', 'arizona': 'az', 'arkansas': 'ar', 'california': 'ca',
        'colorado': 'co', 'connecticut': 'ct', 'delaware': 'de', 'florida': 'fl', 'georgia': 'ga',
        'hawaii': 'hi', 'idaho': 'id', 'illinois': 'il', 'indiana': 'in', 'iowa': 'ia',
        'kansas': 'ks', 'kentucky': 'ky', 'louisiana': 'la', 'maine': 'me', 'maryland': 'md',
        'massachusetts': 'ma', 'michigan': 'mi', 'minnesota': 'mn', 'mississippi': 'ms', 'missouri': 'mo',
        'montana': 'mt', 'nebraska': 'ne', 'nevada': 'nv', 'new hampshire': 'nh', 'new jersey': 'nj',
        'new mexico': 'nm', 'new york': 'ny', 'north carolina': 'nc', 'north dakota': 'nd', 'ohio': 'oh',
        'oklahoma': 'ok', 'oregon': 'or', 'pennsylvania': 'pa', 'rhode island': 'ri', 'south carolina': 'sc',
        'south dakota': 'sd', 'tennessee': 'tn', 'texas': 'tx', 'utah': 'ut', 'vermont': 'vt',
        'virginia': 'va', 'washington': 'wa', 'west virginia': 'wv', 'wisconsin': 'wi', 'wyoming': 'wy',
        'district of columbia': 'dc', 'puerto rico': 'pr'
    }
    
    def __init__(self):
        """Initialize the FHIR data extractor"""
        pass
    
    def _normalize_state_code(self, state_value: str) -> Optional[str]:
        """
        Normalize state code to lowercase 2-letter format.
        
        Args:
            state_value: State name or code (e.g., "CO", "Colorado", "california")
            
        Returns:
            Lowercase 2-letter state code (e.g., "co") or None if invalid
        """
        if not state_value:
            return None
        
        state_clean = state_value.strip().lower()
        
        # If already 2 letters, return as lowercase
        if len(state_clean) == 2 and state_clean.isalpha():
            return state_clean
        
        # Try to map full state name to code
        if state_clean in self.STATE_CODES:
            return self.STATE_CODES[state_clean]
        
        # Log warning if state cannot be normalized
        logger.warning("Could not normalize state code", state_value=state_value)
        return None
    
    def extract_from_fhir_bundle(self, fhir_data: Dict[str, Any], document_id: str) -> ExtractedData:
        """
        Extract medical data from FHIR Bundle for prior authorization.
        
        Args:
            fhir_data: Parsed FHIR JSON bundle
            document_id: Document identifier
            
        Returns:
            ExtractedData: Structured extracted information
            
        Raises:
            FHIRParsingException: If parsing fails
        """
        logger.info("Starting FHIR data extraction", document_id=document_id)
        
        try:
            # Validate Bundle structure
            if fhir_data.get('resourceType') != 'Bundle':
                raise FHIRParsingException(
                    "Not a FHIR Bundle resource",
                    document_id=document_id
                )
            
            # Initialize data structures
            patient_info = FHIRPatientInfo()
            coverage_info = FHIRCoverageInfo()
            service_info = FHIRServiceInfo()
            patient_address_state = None  # For fallback if coverage state not found
            
            # Convert to string for full text
            full_text = json.dumps(fhir_data, indent=2)
            
            # Extract data from FHIR bundle
            organizations = {}  # Store organizations by ID for reference lookup
            document_contents = []  # Store decoded document contents
            
            if 'entry' not in fhir_data:
                raise FHIRParsingException(
                    "FHIR Bundle has no entry array",
                    document_id=document_id
                )
            
            entries = fhir_data.get('entry', [])
            
            # First pass: collect all organizations for reference lookup
            for entry in entries:
                resource = entry.get('resource', {})
                resource_type = resource.get('resourceType')
                
                if resource_type == 'Organization':
                    org_id = resource.get('id')
                    if org_id:
                        organizations[org_id] = resource
            
            logger.debug("Organizations collected", count=len(organizations))
            
            # Second pass: extract data, prioritizing Claim resource for prior auth details
            for entry in entries:
                resource = entry.get('resource', {})
                resource_type = resource.get('resourceType')
                
                try:
                    if resource_type == 'Patient':
                        patient_info, patient_address_state = self._extract_patient_from_fhir(resource)
                    
                    elif resource_type == 'DocumentReference':
                        # Extract and decode document content
                        doc_content = self._extract_document_content(resource)
                        if doc_content:
                            document_contents.append(doc_content)
                    
                    elif resource_type == 'Claim':
                        # PRIMARY SOURCE: Extract all prior auth details from Claim
                        self._extract_from_claim(resource, service_info, coverage_info, organizations)
                    
                    elif resource_type in ['ServiceRequest', 'ProcedureRequest', 'DeviceRequest', 'MedicationRequest']:
                        # Extract service information from various request types
                        if not service_info.cpt_code:  # Only use if not already extracted from Claim
                            self._extract_service_from_request(resource, resource_type, service_info)
                    
                    elif resource_type == 'Coverage':
                        # SUPPLEMENTARY: Only use Coverage resource if Claim didn't provide coverage info
                        if not coverage_info.payor or not coverage_info.member_id:
                            self._extract_coverage_from_fhir(resource, coverage_info, organizations)
                
                except Exception as e:
                    logger.warning(f"Error extracting from {resource_type} resource",
                                 error=str(e),
                                 resource_type=resource_type)
                    # Continue processing other resources
            
            # Append decoded document contents to full_text if available
            if document_contents:
                full_text += "\n\n" + "="*50 + "\nDECODED DOCUMENT CONTENTS:\n" + "="*50 + "\n"
                for i, doc in enumerate(document_contents, 1):
                    full_text += f"\n--- Document {i}: {doc.title or 'Untitled'} ---\n"
                    if doc.decoded_text:
                        full_text += doc.decoded_text + "\n"
            
            # Apply fallback logic for coverage state (PRIORITY 2)
            # If coverage state not found, use patient address state as fallback
            if not coverage_info.state and patient_address_state:
                coverage_info.state = patient_address_state
                logger.info(
                    "Using patient address state as fallback for coverage state",
                    patient_address_state=patient_address_state,
                    document_id=document_id
                )
            
            # Map to ExtractedData model
            extracted_data = self._map_to_extracted_data(
                patient_info,
                coverage_info,
                service_info,
                document_id,
                full_text,
                document_contents,
                patient_address_state  # Pass for structured_fields
            )
            
            logger.info("FHIR data extraction completed successfully",
                       document_id=document_id,
                       cpt_codes_count=len(extracted_data.cpt_codes),
                       icd_codes_count=len(extracted_data.icd_codes))
            
            return extracted_data
            
        except FHIRParsingException:
            raise
        except Exception as e:
            logger.error("FHIR extraction failed",
                        document_id=document_id,
                        error=str(e))
            raise FHIRParsingException(str(e), document_id)
    
    def _extract_from_claim(self, claim_resource: Dict, service_info: FHIRServiceInfo,
                           coverage_info: FHIRCoverageInfo, organizations: Dict):
        """Extract all data from Claim resource"""
        # Extract service information
        self._extract_complete_service_from_claim(claim_resource, service_info)
        
        # Extract diagnosis codes and descriptions
        self._extract_diagnoses_from_claim(claim_resource, service_info)
        
        # Extract payor information
        payor_name = self._extract_payor_from_claim(claim_resource, organizations)
        if payor_name:
            coverage_info.payor = payor_name
        
        # Extract coverage details
        self._extract_coverage_from_claim(claim_resource, coverage_info, organizations)
    
    def _extract_patient_from_fhir(self, patient_resource: Dict) -> FHIRPatientInfo:
        """Extract patient information from FHIR Patient resource"""
        patient_info = FHIRPatientInfo()
        patient_address_state = None  # Store separately for fallback
        
        try:
            # Extract name
            if 'name' in patient_resource and patient_resource['name']:
                name_parts = []
                name = patient_resource['name'][0]  # Take first name
                if 'given' in name:
                    name_parts.extend(name['given'])
                if 'family' in name:
                    name_parts.append(name['family'])
                patient_info.name = ' '.join(name_parts)
            
            # Extract gender
            if 'gender' in patient_resource:
                patient_info.gender = patient_resource['gender']
            
            # Extract birth date
            if 'birthDate' in patient_resource:
                patient_info.dob = patient_resource['birthDate']
                # Calculate age
                try:
                    birth_date = datetime.strptime(patient_resource['birthDate'], '%Y-%m-%d')
                    age = (datetime.now() - birth_date).days // 365
                    patient_info.age = str(age)
                except Exception as e:
                    logger.warning("Failed to calculate age", error=str(e))
            
            # Extract identifiers (MRN)
            if 'identifier' in patient_resource:
                for identifier in patient_resource['identifier']:
                    # Check if this is a Medical Record Number
                    id_type = identifier.get('type', {})
                    coding = id_type.get('coding', [])
                    for code in coding:
                        if code.get('code') == 'MR':
                            patient_info.mrn = identifier.get('value')
                            break
                    if patient_info.mrn:
                        break
            
            # Extract address and state
            if 'address' in patient_resource and patient_resource['address']:
                address = patient_resource['address'][0]
                address_parts = []
                for field in ['line', 'city', 'state', 'postalCode']:
                    if field in address:
                        if isinstance(address[field], list):
                            address_parts.extend(address[field])
                        else:
                            address_parts.append(address[field])
                            # Extract state separately for fallback
                            if field == 'state':
                                patient_address_state = self._normalize_state_code(address[field])
                patient_info.address = ', '.join(address_parts)
            
            # Extract phone
            if 'telecom' in patient_resource:
                for telecom in patient_resource['telecom']:
                    if telecom.get('system') == 'phone':
                        patient_info.phone = telecom.get('value')
                        break
            
            logger.debug("Patient information extracted",
                        name=patient_info.name,
                        mrn=patient_info.mrn,
                        gender=patient_info.gender,
                        address_state=patient_address_state)
            
        except Exception as e:
            logger.warning("Error extracting patient information", error=str(e))
            raise FHIRParsingException(
                f"Failed to extract patient info: {str(e)}",
                resource_type="Patient"
            )
        
        return patient_info, patient_address_state
    
    def _extract_coverage_from_fhir(self, coverage_resource: Dict, coverage_info: FHIRCoverageInfo,
                                   organizations: Dict):
        """Extract coverage information from FHIR Coverage resource"""
        try:
            # Extract payor from Coverage.payor
            if 'payor' in coverage_resource and coverage_resource['payor']:
                payor = coverage_resource['payor'][0]
                if 'display' in payor:
                    coverage_info.payor = payor['display']
                elif 'reference' in payor:
                    # Try to resolve organization reference
                    payor_name = self._extract_payor_from_coverage(coverage_resource, organizations)
                    if payor_name:
                        coverage_info.payor = payor_name
            
            # Extract member ID
            if 'subscriberId' in coverage_resource:
                coverage_info.member_id = coverage_resource['subscriberId']
            
            # Extract plan details from Coverage.class
            if 'class' in coverage_resource:
                for class_item in coverage_resource['class']:
                    class_type = class_item.get('type', {}).get('coding', [{}])[0].get('code')
                    if class_type == 'plan':
                        coverage_info.plan_name = class_item.get('name')
                    elif class_type == 'group':
                        coverage_info.group_number = class_item.get('value')
                    elif class_type == 'state':
                        # Extract state from Coverage.class with type='state'
                        state_value = class_item.get('value')
                        if state_value:
                            coverage_info.state = self._normalize_state_code(state_value)
            
            # Extract plan type from Coverage.type
            if 'type' in coverage_resource:
                type_coding = coverage_resource['type'].get('coding', [])
                if type_coding:
                    coverage_info.plan_type = type_coding[0].get('display', '')
            
            # Extract state from extensions if not found in class
            if not coverage_info.state and 'extension' in coverage_resource:
                for extension in coverage_resource['extension']:
                    # Check for state-specific extensions
                    if 'state' in extension.get('url', '').lower():
                        state_value = extension.get('valueString') or extension.get('valueCode')
                        if state_value:
                            coverage_info.state = self._normalize_state_code(state_value)
                            break
            
            logger.debug("Coverage information extracted",
                        payor=coverage_info.payor,
                        member_id=coverage_info.member_id,
                        state=coverage_info.state)
            
        except Exception as e:
            logger.warning("Error extracting coverage information", error=str(e))
    
    def _extract_payor_from_claim(self, claim_resource: Dict, organizations: Dict) -> Optional[str]:
        """Extract payor name from Claim resource using Organization references"""
        try:
            insurer_ref = claim_resource.get('insurer', {}).get('reference', '')
            if insurer_ref:
                # Extract organization ID from reference (e.g., "Organization/insurance-company-002")
                if '/' in insurer_ref:
                    org_id = insurer_ref.split('/')[-1]
                    if org_id in organizations:
                        org = organizations[org_id]
                        payor_name = org.get('name')
                        return payor_name
                    else:
                        # Fallback: try to infer payor name from the org_id
                        if 'aetna' in org_id.lower():
                            return 'Aetna'
                        elif 'anthem' in org_id.lower():
                            return 'Anthem'
                        elif 'cigna' in org_id.lower():
                            return 'Cigna'
                        elif 'humana' in org_id.lower():
                            return 'Humana'
                        elif 'insurance' in org_id.lower():
                            # Generic fallback - capitalize the org_id
                            return org_id.replace('-', ' ').replace('_', ' ').title()
        except Exception as e:
            logger.warning("Error extracting payor from claim", error=str(e))
        return None
    
    def _extract_payor_from_coverage(self, coverage_resource: Dict, organizations: Dict) -> Optional[str]:
        """Extract payor name from Coverage resource using Organization references"""
        try:
            # Check payor array in Coverage resource
            if 'payor' in coverage_resource and coverage_resource['payor']:
                for payor in coverage_resource['payor']:
                    # Check if payor has a reference to an Organization
                    if 'reference' in payor:
                        payor_ref = payor['reference']
                        if '/' in payor_ref:
                            org_id = payor_ref.split('/')[-1]
                            if org_id in organizations:
                                org = organizations[org_id]
                                payor_name = org.get('name')
                                return payor_name
                    # Check if payor has direct display name
                    elif 'display' in payor:
                        return payor['display']
        except Exception as e:
            logger.warning("Error extracting payor from coverage", error=str(e))
        return None
    
    def _extract_coverage_from_claim(self, claim_resource: Dict, coverage_info: FHIRCoverageInfo,
                                    organizations: Dict):
        """Extract coverage details from Claim resource"""
        try:
            # Extract from insurance array
            if 'insurance' in claim_resource:
                for insurance in claim_resource['insurance']:
                    if insurance.get('focal'):  # Primary insurance
                        coverage_ref = insurance.get('coverage', {}).get('reference', '')
                        # Note: This would need the actual Coverage resource to get member ID
                        # For now, we'll rely on the Coverage resource extraction
                        break
            
            # Extract state information if available in extensions or other fields
            # This would be implementation-specific based on how state is encoded
            
        except Exception as e:
            logger.warning("Error extracting coverage from claim", error=str(e))
    
    def _extract_complete_service_from_claim(self, claim_resource: Dict, service_info: FHIRServiceInfo):
        """Extract comprehensive service information from Claim resource"""
        try:
            # Extract from procedure array (primary location for procedures)
            if 'procedure' in claim_resource:
                for proc in claim_resource['procedure']:
                    if 'procedureCodeableConcept' in proc:
                        coding = proc['procedureCodeableConcept'].get('coding', [])
                        for code in coding:
                            if code.get('system') == 'http://www.ama-assn.org/go/cpt':
                                service_info.cpt_code = code.get('code')
                                service_info.cpt_description = code.get('display')
                                service_info.service_type = 'Procedure'
                                break
                    if 'date' in proc:
                        service_info.procedure_date = proc['date']
                    if service_info.cpt_code:  # Found procedure, break
                        break
            
            # Extract from item array if no procedure found (services, supplies, medications)
            if not service_info.cpt_code and 'item' in claim_resource:
                for item in claim_resource['item']:
                    if 'productOrService' in item:
                        coding = item['productOrService'].get('coding', [])
                        for code in coding:
                            # Handle CPT codes
                            if code.get('system') == 'http://www.ama-assn.org/go/cpt':
                                service_info.cpt_code = code.get('code')
                                service_info.cpt_description = code.get('display')
                                service_info.service_type = 'Service'
                                break
                            # Handle HCPCS codes (for DME, supplies)
                            elif code.get('system') == 'https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets':
                                service_info.cpt_code = code.get('code')
                                service_info.cpt_description = code.get('display')
                                service_info.service_type = 'Supply/Equipment'
                                break
                            # Handle NDC codes (for medications)
                            elif code.get('system') == 'http://hl7.org/fhir/sid/ndc':
                                service_info.cpt_code = code.get('code')
                                service_info.cpt_description = code.get('display')
                                service_info.service_type = 'Medication'
                                break
                            # Handle RxNorm codes (for medications) - ENHANCED for oncology drugs
                            elif code.get('system') == 'http://www.nlm.nih.gov/research/umls/rxnorm':
                                service_info.cpt_code = code.get('code')
                                service_info.cpt_description = code.get('display')
                                service_info.service_type = 'Specialty Drug'
                                
                                # For oncology drugs, also extract drug name for policy matching
                                drug_name = code.get('display', '').lower()
                                oncology_drugs = [
                                    'trastuzumab', 'bevacizumab', 'rituximab', 'pembrolizumab',
                                    'nivolumab', 'atezolizumab', 'durvalumab', 'ipilimumab'
                                ]
                                
                                if any(oncology_drug in drug_name for oncology_drug in oncology_drugs):
                                    service_info.drug_category = 'Oncology Specialty Drug'
                                    # Extract generic drug name for policy matching
                                    for drug in oncology_drugs:
                                        if drug in drug_name:
                                            service_info.generic_drug_name = drug
                                            break
                                    logger.info("Oncology drug detected",
                                              generic_drug_name=service_info.generic_drug_name,
                                              rxnorm_code=code.get('code'))
                                break
                    
                    # Extract service date
                    if 'servicedDate' in item:
                        service_info.procedure_date = item['servicedDate']
                    elif 'servicedPeriod' in item and 'start' in item['servicedPeriod']:
                        service_info.procedure_date = item['servicedPeriod']['start']
                    
                    # Extract category information for service type
                    if 'category' in item:
                        category_coding = item['category'].get('coding', [])
                        for cat_code in category_coding:
                            if cat_code.get('display') and not service_info.service_type:
                                service_info.service_type = cat_code['display']
                                break
                    
                    if service_info.cpt_code:  # Found service code, break
                        break
            
            # Extract provider information from Claim
            if 'provider' in claim_resource:
                if 'display' in claim_resource['provider']:
                    service_info.provider = claim_resource['provider']['display']
                elif 'reference' in claim_resource['provider']:
                    # Could resolve provider reference if needed
                    service_info.provider = claim_resource['provider']['reference']
            
            # ENHANCED EXTRACTION: Multiple CPT codes, session counts, treatment duration
            if 'item' in claim_resource:
                all_cpts = []
                all_cpt_descs = []
                session_counts = {}
                start_dates = []
                end_dates = []
                
                # Initialize HCPCS and RxNorm tracking
                all_hcpcs = []
                all_hcpcs_descs = []
                all_rxnorm = []
                all_rxnorm_descs = []
                
                for item in claim_resource['item']:
                    # Extract all CPT, HCPCS, and RxNorm codes
                    if 'productOrService' in item:
                        coding = item['productOrService'].get('coding', [])
                        for code in coding:
                            code_system = code.get('system', '')
                            code_value = code.get('code')
                            code_desc = code.get('display')
                            
                            # CPT codes
                            if code_system == 'http://www.ama-assn.org/go/cpt':
                                if code_value:
                                    all_cpts.append(code_value)
                                    if code_desc:
                                        all_cpt_descs.append(f"{code_value}: {code_desc}")
                                    
                                    # Extract session count
                                    if 'quantity' in item and 'value' in item['quantity']:
                                        session_counts[code_value] = int(item['quantity']['value'])
                            
                            # HCPCS codes (CMS HCPCS system)
                            elif 'cms.gov/Medicare/Coding/HCPCSReleaseCodeSets' in code_system:
                                if code_value:
                                    all_hcpcs.append(code_value)
                                    if code_desc:
                                        all_hcpcs_descs.append(f"{code_value}: {code_desc}")
                                    
                                    # Extract session count
                                    if 'quantity' in item and 'value' in item['quantity']:
                                        session_counts[code_value] = int(item['quantity']['value'])
                            
                            # RxNorm codes (medication codes)
                            elif 'nlm.nih.gov/research/umls/rxnorm' in code_system:
                                if code_value:
                                    all_rxnorm.append(code_value)
                                    if code_desc:
                                        all_rxnorm_descs.append(f"{code_value}: {code_desc}")
                                    
                                    # Extract session count
                                    if 'quantity' in item and 'value' in item['quantity']:
                                        session_counts[code_value] = int(item['quantity']['value'])
                    
                    # Extract treatment dates
                    if 'servicedPeriod' in item:
                        if 'start' in item['servicedPeriod']:
                            start_dates.append(item['servicedPeriod']['start'])
                        if 'end' in item['servicedPeriod']:
                            end_dates.append(item['servicedPeriod']['end'])
                    
                    # Extract service location
                    if 'locationCodeableConcept' in item and not service_info.service_location:
                        loc_coding = item['locationCodeableConcept'].get('coding', [])
                        for loc in loc_coding:
                            if loc.get('display'):
                                service_info.service_location = loc['display']
                                break
                
                # Store enhanced fields
                if all_cpts:
                    service_info.all_cpt_codes = all_cpts
                if all_cpt_descs:
                    service_info.all_cpt_descriptions = all_cpt_descs
                if all_hcpcs:
                    service_info.all_hcpcs_codes = all_hcpcs
                if all_hcpcs_descs:
                    service_info.all_hcpcs_descriptions = all_hcpcs_descs
                if all_rxnorm:
                    service_info.all_rxnorm_codes = all_rxnorm
                if all_rxnorm_descs:
                    service_info.all_rxnorm_descriptions = all_rxnorm_descs
                if session_counts:
                    service_info.session_counts = session_counts
                
                # Calculate treatment duration
                if start_dates and end_dates:
                    try:
                        earliest_start = min(start_dates)
                        latest_end = max(end_dates)
                        service_info.treatment_start_date = earliest_start
                        service_info.treatment_end_date = latest_end
                        
                        # Calculate duration in days
                        start_dt = datetime.fromisoformat(earliest_start.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(latest_end.replace('Z', '+00:00'))
                        duration = (end_dt - start_dt).days
                        service_info.treatment_duration_days = duration
                    except Exception as e:
                        logger.warning("Error calculating treatment duration", error=str(e))
            
            # ENHANCED EXTRACTION: Supporting information from Claim.supportingInfo
            if 'supportingInfo' in claim_resource:
                supporting_info_list = []
                for info in claim_resource['supportingInfo']:
                    # Extract category and code
                    category = info.get('category', {})
                    category_text = None
                    if 'coding' in category:
                        for coding in category['coding']:
                            if coding.get('display'):
                                category_text = coding['display']
                                break
                    if not category_text and 'text' in category:
                        category_text = category['text']
                    
                    # Extract code if present
                    code_info = info.get('code', {})
                    code_text = None
                    if 'coding' in code_info:
                        for coding in code_info['coding']:
                            if coding.get('display'):
                                code_text = coding['display']
                                break
                    if not code_text and 'text' in code_info:
                        code_text = code_info['text']
                    
                    # Extract value if present (string, boolean, quantity)
                    value_text = None
                    if 'valueString' in info:
                        value_text = info['valueString']
                    elif 'valueBoolean' in info:
                        value_text = str(info['valueBoolean'])
                    elif 'valueQuantity' in info:
                        qty = info['valueQuantity']
                        value_text = f"{qty.get('value', '')} {qty.get('unit', '')}".strip()
                    
                    # Extract timing if present
                    timing_text = None
                    if 'timingDate' in info:
                        timing_text = info['timingDate']
                    elif 'timingPeriod' in info:
                        period = info['timingPeriod']
                        if 'start' in period and 'end' in period:
                            timing_text = f"{period['start']} to {period['end']}"
                        elif 'start' in period:
                            timing_text = f"from {period['start']}"
                    
                    # Build supporting info string
                    info_parts = []
                    if category_text:
                        info_parts.append(category_text)
                    if code_text:
                        info_parts.append(code_text)
                    if value_text:
                        info_parts.append(value_text)
                    if timing_text:
                        info_parts.append(f"({timing_text})")
                    
                    if info_parts:
                        supporting_info_list.append(": ".join(info_parts))
                
                if supporting_info_list:
                    service_info.supporting_info = supporting_info_list
            
            logger.debug("Service information extracted",
                        cpt_code=service_info.cpt_code,
                        service_type=service_info.service_type,
                        all_cpt_codes_count=len(service_info.all_cpt_codes) if service_info.all_cpt_codes else 0)
            
        except Exception as e:
            logger.warning("Error extracting service from claim", error=str(e))
            raise FHIRParsingException(
                f"Failed to extract service info: {str(e)}",
                resource_type="Claim"
            )
    
    def _extract_diagnoses_from_claim(self, claim_resource: Dict, service_info: FHIRServiceInfo):
        """Extract diagnosis codes and descriptions from Claim resource"""
        diagnosis_codes = []
        diagnosis_descriptions = []
        
        try:
            if 'diagnosis' in claim_resource:
                for diag in claim_resource['diagnosis']:
                    if 'diagnosisCodeableConcept' in diag:
                        coding = diag['diagnosisCodeableConcept'].get('coding', [])
                        for code in coding:
                            # Look for ICD-10 codes
                            if code.get('system') == 'http://hl7.org/fhir/sid/icd-10-cm':
                                if code.get('code'):
                                    diagnosis_codes.append(code.get('code'))
                                if code.get('display'):
                                    diagnosis_descriptions.append(code.get('display'))
                            # Also handle other diagnosis coding systems
                            elif 'icd' in code.get('system', '').lower():
                                if code.get('code'):
                                    diagnosis_codes.append(code.get('code'))
                                if code.get('display'):
                                    diagnosis_descriptions.append(code.get('display'))
            
            if diagnosis_codes:
                service_info.diagnosis_codes = diagnosis_codes
            if diagnosis_descriptions:
                service_info.diagnosis_descriptions = diagnosis_descriptions
            
            logger.debug("Diagnosis information extracted",
                        codes_count=len(diagnosis_codes),
                        descriptions_count=len(diagnosis_descriptions))
            
        except Exception as e:
            logger.warning("Error extracting diagnoses from claim", error=str(e))
    
    def _extract_service_from_request(self, request_resource: Dict, resource_type: str,
                                     service_info: FHIRServiceInfo):
        """Extract service information from various FHIR request resources"""
        try:
            # Extract from code field (common across all request types)
            code_field = None
            if 'code' in request_resource:
                code_field = request_resource['code']
            elif 'medicationCodeableConcept' in request_resource:  # MedicationRequest
                code_field = request_resource['medicationCodeableConcept']
            elif 'codeCodeableConcept' in request_resource:  # DeviceRequest
                code_field = request_resource['codeCodeableConcept']
            
            if code_field:
                coding = code_field.get('coding', [])
                for code in coding:
                    # Handle CPT codes
                    if code.get('system') == 'http://www.ama-assn.org/go/cpt':
                        service_info.cpt_code = code.get('code')
                        service_info.cpt_description = code.get('display')
                        service_info.service_type = self._get_service_type_from_resource_type(resource_type)
                        break
                    # Handle HCPCS codes (for DME, supplies)
                    elif code.get('system') == 'https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets':
                        service_info.cpt_code = code.get('code')
                        service_info.cpt_description = code.get('display')
                        service_info.service_type = 'Supply/Equipment'
                        break
                    # Handle NDC codes (for medications)
                    elif code.get('system') == 'http://hl7.org/fhir/sid/ndc':
                        service_info.cpt_code = code.get('code')
                        service_info.cpt_description = code.get('display')
                        service_info.service_type = 'Medication'
                        service_info.drug_category = 'Prescription Drug'
                        break
                    # Handle RxNorm codes (for medications)
                    elif code.get('system') == 'http://www.nlm.nih.gov/research/umls/rxnorm':
                        service_info.cpt_code = code.get('code')
                        service_info.cpt_description = code.get('display')
                        service_info.service_type = 'Medication'
                        service_info.drug_category = 'Prescription Drug'
                        service_info.generic_drug_name = code.get('display')
                        break
                    # Handle SNOMED CT codes
                    elif code.get('system') == 'http://snomed.info/sct':
                        service_info.cpt_code = code.get('code')
                        service_info.cpt_description = code.get('display')
                        service_info.service_type = self._get_service_type_from_resource_type(resource_type)
                        break
            
            # Extract timing information (different fields for different resource types)
            timing_fields = ['occurrenceDateTime', 'occurrencePeriod', 'authoredOn', 'dispenseRequest']
            for field in timing_fields:
                if field in request_resource:
                    if field == 'occurrenceDateTime' or field == 'authoredOn':
                        service_info.procedure_date = request_resource[field]
                        break
                    elif field == 'occurrencePeriod':
                        period = request_resource[field]
                        if 'start' in period:
                            service_info.procedure_date = period['start']
                        break
                    elif field == 'dispenseRequest' and 'validityPeriod' in request_resource[field]:
                        validity = request_resource[field]['validityPeriod']
                        if 'start' in validity:
                            service_info.procedure_date = validity['start']
                        break
            
            logger.debug("Service information extracted from request",
                        resource_type=resource_type,
                        cpt_code=service_info.cpt_code)
            
        except Exception as e:
            logger.warning(f"Error extracting service from {resource_type}", error=str(e))
    
    def _get_service_type_from_resource_type(self, resource_type: str) -> str:
        """Map FHIR resource type to service type"""
        mapping = {
            'ServiceRequest': 'Service',
            'ProcedureRequest': 'Procedure',
            'DeviceRequest': 'Medical Device',
            'MedicationRequest': 'Medication'
        }
        return mapping.get(resource_type, 'Service')
    
    def _extract_document_content(self, document_resource: Dict) -> Optional[FHIRDocumentContent]:
        """Extract and decode content from FHIR DocumentReference resource"""
        try:
            doc_content = FHIRDocumentContent()
            
            # Extract document metadata
            if 'description' in document_resource:
                doc_content.title = document_resource['description']
            elif 'type' in document_resource and 'text' in document_resource['type']:
                doc_content.title = document_resource['type']['text']
            
            # Extract creation date
            if 'date' in document_resource:
                doc_content.creation_date = document_resource['date']
            
            # Extract content from attachment(s)
            if 'content' in document_resource:
                for content_item in document_resource['content']:
                    if 'attachment' in content_item:
                        attachment = content_item['attachment']
                        
                        # Get content type
                        if 'contentType' in attachment:
                            doc_content.content_type = attachment['contentType']
                        
                        # Get size
                        if 'size' in attachment:
                            doc_content.size = attachment['size']
                        
                        # Decode base64 content
                        if 'data' in attachment:
                            try:
                                encoded_data = attachment['data']
                                decoded_bytes = base64.b64decode(encoded_data)
                                
                                # Handle different content types
                                if doc_content.content_type:
                                    content_type_lower = doc_content.content_type.lower()
                                    
                                    if 'text/' in content_type_lower:
                                        # Text content - decode as UTF-8
                                        doc_content.decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                                    
                                    elif 'application/pdf' in content_type_lower:
                                        # PDF content - extract text using pypdf
                                        doc_content.decoded_text = self._extract_text_from_pdf_bytes(decoded_bytes)
                                    
                                    elif 'application/json' in content_type_lower:
                                        # JSON content
                                        try:
                                            json_data = json.loads(decoded_bytes.decode('utf-8'))
                                            doc_content.decoded_text = json.dumps(json_data, indent=2)
                                        except:
                                            doc_content.decoded_text = "[Invalid JSON content]"
                                    
                                    elif any(img_type in content_type_lower for img_type in 
                                           ['image/jpeg', 'image/jpg', 'image/png', 'image/tiff', 'image/gif']):
                                        # Image content - cannot extract text, but note the image
                                        doc_content.decoded_text = f"[Image file: {doc_content.content_type}, Size: {len(decoded_bytes)} bytes]"
                                        logger.debug("Image document detected", title=doc_content.title)
                                    
                                    elif 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type_lower:
                                        # Word document (.docx)
                                        doc_content.decoded_text = self._extract_text_from_docx_bytes(decoded_bytes)
                                    
                                    elif 'text/csv' in content_type_lower:
                                        # CSV content
                                        try:
                                            csv_text = decoded_bytes.decode('utf-8', errors='ignore')
                                            doc_content.decoded_text = f"CSV Data:\n{csv_text}"
                                        except:
                                            doc_content.decoded_text = "[CSV file - decoding failed]"
                                    
                                    elif any(xml_type in content_type_lower for xml_type in 
                                           ['application/xml', 'text/xml']):
                                        # XML content
                                        try:
                                            xml_text = decoded_bytes.decode('utf-8', errors='ignore')
                                            doc_content.decoded_text = f"XML Content:\n{xml_text}"
                                        except:
                                            doc_content.decoded_text = "[XML file - decoding failed]"
                                    
                                    elif 'application/rtf' in content_type_lower:
                                        # RTF content - try basic text extraction
                                        doc_content.decoded_text = self._extract_text_from_rtf_bytes(decoded_bytes)
                                    
                                    elif self._is_likely_text_content(decoded_bytes):
                                        # Unknown type but appears to be text - try UTF-8 decoding
                                        try:
                                            doc_content.decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                                            logger.warning("Unknown text content type", content_type=doc_content.content_type)
                                        except:
                                            doc_content.decoded_text = f"[Unknown content type - {doc_content.content_type}]"
                                    
                                    else:
                                        # Binary content that we can't process
                                        doc_content.decoded_text = f"[Binary content - {doc_content.content_type}, Size: {len(decoded_bytes)} bytes]"
                                        logger.debug("Binary document detected", title=doc_content.title)
                                
                                else:
                                    # No content type specified - try to detect and decode
                                    if self._is_likely_text_content(decoded_bytes):
                                        try:
                                            doc_content.decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                                            logger.warning("No content type specified, decoded as text")
                                        except:
                                            doc_content.decoded_text = "[Binary content - unknown type]"
                                    else:
                                        doc_content.decoded_text = f"[Binary content - unknown type, Size: {len(decoded_bytes)} bytes]"
                                
                                logger.debug("Decoded document",
                                           title=doc_content.title,
                                           content_length=len(doc_content.decoded_text) if doc_content.decoded_text else 0)
                                break  # Use first attachment with data
                                
                            except Exception as e:
                                logger.warning("Error decoding document content", error=str(e))
                                doc_content.decoded_text = f"[Error decoding content: {str(e)}]"
                        
                        elif 'url' in attachment:
                            # External URL reference - note it but don't fetch
                            doc_content.decoded_text = f"[External document URL: {attachment['url']}]"
            
            # Only return if we have meaningful content
            if doc_content.decoded_text and len(doc_content.decoded_text.strip()) > 10:
                return doc_content
            else:
                return None
                
        except Exception as e:
            logger.warning("Error extracting DocumentReference", error=str(e))
            return None
    
    def _extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes using pypdf"""
        try:
            import pypdf
            import io
            
            pdf_file = io.BytesIO(pdf_bytes)
            pdf_reader = pypdf.PdfReader(pdf_file)
            
            text_content = []
            
            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text.strip():
                        text_content.append(f"--- Page {page_num + 1} ---")
                        text_content.append(page_text.strip())
                except Exception as e:
                    logger.warning(f"Error extracting page {page_num + 1}", error=str(e))
                    continue
            
            if text_content:
                return '\n\n'.join(text_content)
            else:
                return "[PDF content could not be extracted]"
                
        except ImportError:
            return "[pypdf not available for PDF extraction]"
        except Exception as e:
            return f"[Error extracting PDF: {str(e)}]"
    
    def _extract_text_from_docx_bytes(self, docx_bytes: bytes) -> str:
        """Extract text from Word document bytes using python-docx"""
        try:
            import docx
            import io
            
            docx_file = io.BytesIO(docx_bytes)
            doc = docx.Document(docx_file)
            
            text_content = []
            
            # Extract paragraphs
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_content.append(paragraph.text.strip())
            
            # Extract tables
            for table in doc.tables:
                table_text = []
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        if cell.text.strip():
                            row_text.append(cell.text.strip())
                    if row_text:
                        table_text.append(' | '.join(row_text))
                
                if table_text:
                    text_content.append("--- Table ---")
                    text_content.extend(table_text)
            
            if text_content:
                return '\n\n'.join(text_content)
            else:
                return "[Word document content could not be extracted]"
                
        except ImportError:
            return "[python-docx not available for Word document extraction]"
        except Exception as e:
            return f"[Error extracting Word document: {str(e)}]"
    
    def _extract_text_from_rtf_bytes(self, rtf_bytes: bytes) -> str:
        """Extract text from RTF bytes using basic parsing"""
        try:
            import re
            
            # Try to decode as text first
            rtf_text = rtf_bytes.decode('utf-8', errors='ignore')
            
            # Basic RTF text extraction (remove RTF control codes)
            # Remove RTF header and control words
            text = re.sub(r'\\[a-z]+\d*\s?', '', rtf_text)
            text = re.sub(r'[{}]', '', text)
            text = re.sub(r'\\\*.*?;', '', text)
            text = re.sub(r'\\[^a-z]', '', text)
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            if text and len(text) > 10:
                return f"RTF Content (basic extraction):\n{text}"
            else:
                return "[RTF file - basic text extraction failed]"
                
        except Exception as e:
            return f"[Error extracting RTF: {str(e)}]"
    
    def _is_likely_text_content(self, data_bytes: bytes) -> bool:
        """Determine if bytes are likely to contain text content"""
        try:
            # Check if first 1KB contains mostly printable characters
            sample = data_bytes[:1024]
            
            # Try to decode as UTF-8
            try:
                text = sample.decode('utf-8')
            except UnicodeDecodeError:
                return False
            
            # Count printable characters
            printable_chars = sum(1 for c in text if c.isprintable() or c.isspace())
            total_chars = len(text)
            
            if total_chars == 0:
                return False
            
            # If more than 80% are printable, likely text
            printable_ratio = printable_chars / total_chars
            return printable_ratio > 0.8
            
        except Exception:
            return False
    
    def _map_to_extracted_data(self, patient_info: FHIRPatientInfo, coverage_info: FHIRCoverageInfo,
                               service_info: FHIRServiceInfo, document_id: str, full_text: str,
                               document_contents: List[FHIRDocumentContent],
                               patient_address_state: Optional[str] = None) -> ExtractedData:
        """Map FHIR data to ExtractedData model"""
        try:
            # Prepare CPT codes (validate format)
            cpt_codes = []
            if service_info.cpt_code:
                if MedicalCodeValidator.validate_cpt_code(service_info.cpt_code):
                    cpt_codes.append(service_info.cpt_code)
                else:
                    logger.warning("Invalid CPT code format", cpt_code=service_info.cpt_code)
            
            # Prepare ICD codes (validate format)
            icd_codes = []
            if service_info.diagnosis_codes:
                for code in service_info.diagnosis_codes:
                    if MedicalCodeValidator.validate_icd_code(code):
                        icd_codes.append(code)
                    else:
                        logger.warning("Invalid ICD code format", icd_code=code)
            
            # Create age range from DOB
            age_range = 'unknown'
            if patient_info.dob:
                age_range = create_age_range(patient_info.dob)
            
            # Anonymize patient ID
            patient_id = anonymize_patient_id(document_id)
            if patient_info.mrn:
                patient_id = anonymize_patient_id(patient_info.mrn)
            
            # Get primary diagnosis
            primary_diagnosis = ''
            if service_info.diagnosis_descriptions and len(service_info.diagnosis_descriptions) > 0:
                primary_diagnosis = service_info.diagnosis_descriptions[0]
            
            # Create PatientInfo object
            patient_info_obj = PatientInfo(
                patient_id=patient_id,
                age_range=age_range,
                gender=patient_info.gender or 'unknown',
                primary_diagnosis=primary_diagnosis,
                comorbidities=[]  # Could extract from additional Condition resources
            )
            
            # Build consolidated service_codes list for payor validation
            # Combine all service codes (CPT, HCPCS, RxNorm) into a single list
            consolidated_service_codes = []
            
            # Add primary CPT codes
            if cpt_codes:
                consolidated_service_codes.extend(cpt_codes)
            
            # Add all CPT codes (may include additional codes beyond primary)
            if service_info.all_cpt_codes:
                for code in service_info.all_cpt_codes:
                    if code not in consolidated_service_codes:
                        consolidated_service_codes.append(code)
            
            # Add HCPCS codes
            if service_info.all_hcpcs_codes:
                consolidated_service_codes.extend(service_info.all_hcpcs_codes)
            
            # Add RxNorm codes
            if service_info.all_rxnorm_codes:
                consolidated_service_codes.extend(service_info.all_rxnorm_codes)
            
            logger.debug("Consolidated service codes",
                        service_codes=consolidated_service_codes,
                        count=len(consolidated_service_codes))
            
            # Build structured_fields dictionary with extended information
            structured_fields = {
                'service_codes': consolidated_service_codes,  # Consolidated list for payor validation
                'patient_details': {
                    'name': patient_info.name,
                    'mrn': patient_info.mrn,
                    'dob': patient_info.dob,
                    'address': patient_info.address,
                    'phone': patient_info.phone
                },
                'coverage_details': {
                    'member_id': coverage_info.member_id,
                    'group_number': coverage_info.group_number,
                    'plan_name': coverage_info.plan_name,
                    'state': coverage_info.state,
                    'patient_address_state': patient_address_state  # Store for reference (like PDF extractor)
                },
                'service_details': {
                    'provider': service_info.provider,
                    'all_cpt_codes': service_info.all_cpt_codes,
                    'all_cpt_descriptions': service_info.all_cpt_descriptions,
                    'hcpcs_codes': service_info.all_hcpcs_codes,
                    'hcpcs_descriptions': service_info.all_hcpcs_descriptions,
                    'rxnorm_codes': service_info.all_rxnorm_codes,
                    'rxnorm_descriptions': service_info.all_rxnorm_descriptions,
                    'session_counts': service_info.session_counts,
                    'treatment_duration_days': service_info.treatment_duration_days,
                    'treatment_start_date': service_info.treatment_start_date,
                    'treatment_end_date': service_info.treatment_end_date,
                    'service_location': service_info.service_location,
                    'supporting_info': service_info.supporting_info,
                    'drug_category': service_info.drug_category,
                    'generic_drug_name': service_info.generic_drug_name
                },
                'diagnosis_details': {
                    'diagnosis_codes': service_info.diagnosis_codes,
                    'diagnosis_descriptions': service_info.diagnosis_descriptions
                },
                'extraction_metadata': {
                    'file_type': 'FHIR_JSON',
                    'extraction_method': 'FHIR_PARSING'
                }
            }
            
            # Calculate extraction confidence
            confidence_factors = []
            
            # CPT code confidence
            if cpt_codes:
                confidence_factors.append(1.0)
            else:
                confidence_factors.append(0.0)
            
            # ICD code confidence
            if icd_codes:
                confidence_factors.append(1.0)
            else:
                confidence_factors.append(0.5)
            
            # Payor confidence
            if coverage_info.payor:
                confidence_factors.append(1.0)
            else:
                confidence_factors.append(0.0)
            
            # Patient info confidence
            if patient_info.name and patient_info.dob:
                confidence_factors.append(1.0)
            elif patient_info.name or patient_info.dob:
                confidence_factors.append(0.7)
            else:
                confidence_factors.append(0.3)
            
            extraction_confidence = sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.5
            
            # Create ExtractedData object
            extracted_data = ExtractedData(
                document_id=document_id,
                cpt_codes=cpt_codes,
                icd_codes=icd_codes,
                service_type=service_info.service_type or 'unknown',
                payor_name=coverage_info.payor or '',
                plan_type=coverage_info.plan_type or 'unknown',
                patient_info=patient_info_obj,
                extraction_confidence=extraction_confidence,
                raw_text=full_text,  # Store complete text including decoded document contents
                coverage_state=coverage_info.state,  # Lowercase 2-letter state code from insurance coverage
                structured_fields=structured_fields
            )
            
            logger.info("Data model mapping completed",
                       document_id=document_id,
                       cpt_codes_count=len(cpt_codes),
                       icd_codes_count=len(icd_codes),
                       confidence=extraction_confidence)
            
            return extracted_data
            
        except Exception as e:
            logger.warning("Error mapping to ExtractedData model", error=str(e))
            raise FHIRParsingException(
                f"Failed to map data to ExtractedData model: {str(e)}",
                document_id=document_id
            )
