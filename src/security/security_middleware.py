"""
Security middleware for HIPAA-compliant API communications.

This module provides middleware for enforcing encryption in transit,
security headers, and access controls for all API endpoints.
"""

import json
import time
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from urllib.parse import urlparse

from common.exceptions import SecurityError, AuthenticationError, RateLimitError
from common.logging_config import get_logger, get_audit_logger
from common.decorators import handle_processing_errors
from .iam_policies import SecurityConfiguration

logger = get_logger(__name__)
audit_logger = get_audit_logger()


class SecurityMiddleware:
    """Middleware for enforcing security policies"""
    
    def __init__(self):
        self.security_config = SecurityConfiguration()
        self.rate_limit_cache = {}  # In production, use Redis or DynamoDB
    
    @handle_processing_errors
    def enforce_https(self, event: Dict[str, Any]) -> None:
        """Enforce HTTPS for all API communications"""
        
        headers = event.get('headers', {})
        
        # Check X-Forwarded-Proto header (API Gateway sets this)
        protocol = headers.get('X-Forwarded-Proto', '').lower()
        if protocol != 'https':
            # Also check CloudFront-Forwarded-Proto
            cf_protocol = headers.get('CloudFront-Forwarded-Proto', '').lower()
            if cf_protocol != 'https':
                logger.warning("Non-HTTPS request blocked", 
                             protocol=protocol, 
                             cf_protocol=cf_protocol)
                raise SecurityError("HTTPS required for all API communications")
        
        # Log secure connection
        logger.debug("HTTPS connection verified")
    
    @handle_processing_errors
    def add_security_headers(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Add security headers to API response"""
        
        if 'headers' not in response:
            response['headers'] = {}
        
        # Add HIPAA-compliant security headers
        security_headers = self.security_config.get_security_headers()
        response['headers'].update(security_headers)
        
        # Add CORS headers if needed
        cors_config = self.security_config.get_cors_configuration()
        if cors_config:
            response['headers'].update({
                'Access-Control-Allow-Origin': cors_config['AllowOrigins'][0],
                'Access-Control-Allow-Methods': ', '.join(cors_config['AllowMethods']),
                'Access-Control-Allow-Headers': ', '.join(cors_config['AllowHeaders']),
                'Access-Control-Max-Age': str(cors_config['MaxAge'])
            })
        
        return response
    
    @handle_processing_errors
    def validate_content_type(self, event: Dict[str, Any]) -> None:
        """Validate request content type"""
        
        method = event.get('httpMethod', '')
        headers = event.get('headers', {})
        
        # Skip validation for GET and OPTIONS requests
        if method in ['GET', 'OPTIONS']:
            return
        
        content_type = headers.get('Content-Type', '').lower()
        
        # Allow specific content types for medical document uploads
        allowed_types = [
            'application/json',
            'multipart/form-data',
            'application/pdf',
            'image/jpeg',
            'image/png',
            'image/tiff'
        ]
        
        if not any(allowed_type in content_type for allowed_type in allowed_types):
            logger.warning("Invalid content type", content_type=content_type)
            raise SecurityError(f"Content type not allowed: {content_type}")
    
    @handle_processing_errors
    def enforce_rate_limiting(self, event: Dict[str, Any]) -> None:
        """Enforce rate limiting to prevent abuse"""
        
        # Extract client identifier
        client_ip = self._get_client_ip(event)
        user_id = self._get_user_id(event)
        
        # Use user_id if available, otherwise use IP
        client_key = user_id or client_ip
        
        if not client_key:
            logger.warning("Unable to identify client for rate limiting")
            return
        
        current_time = int(time.time())
        window_size = 60  # 1 minute window
        max_requests = 100  # Max requests per minute
        
        # Clean old entries
        self._clean_rate_limit_cache(current_time, window_size)
        
        # Check current rate
        if client_key not in self.rate_limit_cache:
            self.rate_limit_cache[client_key] = []
        
        client_requests = self.rate_limit_cache[client_key]
        
        # Remove requests outside the window
        client_requests[:] = [req_time for req_time in client_requests 
                             if current_time - req_time < window_size]
        
        # Check if limit exceeded
        if len(client_requests) >= max_requests:
            logger.warning("Rate limit exceeded", 
                          client_key=client_key, 
                          requests_count=len(client_requests))
            raise RateLimitError("Rate limit exceeded. Please try again later.")
        
        # Add current request
        client_requests.append(current_time)
    
    def _get_client_ip(self, event: Dict[str, Any]) -> Optional[str]:
        """Extract client IP address from event"""
        
        request_context = event.get('requestContext', {})
        identity = request_context.get('identity', {})
        
        # Try various IP sources
        ip_sources = [
            identity.get('sourceIp'),
            event.get('headers', {}).get('X-Forwarded-For', '').split(',')[0].strip(),
            event.get('headers', {}).get('X-Real-IP'),
            request_context.get('http', {}).get('sourceIp')
        ]
        
        for ip in ip_sources:
            if ip and ip != '127.0.0.1':
                return ip
        
        return None
    
    def _get_user_id(self, event: Dict[str, Any]) -> Optional[str]:
        """Extract user ID from event (if authenticated)"""
        
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        
        return authorizer.get('user_id')
    
    def _clean_rate_limit_cache(self, current_time: int, window_size: int) -> None:
        """Clean old entries from rate limit cache"""
        
        # Remove entries older than 5 minutes to prevent memory buildup
        cleanup_threshold = current_time - (window_size * 5)
        
        for client_key in list(self.rate_limit_cache.keys()):
            client_requests = self.rate_limit_cache[client_key]
            client_requests[:] = [req_time for req_time in client_requests 
                                 if req_time > cleanup_threshold]
            
            # Remove empty entries
            if not client_requests:
                del self.rate_limit_cache[client_key]
    
    @handle_processing_errors
    def validate_request_size(self, event: Dict[str, Any]) -> None:
        """Validate request size limits"""
        
        # Check Content-Length header
        headers = event.get('headers', {})
        content_length = headers.get('Content-Length')
        
        if content_length:
            try:
                size_bytes = int(content_length)
                max_size = 50 * 1024 * 1024  # 50MB limit for medical documents
                
                if size_bytes > max_size:
                    logger.warning("Request size exceeds limit", 
                                  size_bytes=size_bytes, 
                                  max_size=max_size)
                    raise SecurityError("Request size exceeds maximum allowed limit")
            except ValueError:
                logger.warning("Invalid Content-Length header", content_length=content_length)
    
    @handle_processing_errors
    def log_security_event(self, event: Dict[str, Any], event_type: str, 
                          details: Dict[str, Any] = None) -> None:
        """Log security-related events for audit"""
        
        client_ip = self._get_client_ip(event)
        user_id = self._get_user_id(event)
        
        audit_details = {
            'client_ip': client_ip,
            'user_agent': event.get('headers', {}).get('User-Agent'),
            'method': event.get('httpMethod'),
            'path': event.get('path'),
            'timestamp': datetime.utcnow().isoformat(),
            **(details or {})
        }
        
        audit_logger.log_security_event(
            event_type=event_type,
            details=audit_details,
            user_id=user_id,
            source_ip=client_ip
        )


class InputSanitizer:
    """Sanitize and validate input data"""
    
    @staticmethod
    @handle_processing_errors
    def sanitize_json_input(data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize JSON input data"""
        
        if not isinstance(data, dict):
            raise SecurityError("Invalid input data format")
        
        sanitized = {}
        
        for key, value in data.items():
            # Sanitize key
            clean_key = InputSanitizer._sanitize_string(str(key))
            
            # Sanitize value based on type
            if isinstance(value, str):
                sanitized[clean_key] = InputSanitizer._sanitize_string(value)
            elif isinstance(value, (int, float, bool)):
                sanitized[clean_key] = value
            elif isinstance(value, dict):
                sanitized[clean_key] = InputSanitizer.sanitize_json_input(value)
            elif isinstance(value, list):
                sanitized[clean_key] = [
                    InputSanitizer._sanitize_string(str(item)) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                # Convert other types to string and sanitize
                sanitized[clean_key] = InputSanitizer._sanitize_string(str(value))
        
        return sanitized
    
    @staticmethod
    def _sanitize_string(text: str) -> str:
        """Sanitize string input"""
        
        if not isinstance(text, str):
            return str(text)
        
        # Remove potentially dangerous characters
        dangerous_chars = ['<', '>', '"', "'", '&', '\x00', '\r', '\n']
        sanitized = text
        
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, '')
        
        # Limit length
        max_length = 10000  # Reasonable limit for medical text
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        
        return sanitized.strip()
    
    @staticmethod
    @handle_processing_errors
    def validate_medical_codes(data: Dict[str, Any]) -> None:
        """Validate medical codes format"""
        
        # CPT code validation (5 digits)
        cpt_codes = data.get('cpt_codes', [])
        if cpt_codes:
            for code in cpt_codes:
                if not isinstance(code, str) or not code.isdigit() or len(code) != 5:
                    raise SecurityError(f"Invalid CPT code format: {code}")
        
        # ICD code validation (basic format check)
        icd_codes = data.get('icd_codes', [])
        if icd_codes:
            for code in icd_codes:
                if not isinstance(code, str) or len(code) < 3 or len(code) > 7:
                    raise SecurityError(f"Invalid ICD code format: {code}")


class SecurityMiddlewareChain:
    """Chain of security middleware for request processing"""
    
    def __init__(self):
        self.security_middleware = SecurityMiddleware()
        self.input_sanitizer = InputSanitizer()
    
    @handle_processing_errors
    def process_request(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process request through security middleware chain"""
        
        # 1. Enforce HTTPS
        self.security_middleware.enforce_https(event)
        
        # 2. Validate content type
        self.security_middleware.validate_content_type(event)
        
        # 3. Validate request size
        self.security_middleware.validate_request_size(event)
        
        # 4. Enforce rate limiting
        self.security_middleware.enforce_rate_limiting(event)
        
        # 5. Sanitize input data
        body = event.get('body')
        if body:
            try:
                if isinstance(body, str):
                    parsed_body = json.loads(body)
                else:
                    parsed_body = body
                
                sanitized_body = self.input_sanitizer.sanitize_json_input(parsed_body)
                event['body'] = json.dumps(sanitized_body)
                
                # Validate medical codes if present
                self.input_sanitizer.validate_medical_codes(sanitized_body)
                
            except json.JSONDecodeError:
                # Skip sanitization for non-JSON bodies (e.g., file uploads)
                pass
        
        # 6. Log security event
        self.security_middleware.log_security_event(
            event, 
            'api_request_processed',
            {'middleware_chain': 'completed'}
        )
        
        return event
    
    @handle_processing_errors
    def process_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Process response through security middleware chain"""
        
        # Add security headers
        response = self.security_middleware.add_security_headers(response)
        
        return response
    
    @handle_processing_errors
    def handle_security_error(self, error: Exception, event: Dict[str, Any]) -> Dict[str, Any]:
        """Handle security errors and return appropriate response"""
        
        error_response = {
            'statusCode': 403,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'error': 'Security Error',
                'message': str(error),
                'timestamp': datetime.utcnow().isoformat()
            })
        }
        
        # Log security incident
        self.security_middleware.log_security_event(
            event,
            'security_error',
            {
                'error_type': type(error).__name__,
                'error_message': str(error)
            }
        )
        
        # Add security headers to error response
        return self.process_response(error_response)


