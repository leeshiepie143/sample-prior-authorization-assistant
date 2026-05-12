"""
Lambda handler for payor validation.

Validates that policies exist for a payor before proceeding with policy search.
"""

import boto3
import json
import os
from typing import Dict, Any
import structlog

from .payor_normalizer import normalize_payor_name, extract_payor_from_extraction_result
from .s3_prefix_checker import validate_payor_policies_exist
from .service_code_extractor import extract_service_codes_from_extraction_result
from .policy_extraction_handler import handle_missing_policies

# Initialize logger
logger = structlog.get_logger(__name__)

# Initialize AWS clients
s3_client = boto3.client('s3')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for payor validation.
    
    Args:
        event: Step Functions event with extraction result
        context: Lambda context
        
    Returns:
        Response dictionary with validation result
    """
    logger.info("Payor validation Lambda invoked", event_keys=list(event.keys()))
    
    try:
        # Get policies bucket from environment
        policies_bucket = os.environ.get('POLICIES_BUCKET', 'prior-auth-policies-dev')
        
        # Extract payor name from extraction result
        try:
            payor_name = extract_payor_from_extraction_result(event)
        except ValueError as e:
            logger.error(
                "Failed to extract payor name",
                error=str(e)
            )
            return {
                'statusCode': 400,
                'error': 'PayorNotFound',
                'message': 'Could not extract payor name from extraction result',
                'details': str(e)
            }
        
        logger.info(
            "Extracted payor name",
            payor_name=payor_name
        )
        
        # Normalize payor name
        try:
            normalized_payor = normalize_payor_name(payor_name)
        except ValueError as e:
            logger.error(
                "Failed to normalize payor name",
                payor_name=payor_name,
                error=str(e)
            )
            return {
                'statusCode': 400,
                'error': 'InvalidPayorName',
                'message': f'Invalid payor name: {payor_name}',
                'details': str(e)
            }
        
        logger.info(
            "Normalized payor name",
            payor_name=payor_name,
            normalized_payor=normalized_payor
        )
        
        # Extract service codes from extraction result
        service_codes = extract_service_codes_from_extraction_result(event)
        
        logger.info(
            "Extracted service codes",
            service_codes=service_codes,
            count=len(service_codes)
        )
        
        # Extract coverage state from extraction result (for Anthem state-specific search)
        coverage_state = None
        # Navigate nested Step Functions payload structure
        extraction_result = event.get('extraction_result', {})
        if isinstance(extraction_result, dict):
            # Try direct path first (for testing)
            coverage_state = extraction_result.get('coverage_state')
            # If not found, try nested Payload structure (from Step Functions)
            if not coverage_state:
                payload = extraction_result.get('Payload', {})
                if isinstance(payload, dict):
                    nested_result = payload.get('extraction_result', {})
                    if isinstance(nested_result, dict):
                        coverage_state = nested_result.get('coverage_state')
        
        if coverage_state:
            logger.info(
                "Extracted coverage state",
                coverage_state=coverage_state,
                payor_name=payor_name
            )
        else:
            logger.debug(
                "No coverage state found in extraction result",
                payor_name=payor_name
            )
        
        # Validate that policies exist for this payor and service codes
        validation_result = validate_payor_policies_exist(
            s3_client,
            policies_bucket,
            payor_name,
            normalized_payor,
            service_codes=service_codes if service_codes else None
        )
        
        if validation_result['valid']:
            # Payor is valid, return success
            logger.info(
                "Payor validation successful",
                payor_name=payor_name,
                normalized_payor=normalized_payor,
                policy_count=validation_result.get('policy_count', 0),
                service_codes_checked=bool(service_codes)
            )
            
            response = {
                'statusCode': 200,
                'payor_valid': True,
                'payor_name': payor_name,
                'normalized_payor': normalized_payor,
                'policy_count': validation_result.get('policy_count', 0)
            }
            
            # Include service codes info if they were checked
            if service_codes:
                response['service_codes'] = service_codes
                response['service_codes_found'] = validation_result.get('service_codes_found', False)
            
            return response
        else:
            # Policies are missing - check if we can extract them automatically
            logger.warning(
                "Payor validation failed - policies missing",
                payor_name=payor_name,
                normalized_payor=normalized_payor,
                service_codes=service_codes,
                policies_missing=validation_result.get('policies_missing', False),
                policies_missing_for_codes=validation_result.get('policies_missing_for_codes', False)
            )
            
            # If policies are missing (either no prefix or no policies for codes),
            # attempt automatic extraction
            if validation_result.get('policies_missing') or validation_result.get('policies_missing_for_codes'):
                logger.info(
                    "Attempting automatic policy extraction",
                    payor_name=payor_name,
                    service_codes=service_codes
                )
                
                # Handle missing policies - will invoke extraction workflow if supported
                return handle_missing_policies(
                    payor_name,
                    normalized_payor,
                    service_codes,
                    coverage_state=coverage_state  # Pass state for Anthem state-specific search
                )
            
            # Otherwise, return standard error response
            response = {
                'statusCode': 404,
                'error': 'PayorNotFound',
                'payor_valid': False,
                'payor_name': payor_name,
                'normalized_payor': normalized_payor,
                'message': validation_result.get('error', f'No policies available for {payor_name}')
            }
            
            # Include additional context
            if service_codes:
                response['service_codes'] = service_codes
            
            return response
    
    except Exception as e:
        # Re-raise PolicyExtractionInitiatedException to signal Step Functions
        from .policy_extraction_handler import PolicyExtractionInitiatedException
        if isinstance(e, PolicyExtractionInitiatedException):
            raise
        
        logger.error(
            "Unexpected error in payor validation",
            error=str(e),
            error_type=type(e).__name__
        )
        return {
            'statusCode': 500,
            'error': 'InternalError',
            'message': 'Unexpected error during payor validation',
            'details': str(e)
        }
