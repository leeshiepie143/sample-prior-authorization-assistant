"""
S3 Uploader Lambda Handler

Uploads policy text files and metadata to S3 with proper organization.
Creates both S3 object metadata and .metadata.json files for Bedrock indexing.
"""

import boto3
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any
import structlog

# Import existing modules
import sys
sys.path.append('/opt/python')  # Lambda layer path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from metadata_extractor.s3_metadata_updater import (
    update_s3_metadata,
    create_bedrock_metadata_file
)
from metadata_extractor.metadata_extractor import format_metadata_for_s3
from common.policy_models import PolicyExtractionResult
from common.metadata_models import PolicyMetadata

logger = structlog.get_logger(__name__)

# Initialize S3 client
s3_client = boto3.client('s3')

# Environment variables
POLICIES_BUCKET = os.environ.get('POLICIES_BUCKET', 'prior-auth-policies-dev')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for updating S3 metadata and creating .metadata.json file.
    
    Expected input (from ExtractMetadata Lambda):
    {
        "s3_key": "AetnaPolicy/AetnaPolicy_0728.md",
        "s3_bucket": "prior-auth-policies-dev",
        "metadata": {
            "payor": "Aetna",
            "procedure_codes": ["93458", "93600"],
            "icd_codes": ["I25.10", "I20.0"],
            "effective_date": "2024-01-01",
            "policy_number": "0743",
            "service_category": "Cardiac Catheterization",
            "source": "https://www.aetna.com/cpb/medical/data/700_799/0728.html",
            "search_code": "93458",
            "extracted_timestamp": "2024-11-12T16:30:00Z"
        }
    }
    
    Returns:
    {
        "statusCode": 200,
        "s3_key": "AetnaPolicy/AetnaPolicy_0728.md",
        "metadata_key": "AetnaPolicy/AetnaPolicy_0728.md.metadata.json",
        "upload_timestamp": "2024-11-12T16:30:00Z"
    }
    """
    logger.info(
        "S3 uploader invoked",
        request_id=context.aws_request_id if context else None
    )
    
    try:
        # Extract input parameters
        s3_key = event.get('s3_key')
        s3_bucket = event.get('s3_bucket', POLICIES_BUCKET)
        metadata = event.get('metadata', {})
        
        # Validate required fields
        if not s3_key:
            raise ValueError("s3_key is required")
        if not metadata:
            raise ValueError("metadata is required")
        
        logger.info(
            "Updating S3 metadata",
            s3_key=s3_key,
            bucket=s3_bucket
        )
        
        # Format metadata for S3 object metadata
        s3_metadata = format_metadata_for_s3(metadata)
        
        # Update S3 object metadata (file already exists from scraper)
        update_s3_metadata(s3_client, s3_bucket, s3_key, s3_metadata)
        
        logger.info(
            "S3 object metadata updated successfully",
            s3_key=s3_key
        )
        
        # Create and upload .metadata.json file for Bedrock
        create_bedrock_metadata_file(
            s3_client,
            s3_bucket,
            s3_key,
            metadata
        )
        
        metadata_key = f"{s3_key}.metadata.json"
        
        logger.info(
            "Bedrock metadata file created successfully",
            metadata_key=metadata_key
        )
        
        # Return success response
        return {
            'statusCode': 200,
            's3_key': s3_key,
            'metadata_key': metadata_key,
            'upload_timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'bucket': s3_bucket
        }
        
    except ValueError as e:
        logger.error(
            "Validation error",
            error=str(e),
            s3_key=event.get('s3_key')
        )
        return {
            'statusCode': 400,
            'error': 'ValidationError',
            'message': str(e)
        }
        
    except Exception as e:
        logger.error(
            "Failed to update S3 metadata",
            error=str(e),
            error_type=type(e).__name__,
            s3_key=event.get('s3_key')
        )
        return {
            'statusCode': 500,
            'error': 'UploadError',
            'message': str(e)
        }
