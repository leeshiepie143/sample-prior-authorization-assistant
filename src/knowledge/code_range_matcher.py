"""
Code range matching utilities for policy search.

This module provides functions to parse and match medical codes against ranges,
supporting CPT, HCPCS, J-codes, and ICD code formats.
"""

from typing import Tuple, Optional
import re
from common.logging_config import get_logger

logger = get_logger(__name__)


def parse_code_range(range_str: str) -> Optional[Tuple[str, str]]:
    """
    Parse a code range string into start and end codes.
    
    Supports formats like:
    - "93600-93603" (CPT range)
    - "E0250-E0255" (HCPCS range)
    - "J0100-J0200" (J-code range)
    - "I20.0-I20.9" (ICD range)
    
    Args:
        range_str: Range string to parse
        
    Returns:
        Tuple of (start_code, end_code) or None if not a valid range
    """
    if not range_str or '-' not in range_str:
        return None
    
    # Split on hyphen
    parts = range_str.split('-')
    
    # Must have exactly 2 parts
    if len(parts) != 2:
        return None
    
    start_code = parts[0].strip()
    end_code = parts[1].strip()
    
    # Both parts must be non-empty
    if not start_code or not end_code:
        return None
    
    return (start_code, end_code)


def get_code_type(code: str) -> str:
    """
    Determine the type of medical code.
    
    Args:
        code: Medical code to classify
        
    Returns:
        Code type: 'cpt', 'hcpcs', 'j-code', 'icd', or 'unknown'
    """
    if not code:
        return 'unknown'
    
    code = code.strip().upper()
    
    # CPT codes: 5 digits (numeric only)
    if re.match(r'^\d{5}$', code):
        return 'cpt'
    
    # HCPCS codes: Letter followed by 4 digits
    if re.match(r'^[A-Z]\d{4}$', code):
        # J-codes are a subset of HCPCS
        if code.startswith('J'):
            return 'j-code'
        return 'hcpcs'
    
    # ICD codes: Letter followed by digits and optional decimal
    if re.match(r'^[A-Z]\d{2}(\.\d{1,4})?$', code):
        return 'icd'
    
    return 'unknown'


def extract_numeric_part(code: str) -> Optional[int]:
    """
    Extract the numeric part of a code for comparison.
    
    Args:
        code: Medical code
        
    Returns:
        Numeric part as integer, or None if no numeric part
    """
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, code))
    
    if not digits:
        return None
    
    try:
        return int(digits)
    except ValueError:
        return None


def extract_alpha_prefix(code: str) -> str:
    """
    Extract the alphabetic prefix of a code.
    
    Args:
        code: Medical code
        
    Returns:
        Alphabetic prefix (uppercase) or empty string
    """
    # Get all leading alphabetic characters
    match = re.match(r'^([A-Za-z]+)', code)
    if match:
        return match.group(1).upper()
    return ''



def is_code_in_cpt_range(query_code: str, range_str: str) -> bool:
    """
    Check if a CPT code is within a CPT code range.
    
    CPT codes are 5-digit numeric codes. Range matching is done by
    comparing the numeric values.
    
    Args:
        query_code: CPT code to check (e.g., "93601")
        range_str: Range string (e.g., "93600-93603")
        
    Returns:
        True if code is in range, False otherwise
    """
    # Parse the range
    parsed_range = parse_code_range(range_str)
    if not parsed_range:
        # Not a range, check for exact match
        return query_code.strip() == range_str.strip()
    
    start_code, end_code = parsed_range
    
    # Verify all codes are CPT codes
    if get_code_type(query_code) != 'cpt':
        return False
    if get_code_type(start_code) != 'cpt':
        return False
    if get_code_type(end_code) != 'cpt':
        return False
    
    # Extract numeric values
    query_num = extract_numeric_part(query_code)
    start_num = extract_numeric_part(start_code)
    end_num = extract_numeric_part(end_code)
    
    if query_num is None or start_num is None or end_num is None:
        return False
    
    # Check if query is in range
    result = start_num <= query_num <= end_num
    
    logger.debug("CPT range check",
                query_code=query_code,
                range_str=range_str,
                in_range=result)
    
    return result



