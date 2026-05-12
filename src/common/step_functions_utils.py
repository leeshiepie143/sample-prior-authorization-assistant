"""
Utilities for Step Functions integration and error handling.
"""

import json
from typing import Dict, Any, Optional
from common.serialization import create_serializable_response


def is_step_functions_context(event: Dict[str, Any]) -> bool:
    """
    Determine if the Lambda is being called from Step Functions.
    
    Step Functions events typically don't have httpMethod, path, or headers
    that are present in API Gateway events.
    """
    # API Gateway events have these fields
    api_gateway_fields = ['httpMethod', 'path', 'headers', 'requestContext']
    
    # If any API Gateway specific fields are present, it's not Step Functions
    if any(field in event for field in api_gateway_fields):
        return False
    
    # Step Functions events are typically plain JSON objects
    # without the API Gateway wrapper structure
    return True


def handle_step_functions_error(error: Exception) -> None:
    """
    Handle errors in Step Functions context by raising the exception.
    This will cause Step Functions to mark the execution as failed.
    """
    raise error


def handle_api_gateway_error(error: Exception, retry_able: bool = True) -> Dict[str, Any]:
    """
    Handle errors in API Gateway context by returning HTTP error response.
    """
    from common.exceptions import PriorAuthException
    
    if isinstance(error, PriorAuthException):
        status_code = 400 if not error.retry_able else 500
        return {
            'statusCode': status_code,
            'body': json.dumps({
                'error': str(error),
                'error_code': error.error_code,
                'retry_able': error.retry_able
            })
        }
    else:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal processing error',
                'message': str(error),
                'retry_able': retry_able
            })
        }


def create_step_functions_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a response for Step Functions context.
    Returns the data directly without HTTP wrapper, with proper serialization.
    """
    return create_serializable_response(data)


def create_api_gateway_response(status_code: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a response for API Gateway context with proper HTTP structure.
    """
    from common.serialization import safe_json_dumps
    
    return {
        'statusCode': status_code,
        'body': safe_json_dumps(create_serializable_response(data))
    }


class ContextAwareErrorHandler:
    """
    Context-aware error handler that adapts behavior based on invocation context.
    """
    
    def __init__(self, event: Dict[str, Any]):
        self.is_step_functions = is_step_functions_context(event)  # nosemgrep: is-function-without-parentheses — boolean property assignment
    
    def handle_error(self, error: Exception, retry_able: bool = True) -> Optional[Dict[str, Any]]:
        """
        Handle error based on context.
        
        For Step Functions: Raises the exception (returns None)
        For API Gateway: Returns HTTP error response
        """
        if self.is_step_functions:  # nosemgrep: is-function-without-parentheses
            handle_step_functions_error(error)
            return None  # This line won't be reached due to exception
        else:
            return handle_api_gateway_error(error, retry_able)
    
    def create_success_response(self, data: Dict[str, Any], status_code: int = 200) -> Dict[str, Any]:
        """
        Create success response based on context.
        """
        if self.is_step_functions:  # nosemgrep: is-function-without-parentheses
            return create_step_functions_response(data)
        else:
            return create_api_gateway_response(status_code, data)