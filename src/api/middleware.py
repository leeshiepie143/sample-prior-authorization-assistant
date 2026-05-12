"""
API middleware for request validation, rate limiting, and security.

This module provides middleware functions for API Gateway requests
including input validation, rate limiting, and security headers.
"""

import json
import time
import hashlib
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from common.exceptions import APIError, ValidationError, RateLimitError
from common.logging_config import get_logger
from common.decorators import handle_processing_errors
from common.validators import RequestValidator
from common.aws_clients import get_dynamodb_service

logger = get_logger(__name__)


class RateLimitType(Enum):
    """Types of rate limiting"""
    PER_IP = "per_ip"
    PER_USER = "per_user"
    PER_ENDPOINT = "per_endpoint"
    GLOBAL = "global"


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    burst_limit: int = 10


@dataclass
class ValidationRule:
    """Request validation rule"""
    field_name: str
    required: bool = True
    data_type: type = str
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    allowed_values: Optional[list] = None


class RequestValidationMiddleware:
    """Middleware for request validation"""
    
    def __init__(self):
        self.validator = RequestValidator()
    
    def validate_request(self, event: Dict[str, Any], validation_rules: Dict[str, ValidationRule]) -> Dict[str, Any]:
        """Validate API Gateway request"""
        
        errors = []
        
        # Extract request data
        body = event.get('body', '')
        query_params = event.get('queryStringParameters') or {}
        path_params = event.get('pathParameters') or {}
        headers = event.get('headers') or {}
        
        # Parse body if JSON
        body_data = {}
        if body:
            try:
                body_data = json.loads(body)
            except json.JSONDecodeError:
                errors.append("Invalid JSON in request body")
        
        # Combine all request data
        request_data = {
            **body_data,
            **query_params,
            **path_params
        }
        
        # Validate each field
        for field_name, rule in validation_rules.items():
            field_value = request_data.get(field_name)
            
            # Check required fields
            if rule.required and (field_value is None or field_value == ''):
                errors.append(f"Missing required field: {field_name}")
                continue
            
            # Skip validation if field is not present and not required
            if field_value is None:
                continue
            
            # Validate data type
            if not isinstance(field_value, rule.data_type):
                try:
                    # Try to convert to expected type
                    if rule.data_type == int:
                        field_value = int(field_value)
                    elif rule.data_type == float:
                        field_value = float(field_value)
                    elif rule.data_type == bool:
                        field_value = str(field_value).lower() in ['true', '1', 'yes']
                    request_data[field_name] = field_value
                except (ValueError, TypeError):
                    errors.append(f"Invalid data type for {field_name}: expected {rule.data_type.__name__}")
                    continue
            
            # Validate string length
            if rule.data_type == str and isinstance(field_value, str):
                if rule.min_length and len(field_value) < rule.min_length:
                    errors.append(f"{field_name} must be at least {rule.min_length} characters")
                
                if rule.max_length and len(field_value) > rule.max_length:
                    errors.append(f"{field_name} must be no more than {rule.max_length} characters")
            
            # Validate pattern
            if rule.pattern and isinstance(field_value, str):
                import re
                if not re.match(rule.pattern, field_value):
                    errors.append(f"{field_name} does not match required pattern")
            
            # Validate allowed values
            if rule.allowed_values and field_value not in rule.allowed_values:
                errors.append(f"{field_name} must be one of: {', '.join(map(str, rule.allowed_values))}")
        
        if errors:
            raise ValidationError(f"Validation errors: {'; '.join(errors)}")
        
        return request_data


