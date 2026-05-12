"""
Medical Records Extractor Module

Handles document processing and extraction of key medical data including:
- CPT codes and ICD codes
- Payor and insurance information
- Service types and clinical context
- Patient demographics and medical history
"""

from .document_processor import DocumentProcessor, DocumentValidationService
from .medical_extractor import MedicalDataExtractor
from .fhir_extractor import FHIRDataExtractor
from .format_detector import FormatDetector, DocumentFormat
from .handler import lambda_handler, health_check

__all__ = [
    'DocumentProcessor',
    'DocumentValidationService', 
    'MedicalDataExtractor',
    'FHIRDataExtractor',
    'FormatDetector',
    'DocumentFormat',
    'lambda_handler',
    'health_check'
]
