"""
Policy extraction request handler.

Handles invocation of policy extraction workflow when policies are missing.
"""

import boto3
import json
import os
from typing import Dict, List
import structlog

logger = structlog.get_logger(__name__)

# Supported payors for automatic policy extraction (Phase 3: Aetna, Humana, Anthem)
# Can be overridden via SUPPORTED_PAYORS environment variable (comma-separated)
SUPPORTED_PAYORS = os.environ.get('SUPPORTED_PAYORS', 'Aetna,Humana,Anthem').split(',')


class PolicyExtractionInitiatedException(Exception):
    """
    Exception raised when policy extraction workflow is initiated.
    
    This signals to Step Functions that the workflow should stop gracefully
    and inform the user to retry later.
    """
    pass


def is_payor_supported(payor_name: str) -> bool:
    """
    Check if payor is supported for automatic policy extraction.
    Uses partial matching to handle payor name variations (e.g., "Aetna Better Health" matches "Aetna").
    
    Args:
        payor_name: Payor name to check
        
    Returns:
        True if payor is supported, False otherwise
    """
    # Check for exact match first
    if payor_name in SUPPORTED_PAYORS:
        return True
    
    # Check if any supported payor is a substring of the payor name (case-insensitive)
    payor_name_lower = payor_name.lower()
    for supported_payor in SUPPORTED_PAYORS:
        if supported_payor.lower() in payor_name_lower:
            return True
    
    return False


def invoke_policy_extraction_workflow(
    payor_name: str,
    normalized_payor: str,
    service_codes: List[str],
    coverage_state: str = None
) -> Dict[str, any]:
    """
    Invoke the policy extraction workflow asynchronously.
    
    Args:
        payor_name: Original payor name
        normalized_payor: Normalized payor name (e.g., "AetnaPolicy")
        service_codes: List of service codes to extract policies for
        coverage_state: Optional lowercase 2-letter state code for state-specific policy search (Anthem)
        
    Returns:
        Dictionary with execution details
        
    Raises:
        Exception: If workflow invocation fails
    """
    # Get workflow ARN from environment
    workflow_arn = os.environ.get('POLICY_EXTRACTOR_WORKFLOW_ARN')
    
    if not workflow_arn:
        logger.error("POLICY_EXTRACTOR_WORKFLOW_ARN environment variable not set")
        raise ValueError("Policy extraction workflow ARN not configured")
    
    logger.info(
        "Invoking policy extraction workflow",
        payor_name=payor_name,
        normalized_payor=normalized_payor,
        service_codes=service_codes,
        coverage_state=coverage_state,
        workflow_arn=workflow_arn
    )
    
    # Create Step Functions client
    sfn_client = boto3.client('stepfunctions')
    
    # Prepare workflow input
    execution_input = {
        'payor': payor_name,
        'normalized_payor': normalized_payor,
        'service_codes': service_codes
    }
    
    # Add state_code for Anthem (state-specific policy search)
    if coverage_state:
        # Ensure state code is lowercase
        state_code = coverage_state.lower() if isinstance(coverage_state, str) else None
        if state_code and len(state_code) == 2:
            execution_input['state_code'] = state_code
            logger.info(
                "Including state code for state-specific policy search",
                payor_name=payor_name,
                state_code=state_code
            )
    
    try:
        # Start workflow execution
        response = sfn_client.start_execution(
            stateMachineArn=workflow_arn,
            input=json.dumps(execution_input)
        )
        
        execution_arn = response['executionArn']
        
        logger.info(
            "Policy extraction workflow started",
            execution_arn=execution_arn,
            payor_name=payor_name,
            service_codes=service_codes
        )
        
        # Handle startDate - it's a datetime object from AWS but string in tests
        start_date = response['startDate']
        if hasattr(start_date, 'isoformat'):
            start_date = start_date.isoformat()
        
        return {
            'execution_arn': execution_arn,
            'start_date': start_date
        }
        
    except Exception as e:
        logger.warning(
            "Failed to start policy extraction workflow",
            payor_name=payor_name,
            service_codes=service_codes,
            error=str(e),
            error_type=type(e).__name__
        )
        raise


def handle_missing_policies(
    payor_name: str,
    normalized_payor: str,
    service_codes: List[str],
    coverage_state: str = None
) -> Dict[str, any]:
    """
    Handle case where no policies exist for payor/service codes.
    Check if payor is supported and invoke extraction workflow.
    
    Args:
        payor_name: Original payor name
        normalized_payor: Normalized payor name
        service_codes: List of service codes
        coverage_state: Optional lowercase 2-letter state code for state-specific policy search (Anthem)
        
    Returns:
        Response dictionary with appropriate status code and message
    """
    logger.info(
        "Handling missing policies",
        payor_name=payor_name,
        normalized_payor=normalized_payor,
        service_codes=service_codes,
        coverage_state=coverage_state
    )
    
    # Check if payor is supported for automatic extraction
    if not is_payor_supported(payor_name):
        logger.warning(
            "Payor not supported for automatic policy extraction",
            payor_name=payor_name,
            supported_payors=SUPPORTED_PAYORS
        )
        
        return {
            'statusCode': 404,
            'error': 'PayorNotSupported',
            'payor_valid': False,
            'payor_name': payor_name,
            'normalized_payor': normalized_payor,
            'message': f'Payor {payor_name} is not supported for automatic policy extraction at this time'
        }
    
    # Payor is supported - invoke extraction workflow
    try:
        execution_details = invoke_policy_extraction_workflow(
            payor_name,
            normalized_payor,
            service_codes,
            coverage_state=coverage_state  # Pass state for Anthem state-specific search
        )
        
        logger.info(
            "Policy extraction initiated successfully",
            payor_name=payor_name,
            execution_arn=execution_details['execution_arn']
        )
        
        # Raise exception to signal Step Functions to stop gracefully
        # The exception message contains the response data for the UI
        extraction_response = {
            'statusCode': 202,
            'extraction_initiated': True,
            'payor_name': payor_name,
            'normalized_payor': normalized_payor,
            'service_codes': service_codes,
            'message': f'Policy extraction has been initiated for {payor_name}. Please check back in 5-10 minutes and retry your request.',
            'execution_arn': execution_details['execution_arn'],
            'start_date': execution_details['start_date']
        }
        
        raise PolicyExtractionInitiatedException(json.dumps(extraction_response))
        
    except PolicyExtractionInitiatedException:
        # Re-raise our custom exception
        raise
        
    except Exception as e:
        logger.error(
            "Failed to initiate policy extraction",
            payor_name=payor_name,
            service_codes=service_codes,
            error=str(e)
        )
        
        return {
            'statusCode': 500,
            'error': 'PolicyExtractionFailed',
            'payor_name': payor_name,
            'message': f'Failed to initiate policy extraction for {payor_name}',
            'details': str(e)
        }
