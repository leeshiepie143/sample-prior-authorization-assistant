"""
Lambda handler for metadata processor.

Extracts structured metadata from policy text using Bedrock and enhances
it with source tracking fields.
"""

import json
import boto3
import structlog
from datetime import datetime, timezone
from typing import Any, Dict
import sys
import os

# Add parent directory to path
sys.path.insert(0, '/var/task')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import existing metadata extraction functions
from metadata_extractor.metadata_extractor import extract_metadata_from_text
from metadata_extractor.s3_metadata_updater import extract_payor_from_s3_key
from common.metadata_models import PolicyMetadata

# Initialize clients and logger
bedrock_client = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')
logger = structlog.get_logger(__name__)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for metadata processor.
    
    Input event format (from Map state):
    {
        "s3_key": "AetnaPolicy/AetnaPolicy_0728.md",
        "s3_bucket": "prior-auth-policies-dev",
        "source": "https://www.aetna.com/cpb/medical/data/700_799/0728.html",
        "search_code": "93458",
        "extracted_timestamp": "2024-11-12T16:30:00Z",
        "title": "Barrett's Esophagus",
        "extraction_method": "selenium_markdown"
    }
    
    Output format:
    {
        "s3_key": "AetnaPolicy/AetnaPolicy_0728.md",
        "s3_bucket": "prior-auth-policies-dev",
        "metadata": {
            "payor": "Aetna",
            "procedure_codes": ["93458", "93600", "93601"],
            "icd_codes": ["I25.10", "I20.0"],
            "effective_date": "2024-01-01",
            "policy_number": "0743",
            "service_category": "Cardiac Catheterization",
            "source": "https://...",
            "search_code": "93458",
            "extracted_timestamp": "2024-11-12T16:30:00Z"
        }
    }
    
    Args:
        event: Policy S3 location and tracking fields from scraper
        context: Lambda context
        
    Returns:
        S3 key with complete metadata
    """
    logger.info("Metadata processor Lambda invoked")
    
    try:
        # Extract inputs
        s3_key = event.get('s3_key')
        s3_bucket = event.get('s3_bucket', 'prior-auth-policies-dev')
        source = event.get('source')
        search_code = event.get('search_code')
        extracted_timestamp = event.get('extracted_timestamp')
        
        if not s3_key:
            raise ValueError("s3_key is required")
        
        logger.info(
            "Processing policy from S3",
            s3_key=s3_key,
            s3_bucket=s3_bucket,
            source=source
        )
        
        # Read policy content from S3
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        policy_content = response['Body'].read().decode('utf-8')
        
        logger.info(
            "Read policy from S3",
            s3_key=s3_key,
            content_length=len(policy_content)
        )
        
        # Extract payor from S3 key
        payor = extract_payor_from_s3_key(s3_key)
        
        logger.info(
            "Extracting metadata with Bedrock",
            s3_key=s3_key,
            payor=payor
        )
        
        # Extract base metadata using existing function
        # This already expands code ranges
        base_metadata = extract_metadata_from_text(
            bedrock_client,
            policy_content,
            payor
        )
        
        # Merge with source tracking fields
        complete_metadata = {
            **base_metadata,
            'source': source,
            'search_code': search_code,
            'extracted_timestamp': extracted_timestamp
        }
        
        logger.info(
            "Metadata extraction complete",
            s3_key=s3_key,
            procedure_codes_count=len(complete_metadata.get('procedure_codes', [])),
            icd_codes_count=len(complete_metadata.get('icd_codes', []))
        )
        
        # Return S3 key with complete metadata (no content!)
        return {
            's3_key': s3_key,
            's3_bucket': s3_bucket,
            'metadata': complete_metadata
        }
        
    except Exception as e:
        logger.error(
            "Error in metadata processor",
            error=str(e),
            error_type=type(e).__name__,
            s3_key=event.get('s3_key')
        )
        
        # Return with minimal metadata
        return {
            's3_key': event.get('s3_key'),
            's3_bucket': event.get('s3_bucket', 'prior-auth-policies-dev'),
            'metadata': {
                'payor': 'Aetna',
                'procedure_codes': [],
                'icd_codes': [],
                'effective_date': None,
                'policy_number': None,
                'service_category': None,
                'source': event.get('source'),
                'search_code': event.get('search_code'),
                'extracted_timestamp': event.get('extracted_timestamp')
            },
            'error': str(e)
        }
