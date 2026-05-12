"""
Lambda handler for the Policy Selector module.

This module provides the AWS Lambda entry point for intelligent policy
selection and clinical criteria extraction functionality.
"""

import json
from typing import Dict, Any

from selector.policy_selector import IntelligentPolicySelector, PolicySelectionValidator
from selector.criteria_extractor import ClinicalCriteriaExtractor, CriteriaEnhancementService
from selector.validation_service import PolicySelectionValidator as ValidationService
from common.models import ExtractedData, SelectedPolicy
from common.exceptions import PolicySelectionError, PriorAuthException
from common.logging_config import get_logger, get_audit_logger
from common.decorators import handle_processing_errors
from common.step_functions_utils import ContextAwareErrorHandler
from common.utils import safe_json_loads

logger = get_logger(__name__)
audit_logger = get_audit_logger()


@handle_processing_errors
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for policy selection operations.
    
    Expected event structure:
    {
        "action": "select_policy" | "extract_criteria" | "validate_selection",
        "extracted_data": {...},  # ExtractedData object for select_policy
        "selected_policy": {...},  # SelectedPolicy object for validation
        "max_candidates": 5  # Optional, for select_policy
    }
    """
    
    # Initialize context-aware error handler
    error_handler = ContextAwareErrorHandler(event)
    
    logger.info("Policy Selector handler invoked", 
               action=event.get('action'),
               request_id=context.aws_request_id if context else None)
    
    try:
        action = event.get('action')
        
        # Auto-detect action for Step Functions workflow
        if not action and error_handler.is_step_functions:  # nosemgrep: is-function-without-parentheses — is_step_functions is a boolean property, not a method
            # In Step Functions workflow, default to select_policy
            action = 'select_policy'
            logger.info("Auto-detected action for Step Functions workflow", action=action)
        
        if action == 'select_policy':
            result = handle_policy_selection(event, context)
        elif action == 'extract_criteria':
            result = handle_criteria_extraction(event, context)
        elif action == 'validate_selection':
            result = handle_selection_validation(event, context)
        elif action == 'enhance_criteria':
            result = handle_criteria_enhancement(event, context)
        else:
            raise ValueError(f"Unknown action: {action}")
        
        # Return success response based on context
        return error_handler.create_success_response(result)
    
    except PriorAuthException as e:
        logger.error("Processing failed with known error", error=str(e))
        return error_handler.handle_error(e, e.retry_able)
    
    except Exception as e:
        logger.error("Processing failed with unexpected error", error=str(e))
        return error_handler.handle_error(e, True)


def handle_policy_selection(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle intelligent policy selection"""
    
    # Extract and validate parameters
    extracted_data_dict = event.get('extracted_data')
    max_candidates = event.get('max_candidates', 5)
    
    # For Step Functions workflow, extract data from extraction result
    if not extracted_data_dict and event.get('extraction_result'):
        extraction_data = event['extraction_result']
        if isinstance(extraction_data, dict) and 'Payload' in extraction_data:
            # Handle Lambda response format
            payload = extraction_data['Payload']
            if isinstance(payload, dict) and 'extraction_result' in payload:
                extracted = payload['extraction_result']
                extracted_data_dict = extracted
                logger.info("Extracted data from workflow for policy selection", document_id=extracted.get('document_id'))
    
    if not extracted_data_dict:
        raise ValueError("extracted_data is required for policy selection")
    
    # Convert to ExtractedData object
    try:
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
    except Exception as e:
        raise ValueError(f"Invalid extracted_data format: {str(e)}")
    
    # Get policy search results from knowledge step
    policy_candidates = []
    if event.get('knowledge_result'):
        knowledge_data = event['knowledge_result']
        if isinstance(knowledge_data, dict) and 'Payload' in knowledge_data:
            payload = knowledge_data['Payload']
            if isinstance(payload, dict) and 'search_results' in payload:
                policy_candidates = payload['search_results']
                logger.info("Found policy candidates from knowledge search", count=len(policy_candidates))
    
    # Perform policy selection
    policy_selector = IntelligentPolicySelector()
    
    # Check if policies were found
    if not policy_candidates:
        logger.warning("No policies found in knowledge base for selection")
        raise PolicySelectionError(
            f"No policies available for payor: {extracted_data_dict.get('payor_name', 'unknown')}. "
            f"Please ensure policy documents are uploaded to the knowledge base.",
            payor=extracted_data_dict.get('payor_name', 'unknown')
        )
    
    # Perform policy selection with found candidates
    selected_policy = policy_selector.select_best_policy(extracted_data, max_candidates)
    
    # Get selection explanation
    selection_explanation = policy_selector.get_policy_selection_explanation(
        selected_policy, extracted_data
    )
    
    # Validate the selection
    validator = PolicySelectionValidator()
    is_valid, validation_errors = validator.validate_policy_selection(
        selected_policy, extracted_data
    )
    
    # Assess selection quality
    quality_metrics = validator.assess_selection_quality(selected_policy, extracted_data)
    
    # Log successful selection
    audit_logger.log_policy_access(
        policy_id=selected_policy.policy_id,
        payor=selected_policy.payor,
        access_type="select"
    )
    
    # Create serializable response
    response_data = {
        'status': 'success',
        'selected_policy': selected_policy.to_dict(),
        'selection_explanation': selection_explanation,
        'validation': {
            'is_valid': is_valid,
            'validation_errors': validation_errors,
            'quality_metrics': quality_metrics
        }
    }
    
    # Use serialization utilities to handle datetime objects
    from common.serialization import create_serializable_response
    serializable_data = create_serializable_response(response_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps(serializable_data)
    }


