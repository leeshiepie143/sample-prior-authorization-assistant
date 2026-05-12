"""
Metadata filtering utilities for policy search.

This module provides two-tier metadata filtering for Bedrock Knowledge Base
to enable precise policy retrieval before semantic search.

Note: S3 Vectors storage only supports 'equals' operator for metadata filtering.
Procedure and ICD code filtering is performed post-retrieval during ranking.

Updated: 2025-11-10 - Enhanced logging for payor normalization debugging
"""

from typing import Dict, Any, List, Optional
from common.logging_config import get_logger
from common.exceptions import NoPayorPoliciesError, NoProcedurePoliciesError
from .code_range_matcher import is_code_in_range

logger = get_logger(__name__)


def normalize_payor_for_metadata(payor: str) -> str:
    """
    Normalize payor name to match S3 metadata format.
    
    S3 metadata stores payor as the base name without suffixes or plan types.
    For example: 
    - "Humana Inc." -> "Humana"
    - "Aetna Better Health" -> "Aetna"
    - "Anthem Blue Cross" -> "Anthem"
    
    Args:
        payor: Raw payor name from extraction
        
    Returns:
        Normalized payor name for metadata matching
    """
    # Remove common corporate suffixes and plan-specific names
    suffixes_to_remove = [
        # Corporate suffixes
        ' Inc.',
        ' Inc',
        ' LLC',
        ' LLC.',
        ' Corporation',
        ' Corp.',
        ' Corp',
        ' Company',
        ' Co.',
        ' Co',
        ' Limited',
        ' Ltd.',
        ' Ltd',
        # Plan-specific suffixes (order matters - check longer ones first)
        ' Better Health',
        ' Medicare Advantage',
        ' Medicare',
        ' Medicaid',
        ' Blue Cross Blue Shield',
        ' Blue Cross',
        ' Blue Shield',
        ' Health Plan',
        ' Health Plans',
        ' Health Insurance',
        ' Insurance',
        ' HealthCare',
        ' Health Care',
        ' Health'
    ]
    
    normalized = payor.strip()
    
    # Keep trying to remove suffixes until none match
    # This handles cases like "Aetna Better Health Inc."
    changed = True
    while changed:
        changed = False
        for suffix in suffixes_to_remove:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
                changed = True
                break
    
    logger.debug("Normalized payor for metadata",
                original=payor,
                normalized=normalized)
    
    return normalized


def create_tier1_filter(payor: str, procedure_codes: List[str], icd_codes: List[str]) -> Dict[str, Any]:
    """
    Create Tier 1 metadata filter: payor only (simplified for S3 Vectors).
    
    S3 Vectors storage type has limited metadata filtering support.
    Only 'equals' operator is reliably supported for exact matches.
    
    This filter retrieves policies that match:
    - Exact payor match
    
    Note: Procedure and ICD code filtering is done post-retrieval in ranking.
    
    Args:
        payor: Payor name (e.g., "Humana Inc.")
        procedure_codes: List of procedure codes (used for logging only)
        icd_codes: List of ICD diagnosis codes (used for logging only)
        
    Returns:
        Bedrock Knowledge Base filter dictionary
    """
    # Normalize payor to match S3 metadata format
    normalized_payor = normalize_payor_for_metadata(payor)
    
    # S3 Vectors only reliably supports 'equals' operator
    # Filter by payor only, then rank by procedure/ICD codes
    bedrock_filter = {
        "equals": {
            "key": "payor",
            "value": normalized_payor
        }
    }
    
    logger.info("Created Tier 1 filter (payor only)",
                original_payor=payor,
                normalized_payor=normalized_payor,
                procedure_codes_count=len(procedure_codes),
                icd_codes_count=len(icd_codes),
                bedrock_filter=bedrock_filter,
                note="S3 Vectors limitation - procedure/ICD filtering done in ranking")
    
    return bedrock_filter