def is_code_in_hcpcs_range(query_code: str, range_str: str) -> bool:
    """
    Check if an HCPCS code is within an HCPCS code range.
    
    HCPCS codes are alphanumeric: one letter followed by 4 digits.
    Range matching requires:
    1. Same letter prefix
    2. Numeric part within range
    
    Args:
        query_code: HCPCS code to check (e.g., "E0251")
        range_str: Range string (e.g., "E0250-E0255")
        
    Returns:
        True if code is in range, False otherwise
    """
    # Parse the range
    parsed_range = parse_code_range(range_str)
    if not parsed_range:
        # Not a range, check for exact match
        return query_code.strip().upper() == range_str.strip().upper()
    
    start_code, end_code = parsed_range
    
    # Verify all codes are HCPCS codes (including J-codes)
    query_type = get_code_type(query_code)
    start_type = get_code_type(start_code)
    end_type = get_code_type(end_code)
    
    if query_type not in ['hcpcs', 'j-code']:
        return False
    if start_type not in ['hcpcs', 'j-code']:
        return False
    if end_type not in ['hcpcs', 'j-code']:
        return False
    
    # Extract letter prefixes
    query_prefix = extract_alpha_prefix(query_code)
    start_prefix = extract_alpha_prefix(start_code)
    end_prefix = extract_alpha_prefix(end_code)
    
    # All codes must have the same letter prefix
    if query_prefix != start_prefix or query_prefix != end_prefix:
        return False
    
    # Extract numeric values
    query_num = extract_numeric_part(query_code)
    start_num = extract_numeric_part(start_code)
    end_num = extract_numeric_part(end_code)
    
    if query_num is None or start_num is None or end_num is None:
        return False
    
    # Check if query is in range
    result = start_num <= query_num <= end_num
    
    logger.debug("HCPCS range check",
                query_code=query_code,
                range_str=range_str,
                in_range=result)
    
    return result



def are_codes_same_format(code1: str, code2: str) -> bool:
    """
    Check if two codes are of the same format type.
    
    This ensures that CPT codes are only compared with CPT codes,
    HCPCS codes with HCPCS codes, etc.
    
    Args:
        code1: First code
        code2: Second code
        
    Returns:
        True if codes are same format, False otherwise
    """
    type1 = get_code_type(code1)
    type2 = get_code_type(code2)
    
    # Unknown types don't match anything
    if type1 == 'unknown' or type2 == 'unknown':
        return False
    
    # J-codes are a subset of HCPCS, so they can match
    if {type1, type2} <= {'hcpcs', 'j-code'}:
        return True
    
    # Otherwise, types must match exactly
    return type1 == type2


def validate_code_format_compatibility(query_code: str, range_str: str) -> bool:
    """
    Validate that a query code and range are format-compatible.
    
    Args:
        query_code: Code to check
        range_str: Range string
        
    Returns:
        True if compatible, False otherwise
    """
    # Parse range
    parsed_range = parse_code_range(range_str)
    
    if not parsed_range:
        # Not a range, just check if same format
        return are_codes_same_format(query_code, range_str)
    
    start_code, end_code = parsed_range
    
    # Check if query matches start and end format
    return (are_codes_same_format(query_code, start_code) and
            are_codes_same_format(query_code, end_code))



def is_code_in_icd_range(query_code: str, range_str: str) -> bool:
    """
    Check if an ICD code is within an ICD code range.
    
    ICD codes have format: Letter + 2 digits + optional decimal + digits
    Examples: I25.10, I20.0-I20.9, A01
    
    Range matching requires:
    1. Same letter prefix
    2. Numeric part within range (treating decimal as part of number)
    
    Args:
        query_code: ICD code to check (e.g., "I20.5")
        range_str: Range string (e.g., "I20.0-I20.9")
        
    Returns:
        True if code is in range, False otherwise
    """
    # Parse the range
    parsed_range = parse_code_range(range_str)
    if not parsed_range:
        # Not a range, check for exact match
        return query_code.strip().upper() == range_str.strip().upper()
    
    start_code, end_code = parsed_range
    
    # Verify all codes are ICD codes
    if get_code_type(query_code) != 'icd':
        return False
    if get_code_type(start_code) != 'icd':
        return False
    if get_code_type(end_code) != 'icd':
        return False
    
    # Extract letter prefixes
    query_prefix = extract_alpha_prefix(query_code)
    start_prefix = extract_alpha_prefix(start_code)
    end_prefix = extract_alpha_prefix(end_code)
    
    # All codes must have the same letter prefix
    if query_prefix != start_prefix or query_prefix != end_prefix:
        return False
    
    # Extract numeric values (including decimal part)
    query_num = extract_numeric_part(query_code)
    start_num = extract_numeric_part(start_code)
    end_num = extract_numeric_part(end_code)
    
    if query_num is None or start_num is None or end_num is None:
        return False
    
    # Check if query is in range
    result = start_num <= query_num <= end_num
    
    logger.debug("ICD range check",
                query_code=query_code,
                range_str=range_str,
                in_range=result)
    
    return result


def is_code_in_range(query_code: str, range_str: str) -> bool:
    """
    Universal function to check if a code is in a range.
    
    Automatically detects code type and uses appropriate range matching logic.
    
    Args:
        query_code: Code to check
        range_str: Range string or single code
        
    Returns:
        True if code matches or is in range, False otherwise
    """
    # Determine code type
    code_type = get_code_type(query_code)
    
    # Use appropriate range matching function
    if code_type == 'cpt':
        return is_code_in_cpt_range(query_code, range_str)
    elif code_type in ['hcpcs', 'j-code']:
        return is_code_in_hcpcs_range(query_code, range_str)
    elif code_type == 'icd':
        return is_code_in_icd_range(query_code, range_str)
    else:
        # Unknown type, try exact match
        return query_code.strip().upper() == range_str.strip().upper()
