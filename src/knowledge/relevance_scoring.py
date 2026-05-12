"""
Enhanced relevance scoring for policy search results.

This module implements the new scoring algorithm with weighted factors:
- Semantic similarity: 45%
- Diagnosis code match: 25%
- Clinical context match: 15%
- Patient condition relevance: 15%
"""

from typing import Dict, Any, List
from common.logging_config import get_logger
from .code_range_matcher import is_code_in_range

logger = get_logger(__name__)


def calculate_diagnosis_match_score(result: Dict[str, Any], query_icd_codes: List[str]) -> float:
    """
    Calculate diagnosis code match score (25% weight in total score).
    
    Checks if policy metadata "icd-codes" contains at least one matching ICD code or range.
    - 1.0 for match
    - 0.5 for no match (policies without ICD metadata still get partial credit)
    
    Args:
        result: Search result with metadata
        query_icd_codes: List of ICD codes from query
        
    Returns:
        Score between 0.5 and 1.0
    """
    if not query_icd_codes:
        # No ICD codes in query, give neutral score
        return 0.5
    
    # Get policy ICD codes from metadata
    metadata = result.get('metadata', {})
    policy_icd_codes_str = metadata.get('icd-codes', '')
    
    if not policy_icd_codes_str:
        # Policy has no ICD metadata, give partial credit
        return 0.5
    
    # Parse policy ICD codes (comma-separated)
    policy_icd_codes = [code.strip() for code in policy_icd_codes_str.split(',') if code.strip()]
    
    # Check for matches (including range matches)
    for query_code in query_icd_codes:
        for policy_code in policy_icd_codes:
            if is_code_in_range(query_code, policy_code):
                logger.debug("ICD code match found",
                           query_code=query_code,
                           policy_code=policy_code)
                return 1.0
    
    # No match found
    return 0.5



def calculate_clinical_context_score(result: Dict[str, Any], extraction_result: Dict[str, Any]) -> float:
    """
    Calculate clinical context match score (15% weight in total score).
    
    Assesses how well the policy text addresses:
    - Clinical justification
    - Test results
    - Medical necessity rationale
    
    Args:
        result: Search result with content
        extraction_result: Complete extraction result with clinical context
        
    Returns:
        Score between 0.0 and 1.0
    """
    content = result.get('content', '').lower()
    
    if not content:
        return 0.5
    
    # Get clinical context from extraction result
    structured_fields = extraction_result.get('structured_fields', {})
    raw_text = extraction_result.get('raw_text', '').lower()
    
    matches = 0
    total_checks = 0
    
    # Check for medical necessity / clinical justification
    medical_necessity = structured_fields.get('medical_necessity', '')
    if medical_necessity:
        total_checks += 1
        # Check if key terms from medical necessity appear in policy
        necessity_terms = medical_necessity.lower().split()
        # Look for at least 20% of terms
        term_matches = sum(1 for term in necessity_terms if len(term) > 3 and term in content)
        if term_matches >= len(necessity_terms) * 0.2:
            matches += 1
    
    # Check for test results mentions
    test_results = structured_fields.get('test_results', '')
    if test_results:
        total_checks += 1
        # Look for test-related terms
        test_terms = ['test', 'result', 'finding', 'study', 'imaging', 'lab', 'diagnostic']
        if any(term in content for term in test_terms):
            matches += 1
    
    # Check for clinical history relevance
    clinical_history = structured_fields.get('clinical_history', '')
    if clinical_history:
        total_checks += 1
        history_terms = clinical_history.lower().split()
        # Look for at least 15% of terms
        term_matches = sum(1 for term in history_terms if len(term) > 3 and term in content)
        if term_matches >= len(history_terms) * 0.15:
            matches += 1
    
    # Check for provider notes relevance
    provider_notes = structured_fields.get('provider_notes', '')
    if provider_notes:
        total_checks += 1
        notes_terms = provider_notes.lower().split()
        # Look for at least 15% of terms
        term_matches = sum(1 for term in notes_terms if len(term) > 3 and term in content)
        if term_matches >= len(notes_terms) * 0.15:
            matches += 1
    
    # If no clinical context available, return neutral score
    if total_checks == 0:
        return 0.5
    
    # Calculate score based on matches
    score = matches / total_checks
    
    logger.debug("Clinical context score calculated",
                matches=matches,
                total_checks=total_checks,
                score=score)
    
    return score