def create_tier2_filter(payor: str, procedure_codes: List[str]) -> Dict[str, Any]:
    """
    Create Tier 2 metadata filter: payor only (simplified for S3 Vectors).
    
    S3 Vectors storage type has limited metadata filtering support.
    Only 'equals' operator is reliably supported for exact matches.
    
    This filter retrieves policies that match:
    - Exact payor match
    
    Note: Procedure code filtering is done post-retrieval in ranking.
    
    Args:
        payor: Payor name (e.g., "Humana Inc.")
        procedure_codes: List of procedure codes (used for logging only)
        
    Returns:
        Bedrock Knowledge Base filter dictionary
    """
    # Normalize payor to match S3 metadata format
    normalized_payor = normalize_payor_for_metadata(payor)
    
    # S3 Vectors only reliably supports 'equals' operator
    # Filter by payor only, then rank by procedure codes
    bedrock_filter = {
        "equals": {
            "key": "payor",
            "value": normalized_payor
        }
    }
    
    logger.info("Created Tier 2 filter (payor only)",
                original_payor=payor,
                normalized_payor=normalized_payor,
                procedure_codes_count=len(procedure_codes),
                bedrock_filter=bedrock_filter,
                note="S3 Vectors limitation - procedure filtering done in ranking")
    
    return bedrock_filter



def apply_two_tier_filtering(
    bedrock_retrieve_fn,
    query_text: str,
    payor: str,
    procedure_codes: List[str],
    icd_codes: List[str],
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    Apply two-tier metadata filtering with fallback logic.
    
    Tier 1: Payor + Procedure Codes + ICD Codes
    Tier 2: Payor + Procedure Codes only (if Tier 1 < max_results)
    
    Args:
        bedrock_retrieve_fn: Function to call Bedrock retrieve API
        query_text: Natural language search query
        payor: Payor name
        procedure_codes: List of procedure codes
        icd_codes: List of ICD codes
        max_results: Maximum total results to return
        
    Returns:
        List of search results with tier marking
    """
    results = []
    
    # Tier 1: Try with ICD codes
    if icd_codes:
        tier1_filter = create_tier1_filter(payor, procedure_codes, icd_codes)
        
        logger.info("Applying Tier 1 filter",
                   payor=payor,
                   procedure_codes=len(procedure_codes),
                   icd_codes=len(icd_codes))
        
        tier1_results = bedrock_retrieve_fn(
            query_text=query_text,
            filter=tier1_filter,
            max_results=max_results
        )
        
        # Mark as Tier 1
        for result in tier1_results:
            result['tier'] = 1
            results.append(result)
        
        logger.info("Tier 1 results retrieved",
                   count=len(tier1_results))
    
    # Tier 2: Fallback if we don't have enough results
    if len(results) < max_results:
        remaining_needed = max_results - len(results)
        
        tier2_filter = create_tier2_filter(payor, procedure_codes)
        
        logger.info("Applying Tier 2 filter",
                   payor=payor,
                   procedure_codes=len(procedure_codes),
                   remaining_needed=remaining_needed)
        
        tier2_results = bedrock_retrieve_fn(
            query_text=query_text,
            filter=tier2_filter,
            max_results=remaining_needed
        )
        
        # Mark as Tier 2 and add to results
        for result in tier2_results:
            result['tier'] = 2
            results.append(result)
        
        logger.info("Tier 2 results retrieved",
                   count=len(tier2_results),
                   total_results=len(results))
    
    # Check if we got any results
    if len(results) == 0:
        # Log the failed search
        logger.error("No policies found",
                   payor=payor,
                   procedure_codes=procedure_codes,
                   icd_codes=icd_codes)
        
        # Determine which error to raise
        # If we have procedure codes but no results, it's likely a procedure match issue
        if procedure_codes:
            raise NoProcedurePoliciesError(payor, procedure_codes)
        else:
            # No procedure codes specified, must be payor issue
            raise NoPayorPoliciesError(payor)
    
    return results[:max_results]



def get_result_tier(result: Dict[str, Any]) -> int:
    """
    Get the tier marking from a search result.
    
    Args:
        result: Search result dictionary
        
    Returns:
        Tier number (1 or 2), or 0 if not marked
    """
    return result.get('tier', 0)


def is_tier1_result(result: Dict[str, Any]) -> bool:
    """
    Check if a result is from Tier 1 (ICD-matching).
    
    Args:
        result: Search result dictionary
        
    Returns:
        True if Tier 1 result, False otherwise
    """
    return get_result_tier(result) == 1


def is_tier2_result(result: Dict[str, Any]) -> bool:
    """
    Check if a result is from Tier 2 (procedure-only).
    
    Args:
        result: Search result dictionary
        
    Returns:
        True if Tier 2 result, False otherwise
    """
    return get_result_tier(result) == 2
