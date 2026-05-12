"""
Lambda handler for the Medical Records Extractor module.

This module provides the AWS Lambda entry point for document processing
and medical data extraction functionality.
"""

import json
import base64
from typing import Dict, Any

from extractors.document_processor import DocumentProcessor, DocumentValidationService
from extractors.medical_extractor import MedicalDataExtractor
from extractors.format_detector import FormatDetector, DocumentFormat, FormatDetectionException, UnsupportedFormatException
from extractors.fhir_extractor import FHIRDataExtractor, FHIRParsingException
from common.models import ProcessingState, ProcessingStatus
from common.aws_clients import get_dynamodb_service, get_s3_service
from common.exceptions import DocumentParsingException, PriorAuthException
from common.logging_config import get_logger, get_audit_logger
from common.decorators import handle_processing_errors
from common.cloudwatch_metrics import get_metrics
from common.step_functions_utils import ContextAwareErrorHandler
from common.serialization import create_serializable_response
from security.encryption_service import HIPAAEncryptionService
from security.middleware import apply_security_middleware
import os

logger = get_logger(__name__)
audit_logger = get_audit_logger()


@handle_processing_errors
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for medical records extraction.
    
    Expected event structure:
    {
        "action": "upload_and_extract" | "extract_only",
        "document_id": "string",  # Required for extract_only
        "file_content": "base64_encoded_content",  # Required for upload_and_extract
        "filename": "string",  # Required for upload_and_extract
        "content_type": "string"  # Optional
    }
    """
    
    # Initialize context-aware error handler
    error_handler = ContextAwareErrorHandler(event)
    
    logger.info("Medical Records Extractor invoked", 
               action=event.get('action'),
               document_id=event.get('document_id'),
               request_id=context.aws_request_id if context else None)
    
    try:
        # Auto-detect action based on input parameters
        if event.get('file_content') and event.get('filename'):
            # Direct upload scenario
            action = 'upload_and_extract'
            result = handle_upload_and_extract(event, context)
        elif event.get('document_id') and (event.get('bucket_name') or event.get('object_key')):
            # Step Functions scenario - document already uploaded
            action = 'extract_only'
            result = handle_extract_only(event, context)
        else:
            # Fallback to explicit action
            action = event.get('action', 'upload_and_extract')
            if action == 'upload_and_extract':
                result = handle_upload_and_extract(event, context)
            elif action == 'extract_only':
                result = handle_extract_only(event, context)
            else:
                raise ValueError(f"Unknown action: {action}. Expected parameters: file_content+filename OR document_id+bucket_name")
        
        # Return success response based on context (with proper serialization)
        serializable_result = create_serializable_response(result)
        return error_handler.create_success_response(serializable_result)
    
    except PriorAuthException as e:
        logger.error("Processing failed with known error", error=str(e))
        return error_handler.handle_error(e, e.retry_able)
    
    except Exception as e:
        logger.error("Processing failed with unexpected error", error=str(e))
        return error_handler.handle_error(e, True)


def handle_upload_and_extract(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle document upload and extraction workflow"""
    
    # Extract parameters
    file_content_b64 = event.get('file_content')
    filename = event.get('filename')
    content_type = event.get('content_type')
    
    if not file_content_b64 or not filename:
        raise ValueError("file_content and filename are required for upload_and_extract")
    
    # Decode file content
    try:
        file_content = base64.b64decode(file_content_b64)
    except Exception as e:
        raise ValueError(f"Invalid base64 file content: {str(e)}")
    
    # Validate document
    is_valid, validation_errors = DocumentValidationService.validate_document_content(
        file_content, filename
    )
    
    if not is_valid:
        raise DocumentParsingException(
            f"Document validation failed: {'; '.join(validation_errors)}"
        )
    
    # Initialize services
    document_processor = DocumentProcessor()
    medical_extractor = MedicalDataExtractor()
    dynamodb_service = get_dynamodb_service()
    
    # Upload document
    document_id = document_processor.upload_document(
        file_content=file_content,
        filename=filename,
        content_type=content_type
    )
    
    # Initialize processing state
    processing_state = ProcessingState(
        document_id=document_id,
        status=ProcessingStatus.EXTRACTING,
        current_step="document_upload",
        progress_percentage=20
    )
    dynamodb_service.save_processing_state(processing_state)
    
    # Extract text from document
    processing_state.update_progress("text_extraction", 40)
    dynamodb_service.save_processing_state(processing_state)
    
    # Get object_key from event if available (Step Functions scenario)
    object_key = event.get('object_key')
    extraction_result = document_processor.extract_text_from_document(document_id, object_key)
    
    # Extract medical data
    processing_state.update_progress("medical_extraction", 80)
    dynamodb_service.save_processing_state(processing_state)
    
    medical_data = medical_extractor.extract_medical_data(
        document_id=document_id,
        raw_text=extraction_result['raw_text'],
        structured_data=extraction_result['structured_data']
    )
    
    # Complete processing
    processing_state.update_progress("extraction_complete", 100, medical_data)
    processing_state.status = ProcessingStatus.COMPLETED
    dynamodb_service.save_processing_state(processing_state)
    
    # Log successful extraction
    audit_logger.log_processing_step(
        document_id=document_id,
        step_name="medical_extraction",
        status="completed"
    )
    
    return {
        'document_id': document_id,
        'extraction_result': create_serializable_response(medical_data),
        'processing_status': 'completed'
    }


