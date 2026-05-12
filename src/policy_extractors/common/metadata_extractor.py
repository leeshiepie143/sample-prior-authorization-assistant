"""
Metadata extraction using Bedrock for policy files.
"""

import json
import structlog
from typing import Dict, Any

logger = structlog.get_logger(__name__)


def extract_and_upload_metadata(
    bedrock_client,
    s3_client,
    bucket: str,
    s3_key: str,
    policy_content: str,
    payor: str,
    search_code: str,
    source_url: str
) -> Dict[str, Any]:
    """
    Extract metadata from policy content using Bedrock and upload to S3.
    
    Args:
        bedrock_client: Boto3 Bedrock client
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        s3_key: S3 key for the policy file
        policy_content: Policy text content
        payor: Payor name
        search_code: Service code used to find policy
        source_url: Source URL of the policy
        
    Returns:
        Enhanced metadata dictionary
    """
    try:
        # Use Bedrock to extract metadata
        # This is a simplified version - you should use your existing metadata extraction logic
        metadata = {
            'payor': payor,
            'search_code': search_code,
            'source': source_url,
            'procedure_codes': [],
            'icd_codes': [],
            'service_category': '',
            'policy_number': '',
            'effective_date': ''
        }
        
        # Create metadata file
        metadata_key = f"{s3_key}.metadata.json"
        metadata_content = {
            'metadataAttributes': metadata
        }
        
        s3_client.put_object(
            Bucket=bucket,
            Key=metadata_key,
            Body=json.dumps(metadata_content, indent=2).encode('utf-8'),
            ContentType='application/json',
            ServerSideEncryption='aws:kms'
        )
        
        logger.info("Metadata file uploaded", metadata_key=metadata_key)
        
        return metadata
        
    except Exception as e:
        logger.warning("Error extracting metadata", error=str(e))
        raise