# Decorator for applying security middleware
def apply_security_middleware(handler_func: Callable) -> Callable:
    """Decorator to apply security middleware to Lambda handlers"""
    
    def wrapper(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        middleware_chain = SecurityMiddlewareChain()
        
        try:
            # Process request through security middleware
            processed_event = middleware_chain.process_request(event)
            
            # Call the original handler
            response = handler_func(processed_event, context)
            
            # Process response through security middleware
            return middleware_chain.process_response(response)
            
        except (SecurityError, AuthenticationError, RateLimitError) as e:
            # Handle security errors
            return middleware_chain.handle_security_error(e, event)
        except Exception as e:
            # Log unexpected errors
            logger.error("Unexpected error in security middleware", error=str(e))
            return middleware_chain.handle_security_error(
                SecurityError("Internal security error"), event
            )
    
    return wrapper


# Utility functions
def create_security_response(status_code: int, message: str, 
                           details: Dict[str, Any] = None) -> Dict[str, Any]:
    """Create standardized security response"""
    
    response_body = {
        'error': 'Security Error' if status_code >= 400 else 'Success',
        'message': message,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    if details:
        response_body['details'] = details
    
    response = {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps(response_body)
    }
    
    # Add security headers
    middleware = SecurityMiddleware()
    return middleware.add_security_headers(response)


def validate_api_key(event: Dict[str, Any]) -> bool:
    """Validate API key from request headers"""
    
    headers = event.get('headers', {})
    api_key = headers.get('X-API-Key') or headers.get('x-api-key')
    
    if not api_key:
        return False
    
    # In production, validate against stored API keys
    # For now, just check if it exists and has minimum length
    return len(api_key) >= 32