class RateLimitingMiddleware:
    """Middleware for API rate limiting"""
    
    def __init__(self):
        self.dynamodb_service = get_dynamodb_service()
        self.rate_limit_table = 'api-rate-limits'
        
        # Default rate limit configurations
        self.default_limits = {
            'upload': RateLimitConfig(
                requests_per_minute=5,
                requests_per_hour=50,
                requests_per_day=200,
                burst_limit=3
            ),
            'status': RateLimitConfig(
                requests_per_minute=30,
                requests_per_hour=500,
                requests_per_day=2000,
                burst_limit=10
            ),
            'results': RateLimitConfig(
                requests_per_minute=20,
                requests_per_hour=300,
                requests_per_day=1000,
                burst_limit=5
            ),
            'default': RateLimitConfig(
                requests_per_minute=10,
                requests_per_hour=100,
                requests_per_day=500,
                burst_limit=5
            )
        }
    
    @handle_processing_errors
    def check_rate_limit(self, event: Dict[str, Any], endpoint_type: str = 'default') -> None:
        """Check if request exceeds rate limits"""
        
        # Get client identifier
        client_id = self._get_client_identifier(event)
        
        # Get rate limit configuration
        config = self.default_limits.get(endpoint_type, self.default_limits['default'])
        
        # Check rate limits
        current_time = datetime.utcnow()
        
        # Check minute limit
        self._check_time_window_limit(
            client_id, endpoint_type, 'minute',
            config.requests_per_minute, current_time, timedelta(minutes=1)
        )
        
        # Check hour limit
        self._check_time_window_limit(
            client_id, endpoint_type, 'hour',
            config.requests_per_hour, current_time, timedelta(hours=1)
        )
        
        # Check day limit
        self._check_time_window_limit(
            client_id, endpoint_type, 'day',
            config.requests_per_day, current_time, timedelta(days=1)
        )
        
        # Record this request
        self._record_request(client_id, endpoint_type, current_time)
    
    def _get_client_identifier(self, event: Dict[str, Any]) -> str:
        """Get unique identifier for the client"""
        
        # Try to get user ID from context (if authenticated)
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        user_id = authorizer.get('user_id')
        
        if user_id:
            return f"user:{user_id}"
        
        # Fall back to IP address
        source_ip = request_context.get('identity', {}).get('sourceIp', 'unknown')
        return f"ip:{source_ip}"
    
    def _check_time_window_limit(self, client_id: str, endpoint_type: str,
                               window_type: str, limit: int,
                               current_time: datetime, window_duration: timedelta) -> None:
        """Check rate limit for a specific time window"""
        
        try:
            # Create key for this time window
            window_start = current_time - window_duration
            key = f"{client_id}:{endpoint_type}:{window_type}:{window_start.strftime('%Y%m%d%H%M')}"
            
            # Get current count from DynamoDB
            response = self.dynamodb_service.get_item(
                table_name=self.rate_limit_table,
                key={'limit_key': key}
            )
            
            current_count = 0
            if response and 'Item' in response:
                current_count = int(response['Item'].get('request_count', 0))
            
            # Check if limit exceeded
            if current_count >= limit:
                raise RateLimitError(
                    f"Rate limit exceeded: {current_count}/{limit} requests per {window_type}",
                    retry_after=int(window_duration.total_seconds())
                )
            
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Rate limit check failed", error=str(e))
            # Don't block requests if rate limiting fails
    
    def _record_request(self, client_id: str, endpoint_type: str, timestamp: datetime) -> None:
        """Record a request for rate limiting"""
        
        try:
            # Record for different time windows
            windows = [
                ('minute', timedelta(minutes=1)),
                ('hour', timedelta(hours=1)),
                ('day', timedelta(days=1))
            ]
            
            for window_type, duration in windows:
                window_start = timestamp - duration
                key = f"{client_id}:{endpoint_type}:{window_type}:{window_start.strftime('%Y%m%d%H%M')}"
                
                # Increment counter in DynamoDB
                self.dynamodb_service.update_item(
                    table_name=self.rate_limit_table,
                    key={'limit_key': key},
                    update_expression='ADD request_count :inc SET last_request = :timestamp, expires_at = :expires',
                    expression_attribute_values={
                        ':inc': 1,
                        ':timestamp': timestamp.isoformat(),
                        ':expires': int((timestamp + duration).timestamp())
                    }
                )
                
        except Exception as e:
            logger.warning("Failed to record request for rate limiting", error=str(e))


class SecurityHeadersMiddleware:
    """Middleware for adding security headers"""
    
    @staticmethod
    def add_security_headers(response: Dict[str, Any]) -> Dict[str, Any]:
        """Add security headers to API response"""
        
        if 'headers' not in response:
            response['headers'] = {}
        
        security_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Content-Security-Policy': "default-src 'self'",
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Cache-Control': 'no-store, no-cache, must-revalidate, private'
        }
        
        response['headers'].update(security_headers)
        return response