def handle_criteria_extraction(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle clinical criteria extraction from selected policy"""
    
    # Extract parameters
    selected_policy_dict = event.get('selected_policy')
    extracted_data_dict = event.get('extracted_data')
    
    if not all([selected_policy_dict, extracted_data_dict]):
        raise ValueError("selected_policy and extracted_data are required")
    
    # Convert to objects
    try:
        selected_policy = SelectedPolicy.from_dict(selected_policy_dict)
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Note: For this implementation, we'll work with the criteria already in selected_policy
    # In a full implementation, this would extract criteria from the full policy document
    
    criteria_extractor = ClinicalCriteriaExtractor()
    
    # Simulate criteria extraction (in real implementation, would extract from policy document)
    clinical_criteria = selected_policy.applicable_criteria
    
    # Enhance criteria with context
    enhancement_service = CriteriaEnhancementService()
    enhanced_criteria = enhancement_service.enhance_criteria_with_context(
        clinical_criteria, extracted_data
    )
    
    # Create serializable response
    response_data = {
        'status': 'success',
        'clinical_criteria': [criterion.to_dict() for criterion in enhanced_criteria],
        'criteria_count': len(enhanced_criteria),
        'extraction_metadata': {
            'policy_id': selected_policy.policy_id,
            'payor': selected_policy.payor,
            'extracted_at': context.aws_request_id if context else 'local'
        }
    }
    
    # Use serialization utilities to handle datetime objects
    from common.serialization import create_serializable_response
    serializable_data = create_serializable_response(response_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps(serializable_data)
    }


def handle_selection_validation(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle comprehensive policy selection validation"""
    
    # Extract parameters
    selected_policy_dict = event.get('selected_policy')
    extracted_data_dict = event.get('extracted_data')
    candidate_policies = event.get('candidate_policies', [])
    
    if not all([selected_policy_dict, extracted_data_dict]):
        raise ValueError("selected_policy and extracted_data are required")
    
    # Convert to objects
    try:
        selected_policy = SelectedPolicy.from_dict(selected_policy_dict)
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Perform comprehensive validation
    validation_service = ValidationService()
    validation_result = validation_service.validate_policy_selection(
        selected_policy, extracted_data, candidate_policies
    )
    
    # Log validation results
    audit_logger.log_processing_step(
        document_id=extracted_data.document_id,
        step_name="policy_validation",
        status="completed" if validation_result.is_valid else "failed"  # nosemgrep: is-function-without-parentheses — is_valid is a boolean property
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'validation_complete',
            'validation_result': {
                'is_valid': validation_result.is_valid,  # nosemgrep: is-function-without-parentheses
                'confidence_score': validation_result.confidence_score,
                'overall_quality': validation_result.overall_quality,
                'issues_count': len(validation_result.issues),
                'issues': [
                    {
                        'severity': issue.severity.value,
                        'category': issue.category,
                        'message': issue.message,
                        'field': issue.field,
                        'recommendation': issue.recommendation
                    }
                    for issue in validation_result.issues
                ],
                'validation_summary': validation_result.validation_summary
            }
        })
    }


