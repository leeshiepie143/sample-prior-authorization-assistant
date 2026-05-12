"""
S3 metadata update functionality.

Updates S3 object metadata with extracted policy metadata.
Creates Bedrock-compatible .metadata.json files for Knowledge Base indexing.
"""

import boto3
import json
from typing import Dict, Any
import structlog

logger = structlog.get_logger(__name__)


def update_s3_metadata(
    s3_client: boto3.client,
    bucket: str,
    key: str,
    metadata: Dict[str, str]
) -> bool:
    """
    Update S3 object metadata.
    
    S3 requires copying the object to itself to update metadata.
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        key: S3 object key
        metadata: Metadata dictionary (string values only)
        
    Returns:
        True if successful, False otherwise
        
    Raises:
        Exception: If update fails
    """
    logger.info(
        "Updating S3 object metadata",
        bucket=bucket,
        key=key,
        metadata_fields=list(metadata.keys())
    )
    
    try:
        # Copy object to itself with new metadata
        # This is the AWS-recommended way to update metadata
        s3_client.copy_object(
            Bucket=bucket,
            Key=key,
            CopySource={'Bucket': bucket, 'Key': key},
            Metadata=metadata,
            MetadataDirective='REPLACE'
        )
        
        logger.info(
            "S3 metadata updated successfully",
            bucket=bucket,
            key=key
        )
        
        return True
        
    except Exception as e:
        logger.warning(
            "Failed to update S3 metadata",
            bucket=bucket,
            key=key,
            error=str(e)
        )
        raise


def extract_payor_from_s3_key(key: str) -> str:
    """
    Extract payor name from S3 object key.
    
    Assumes format: {PayorName}Policy/filename.ext
    Example: "HumanaPolicy/cardiac_policy.pdf" -> "Humana"
    
    Args:
        key: S3 object key
        
    Returns:
        Payor name
        
    Raises:
        ValueError: If key format is invalid
    """
    # Split by forward slash
    parts = key.split('/')
    
    if len(parts) < 2:
        raise ValueError(f"Invalid S3 key format: {key}. Expected format: {{PayorName}}Policy/filename.ext")
    
    # Get first part (should be like "HumanaPolicy")
    prefix = parts[0]
    
    # Remove "Policy" suffix
    if not prefix.endswith('Policy'):
        raise ValueError(f"Invalid payor prefix: {prefix}. Expected format: {{PayorName}}Policy")
    
    payor = prefix[:-6]  # Remove "Policy" (6 characters)
    
    if not payor:
        raise ValueError(f"Empty payor name in key: {key}")
    
    logger.debug(
        "Extracted payor from S3 key",
        key=key,
        payor=payor
    )
    
    return payor


def compress_code_ranges(codes: list) -> str:
    """
    Compress consecutive numeric codes into ranges to reduce metadata size.
    
    Examples:
        ['93451', '93452', '93453'] -> '93451-93453'
        ['92978', '92979', '93451'] -> '92978-92979,93451'
        ['C7516', 'C7517', 'C7518'] -> 'C7516-C7518'
    
    Args:
        codes: List of procedure/ICD codes
        
    Returns:
        Comma-separated string with ranges where applicable
    """
    if not codes:
        return ''
    
    # Separate numeric and alphanumeric codes
    numeric_codes = []
    alpha_codes = []
    
    for code in codes:
        # Extract numeric part for sorting
        numeric_part = ''.join(filter(str.isdigit, code))
        if numeric_part:
            numeric_codes.append((code, int(numeric_part)))
        else:
            alpha_codes.append(code)
    
    # Sort numeric codes by their numeric value
    numeric_codes.sort(key=lambda x: x[1])
    
    # Compress numeric codes into ranges
    compressed = []
    i = 0
    while i < len(numeric_codes):
        start_code, start_num = numeric_codes[i]
        end_code, end_num = start_code, start_num
        
        # Find consecutive codes
        j = i + 1
        while j < len(numeric_codes):
            curr_code, curr_num = numeric_codes[j]
            # Check if consecutive and same prefix
            prefix_start = start_code.rstrip('0123456789')
            prefix_curr = curr_code.rstrip('0123456789')
            
            if prefix_start == prefix_curr and curr_num == end_num + 1:
                end_code, end_num = curr_code, curr_num
                j += 1
            else:
                break
        
        # Add range or single code
        if j - i >= 3:  # Only create range if 3+ consecutive codes
            compressed.append(f"{start_code}-{end_code}")
        else:
            # Add individual codes
            for k in range(i, j):
                compressed.append(numeric_codes[k][0])
        
        i = j
    
    # Add alphanumeric codes (sorted)
    compressed.extend(sorted(alpha_codes))
    
    return ','.join(compressed)


