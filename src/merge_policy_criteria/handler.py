"""
Lambda handler for merging clinical criteria into selected policy.

This is a simple pass-through function that combines the selected_policy
from IntelligentPolicySelector with the clinical_criteria from ExtractClinicalCriteria.

Version: 1.0
"""

import json
from typing import Dict, Any
import structlog

from common.logging_config import get_logger
from common.decorators import handle_processing_errors
from common.step_functions_utils import ContextAwareErrorHandler
from common.serialization import create_serializable_response

logger = get_logger(__name__)


@handle_processing_errors
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Merge clinical criteria into selected policy.
    
    Expected input:
    {
        "selector_result": {
            "Payload": {
                "selected_policy": {...},
                "extraction_context": {...}
            }
        },
        "criteria_result": {
            "Payload": {
                "clinical_criteria": [...]
            }
        }
    }
    
    Returns:
    {
        "selected_policy": {
            ...
            "applicable_criteria": [...]
        }
    }
    """
    
    error_handler = ContextAwareErrorHandler(event)
    
    logger.info("Merge Policy Criteria invoked",
               request_id=context.aws_request_id if context else None)
    
    try:
        # Extract selector result
        selector_result = event.get('selector_result', {}).get('Payload', {})
        selected_policy = selector_result.get('selected_policy', {})
        
        # Extract criteria result
        criteria_result = event.get('criteria_result', {}).get('Payload', {})
        clinical_criteria = criteria_result.get('clinical_criteria', [])
        
        if not selected_policy:
            raise ValueError("selected_policy not found in selector_result")
        
        logger.info("Merging criteria into policy",
                   policy_id=selected_policy.get('policy_id'),
                   criteria_count=len(clinical_criteria))
        
        # Merge criteria into policy
        selected_policy['applicable_criteria'] = clinical_criteria
        
        # Create response
        response_data = {
            'status': 'success',
            'selected_policy': selected_policy
        }
        
        serializable_data = create_serializable_response(response_data)
        return error_handler.create_success_response(serializable_data)
    
    except Exception as e:
        logger.error("Failed to merge policy and criteria",
                    error=str(e),
                    error_type=type(e).__name__)
        return error_handler.handle_error(e, True)