class RequestLoggingMiddleware:
    """Middleware for request logging and monitoring"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    def log_request(self, event: Dict[str, Any], context: Any) -> None:
        """Log incoming request"""
        
        request_context = event.get('requestContext', {})
        
        log_data = {
            'request_id': context.aws_request_id if context else 'unknown',
            'method': event.get('httpMethod'),
            'path': event.get('path'),
            'source_ip': request_context.get('identity', {}).get('sourceIp'),
            'user_agent': event.get('headers', {}).get('User-Agent'),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Add user info if available
        authorizer = request_context.get('authorizer', {})
        if authorizer.get('user_id'):
            log_data['user_id'] = authorizer['user_id']
            log_data['user_role'] = authorizer.get('user_role')
        
        self.logger.info("API request", **log_data)
    
    def log_response(self, response: Dict[str, Any], duration_ms: float) -> None:
        """Log API response"""
        
        log_data = {
            'status_code': response.get('statusCode'),
            'duration_ms': duration_ms,
            'response_size': len(response.get('body', '')),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if response.get('statusCode', 200) >= 400:
            self.logger.warning("API error response", **log_data)
        else:
            self.logger.info("API response", **log_data)


class MiddlewareChain:
    """Chain multiple middleware functions together"""
    
    def __init__(self):
        self.validation_middleware = RequestValidationMiddleware()
        self.rate_limit_middleware = RateLimitingMiddleware()
        self.logging_middleware = RequestLoggingMiddleware()
    
    def process_request(self, event: Dict[str, Any], context: Any,
                       validation_rules: Dict[str, ValidationRule] = None,
                       endpoint_type: str = 'default') -> Dict[str, Any]:
        """Process request through middleware chain"""
        
        start_time = time.time()
        
        try:
            # Log incoming request
            self.logging_middleware.log_request(event, context)
            
            # Check rate limits
            self.rate_limit_middleware.check_rate_limit(event, endpoint_type)
            
            # Validate request
            validated_data = {}
            if validation_rules:
                validated_data = self.validation_middleware.validate_request(event, validation_rules)
            
            return validated_data
            
        except (ValidationError, RateLimitError) as e:
            # Log middleware errors
            duration_ms = (time.time() - start_time) * 1000
            error_response = {
                'statusCode': 400 if isinstance(e, ValidationError) else 429,
                'body': json.dumps({'error': str(e)})
            }
            self.logging_middleware.log_response(error_response, duration_ms)
            raise
    
    def process_response(self, response: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        """Process response through middleware chain"""
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Add security headers
        response = SecurityHeadersMiddleware.add_security_headers(response)
        
        # Log response
        self.logging_middleware.log_response(response, duration_ms)
        
        return response


# Validation rule definitions for common endpoints
UPLOAD_VALIDATION_RULES = {
    'filename': ValidationRule(
        field_name='filename',
        required=True,
        data_type=str,
        min_length=1,
        max_length=255,
        pattern=r'^[a-zA-Z0-9._-]+\.(pdf|doc|docx|jpg|jpeg|png|tiff|tif)$'
    ),
    'file_content': ValidationRule(
        field_name='file_content',
        required=True,
        data_type=str,
        min_length=100  # Minimum base64 content length
    )
}

STATUS_VALIDATION_RULES = {
    'document_id': ValidationRule(
        field_name='document_id',
        required=True,
        data_type=str,
        min_length=10,
        max_length=100,
        pattern=r'^[a-zA-Z0-9_-]+$'
    )
}

WORKFLOW_VALIDATION_RULES = {
    'filename': ValidationRule(
        field_name='filename',
        required=True,
        data_type=str,
        min_length=1,
        max_length=255
    ),
    'file_content': ValidationRule(
        field_name='file_content',
        required=True,
        data_type=str,
        min_length=100
    ),
    'workflow_type': ValidationRule(
        field_name='workflow_type',
        required=False,
        data_type=str,
        allowed_values=['standard', 'express', 'parallel', 'development']
    )
}