def create_bedrock_metadata_file(
    s3_client: boto3.client,
    bucket: str,
    document_key: str,
    metadata: Dict[str, Any]
) -> bool:
    """
    Create and upload a Bedrock-compatible .metadata.json file for a document.
    
    Bedrock Knowledge Base requires a separate .metadata.json file alongside
    each document to enable metadata filtering. The file must:
    - Have the same name as the document with .metadata.json appended
    - Be in the same S3 location as the document
    - Follow the Bedrock metadata format
    - Be under 1024 bytes (S3 Vectors GA limit as of Dec 2024)
    
    Optimizations applied:
    - Compress consecutive procedure/ICD codes into ranges
    - Remove unused fields (policy-number, effective-date, source, extracted-timestamp)
    - Remove includeForEmbedding flags (not required)
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        document_key: S3 key of the source document (e.g., "HumanaPolicy/policy.pdf")
        metadata: Metadata dictionary with extracted fields
        
    Returns:
        True if successful, False otherwise
        
    Raises:
        Exception: If upload fails
    """
    # Create metadata file key
    metadata_key = f"{document_key}.metadata.json"
    
    logger.info(
        "Creating Bedrock metadata file",
        bucket=bucket,
        document_key=document_key,
        metadata_key=metadata_key
    )
    
    # Convert metadata to Bedrock format (optimized for size)
    bedrock_metadata = {
        "metadataAttributes": {}
    }
    
    # Add payor (STRING) - REQUIRED for KB filtering
    if 'payor' in metadata and metadata['payor']:
        bedrock_metadata["metadataAttributes"]["payor"] = {
            "value": {
                "type": "STRING",
                "stringValue": metadata['payor']
            }
        }
    
    # Add procedure codes (STRING - compressed ranges)
    if 'procedure_codes' in metadata and metadata['procedure_codes']:
        procedure_codes_compressed = compress_code_ranges(metadata['procedure_codes'])
        bedrock_metadata["metadataAttributes"]["procedure-codes"] = {
            "value": {
                "type": "STRING",
                "stringValue": procedure_codes_compressed
            }
        }
    
    # Add ICD codes (STRING - compressed ranges)
    if 'icd_codes' in metadata and metadata['icd_codes']:
        icd_codes_compressed = compress_code_ranges(metadata['icd_codes'])
        bedrock_metadata["metadataAttributes"]["icd-codes"] = {
            "value": {
                "type": "STRING",
                "stringValue": icd_codes_compressed
            }
        }
    
    # Add service category (STRING) - used for display
    if 'service_category' in metadata and metadata['service_category']:
        bedrock_metadata["metadataAttributes"]["service-category"] = {
            "value": {
                "type": "STRING",
                "stringValue": metadata['service_category']
            }
        }
    
    # Add title (STRING) - used for display
    title = metadata.get('title') or metadata.get('service_category')
    if title:
        bedrock_metadata["metadataAttributes"]["title"] = {
            "value": {
                "type": "STRING",
                "stringValue": title
            }
        }
    
    # Add search code (STRING) - used by payor validator
    if 'search_code' in metadata and metadata['search_code']:
        bedrock_metadata["metadataAttributes"]["search-code"] = {
            "value": {
                "type": "STRING",
                "stringValue": metadata['search_code']
            }
        }
    
    # REMOVED FIELDS (not used in code, saves ~770 bytes):
    # - policy-number: Not used in filtering or ranking
    # - effective-date: Not used in filtering or ranking
    # - source: Not used in filtering or ranking
    # - extracted-timestamp: Not used in filtering or ranking
    # - includeForEmbedding: Not required by Bedrock KB
    
    # Convert to JSON
    metadata_json = json.dumps(bedrock_metadata, indent=2)
    
    # Check size limit (1024 bytes for S3 Vectors GA)
    metadata_size = len(metadata_json.encode('utf-8'))
    if metadata_size > 1024:
        logger.warning(
            "Metadata file exceeds 1024 byte limit (S3 Vectors GA)",
            metadata_key=metadata_key,
            size_bytes=metadata_size,
            limit_bytes=1024
        )
    else:
        logger.info(
            "Metadata file size within limit",
            metadata_key=metadata_key,
            size_bytes=metadata_size,
            limit_bytes=1024
        )
    
    try:
        # Upload metadata file to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=metadata_key,
            Body=metadata_json.encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(
            "Bedrock metadata file created successfully",
            bucket=bucket,
            metadata_key=metadata_key,
            size_bytes=len(metadata_json.encode('utf-8'))
        )
        
        return True
        
    except Exception as e:
        logger.warning(
            "Failed to create Bedrock metadata file",
            bucket=bucket,
            metadata_key=metadata_key,
            error=str(e)
        )
        raise
