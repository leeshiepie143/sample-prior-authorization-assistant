"""
Security module for HIPAA-compliant Prior Authorization Application.

This module provides comprehensive security features including:
- AES-256 encryption for data at rest and in transit
- IAM policies with least privilege access
- Security middleware for API protection
- HIPAA compliance validation
- Audit logging and monitoring

Key Components:
- HIPAAEncryptionService: Encryption/decryption with AWS KMS
- SecurityMiddleware: API security enforcement
- IAMPolicyTemplates: Least privilege IAM policies
- SecurityConfiguration: HIPAA compliance validation

Usage:
    from src.security import (
        HIPAAEncryptionService,
        apply_security_middleware,
        validate_hipaa_compliance
    )
    
    # Apply security to Lambda handler
    @apply_security_middleware
    def lambda_handler(event, context):
        # Your handler code here
        pass
    
    # Encrypt sensitive data
    encryption_service = HIPAAEncryptionService()
    encrypted_data = encryption_service.encrypt_sensitive_data(data)
"""

# Import main security components
from .encryption_service import (
    HIPAAEncryptionService,
    IAMAccessControlManager,
    DataClassificationService,
    SecureStorageService,
    HIPAAComplianceValidator,
    encrypt_patient_data,
    decrypt_patient_data,
    create_hipaa_compliant_storage
)

from .iam_policies import (
    IAMPolicyTemplates,
    SecurityConfiguration,
    DataEncryptionStandards,
    generate_lambda_role_policy,
    validate_hipaa_compliance
)

from .security_middleware import (
    SecurityMiddleware,
    InputSanitizer,
    SecurityMiddlewareChain,
    apply_security_middleware,
    create_security_response,
    validate_api_key
)

# Version and metadata
__version__ = "1.0.0"
__author__ = "Prior Authorization Security Team"

# Export all public components
__all__ = [
    # Encryption services
    'HIPAAEncryptionService',
    'IAMAccessControlManager',
    'DataClassificationService',
    'SecureStorageService',
    'HIPAAComplianceValidator',
    
    # IAM and policies
    'IAMPolicyTemplates',
    'SecurityConfiguration',
    'DataEncryptionStandards',
    
    # Security middleware
    'SecurityMiddleware',
    'InputSanitizer',
    'SecurityMiddlewareChain',
    
    # Decorators and utilities
    'apply_security_middleware',
    'create_security_response',
    'validate_api_key',
    
    # Convenience functions
    'encrypt_patient_data',
    'decrypt_patient_data',
    'create_hipaa_compliant_storage',
    'generate_lambda_role_policy',
    'validate_hipaa_compliance'
]

# Security configuration validation on import
def _validate_security_setup():
    """Validate security setup on module import"""
    try:
        validation_result = validate_hipaa_compliance()
        if not validation_result['overall_compliant']:
            import warnings
            warnings.warn(
                "HIPAA compliance issues detected. Check security configuration.",
                UserWarning
            )
    except Exception:  # nosec B110
        # Don't fail import if validation fails
        pass

# Run validation
_validate_security_setup()