def handle_criteria_enhancement(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle criteria enhancement with patient-specific context"""
    
    # Extract parameters
    clinical_criteria_list = event.get('clinical_criteria', [])
    extracted_data_dict = event.get('extracted_data')
    
    if not all([clinical_criteria_list, extracted_data_dict]):
        raise ValueError("clinical_criteria and extracted_data are required")
    
    # Convert to objects
    try:
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
        clinical_criteria = [
            ClinicalCriterion.from_dict(criterion_dict) 
            for criterion_dict in clinical_criteria_list
        ]
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Enhance criteria
    enhancement_service = CriteriaEnhancementService()
    enhanced_criteria = enhancement_service.enhance_criteria_with_context(
        clinical_criteria, extracted_data
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'enhancement_complete',
            'enhanced_criteria': [criterion.to_dict() for criterion in enhanced_criteria],
            'enhancement_summary': {
                'original_count': len(clinical_criteria),
                'enhanced_count': len(enhanced_criteria),
                'patient_context': {
                    'age_range': extracted_data.patient_info.age_range,
                    'gender': extracted_data.patient_info.gender,
                    'primary_diagnosis': extracted_data.patient_info.primary_diagnosis
                }
            }
        })
    }


# Utility endpoints
def get_policy_explanation(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Get detailed explanation for policy selection"""
    
    selected_policy_dict = event.get('selected_policy')
    extracted_data_dict = event.get('extracted_data')
    
    if not all([selected_policy_dict, extracted_data_dict]):
        raise ValueError("selected_policy and extracted_data are required")
    
    try:
        selected_policy = SelectedPolicy.from_dict(selected_policy_dict)
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Generate explanation
    policy_selector = IntelligentPolicySelector()
    explanation = policy_selector.get_policy_selection_explanation(
        selected_policy, extracted_data
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'explanation_generated',
            'explanation': explanation
        })
    }


def validate_policy_quality(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Validate policy quality and completeness"""
    
    selected_policy_dict = event.get('selected_policy')
    extracted_data_dict = event.get('extracted_data')
    
    if not all([selected_policy_dict, extracted_data_dict]):
        raise ValueError("selected_policy and extracted_data are required")
    
    try:
        selected_policy = SelectedPolicy.from_dict(selected_policy_dict)
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Assess quality
    validator = PolicySelectionValidator()
    quality_metrics = validator.assess_selection_quality(selected_policy, extracted_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'quality_assessed',
            'quality_metrics': quality_metrics
        })
    }


# Health check endpoint
def health_check(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Health check endpoint for the Lambda function"""
    
    # Test core components
    try:
        policy_selector = IntelligentPolicySelector()
        criteria_extractor = ClinicalCriteriaExtractor()
        validation_service = ValidationService()
        
        component_status = {
            'policy_selector': 'healthy',
            'criteria_extractor': 'healthy',
            'validation_service': 'healthy'
        }
        
    except Exception as e:
        component_status = {
            'error': str(e)
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'healthy',
            'service': 'policy-selector',
            'components': component_status,
            'timestamp': context.aws_request_id if context else 'local'
        })
    }
