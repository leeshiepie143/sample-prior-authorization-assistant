"""
Lambda handler for Aetna policy scraper.

Invoked by Step Functions workflow to scrape policies from Aetna website.
"""

import json
import os
import boto3
import structlog
from datetime import datetime, timezone
from typing import Any, Dict

from scraper import scrape_aetna_policies
from filename_utils import generate_filename
from common.policy_models import PolicyExtractionResult, ScraperOutput

# Initialize logger and AWS clients
logger = structlog.get_logger(__name__)
s3_client = boto3.client('s3')

# Get S3 bucket from environment
POLICIES_BUCKET = os.environ.get('POLICIES_BUCKET', 'prior-auth-policies-dev')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for Aetna policy scraper.
    
    Input event format:
    {
        "service_codes": ["93458", "93600"],
        "payor": "Aetna",
        "normalized_payor": "AetnaPolicy"
    }
    
    Output format:
    {
        "policies": [
            {
                "url": "https://...",
                "content": "...",
                "title": "...",
                "search_code": "93458",
                "extraction_method": "selenium"
            }
        ],
        "total_policies": 1,
        "service_code": "93458",
        "payor": "Aetna",
        "errors": []
    }
    
    Args:
        event: Step Functions input
        context: Lambda context
        
    Returns:
        Scraper output dictionary
    """
    logger.info("Aetna scraper Lambda invoked", event_keys=list(event.keys()))
    
    try:
        # Validate input
        service_codes = event.get('service_codes', [])
        payor = event.get('payor', 'Aetna')
        
        if not service_codes:
            raise ValueError("service_codes is required")
        
        logger.info(
            "Starting policy scrape",
            service_codes=service_codes,
            payor=payor
        )
        
        # Write policies directly to S3 and collect metadata
        normalized_payor = event.get('normalized_payor', 'AetnaPolicy')
        policies_metadata = []
        all_errors = []
        
        # Generate extraction timestamp once for all policies in this batch
        extraction_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Process each service code
        for service_code in service_codes:
            try:
                logger.info(
                    "Scraping policies for code",
                    service_code=service_code
                )
                
                # Scrape policies for this code
                policies = scrape_aetna_policies(service_code)
                
                logger.info(
                    "Scraping complete for code",
                    service_code=service_code,
                    policies_found=len(policies)
                )
                
                # Upload policies to S3 for this code
                for policy in policies:
                    try:
                        # Generate filename
                        filename = generate_filename(policy.url, normalized_payor)
                        s3_key = f"{normalized_payor}/{filename}"
                        
                        # Check if this policy already exists (avoid duplicates across codes)
                        if any(p['s3_key'] == s3_key for p in policies_metadata):
                            logger.info(
                                "Policy already processed, skipping duplicate",
                                s3_key=s3_key,
                                search_code=service_code
                            )
                            continue
                        
                        # Upload policy content to S3 as markdown (no metadata yet)
                        s3_client.put_object(
                            Bucket=POLICIES_BUCKET,
                            Key=s3_key,
                            Body=policy.content.encode('utf-8'),
                            ContentType='text/markdown',
                            ServerSideEncryption='aws:kms'
                        )
                        
                        logger.info(
                            "Uploaded policy to S3",
                            s3_key=s3_key,
                            content_length=len(policy.content)
                        )
                        
                        # Store S3 key and tracking fields (NOT content!)
                        # These will be passed to ExtractMetadata Lambda
                        policies_metadata.append({
                            's3_key': s3_key,
                            's3_bucket': POLICIES_BUCKET,
                            'source': policy.url,
                            'search_code': policy.search_code,
                            'extracted_timestamp': extraction_timestamp,
                            'title': policy.title,
                            'extraction_method': policy.extraction_method
                        })
                        
                    except Exception as e:
                        logger.error(
                            "Error uploading policy to S3",
                            policy_url=policy.url,
                            error=str(e)
                        )
                        continue
                
            except Exception as e:
                logger.error(
                    "Error scraping code",
                    service_code=service_code,
                    error=str(e)
                )
                all_errors.append(f"Error scraping {service_code}: {str(e)}")
                continue
        
        # Build output with metadata only
        output = {
            'policies': policies_metadata,
            'total_policies': len(policies_metadata),
            'service_codes': service_codes,
            'payor': payor,
            'normalized_payor': normalized_payor,
            'errors': all_errors
        }
        
        logger.info(
            "Scraping complete",
            service_codes=service_codes,
            policies_uploaded=len(policies_metadata),
            errors_count=len(all_errors)
        )
        
        return output
        
    except Exception as e:
        logger.error(
            "Error in Aetna scraper",
            error=str(e),
            error_type=type(e).__name__
        )
        
        # Return error response
        return {
            'policies': [],
            'total_policies': 0,
            'service_codes': event.get('service_codes', ['unknown']),
            'payor': event.get('payor', 'Aetna'),
            'normalized_payor': event.get('normalized_payor', 'AetnaPolicy'),
            'errors': [str(e)]
        }
