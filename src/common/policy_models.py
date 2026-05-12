"""
Data models for policy extraction.

These models define the structure of data passed between Lambda functions
in the policy extraction workflow.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PolicyExtractionResult:
    """Result from web scraping a single policy."""
    
    url: str
    """Source URL of the policy"""
    
    content: str
    """Full text content of the policy"""
    
    title: str
    """Policy title from search results (for logging/debugging)"""
    
    search_code: str
    """Service code used to find this policy (CPT/HCPCS/RxNorm/J-code)"""
    
    extraction_method: str
    """Method used to extract content: 'selenium', 'direct_fetch', 'pdf', or 'blocked'"""


@dataclass
class ScraperOutput:
    """Output from policy scraper Lambda function."""
    
    policies: List[PolicyExtractionResult]
    """List of extracted policies"""
    
    total_policies: int
    """Total number of policies extracted"""
    
    service_code: str
    """Service code that was searched"""
    
    payor: str
    """Payor name"""
    
    errors: List[str]
    """List of error messages encountered during scraping"""