def calculate_patient_condition_score(result: Dict[str, Any], extraction_result: Dict[str, Any]) -> float:
    """
    Calculate patient condition relevance score (15% weight in total score).
    
    Assesses matches for:
    - Patient age range
    - Patient gender
    - Comorbidities
    
    Args:
        result: Search result with content
        extraction_result: Complete extraction result with patient info
        
    Returns:
        Score between 0.0 and 1.0
    """
    content = result.get('content', '').lower()
    
    if not content:
        return 0.5
    
    # Get patient info
    patient_info = extraction_result.get('patient_info', {})
    
    if not patient_info:
        return 0.5
    
    score = 0.0
    factors = 0
    
    # Check age range
    age_range = patient_info.get('age_range', '')
    if age_range:
        factors += 1
        # Check if age range or individual ages mentioned
        if age_range in content:
            score += 1.0
        else:
            # Check for individual ages in range (e.g., "60-70" -> check for "60", "65", "70")
            if '-' in age_range:
                try:
                    start_age, end_age = age_range.split('-')
                    # Check if any age in range is mentioned
                    if any(str(age) in content for age in [start_age, end_age, str((int(start_age) + int(end_age)) // 2)]):
                        score += 0.5  # Partial credit
                except:  # nosec B110
                    pass
    
    # Check gender
    gender = patient_info.get('gender', '')
    if gender:
        factors += 1
        if gender.lower() in content:
            score += 1.0
    
    # Check comorbidities
    comorbidities = patient_info.get('comorbidities', [])
    if comorbidities and isinstance(comorbidities, list):
        factors += 1
        # Count how many comorbidities are mentioned in policy
        matching_comorbidities = sum(
            1 for condition in comorbidities
            if condition.lower() in content
        )
        
        if matching_comorbidities > 0:
            # Score proportional to matching comorbidities
            comorbidity_score = min(1.0, matching_comorbidities / len(comorbidities))
            score += comorbidity_score
    
    # If no patient factors to check, return neutral score
    if factors == 0:
        return 0.5
    
    # Calculate average score
    final_score = score / factors
    
    logger.debug("Patient condition score calculated",
                factors=factors,
                score=final_score)
    
    return final_score



def calculate_enhanced_relevance_score(
    result: Dict[str, Any],
    extraction_result: Dict[str, Any],
    apply_tier_boost: bool = True
) -> float:
    """
    Calculate enhanced relevance score with weighted factors.
    
    Weights:
    - Semantic similarity (Bedrock): 45%
    - Diagnosis code match: 25%
    - Clinical context match: 15%
    - Patient condition relevance: 15%
    
    Tier 1 results (ICD-matching) receive a 10% boost.
    
    Args:
        result: Search result with content, metadata, and score
        extraction_result: Complete extraction result
        apply_tier_boost: Whether to apply tier boost (default True)
        
    Returns:
        Final relevance score between 0.0 and 1.0
    """
    # Get Bedrock semantic similarity score (45% weight)
    semantic_score = result.get('score', 0.0)
    
    # Get ICD codes from extraction result
    query_icd_codes = extraction_result.get('icd_codes', [])
    
    # Calculate diagnosis code match score (25% weight)
    diagnosis_score = calculate_diagnosis_match_score(result, query_icd_codes)
    
    # Calculate clinical context match score (15% weight)
    clinical_score = calculate_clinical_context_score(result, extraction_result)
    
    # Calculate patient condition relevance score (15% weight)
    patient_score = calculate_patient_condition_score(result, extraction_result)
    
    # Calculate weighted total
    total_score = (
        0.45 * semantic_score +
        0.25 * diagnosis_score +
        0.15 * clinical_score +
        0.15 * patient_score
    )
    
    # Apply tier boost if enabled and result is Tier 1
    if apply_tier_boost and result.get('tier') == 1:
        total_score *= 1.1  # 10% boost for ICD-matching policies
        logger.debug("Applied Tier 1 boost", original_score=total_score / 1.1, boosted_score=total_score)
    
    # Cap at 1.0
    final_score = min(1.0, total_score)
    
    logger.info("Enhanced relevance score calculated",
               semantic_score=semantic_score,
               diagnosis_score=diagnosis_score,
               clinical_score=clinical_score,
               patient_score=patient_score,
               final_score=final_score,
               tier=result.get('tier', 0))
    
    return final_score
