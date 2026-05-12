"""
Logging configuration for the Prior Authorization Application.

This module provides structured logging configuration with HIPAA-compliant
audit trails and proper log formatting for AWS CloudWatch integration.
"""

import structlog
import logging
import os
import sys
from typing import Any, Dict
from datetime import datetime


def configure_logging(log_level: str = None) -> None:
    """Configure structured logging for the application"""
    
    # Get log level from environment or default to INFO
    if log_level is None:
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            add_timestamp,
            add_request_id,
            sanitize_pii,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def add_timestamp(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add timestamp to log entries"""
    event_dict['timestamp'] = datetime.utcnow().isoformat() + 'Z'
    return event_dict


def add_request_id(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add request ID to log entries for tracing"""
    # Try to get request ID from various sources
    request_id = (
        os.getenv('AWS_REQUEST_ID') or 
        os.getenv('_X_AMZN_TRACE_ID') or
        event_dict.get('request_id')
    )
    
    if request_id:
        event_dict['request_id'] = request_id
    
    return event_dict


def sanitize_pii(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize PII from log entries for HIPAA compliance"""
    
    # Fields that should be sanitized or removed
    pii_fields = {
        'patient_name', 'patient_id', 'ssn', 'medical_record_number',
        'phone_number', 'email', 'address', 'date_of_birth'
    }
    
    # Recursively sanitize the event dictionary
    sanitized_dict = _sanitize_dict(event_dict, pii_fields)
    
    return sanitized_dict


def _sanitize_dict(data: Dict[str, Any], pii_fields: set) -> Dict[str, Any]:
    """Recursively sanitize dictionary for PII"""
    sanitized = {}
    
    for key, value in data.items():
        if key.lower() in pii_fields:
            # Replace PII with placeholder
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_dict(value, pii_fields)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_dict(item, pii_fields) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    
    return sanitized


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a configured logger instance"""
    
    # Configure logging if not already done
    if not structlog.is_configured():
        configure_logging()
    
    return structlog.get_logger(name)


class AuditLogger:
    """Specialized logger for HIPAA audit trails"""
    
    def __init__(self):
        self.logger = get_logger("audit")
    
    def log_document_access(self, document_id: str, user_id: str, 
                           action: str, result: str = "success"):
        """Log document access for audit trail"""
        self.logger.info(
            "Document access",
            event_type="document_access",
            document_id=document_id,
            user_id=user_id,
            action=action,
            result=result,
            compliance_event=True
        )
    
    def log_processing_step(self, document_id: str, step_name: str, 
                           status: str, processing_time: float = None):
        """Log processing step for audit trail"""
        log_data = {
            "event_type": "processing_step",
            "document_id": document_id,
            "step_name": step_name,
            "status": status,
            "compliance_event": True
        }
        
        if processing_time is not None:
            log_data["processing_time_seconds"] = processing_time
        
        self.logger.info("Processing step completed", **log_data)
    
    def log_policy_access(self, policy_id: str, payor: str, 
                         access_type: str = "retrieve"):
        """Log policy access for audit trail"""
        self.logger.info(
            "Policy access",
            event_type="policy_access",
            policy_id=policy_id,
            payor=payor,
            access_type=access_type,
            compliance_event=True
        )
    
    def log_assessment_result(self, assessment_id: str, document_id: str,
                             overall_compliance: str, approval_likelihood: float):
        """Log assessment result for audit trail"""
        self.logger.info(
            "Assessment completed",
            event_type="assessment_result",
            assessment_id=assessment_id,
            document_id=document_id,
            overall_compliance=overall_compliance,
            approval_likelihood=approval_likelihood,
            compliance_event=True
        )
    
    def log_error(self, error_type: str, error_message: str, 
                  document_id: str = None, step_name: str = None):
        """Log error for audit trail"""
        log_data = {
            "event_type": "error",
            "error_type": error_type,
            "error_message": error_message,
            "compliance_event": True
        }
        
        if document_id:
            log_data["document_id"] = document_id
        if step_name:
            log_data["step_name"] = step_name
        
        self.logger.error("Processing error", **log_data)


# Global audit logger instance
_audit_logger: AuditLogger = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
