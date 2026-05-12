"""
S3 prefix existence checker.

Validates that policies exist for a payor by checking S3 prefix.
Enhanced to check for specific service codes in S3 object metadata.
"""

import boto3
from typing import Dict, Tuple, List, Optional
import structlog

logger = structlog.get_logger(__name__)


def check_s3_prefix_exists(
    s3_client: boto3.client,
    bucket: str,
    prefix: str
) -> Tuple[bool, int]:
    """
    Check if S3 prefix exists and contains objects.
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        prefix: S3 prefix to check (e.g., "HumanaPolicy/")
        
    Returns:
        Tuple of (exists: bool, object_count: int)
    """
    # Ensure prefix ends with /
    if not prefix.endswith('/'):
        prefix = f"{prefix}/"
    
    logger.info(
        "Checking S3 prefix existence",
        bucket=bucket,
        prefix=prefix
    )
    
    try:
        # List objects with the prefix (limit to 1 to check existence)
        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=1
        )
        
        # Check if any objects exist
        key_count = response.get('KeyCount', 0)
        exists = key_count > 0
        
        if exists:
            # Get total count for logging (optional, can be expensive for large prefixes)
            # For now, just return that it exists
            logger.info(
                "S3 prefix exists",
                bucket=bucket,
                prefix=prefix,
                has_objects=True
            )
            return True, key_count
        else:
            logger.info(
                "S3 prefix does not exist or is empty",
                bucket=bucket,
                prefix=prefix
            )
            return False, 0
            
    except Exception as e:
        # Check if it's NoSuchBucket error
        error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
        if error_code == 'NoSuchBucket' or 'NoSuchBucket' in str(type(e)):
            logger.error(
                "S3 bucket does not exist",
                bucket=bucket
            )
            return False, 0
        
        # Other errors should be raised
        logger.warning(
            "Error checking S3 prefix",
            bucket=bucket,
            prefix=prefix,
            error=str(e)
        )
        raise


def check_service_code_in_metadata(
    s3_client: boto3.client,
    bucket: str,
    normalized_payor: str,
    service_codes: List[str]
) -> bool:
    """
    Check if any S3 object metadata contains the requested service codes.
    Uses S3 object metadata only - no file downloads.
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        normalized_payor: Normalized payor name (e.g., "AetnaPolicy")
        service_codes: List of service codes to search for (CPT, HCPCS, etc.)
        
    Returns:
        True if at least one policy matches any service code, False otherwise
    """
    # Ensure prefix ends with /
    prefix = normalized_payor if normalized_payor.endswith('/') else f"{normalized_payor}/"
    
    logger.info(
        "Checking S3 metadata for service codes",
        bucket=bucket,
        prefix=prefix,
        service_codes=service_codes
    )
    
    try:
        # Use paginator to handle large result sets
        paginator = s3_client.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if 'Contents' not in page:
                continue
            
            for obj in page['Contents']:
                # Skip .metadata.json files
                if obj['Key'].endswith('.metadata.json'):
                    continue
                
                # Get S3 object metadata
                try:
                    response = s3_client.head_object(
                        Bucket=bucket,
                        Key=obj['Key']
                    )
                    metadata = response.get('Metadata', {})
                    
                    # Check search-code field (hyphenated in S3 metadata)
                    search_codes_str = metadata.get('search-code', '')
                    if not search_codes_str:
                        continue
                    
                    # Split comma-separated codes
                    policy_search_codes = [code.strip() for code in search_codes_str.split(',')]
                    
                    # Check if any requested service code matches
                    for service_code in service_codes:
                        if service_code in policy_search_codes:
                            logger.info(
                                "Found policy for service code",
                                service_code=service_code,
                                s3_key=obj['Key'],
                                policy_search_codes=policy_search_codes
                            )
                            return True
                            
                except Exception as e:
                    logger.warning(
                        "Error checking metadata for object",
                        s3_key=obj['Key'],
                        error=str(e)
                    )
                    continue
        
        logger.info(
            "No policies found for service codes",
            service_codes=service_codes,
            prefix=prefix
        )
        return False
        
    except Exception as e:
        logger.warning(
            "Error checking service codes in metadata",
            bucket=bucket,
            prefix=prefix,
            service_codes=service_codes,
            error=str(e)
        )
        raise


def validate_payor_policies_exist(
    s3_client: boto3.client,
    bucket: str,
    payor_name: str,
    normalized_payor: str,
    service_codes: Optional[List[str]] = None
) -> Dict[str, any]:
    """
    Validate that policies exist for a payor.
    Enhanced to check for specific service codes in S3 metadata.
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        payor_name: Original payor name
        normalized_payor: Normalized payor name (e.g., "HumanaPolicy")
        service_codes: Optional list of service codes to check for
        
    Returns:
        Dictionary with validation result
    """
    # First check if prefix exists
    exists, count = check_s3_prefix_exists(s3_client, bucket, normalized_payor)
    
    if not exists:
        logger.warning(
            "Payor validation failed - no policies found",
            payor_name=payor_name,
            normalized_payor=normalized_payor
        )
        return {
            'valid': False,
            'payor_name': payor_name,
            'normalized_payor': normalized_payor,
            'error': f"No policies available for {payor_name}. Please contact support to add policies for this payor.",
            'policies_missing': True
        }
    
    # If service codes provided, check for specific codes in metadata
    if service_codes:
        logger.info(
            "Checking for service codes in policy metadata",
            payor_name=payor_name,
            service_codes=service_codes
        )
        
        codes_found = check_service_code_in_metadata(
            s3_client,
            bucket,
            normalized_payor,
            service_codes
        )
        
        if codes_found:
            logger.info(
                "Payor validation successful - policies found for service codes",
                payor_name=payor_name,
                normalized_payor=normalized_payor,
                service_codes=service_codes
            )
            return {
                'valid': True,
                'payor_name': payor_name,
                'normalized_payor': normalized_payor,
                'policy_count': count,
                'service_codes_found': True
            }
        else:
            logger.warning(
                "Payor validation failed - no policies for service codes",
                payor_name=payor_name,
                normalized_payor=normalized_payor,
                service_codes=service_codes
            )
            return {
                'valid': False,
                'payor_name': payor_name,
                'normalized_payor': normalized_payor,
                'service_codes': service_codes,
                'error': f"No policies available for {payor_name} with service codes {', '.join(service_codes)}",
                'policies_missing_for_codes': True
            }
    else:
        # No service codes provided, just check prefix exists
        logger.info(
            "Payor validation successful",
            payor_name=payor_name,
            normalized_payor=normalized_payor,
            policy_count=count
        )
        return {
            'valid': True,
            'payor_name': payor_name,
            'normalized_payor': normalized_payor,
            'policy_count': count
        }
