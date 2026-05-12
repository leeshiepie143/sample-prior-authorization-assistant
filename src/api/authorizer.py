"""
Lambda authorizer for API Gateway security.

This module implements JWT-based authentication and authorization
for the Prior Authorization API endpoints.
"""

import json
import jwt
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from common.exceptions import AuthenticationError, AuthorizationError
from common.logging_config import get_logger
from common.decorators import handle_processing_errors

logger = get_logger(__name__)


class APIAuthorizer:
    """JWT-based API authorizer for Lambda"""
    
    def __init__(self):
        self.jwt_secret = os.getenv('JWT_SECRET', 'your-secret-key')
        self.jwt_algorithm = os.getenv('JWT_ALGORITHM', 'HS256')
        self.token_expiry_hours = int(os.getenv('TOKEN_EXPIRY_HOURS', '24'))
    
    @handle_processing_errors
    def lambda_handler(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Lambda authorizer handler"""
        
        try:
            # Extract token from event
            token = self._extract_token(event)
            
            if not token:
                raise AuthenticationError("Missing authorization token")
            
            # Validate and decode token
            payload = self._validate_token(token)
            
            # Extract user information
            user_id = payload.get('user_id')
            user_role = payload.get('role', 'user')
            organization = payload.get('organization')
            
            # Check authorization for the requested resource
            method_arn = event.get('methodArn', '')
            self._check_authorization(user_role, method_arn)
            
            # Generate policy
            policy = self._generate_policy(user_id, 'Allow', method_arn)
            
            # Add context information
            policy['context'] = {
                'user_id': user_id,
                'user_role': user_role,
                'organization': organization or '',
                'authorized_at': datetime.utcnow().isoformat()
            }
            
            logger.info("Authorization successful",
                       user_id=user_id,
                       role=user_role,
                       method=method_arn)
            
            return policy
            
        except (AuthenticationError, AuthorizationError) as e:
            logger.warning("Authorization failed", error=str(e))
            # Return deny policy
            return self._generate_policy('unknown', 'Deny', event.get('methodArn', '*'))
            
        except Exception as e:
            logger.error("Authorizer error", error=str(e))
            # Return deny policy for any unexpected errors
            return self._generate_policy('unknown', 'Deny', event.get('methodArn', '*'))
    
    def _extract_token(self, event: Dict[str, Any]) -> Optional[str]:
        """Extract JWT token from the authorization header"""
        
        # Try different token locations
        
        # 1. Authorization header
        auth_header = event.get('authorizationToken')
        if auth_header:
            if auth_header.startswith('Bearer '):
                return auth_header[7:]  # Remove 'Bearer ' prefix
            return auth_header
        
        # 2. Headers in the event
        headers = event.get('headers', {})
        auth_header = headers.get('Authorization') or headers.get('authorization')
        if auth_header:
            if auth_header.startswith('Bearer '):
                return auth_header[7:]
            return auth_header
        
        # 3. Query parameters
        query_params = event.get('queryStringParameters') or {}
        token = query_params.get('token')
        if token:
            return token
        
        return None
    
    def _validate_token(self, token: str) -> Dict[str, Any]:
        """Validate and decode JWT token"""
        
        try:
            # Decode and validate token
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm]
            )
            
            # Check expiration
            exp = payload.get('exp')
            if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
                raise AuthenticationError("Token has expired")
            
            # Validate required fields
            required_fields = ['user_id', 'role']
            for field in required_fields:
                if field not in payload:
                    raise AuthenticationError(f"Missing required field in token: {field}")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {str(e)}")
        except Exception as e:
            raise AuthenticationError(f"Token validation failed: {str(e)}")
    
    def _check_authorization(self, user_role: str, method_arn: str) -> None:
        """Check if user role is authorized for the requested resource"""
        
        # Define role-based permissions
        role_permissions = {
            'admin': ['*'],  # Admin can access everything
            'provider': [
                'POST:/api/v1/documents/upload',
                'GET:/api/v1/documents/*/status',
                'GET:/api/v1/documents/*/results',
                'POST:/api/v1/workflow/execute',
                'GET:/api/v1/health'
            ],
            'reviewer': [
                'GET:/api/v1/documents/*/status',
                'GET:/api/v1/documents/*/results',
                'GET:/api/v1/health'
            ],
            'user': [
                'GET:/api/v1/health'
            ]
        }
        
        # Get permissions for user role
        allowed_permissions = role_permissions.get(user_role, [])
        
        # Admin has access to everything
        if '*' in allowed_permissions:
            return
        
        # Extract method and resource from ARN
        # ARN format: arn:aws:execute-api:region:account:api-id/stage/METHOD/resource
        try:
            arn_parts = method_arn.split('/')
            if len(arn_parts) >= 3:
                method = arn_parts[-2]
                resource_path = '/' + '/'.join(arn_parts[-1:])
                
                # Construct permission string
                permission = f"{method}:{resource_path}"
                
                # Check exact match
                if permission in allowed_permissions:
                    return
                
                # Check wildcard matches
                for allowed_permission in allowed_permissions:
                    if self._matches_permission_pattern(permission, allowed_permission):
                        return
        
        except Exception as e:
            logger.warning("Failed to parse method ARN", arn=method_arn, error=str(e))
        
        # If no match found, deny access
        raise AuthorizationError(f"User role '{user_role}' not authorized for this resource")
    
    def _matches_permission_pattern(self, permission: str, pattern: str) -> bool:
        """Check if permission matches a pattern with wildcards"""
        
        # Simple wildcard matching
        if '*' in pattern:
            # Replace * with regex pattern and match
            import re
            regex_pattern = pattern.replace('*', '.*')
            return bool(re.match(regex_pattern, permission))
        
        return permission == pattern
    
    def _generate_policy(self, principal_id: str, effect: str, resource: str) -> Dict[str, Any]:
        """Generate IAM policy for API Gateway"""
        
        policy = {
            'principalId': principal_id,
            'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Action': 'execute-api:Invoke',
                        'Effect': effect,
                        'Resource': resource
                    }
                ]
            }
        }
        
        return policy


class TokenManager:
    """Utility class for generating and managing JWT tokens"""
    
    def __init__(self):
        self.jwt_secret = os.getenv('JWT_SECRET', 'your-secret-key')
        self.jwt_algorithm = os.getenv('JWT_ALGORITHM', 'HS256')
        self.token_expiry_hours = int(os.getenv('TOKEN_EXPIRY_HOURS', '24'))
    
    def generate_token(self, user_id: str, role: str, organization: str = None) -> str:
        """Generate JWT token for user"""
        
        # Token payload
        payload = {
            'user_id': user_id,
            'role': role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=self.token_expiry_hours)
        }
        
        if organization:
            payload['organization'] = organization
        
        # Generate token
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        
        return token
    
    def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate token and return payload"""
        
        authorizer = APIAuthorizer()
        return authorizer._validate_token(token)
    
    def refresh_token(self, token: str) -> str:
        """Refresh an existing token"""
        
        try:
            # Decode current token (ignore expiration for refresh)
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm],
                options={"verify_exp": False}
            )
            
            # Generate new token with same payload but new expiration
            return self.generate_token(
                user_id=payload['user_id'],
                role=payload['role'],
                organization=payload.get('organization')
            )
            
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Cannot refresh invalid token: {str(e)}")


