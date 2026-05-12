"""
Custom exception classes for the Prior Authorization Application.

This module defines all custom exceptions used throughout the system
for proper error handling and categorization.
"""

from typing import Optional


class PriorAuthException(Exception):
    """Base exception for Prior Authorization Application"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, 
                 retry_able: bool = False):
        self.message = message
        self.error_code = error_code
        self.retry_able = retry_able
        super().__init__(message)


class AWSServiceError(PriorAuthException):
    """Exception for AWS service-related errors"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, 
                 retry_able: bool = True):
        super().__init__(message, error_code, retry_able)


class BedrockThrottlingException(AWSServiceError):
    """Exception for Bedrock API throttling"""
    
    def __init__(self, message: str):
        super().__init__(message, "BEDROCK_THROTTLE", retry_able=True)


class DocumentParsingException(PriorAuthException):
    """Exception for document parsing errors"""
    
    def __init__(self, message: str, document_id: Optional[str] = None):
        self.document_id = document_id
        super().__init__(message, "DOCUMENT_PARSE_ERROR", retry_able=False)


class DataValidationError(PriorAuthException):
    """Exception for data validation errors"""
    
    def __init__(self, message: str, field_name: Optional[str] = None):
        self.field_name = field_name
        super().__init__(message, "VALIDATION_ERROR", retry_able=False)


class PolicySelectionError(PriorAuthException):
    """Exception for policy selection errors"""
    
    def __init__(self, message: str, payor: Optional[str] = None):
        self.payor = payor
        super().__init__(message, "POLICY_SELECTION_ERROR", retry_able=True)


class MedicalCodeValidationError(DataValidationError):
    """Exception for medical code validation errors"""
    
    def __init__(self, message: str, code: str, code_type: str):
        self.code = code
        self.code_type = code_type
        super().__init__(f"{code_type} code validation failed: {message}", code_type)


class AssessmentError(PriorAuthException):
    """Exception for medical record assessment errors"""
    
    def __init__(self, message: str, criterion_id: Optional[str] = None):
        self.criterion_id = criterion_id
        super().__init__(message, "ASSESSMENT_ERROR", retry_able=True)


class WorkflowError(PriorAuthException):
    """Exception for workflow orchestration errors"""
    
    def __init__(self, message: str, step_name: Optional[str] = None):
        self.step_name = step_name
        super().__init__(message, "WORKFLOW_ERROR", retry_able=True)


class ConfigurationError(PriorAuthException):
    """Exception for configuration-related errors"""
    
    def __init__(self, message: str, config_key: Optional[str] = None):
        self.config_key = config_key
        super().__init__(message, "CONFIG_ERROR", retry_able=False)


class SecurityError(PriorAuthException):
    """Exception for security-related errors"""
    
    def __init__(self, message: str):
        super().__init__(message, "SECURITY_ERROR", retry_able=False)


class UnsupportedFormatException(PriorAuthException):
    """Exception for unsupported document formats"""
    
    def __init__(self, message: str, format_type: Optional[str] = None):
        self.format_type = format_type
        super().__init__(message, "UNSUPPORTED_FORMAT", retry_able=False)


class FormatDetectionException(PriorAuthException):
    """Exception for format detection failures"""
    
    def __init__(self, message: str, document_id: Optional[str] = None):
        self.document_id = document_id
        super().__init__(message, "FORMAT_DETECTION_ERROR", retry_able=True)


class FHIRParsingException(DocumentParsingException):
    """Exception for FHIR parsing errors"""
    
    def __init__(self, message: str, document_id: Optional[str] = None):
        super().__init__(f"FHIR parsing failed: {message}", document_id)
        self.error_code = "FHIR_PARSE_ERROR"


class EncryptionError(SecurityError):
    """Exception for encryption/decryption errors"""
    
    def __init__(self, message: str):
        super().__init__(message)


class AuthenticationError(SecurityError):
    """Exception for authentication errors"""
    
    def __init__(self, message: str):
        super().__init__(message)


class RateLimitError(SecurityError):
    """Exception for rate limiting errors"""
    
    def __init__(self, message: str):
        super().__init__(message)


class NoPoliciesFoundError(PolicySelectionError):
    """Exception when no policies match the search criteria"""
    
    def __init__(self, message: str, payor: str, codes: Optional[list] = None):
        self.payor = payor
        self.codes = codes or []
        super().__init__(message, payor)
        self.error_code = "NO_POLICIES_FOUND"
        self.retry_able = False


class NoPayorPoliciesError(NoPoliciesFoundError):
    """Exception when no policies exist for a payor"""
    
    def __init__(self, payor: str):
        message = f"No policies found for payor {payor}"
        super().__init__(message, payor, [])
        self.error_code = "NO_PAYOR_POLICIES"


class NoProcedurePoliciesError(NoPoliciesFoundError):
    """Exception when no policies cover the requested procedures"""
    
    def __init__(self, payor: str, procedure_codes: list):
        codes_str = ', '.join(procedure_codes)
        message = f"No policies found for payor {payor} covering the requested procedures or medications"
        super().__init__(message, payor, procedure_codes)
        self.error_code = "NO_PROCEDURE_POLICIES"
