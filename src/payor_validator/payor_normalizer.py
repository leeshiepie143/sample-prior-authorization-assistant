"""
Payor name normalization logic.

Converts payor names from various formats to S3 prefix format.
"""

import re
import structlog

logger = structlog.get_logger(__name__)


def normalize_payor_name(payor: str) -> str:
    """
    Normalize payor name to S3 prefix format.
    
    This function is dynamic and works with ANY payor name extracted from 
    the prior auth request.
    
    Examples:
    - "Humana Inc." → "HumanaPolicy"
    - "Aetna LLC" → "AetnaPolicy"
    - "UnitedHealthcare Corp." → "UnitedHealthcarePolicy"
    - "Blue Cross Blue Shield" → "BlueCrossBlueShieldPolicy"
    
    Args:
        payor: Payor name from extraction result
        
    Returns:
        Normalized payor name with "Policy" suffix
        
    Raises:
        ValueError: If payor name is empty or invalid
    """
    if not payor or not payor.strip():
        raise ValueError("Payor name cannot be empty")
    
    original_payor = payor
    
    # Remove common suffixes and plan-specific names
    suffixes_to_remove = [
        # Corporate suffixes
        " Inc.",
        " LLC",
        " Corporation",
        " Corp.",
        " Company",
        " Co.",
        " Limited",
        " Ltd.",
        ", Inc.",
        ", LLC",
        ", Corp.",
        # Plan-specific suffixes (order matters - check longer ones first)
        " Better Health",
        " Medicare Advantage",
        " Medicare",
        " Medicaid",
        " Blue Cross Blue Shield",
        " Blue Cross",
        " Blue Shield",
        " Health Plan",
        " Health Plans",
        " Health Insurance",
        " Insurance",
        " HealthCare",
        " Health Care",
        " Health"
    ]
    
    # Keep trying to remove suffixes until none match
    # This handles cases like "Aetna Better Health Inc."
    changed = True
    while changed:
        changed = False
        for suffix in suffixes_to_remove:
            if payor.endswith(suffix):
                payor = payor[:-len(suffix)].strip()
                changed = True
                break
    
    # Remove special characters (keep only alphanumeric)
    payor = re.sub(r'[^a-zA-Z0-9]', '', payor)
    
    if not payor:
        raise ValueError(f"Payor name '{original_payor}' resulted in empty string after normalization")
    
    # Add "Policy" suffix
    normalized = f"{payor}Policy"
    
    logger.debug(
        "Normalized payor name",
        original=original_payor,
        normalized=normalized
    )
    
    return normalized


def extract_payor_from_extraction_result(extraction_result: dict) -> str:
    """
    Extract payor name from extraction result.
    
    Handles nested structure from Step Functions.
    
    Args:
        extraction_result: Extraction result from Step Functions
        
    Returns:
        Payor name
        
    Raises:
        ValueError: If payor name not found in extraction result
    """
    # Try different possible paths in the extraction result
    possible_paths = [
        ['extraction_result', 'Payload', 'extraction_result', 'payor_name'],
        ['Payload', 'extraction_result', 'payor_name'],
        ['extraction_result', 'payor_name'],
        ['payor_name'],
        ['extraction_result', 'Payload', 'extraction_result', 'structured_fields', 'payor_info', 'payor_name'],
        ['structured_fields', 'payor_info', 'payor_name']
    ]
    
    for path in possible_paths:
        try:
            value = extraction_result
            for key in path:
                value = value[key]
            
            if value and isinstance(value, str):
                logger.debug(
                    "Found payor name in extraction result",
                    path=path,
                    payor_name=value
                )
                return value
        except (KeyError, TypeError):
            continue
    
    # If not found, log the structure for debugging
    logger.error(
        "Could not find payor name in extraction result",
        extraction_result_keys=list(extraction_result.keys()) if isinstance(extraction_result, dict) else None
    )
    
    raise ValueError("Payor name not found in extraction result")
