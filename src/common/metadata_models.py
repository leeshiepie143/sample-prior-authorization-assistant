"""
Data models for policy metadata.

These models define the structure of metadata extracted from policies
and stored in S3.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PolicyMetadata:
    """
    Enhanced metadata with source tracking.
    
    This extends the base metadata from the metadata_extractor module
    with additional fields for tracking policy sources and extraction timestamps.
    """
    
    # Existing fields (from metadata_extractor)
    payor: str
    """Payor name"""
    
    procedure_codes: List[str]
    """List of procedure codes (CPT, HCPCS, J-codes, RxNorm) - ranges expanded"""
    
    icd_codes: List[str]
    """List of ICD diagnosis codes - ranges expanded"""
    
    effective_date: Optional[str]
    """Policy effective date in ISO 8601 format"""
    
    policy_number: Optional[str]
    """Policy number extracted from document"""
    
    service_category: Optional[str]
    """Service category (e.g., 'Cardiac Catheterization')"""
    
    # New fields for dynamic extraction
    source: str
    """Source URL where policy was extracted from"""
    
    search_code: str
    """Service code used to find this policy"""
    
    extracted_timestamp: str
    """Timestamp when policy was extracted from payor website (ISO 8601)"""
