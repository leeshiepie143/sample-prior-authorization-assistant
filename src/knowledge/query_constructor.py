"""
Query construction utilities for enhanced policy search.

This module provides functions to build rich, clinical-context-aware search queries
from extraction results, including code descriptions, patient demographics, and
clinical context.
"""

from typing import Dict, Any, List, Optional
from common.logging_config import get_logger

logger = get_logger(__name__)


def extract_code_descriptions(extraction_result: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Extract code descriptions from extraction result.
    
    Args:
        extraction_result: The complete extraction result containing structured_fields
        
    Returns:
        Dictionary with keys:
        - cpt_descriptions: List of CPT code descriptions
        - hcpcs_descriptions: List of HCPCS code descriptions
        - rxnorm_descriptions: List of RxNorm medication descriptions
        - icd_descriptions: List of ICD diagnosis descriptions
    """
    descriptions = {
        'cpt_descriptions': [],
        'hcpcs_descriptions': [],
        'rxnorm_descriptions': [],
        'icd_descriptions': []
    }
    
    structured_fields = extraction_result.get('structured_fields', {})
    
    # Extract service details (CPT, HCPCS, RxNorm)
    service_details = structured_fields.get('service_details', {})
    
    # CPT descriptions
    all_cpt_descriptions = service_details.get('all_cpt_descriptions', [])
    if isinstance(all_cpt_descriptions, list):
        descriptions['cpt_descriptions'] = all_cpt_descriptions
    elif isinstance(all_cpt_descriptions, str):
        descriptions['cpt_descriptions'] = [all_cpt_descriptions]
    
    # HCPCS descriptions
    hcpcs_descriptions = service_details.get('hcpcs_descriptions', [])
    if isinstance(hcpcs_descriptions, list):
        descriptions['hcpcs_descriptions'] = hcpcs_descriptions
    elif isinstance(hcpcs_descriptions, str):
        descriptions['hcpcs_descriptions'] = [hcpcs_descriptions]
    
    # RxNorm descriptions
    rxnorm_descriptions = service_details.get('rxnorm_descriptions', [])
    if isinstance(rxnorm_descriptions, list):
        descriptions['rxnorm_descriptions'] = rxnorm_descriptions
    elif isinstance(rxnorm_descriptions, str):
        descriptions['rxnorm_descriptions'] = [rxnorm_descriptions]
    
    # Extract diagnosis details (ICD)
    diagnosis_details = structured_fields.get('diagnosis_details', {})
    
    # ICD descriptions
    diagnosis_descriptions = diagnosis_details.get('diagnosis_descriptions', [])
    if isinstance(diagnosis_descriptions, list):
        descriptions['icd_descriptions'] = diagnosis_descriptions
    elif isinstance(diagnosis_descriptions, str):
        descriptions['icd_descriptions'] = [diagnosis_descriptions]
    
    logger.debug("Extracted code descriptions",
                cpt_count=len(descriptions['cpt_descriptions']),
                hcpcs_count=len(descriptions['hcpcs_descriptions']),
                rxnorm_count=len(descriptions['rxnorm_descriptions']),
                icd_count=len(descriptions['icd_descriptions']))
    
    return descriptions


def extract_clinical_context(raw_text: str, structured_fields: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Extract clinical context from raw text and structured fields.
    
    Looks for key clinical information such as:
    - Chief complaint
    - Clinical history
    - Test results
    - Medical necessity rationale
    - Provider notes
    
    Args:
        raw_text: The raw text from the extraction result
        structured_fields: Optional structured fields that may contain clinical context
        
    Returns:
        Dictionary with clinical context fields (empty strings if not found)
    """
    context = {
        'chief_complaint': '',
        'clinical_history': '',
        'test_results': '',
        'medical_necessity': '',
        'provider_notes': ''
    }
    
    if not raw_text:
        return context
    
    raw_text_lower = raw_text.lower()
    
    # Extract chief complaint
    chief_complaint_patterns = [
        r'chief complaint[:\s]+([^\n.]+)',
        r'presenting complaint[:\s]+([^\n.]+)',
        r'reason for visit[:\s]+([^\n.]+)',
        r'cc[:\s]+([^\n.]+)'
    ]
    context['chief_complaint'] = _extract_with_patterns(raw_text, chief_complaint_patterns)
    
    # Extract clinical history
    history_patterns = [
        r'clinical history[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'history of present illness[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'hpi[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'medical history[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)'
    ]
    context['clinical_history'] = _extract_with_patterns(raw_text, history_patterns)
    
    # Extract test results
    test_patterns = [
        r'test results?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'diagnostic findings?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'lab results?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'imaging results?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'stress test[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)'
    ]
    context['test_results'] = _extract_with_patterns(raw_text, test_patterns)
    
    # Extract medical necessity rationale
    necessity_patterns = [
        r'medical necessity[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'clinical justification[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'rationale[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'indication[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)'
    ]
    context['medical_necessity'] = _extract_with_patterns(raw_text, necessity_patterns)
    
    # Extract provider notes
    notes_patterns = [
        r'provider notes?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'physician notes?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'clinical notes?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'assessment[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)'
    ]
    context['provider_notes'] = _extract_with_patterns(raw_text, notes_patterns)
    
    # Check structured fields for additional context
    if structured_fields:
        # Override with structured field values if present
        if 'chief_complaint' in structured_fields and structured_fields['chief_complaint']:
            context['chief_complaint'] = structured_fields['chief_complaint']
        if 'clinical_history' in structured_fields and structured_fields['clinical_history']:
            context['clinical_history'] = structured_fields['clinical_history']
        if 'test_results' in structured_fields and structured_fields['test_results']:
            context['test_results'] = structured_fields['test_results']
        if 'medical_necessity' in structured_fields and structured_fields['medical_necessity']:
            context['medical_necessity'] = structured_fields['medical_necessity']
        if 'provider_notes' in structured_fields and structured_fields['provider_notes']:
            context['provider_notes'] = structured_fields['provider_notes']
    
    # Truncate each field to reasonable length (200 chars each)
    for key in context:
        if context[key]:
            context[key] = context[key][:200].strip()
    
    logger.debug("Extracted clinical context",
                has_chief_complaint=bool(context['chief_complaint']),
                has_clinical_history=bool(context['clinical_history']),
                has_test_results=bool(context['test_results']),
                has_medical_necessity=bool(context['medical_necessity']),
                has_provider_notes=bool(context['provider_notes']))
    
    return context


def _extract_with_patterns(text: str, patterns: List[str]) -> str:
    """
    Extract text using multiple regex patterns.
    
    Args:
        text: Text to search
        patterns: List of regex patterns to try
        
    Returns:
        Extracted text or empty string if no match
    """
    import re
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            extracted = match.group(1).strip()
            # Clean up extra whitespace
            extracted = re.sub(r'\s+', ' ', extracted)
            return extracted
    
    return ''



def build_search_query(extraction_result: Dict[str, Any]) -> str:
    """
    Build a prioritized natural language search query from extraction result.
    
    Query components are ordered by importance for policy matching:
    1. CPT codes + descriptions (most important)
    2. Primary diagnosis + ICD codes
    3. Payor name
    4. Conservative treatment history
    5. Imaging/test results
    6. Functional limitations
    7. Patient demographics
    8. Comorbidities
    9. Service type
    10. Urgency level
    
    Args:
        extraction_result: Complete extraction result with all fields
        
    Returns:
        Prioritized natural language search query string
    """
    query_parts = []
    
    # Extract code descriptions
    descriptions = extract_code_descriptions(extraction_result)
    
    # Get raw codes from extraction result
    cpt_codes = extraction_result.get('cpt_codes', [])
    icd_codes = extraction_result.get('icd_codes', [])
    service_type = extraction_result.get('service_type', '')
    payor_name = extraction_result.get('payor_name', '')
    
    # Get structured fields
    structured_fields = extraction_result.get('structured_fields', {})
    service_details = structured_fields.get('service_details', {})
    hcpcs_codes = service_details.get('hcpcs_codes', [])
    rxnorm_codes = service_details.get('rxnorm_codes', [])
    patient_info = extraction_result.get('patient_info', {})
    
    # Extract clinical context
    raw_text = extraction_result.get('raw_text', '')
    clinical_context = extract_clinical_context(raw_text, structured_fields)
    
    # PRIORITY 1: CPT codes + descriptions (MOST IMPORTANT)
    if cpt_codes or descriptions['cpt_descriptions']:
        cpt_parts = []
        if cpt_codes:
            cpt_parts.append(f"CPT {', '.join(cpt_codes)}")
        if descriptions['cpt_descriptions']:
            cpt_parts.append(' - '.join(descriptions['cpt_descriptions']))
        query_parts.append(f"Procedure: {' '.join(cpt_parts)}")
    
    # Add HCPCS codes + descriptions (if present)
    if hcpcs_codes or descriptions['hcpcs_descriptions']:
        hcpcs_parts = []
        if hcpcs_codes:
            hcpcs_parts.append(f"HCPCS {', '.join(hcpcs_codes)}")
        if descriptions['hcpcs_descriptions']:
            hcpcs_parts.append(' - '.join(descriptions['hcpcs_descriptions']))
        query_parts.append(f"Equipment/Services: {' '.join(hcpcs_parts)}")
    
    # Add RxNorm codes + descriptions (if present)
    if rxnorm_codes or descriptions['rxnorm_descriptions']:
        rxnorm_parts = []
        if rxnorm_codes:
            rxnorm_parts.append(f"RxNorm {', '.join(rxnorm_codes)}")
        if descriptions['rxnorm_descriptions']:
            rxnorm_parts.append(' - '.join(descriptions['rxnorm_descriptions']))
        query_parts.append(f"Medication: {' '.join(rxnorm_parts)}")
    
    # PRIORITY 2: Primary diagnosis + ICD codes
    primary_diagnosis = patient_info.get('primary_diagnosis', '')
    if primary_diagnosis:
        query_parts.append(f"Primary diagnosis: {primary_diagnosis}")
    
    if icd_codes or descriptions['icd_descriptions']:
        icd_parts = []
        if icd_codes:
            icd_parts.append(f"ICD {', '.join(icd_codes)}")
        if descriptions['icd_descriptions']:
            # Only add descriptions if different from primary diagnosis
            icd_desc_text = ', '.join(descriptions['icd_descriptions'])
            if not primary_diagnosis or primary_diagnosis.lower() not in icd_desc_text.lower():
                icd_parts.append(icd_desc_text)
        if icd_parts:
            query_parts.append(f"Diagnosis codes: {' - '.join(icd_parts)}")
    
    # PRIORITY 3: Payor name
    if payor_name:
        query_parts.append(f"Insurance payor: {payor_name}")
    
    # PRIORITY 4: Conservative treatment history (CRITICAL for many policies)
    conservative_treatment = _extract_conservative_treatment(raw_text, clinical_context)
    if conservative_treatment:
        query_parts.append(f"Conservative treatments: {conservative_treatment}")
    
    # PRIORITY 5: Imaging/test results
    if clinical_context['test_results']:
        query_parts.append(f"Diagnostic findings: {clinical_context['test_results']}")
    
    # PRIORITY 6: Functional limitations
    functional_limitations = _extract_functional_limitations(raw_text, clinical_context)
    if functional_limitations:
        query_parts.append(f"Functional limitations: {functional_limitations}")
    
    # PRIORITY 7: Patient demographics (age, gender)
    demographics = []
    if patient_info.get('age_range'):
        demographics.append(f"{patient_info['age_range']} years old")
    if patient_info.get('gender'):
        demographics.append(patient_info['gender'])
    if demographics:
        query_parts.append(f"Patient: {' '.join(demographics)}")
    
    # PRIORITY 8: Comorbidities
    if patient_info.get('comorbidities'):
        comorbidities_list = patient_info['comorbidities']
        if isinstance(comorbidities_list, list) and comorbidities_list:
            comorbidities_text = ', '.join(comorbidities_list)
            query_parts.append(f"Comorbidities: {comorbidities_text}")
    
    # PRIORITY 9: Service type
    if service_type:
        query_parts.append(f"Service type: {service_type}")
    
    # PRIORITY 10: Urgency level (if specified)
    urgency_level = extraction_result.get('urgency_level', 'routine')
    if urgency_level and urgency_level != 'routine':
        query_parts.append(f"Urgency: {urgency_level}")
    
    # Add clinical context fields that have content (lower priority)
    if clinical_context['chief_complaint']:
        query_parts.append(f"Chief complaint: {clinical_context['chief_complaint']}")
    
    if clinical_context['clinical_history']:
        query_parts.append(f"Clinical history: {clinical_context['clinical_history']}")
    
    if clinical_context['medical_necessity']:
        query_parts.append(f"Medical necessity: {clinical_context['medical_necessity']}")
    
    # Add search directive - tell the KB what we're looking for
    # This helps guide semantic search to find the right policy sections
    # Include payor to reinforce the insurance context
    if payor_name:
        search_directive = f"Find the {payor_name} insurance coverage policy that defines medical necessity criteria, clinical requirements, and documentation standards for this procedure and diagnosis"
    else:
        search_directive = "Find the insurance coverage policy that defines medical necessity criteria, clinical requirements, and documentation standards for this procedure and diagnosis"
    query_parts.append(search_directive)
    
    # Combine all parts
    full_query = '. '.join(query_parts)
    
    # Truncate to 500 tokens max
    truncated_query = truncate_to_tokens(full_query, max_tokens=500)
    
    logger.info("Built prioritized search query",
               payor=payor_name,
               query_length=len(truncated_query),
               parts_count=len(query_parts),
               has_conservative_treatment=bool(conservative_treatment),
               has_functional_limitations=bool(functional_limitations),
               truncated=len(truncated_query) < len(full_query))
    
    return truncated_query



def _extract_conservative_treatment(raw_text: str, clinical_context: Dict[str, str]) -> str:
    """
    Extract conservative treatment history from raw text.
    
    This is CRITICAL for many policies (especially orthopedic/spinal procedures)
    that require documentation of failed conservative therapy.
    
    Args:
        raw_text: Raw text from medical records
        clinical_context: Extracted clinical context
        
    Returns:
        Conservative treatment summary or empty string
    """
    if not raw_text:
        return ''
    
    import re
    
    raw_text_lower = raw_text.lower()
    
    # Look for conservative treatment sections
    conservative_patterns = [
        r'conservative treatment[s]?\s*(?:attempted|tried|failed)?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'non-surgical treatment[s]?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'prior treatment[s]?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'failed conservative (?:therapy|treatment)[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)'
    ]
    
    for pattern in conservative_patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE)
        if match:
            treatment_text = match.group(1).strip()
            # Clean up and truncate
            treatment_text = re.sub(r'\s+', ' ', treatment_text)
            return treatment_text[:200]
    
    # Look for specific treatment mentions
    treatments_found = []
    treatment_keywords = {
        'physical therapy': r'physical therapy|pt sessions?',
        'medications': r'nsaids?|pain medication|analgesics',
        'injections': r'injection|epidural|steroid',
        'rest': r'rest|bed rest',
        'bracing': r'brace|bracing|orthotic',
        'chiropractic': r'chiropractic|manipulation'
    }
    
    for treatment_name, pattern in treatment_keywords.items():
        if re.search(pattern, raw_text_lower):
            # Try to find duration
            duration_match = re.search(
                f'{pattern}[^.]*?(\d+\s*(?:week|month|day|session)s?)',
                raw_text_lower
            )
            if duration_match:
                treatments_found.append(f"{treatment_name} ({duration_match.group(1)})")
            else:
                treatments_found.append(treatment_name)
    
    if treatments_found:
        return ', '.join(treatments_found[:5])  # Limit to 5 treatments
    
    return ''


def _extract_functional_limitations(raw_text: str, clinical_context: Dict[str, str]) -> str:
    """
    Extract functional limitations from raw text.
    
    Many policies require documentation of how the condition impacts
    activities of daily living (ADLs) and functional capacity.
    
    Args:
        raw_text: Raw text from medical records
        clinical_context: Extracted clinical context
        
    Returns:
        Functional limitations summary or empty string
    """
    if not raw_text:
        return ''
    
    import re
    
    raw_text_lower = raw_text.lower()
    
    # Look for functional limitation sections
    limitation_patterns = [
        r'functional limitation[s]?[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'activities of daily living[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'adl[s]?\s*(?:impact|limitation)[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)',
        r'difficulty (?:with|performing)[:\s]+([^\n]+(?:\n(?!\n)[^\n]+)*)'
    ]
    
    for pattern in limitation_patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE)
        if match:
            limitation_text = match.group(1).strip()
            # Clean up and truncate
            limitation_text = re.sub(r'\s+', ' ', limitation_text)
            return limitation_text[:200]
    
    # Look for specific limitation mentions
    limitations_found = []
    limitation_keywords = {
        'walking': r'difficulty walking|unable to walk|limited ambulation',
        'standing': r'difficulty standing|cannot stand|limited standing',
        'sitting': r'difficulty sitting|cannot sit|limited sitting',
        'bending': r'difficulty bending|cannot bend|limited flexion',
        'lifting': r'difficulty lifting|cannot lift|limited lifting',
        'climbing stairs': r'difficulty (?:climbing )?stairs|cannot climb stairs',
        'range of motion': r'limited (?:range of )?motion|decreased (?:range of )?motion|restricted motion'
    }
    
    for limitation_name, pattern in limitation_keywords.items():
        if re.search(pattern, raw_text_lower):
            limitations_found.append(limitation_name)
    
    if limitations_found:
        return ', '.join(limitations_found[:5])  # Limit to 5 limitations
    
    return ''


def truncate_to_tokens(text: str, max_tokens: int = 500) -> str:
    """
    Truncate text to a maximum number of tokens.
    
    Uses a simple approximation: 1 token ≈ 4 characters for English text.
    This is a conservative estimate that works well for medical text.
    
    Args:
        text: Text to truncate
        max_tokens: Maximum number of tokens (default 500)
        
    Returns:
        Truncated text
    """
    if not text:
        return text
    
    # Approximate: 1 token ≈ 4 characters
    max_chars = max_tokens * 4
    
    if len(text) <= max_chars:
        return text
    
    # Truncate at word boundary
    truncated = text[:max_chars]
    
    # Find last complete word
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space]
    # If no space found, keep the truncated text as is
    
    logger.debug("Truncated query text",
                original_length=len(text),
                truncated_length=len(truncated),
                max_tokens=max_tokens)
    
    return truncated
