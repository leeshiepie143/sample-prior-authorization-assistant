"""
Security middleware for Lambda functions.

This module provides security middleware functions for request/response processing.
"""

from typing import Dict, Any, Callable
from functools import wraps
from common.logging_config import get_logger

logger = get_logger(__name__)


def apply_security_middleware(func: Callable) -> Callable:
    """
    Apply security middleware to Lambda handler functions.
    
    This decorator adds security headers and basic request validation.
    """
    @wraps(func)
    def wrapper(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        try:
            # Add security headers to the event context
            if 'headers' not in event:
                event['headers'] = {}
            
            # Add security context
            event['security_context'] = {
                'request_id': context.aws_request_id if hasattr(context, 'aws_request_id') else 'unknown',
                'function_name': context.function_name if hasattr(context, 'function_name') else 'unknown',
                'timestamp': context.get_remaining_time_in_millis() if hasattr(context, 'get_remaining_time_in_millis') else None
            }
            
            # Call the original function
            result = func(event, context)
            
            # Add security headers to response if it's a dict
            if isinstance(result, dict) and 'headers' in result:
                result['headers'].update({
                    'X-Content-Type-Options': 'nosniff',
                    'X-Frame-Options': 'DENY',
                    'X-XSS-Protection': '1; mode=block',
                    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Security middleware error: {str(e)}")
            # Return the original function result on middleware error
            return func(event, context)
    
    return wrapper


def validate_request_headers(event: Dict[str, Any]) -> bool:
    """
    Validate request headers for security compliance.
    """
    headers = event.get('headers', {})
    
    # Basic header validation
    required_headers = ['content-type'] if event.get('httpMethod') == 'POST' else []
    
    for header in required_headers:
        if header.lower() not in [h.lower() for h in headers.keys()]:
            logger.warning(f"Missing required header: {header}")
            return False
    
    return True


def sanitize_input(data: Any) -> Any:
    """
    Basic input sanitization for security.
    """
    if isinstance(data, str):
        # Remove potentially dangerous characters
        dangerous_chars = ['<', '>', '"', "'", '&', '\x00']
        for char in dangerous_chars:
            data = data.replace(char, '')
    elif isinstance(data, dict):
        return {k: sanitize_input(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_input(item) for item in data]
    
    return data