class RoleBasedAccessControl:
    """Role-based access control utilities"""
    
    # Define role hierarchy (higher number = more permissions)
    ROLE_HIERARCHY = {
        'user': 1,
        'reviewer': 2,
        'provider': 3,
        'admin': 4
    }
    
    @classmethod
    def has_role_access(cls, user_role: str, required_role: str) -> bool:
        """Check if user role has access to required role level"""
        
        user_level = cls.ROLE_HIERARCHY.get(user_role, 0)
        required_level = cls.ROLE_HIERARCHY.get(required_role, 999)
        
        return user_level >= required_level
    
    @classmethod
    def get_user_permissions(cls, role: str) -> List[str]:
        """Get list of permissions for a role"""
        
        permissions = {
            'admin': [
                'documents:upload',
                'documents:view',
                'documents:status',
                'documents:results',
                'workflow:execute',
                'system:health',
                'admin:manage'
            ],
            'provider': [
                'documents:upload',
                'documents:view',
                'documents:status',
                'documents:results',
                'workflow:execute',
                'system:health'
            ],
            'reviewer': [
                'documents:view',
                'documents:status',
                'documents:results',
                'system:health'
            ],
            'user': [
                'system:health'
            ]
        }
        
        return permissions.get(role, [])


# Lambda handler for the authorizer
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda authorizer entry point"""
    
    authorizer = APIAuthorizer()
    return authorizer.lambda_handler(event, context)


# Utility functions for token management
def generate_user_token(user_id: str, role: str, organization: str = None) -> str:
    """Generate token for a user"""
    
    token_manager = TokenManager()
    return token_manager.generate_token(user_id, role, organization)


def validate_user_token(token: str) -> Dict[str, Any]:
    """Validate user token"""
    
    token_manager = TokenManager()
    return token_manager.validate_token(token)