def handle_extract_only(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle extraction from already uploaded document"""
    
    document_id = event.get('document_id')
    if not document_id:
        raise ValueError("document_id is required for extract_only action")
    
    # Get S3 location
    bucket_name = event.get('bucket_name', os.getenv('DOCUMENTS_BUCKET'))
    object_key = event.get('object_key')
    
    if not bucket_name or not object_key:
        raise ValueError("bucket_name and object_key are required for extract_only action")
    
    # Initialize services
    document_processor = DocumentProcessor()
    medical_extractor = MedicalDataExtractor()
    format_detector = FormatDetector()
    fhir_extractor = FHIRDataExtractor()
    dynamodb_service = get_dynamodb_service()
    s3_service = get_s3_service()
    
    # Update processing state - format detection
    processing_state = ProcessingState(
        document_id=document_id,
        status=ProcessingStatus.EXTRACTING,
        current_step="format_detection",
        progress_percentage=10
    )
    dynamodb_service.save_processing_state(processing_state)
    
    # Detect document format
    logger.info("Detecting document format", document_id=document_id)
    import time
    start_time = time.time()
    
    try:
        format_type = format_detector.detect_format(document_id, bucket_name, object_key)
        duration_ms = (time.time() - start_time) * 1000
        
        # Record successful format detection
        get_metrics().record_format_detection(
            format_type.value, True, duration_ms, document_id
        )
        
        logger.info("Format detected", document_id=document_id, format=format_type.value, duration_ms=duration_ms)
        
        # Store format in processing state
        processing_state.update_progress("format_detected", 20, {'format': format_type.value})
        dynamodb_service.save_processing_state(processing_state)
        
    except FormatDetectionException as e:
        duration_ms = (time.time() - start_time) * 1000
        
        # Record failed format detection
        get_metrics().record_format_detection('UNKNOWN', False, duration_ms, document_id)
        get_metrics().record_error('FormatDetectionException', 'FormatDetector', document_id)
        
        logger.warning("Format detection failed", document_id=document_id, error=str(e), duration_ms=duration_ms)
        processing_state.mark_failed(f"Format detection failed: {str(e)}")
        dynamodb_service.save_processing_state(processing_state)
        raise
    
    # Route to appropriate extractor based on format
    if format_type == DocumentFormat.PDF:
        logger.info("Routing to PDF extractor", document_id=document_id)
        result = handle_pdf_extraction(event, context, processing_state, dynamodb_service)
    elif format_type == DocumentFormat.FHIR_JSON:
        logger.info("Routing to FHIR extractor", document_id=document_id)
        result = handle_fhir_extraction(event, context, processing_state, dynamodb_service)
    elif format_type in [DocumentFormat.X12_278_JSON, DocumentFormat.X12_275_JSON]:
        logger.warning("X12 format not yet supported", document_id=document_id, format=format_type.value)
        processing_state.mark_failed(f"X12 format not yet implemented: {format_type.value}")
        dynamodb_service.save_processing_state(processing_state)
        raise NotImplementedError(f"X12 extraction not yet implemented for format: {format_type.value}")
    else:
        logger.warning("Unknown or unsupported format", document_id=document_id, format=format_type.value)
        processing_state.mark_failed(f"Unsupported format: {format_type.value}")
        dynamodb_service.save_processing_state(processing_state)
        raise UnsupportedFormatException(format_type.value, document_id)
    
    return result


def handle_pdf_extraction(event: Dict[str, Any], context: Any, 
                         processing_state: ProcessingState,
                         dynamodb_service: Any) -> Dict[str, Any]:
    """Handle PDF document extraction (existing workflow)"""
    
    document_id = event.get('document_id')
    object_key = event.get('object_key')
    
    # Initialize services
    document_processor = DocumentProcessor()
    medical_extractor = MedicalDataExtractor()
    
    # Update processing state for text extraction
    processing_state.update_progress("text_extraction", 30)
    dynamodb_service.save_processing_state(processing_state)
    
    # Extract text from document
    extraction_result = document_processor.extract_text_from_document(document_id, object_key)
    
    # Extract medical data
    processing_state.update_progress("medical_extraction", 80)
    dynamodb_service.save_processing_state(processing_state)
    
    import time
    start_time = time.time()
    
    try:
        medical_data = medical_extractor.extract_medical_data(
            document_id=document_id,
            raw_text=extraction_result['raw_text'],
            structured_data=extraction_result['structured_data']
        )
        duration_ms = (time.time() - start_time) * 1000
        
        # Record successful PDF extraction
        get_metrics().record_pdf_extraction(
            success=True,
            duration_ms=duration_ms,
            document_id=document_id,
            confidence=medical_data.get('extraction_confidence', 0.0),
            payor=medical_data.get('payor_name')
        )
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        get_metrics().record_pdf_extraction(False, duration_ms, document_id)
        get_metrics().record_error('PDFExtractionException', 'PDFExtractor', document_id)
        raise
    
    # Complete processing
    processing_state.update_progress("extraction_complete", 100, medical_data)
    processing_state.status = ProcessingStatus.COMPLETED
    dynamodb_service.save_processing_state(processing_state)
    
    # Log successful extraction
    audit_logger.log_processing_step(
        document_id=document_id,
        step_name="pdf_extraction",
        status="completed"
    )
    
    return {
        'document_id': document_id,
        'extraction_result': create_serializable_response(medical_data),
        'processing_status': 'completed'
    }


def handle_fhir_extraction(event: Dict[str, Any], context: Any,
                          processing_state: ProcessingState,
                          dynamodb_service: Any) -> Dict[str, Any]:
    """Handle FHIR JSON document extraction"""
    
    document_id = event.get('document_id')
    bucket_name = event.get('bucket_name', os.getenv('DOCUMENTS_BUCKET'))
    object_key = event.get('object_key')
    
    # Initialize services
    fhir_extractor = FHIRDataExtractor()
    s3_service = get_s3_service()
    
    # Update processing state for FHIR extraction
    processing_state.update_progress("fhir_extraction", 30)
    dynamodb_service.save_processing_state(processing_state)
    
    try:
        # Read FHIR JSON from S3
        logger.info("Reading FHIR JSON from S3", document_id=document_id, object_key=object_key)
        s3_client = s3_service.s3_client
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        fhir_content = response['Body'].read().decode('utf-8')
        
        # Parse JSON
        fhir_data = json.loads(fhir_content)
        
        # Extract medical data from FHIR bundle
        processing_state.update_progress("fhir_parsing", 60)
        dynamodb_service.save_processing_state(processing_state)
        
        import time
        start_time = time.time()
        
        try:
            extracted_data = fhir_extractor.extract_from_fhir_bundle(fhir_data, document_id)
            duration_ms = (time.time() - start_time) * 1000
            
            # Record successful FHIR extraction
            get_metrics().record_fhir_extraction(
                success=True,
                duration_ms=duration_ms,
                document_id=document_id,
                payor=extracted_data.payor_name,
                cpt_count=len(extracted_data.cpt_codes),
                icd_count=len(extracted_data.icd_codes)
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            get_metrics().record_fhir_extraction(False, duration_ms, document_id)
            get_metrics().record_error('FHIRExtractionException', 'FHIRExtractor', document_id)
            raise
        
        # Convert to dict for serialization
        medical_data = extracted_data.to_dict()
        
        # Complete processing
        processing_state.update_progress("extraction_complete", 100, medical_data)
        processing_state.status = ProcessingStatus.COMPLETED
        dynamodb_service.save_processing_state(processing_state)
        
        # Log successful extraction
        audit_logger.log_processing_step(
            document_id=document_id,
            step_name="fhir_extraction",
            status="completed"
        )
        
        return {
            'document_id': document_id,
            'extraction_result': create_serializable_response(medical_data),
            'processing_status': 'completed'
        }
        
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON content", document_id=document_id, error=str(e))
        processing_state.mark_failed(f"Invalid JSON: {str(e)}")
        dynamodb_service.save_processing_state(processing_state)
        raise DocumentParsingException(f"Invalid JSON content: {str(e)}", document_id)
    
    except FHIRParsingException as e:
        logger.warning("FHIR parsing failed", document_id=document_id, error=str(e))
        processing_state.mark_failed(f"FHIR parsing failed: {str(e)}")
        dynamodb_service.save_processing_state(processing_state)
        raise
    
    except Exception as e:
        logger.warning("FHIR extraction failed", document_id=document_id, error=str(e))
        processing_state.mark_failed(f"FHIR extraction failed: {str(e)}")
        dynamodb_service.save_processing_state(processing_state)
        raise DocumentParsingException(f"FHIR extraction failed: {str(e)}", document_id)


# Health check endpoint
def health_check(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Health check endpoint for the Lambda function"""
    error_handler = ContextAwareErrorHandler(event)
    return error_handler.create_success_response({
        'status': 'healthy',
        'service': 'medical-records-extractor',
        'timestamp': context.aws_request_id if context else 'local'
    })
