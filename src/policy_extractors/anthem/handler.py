"""
Anthem Policy Scraper Lambda Handler

Extracts policies from Anthem's website for given service codes.
Uploads directly to S3 and returns S3 keys (not content).
"""

import boto3
import json
import os
from typing import Dict, Any, List
from datetime import datetime
import structlog

from scraper import scrape_anthem_policies

# Initialize logger
logger = structlog.get_logger(__name__)

# Initialize AWS clients
s3_client = boto3.client('s3')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for Anthem policy extraction.
    
    Processes ALL service codes in the input array and uploads policies directly to S3.
    Returns S3 keys instead of content to avoid payload size limits.
    
    Args:
        event: {
            'service_codes': ['43775', '43370', ...],  # Array of codes
            'payor': 'Anthem',
            'normalized_payor': 'AnthemPolicy',
            'state_code': 'co'  # Optional state code
        }
        context: Lambda context
        
    Returns:
        {
            'policies': [
                {
                    's3_key': 'AnthemPolicy/AnthemPolicy_gl_pw_e000366.md',
                    's3_bucket': 'prior-auth-policies-dev',
                    'source': 'https://www.anthem.com/medpolicies/...',
                    'search_code': '43775',
                    'extracted_timestamp': '2025-11-13T...',
                    'title': 'Policy Title',
                    'extraction_method': 'selenium_markdown',
                    'state_code': 'co'
                }
            ],
            'total_policies': 1,
            'service_codes': ['43775'],
            'payor': 'Anthem',
            'normalized_payor': 'AnthemPolicy',
            'state_code': 'co',
            'errors': []
        }
    """
    logger.info("Anthem scraper Lambda invoked", event_keys=list(event.keys()))
    
    try:
        # Extract parameters
        service_codes = event.get('service_codes', [])
        payor = event.get('payor', 'Anthem')
        normalized_payor = event.get('normalized_payor', 'AnthemPolicy')
        state_code = event.get('state_code')  # Optional
        
        # Get S3 bucket from environment
        policies_bucket = os.environ.get('POLICIES_BUCKET', 'prior-auth-policies-dev')
        
        # Validate input
        if not service_codes:
            logger.error("No service codes provided")
            return {
                'policies': [],
                'total_policies': 0,
                'service_codes': [],
                'payor': payor,
                'normalized_payor': normalized_payor,
                'state_code': state_code,
                'errors': ['No service codes provided']
            }
        
        if not isinstance(service_codes, list):
            service_codes = [service_codes]
        
        logger.info(
            "Processing service codes",
            service_codes=service_codes,
            count=len(service_codes),
            payor=payor,
            state_code=state_code
        )
        
        # Process all service codes
        all_policies = []
        errors = []
        seen_policies = set()  # For duplicate detection
        
        for service_code in service_codes:
            try:
                logger.info(
                    "Scraping policies",
                    service_code=service_code,
                    state_code=state_code
                )
                
                # Scrape policies for this code
                policies = scrape_anthem_policies(service_code, state_code)
                
                if not policies:
                    logger.warning("No policies found", service_code=service_code)
                    continue
                
                logger.info(
                    "Policies scraped",
                    service_code=service_code,
                    count=len(policies)
                )
                
                # Upload each policy to S3
                for policy in policies:
                    try:
                        # Check for duplicates
                        policy_key = policy['filename']
                        if policy_key in seen_policies:
                            logger.info(
                                "Duplicate policy detected, skipping",
                                filename=policy_key,
                                service_code=service_code
                            )
                            continue
                        
                        seen_policies.add(policy_key)
                        
                        # Upload policy to S3
                        s3_key = f"{normalized_payor}/{policy['filename']}"
                        
                        # Create metadata
                        metadata = {
                            'payor': payor,
                            'search_code': service_code,
                            'source': policy['url'],
                            'extracted_timestamp': datetime.utcnow().isoformat() + 'Z',
                            'extraction_method': policy['extraction_method']
                        }
                        
                        # Add state code if provided
                        if state_code:
                            metadata['state_code'] = state_code
                        
                        # Prepare S3 metadata
                        s3_metadata = {
                            'payor': payor,
                            'search-code': service_code,
                            'source': policy['url'],
                            'extracted-timestamp': metadata['extracted_timestamp'],
                            'extraction-method': policy['extraction_method']
                        }
                        
                        if state_code:
                            s3_metadata['state-code'] = state_code
                        
                        # Upload policy file (content only, no metadata yet)
                        # Metadata will be extracted and uploaded by ProcessPolicies Map state
                        s3_client.put_object(
                            Bucket=policies_bucket,
                            Key=s3_key,
                            Body=policy['content'].encode('utf-8'),
                            ContentType='text/markdown',
                            ServerSideEncryption='aws:kms'
                        )
                        
                        logger.info(
                            "Policy uploaded to S3",
                            s3_key=s3_key,
                            service_code=service_code,
                            content_length=len(policy['content'])
                        )
                        
                        # Add to results (return S3 key, not content)
                        result_item = {
                            's3_key': s3_key,
                            's3_bucket': policies_bucket,
                            'source': policy['url'],
                            'search_code': service_code,
                            'extracted_timestamp': metadata['extracted_timestamp'],
                            'title': policy['title'],
                            'extraction_method': policy['extraction_method']
                        }
                        
                        if state_code:
                            result_item['state_code'] = state_code
                        
                        all_policies.append(result_item)
                        
                    except Exception as e:
                        logger.error(
                            "Error uploading policy",
                            filename=policy.get('filename'),
                            service_code=service_code,
                            error=str(e)
                        )
                        errors.append({
                            'service_code': service_code,
                            'filename': policy.get('filename'),
                            'error': str(e)
                        })
                
            except Exception as e:
                logger.error(
                    "Error processing service code",
                    service_code=service_code,
                    error=str(e),
                    error_type=type(e).__name__
                )
                errors.append({
                    'service_code': service_code,
                    'error': str(e)
                })
                continue
        
        # Return results
        result = {
            'policies': all_policies,
            'total_policies': len(all_policies),
            'service_codes': service_codes,
            'payor': payor,
            'normalized_payor': normalized_payor,
            'errors': errors
        }
        
        if state_code:
            result['state_code'] = state_code
        
        logger.info(
            "Anthem scraper complete",
            total_policies=len(all_policies),
            service_codes_processed=len(service_codes),
            errors_count=len(errors),
            state_code=state_code
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "Unexpected error in Anthem scraper",
            error=str(e),
            error_type=type(e).__name__
        )
        return {
            'policies': [],
            'total_policies': 0,
            'service_codes': event.get('service_codes', []),
            'payor': event.get('payor', 'Anthem'),
            'normalized_payor': event.get('normalized_payor', 'AnthemPolicy'),
            'state_code': event.get('state_code'),
            'errors': [str(e)]
        }
