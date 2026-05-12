"""
API Gateway module for the Prior Authorization Application.

This module provides REST API endpoints with Lambda integration,
authentication, authorization, and request validation.

Key Components:
- Gateway Handler: Main API request routing and processing
- Authorizer: JWT-based authentication and authorization
- Middleware: Request validation, rate limiting, and security
- Configuration: API Gateway setup and deployment utilities

API Endpoints:
- POST /api/v1/documents/upload - Upload prior authorization documents
- GET /api/v1/documents/{id}/status - Check processing status
- GET /api/v1/documents/{id}/results - Retrieve assessment results
- POST /api/v1/workflow/execute - Direct workflow execution
- GET /api/v1/health - Health check endpoint

Security Features:
- JWT-based authentication
- Role-based access control
- Rate limiting per user/IP
- Request validation
- Security headers
- CORS support

Usage:
    from src.api import APIGatewayHandler, APIAuthorizer
    
    # Create API handler
    handler = APIGatewayHandler()
    
    # Process API Gateway event
    response = handler.lambda_handler(event, context)
"""

from .gateway_handler import APIGatewayHandler, lambda_handler

# Conditional imports to avoid dependency issues in Lambda
try:
    from .authorizer import APIAuthorizer, TokenManager, RoleBasedAccessControl
except ImportError:
    # JWT not available in Lambda environment
    APIAuthorizer = None
    TokenManager = None
    RoleBasedAccessControl = None

try:
    from .middleware import (
        MiddlewareChain, 
        RequestValidationMiddleware,
        RateLimitingMiddleware,
        SecurityHeadersMiddleware,
        UPLOAD_VALIDATION_RULES,
        STATUS_VALIDATION_RULES,
        WORKFLOW_VALIDATION_RULES
    )
except ImportError:
    # Fallback implementations
    class MiddlewareChain:
        def process_request(self, event):
            return event
        def process_response(self, response, start_time):
            return response
    
    RequestValidationMiddleware = None
    RateLimitingMiddleware = None
    SecurityHeadersMiddleware = None
    UPLOAD_VALIDATION_RULES = {}
    STATUS_VALIDATION_RULES = {}
    WORKFLOW_VALIDATION_RULES = {}

__all__ = [
    'APIGatewayHandler',
    'lambda_handler'
]

# Add conditionally imported items if they exist
if APIAuthorizer is not None:
    __all__.extend(['APIAuthorizer', 'TokenManager', 'RoleBasedAccessControl'])

if RequestValidationMiddleware is not None:
    __all__.extend([
        'MiddlewareChain',
        'RequestValidationMiddleware',
        'RateLimitingMiddleware', 
        'SecurityHeadersMiddleware',
        'UPLOAD_VALIDATION_RULES',
        'STATUS_VALIDATION_RULES',
        'WORKFLOW_VALIDATION_RULES'
    ])
