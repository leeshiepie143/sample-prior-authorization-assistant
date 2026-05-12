"""
Service code extraction logic.

Extracts service codes (CPT, HCPCS, RxNorm, J-codes) from extraction result.
Updated to extract HCPCS and RxNorm codes from structured_fields.
"""

from typing import List
import structlog

logger = structlog.get_logger(__name__)


def extract_service_codes_from_extraction_result(extraction_result: dict) -> List[str]:
    """
    Extract service codes from extraction result.
    
    Handles nested structure from Step Functions and extracts all types of service codes:
    - CPT codes
    - HCPCS codes
    - RxNorm codes
    - J-codes
    
    Args:
        extraction_result: Extraction result from Step Functions
        
    Returns:
        List of service codes (may be empty if none found)
    """
    service_codes = []
    
    # Helper function to safely navigate nested dicts
    def get_nested(data, path):
        try:
            value = data
            for key in path:
                value = value[key]
            return value
        except (KeyError, TypeError, AttributeError):
            return None
    
    # Extract CPT codes from top-level cpt_codes field
    cpt_paths = [
        ['extraction_result', 'Payload', 'extraction_result', 'cpt_codes'],
        ['Payload', 'extraction_result', 'cpt_codes'],
        ['extraction_result', 'cpt_codes'],
        ['cpt_codes']
    ]
    
    for path in cpt_paths:
        value = get_nested(extraction_result, path)
        if value:
            if isinstance(value, list):
                service_codes.extend([str(code) for code in value if code])
                logger.debug("Found CPT codes", path=path, codes=value)
            elif isinstance(value, str):
                codes = [code.strip() for code in value.split(',') if code.strip()]
                service_codes.extend(codes)
                logger.debug("Found CPT codes (string)", path=path, codes=codes)
            break
    
    # Extract HCPCS codes from structured_fields.service_details.hcpcs_codes
    hcpcs_paths = [
        ['extraction_result', 'Payload', 'extraction_result', 'structured_fields', 'service_details', 'hcpcs_codes'],
        ['Payload', 'extraction_result', 'structured_fields', 'service_details', 'hcpcs_codes'],
        ['extraction_result', 'structured_fields', 'service_details', 'hcpcs_codes'],
        ['structured_fields', 'service_details', 'hcpcs_codes']
    ]
    
    for path in hcpcs_paths:
        value = get_nested(extraction_result, path)
        if value and isinstance(value, list):
            service_codes.extend([str(code) for code in value if code])
            logger.debug("Found HCPCS codes", path=path, codes=value)
            break
    
    # Extract RxNorm codes from structured_fields.service_details.rxnorm_codes
    rxnorm_paths = [
        ['extraction_result', 'Payload', 'extraction_result', 'structured_fields', 'service_details', 'rxnorm_codes'],
        ['Payload', 'extraction_result', 'structured_fields', 'service_details', 'rxnorm_codes'],
        ['extraction_result', 'structured_fields', 'service_details', 'rxnorm_codes'],
        ['structured_fields', 'service_details', 'rxnorm_codes']
    ]
    
    for path in rxnorm_paths:
        value = get_nested(extraction_result, path)
        if value and isinstance(value, list):
            service_codes.extend([str(code) for code in value if code])
            logger.debug("Found RxNorm codes", path=path, codes=value)
            break
    
    # Remove duplicates while preserving order
    unique_codes = []
    seen = set()
    for code in service_codes:
        if code not in seen:
            unique_codes.append(code)
            seen.add(code)
    
    logger.info(
        "Extracted service codes from extraction result",
        service_codes=unique_codes,
        count=len(unique_codes)
    )
    
    return unique_codes
