"""
CloudWatch metrics for FHIR JSON intake monitoring.

Tracks format detection, extraction success/failure rates, processing times,
and document type distributions.
"""

import boto3
import time
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from .logging_config import get_logger

logger = get_logger(__name__)


class CloudWatchMetrics:
    """CloudWatch metrics publisher for FHIR processing"""
    
    def __init__(self, namespace: str = "PriorAuth/FHIRIntake"):
        self.namespace = namespace
        self.cloudwatch = boto3.client('cloudwatch')
        
    def put_metric(self, metric_name: str, value: float, unit: str = 'Count', 
                   dimensions: Optional[Dict[str, str]] = None):
        """Put a single metric to CloudWatch"""
        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit,
                'Timestamp': datetime.utcnow()
            }
            
            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': v} for k, v in dimensions.items()
                ]
            
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data]
            )
            
            logger.debug("CloudWatch metric published", 
                        metric_name=metric_name, 
                        value=value, 
                        dimensions=dimensions)
                        
        except Exception as e:
            logger.error("Failed to publish CloudWatch metric", 
                        metric_name=metric_name, 
                        error=str(e))
    
    def increment_counter(self, metric_name: str, dimensions: Optional[Dict[str, str]] = None):
        """Increment a counter metric"""
        self.put_metric(metric_name, 1.0, 'Count', dimensions)
    
    def record_duration(self, metric_name: str, duration_ms: float, 
                       dimensions: Optional[Dict[str, str]] = None):
        """Record a duration metric in milliseconds"""
        self.put_metric(metric_name, duration_ms, 'Milliseconds', dimensions)
    
    def record_format_detection(self, detected_format: str, success: bool, 
                               duration_ms: float, document_id: str):
        """Record format detection metrics"""
        dimensions = {
            'Format': detected_format,
            'Success': str(success)
        }
        
        # Count of format detections
        self.increment_counter('FormatDetection.Count', dimensions)
        
        # Detection duration
        self.record_duration('FormatDetection.Duration', duration_ms, dimensions)
        
        # Success rate (will be aggregated in CloudWatch)
        success_value = 1.0 if success else 0.0
        self.put_metric('FormatDetection.SuccessRate', success_value, 'None', dimensions)
        
        logger.info("Format detection metrics recorded", 
                   document_id=document_id,
                   format=detected_format, 
                   success=success, 
                   duration_ms=duration_ms)
    
    def record_fhir_extraction(self, success: bool, duration_ms: float, 
                              document_id: str, payor: Optional[str] = None,
                              cpt_count: int = 0, icd_count: int = 0):
        """Record FHIR extraction metrics"""
        dimensions = {
            'ExtractionType': 'FHIR',
            'Success': str(success)
        }
        
        if payor:
            dimensions['Payor'] = payor
        
        # Count of extractions
        self.increment_counter('Extraction.Count', dimensions)
        
        # Extraction duration
        self.record_duration('Extraction.Duration', duration_ms, dimensions)
        
        # Success rate
        success_value = 1.0 if success else 0.0
        self.put_metric('Extraction.SuccessRate', success_value, 'None', dimensions)
        
        if success:
            # Code extraction counts
            self.put_metric('Extraction.CPTCodes', float(cpt_count), 'Count', dimensions)
            self.put_metric('Extraction.ICDCodes', float(icd_count), 'Count', dimensions)
        
        logger.info("FHIR extraction metrics recorded", 
                   document_id=document_id,
                   success=success, 
                   duration_ms=duration_ms,
                   payor=payor,
                   cpt_count=cpt_count,
                   icd_count=icd_count)
    
    def record_pdf_extraction(self, success: bool, duration_ms: float, 
                             document_id: str, confidence: float = 0.0,
                             payor: Optional[str] = None):
        """Record PDF extraction metrics"""
        dimensions = {
            'ExtractionType': 'PDF',
            'Success': str(success)
        }
        
        if payor:
            dimensions['Payor'] = payor
        
        # Count of extractions
        self.increment_counter('Extraction.Count', dimensions)
        
        # Extraction duration
        self.record_duration('Extraction.Duration', duration_ms, dimensions)
        
        # Success rate
        success_value = 1.0 if success else 0.0
        self.put_metric('Extraction.SuccessRate', success_value, 'None', dimensions)
        
        if success:
            # Extraction confidence
            self.put_metric('Extraction.Confidence', confidence, 'None', dimensions)
        
        logger.info("PDF extraction metrics recorded", 
                   document_id=document_id,
                   success=success, 
                   duration_ms=duration_ms,
                   confidence=confidence,
                   payor=payor)
    
    def record_document_reference_decoding(self, success: bool, content_type: str,
                                          document_id: str):
        """Record DocumentReference decoding metrics"""
        dimensions = {
            'ContentType': content_type,
            'Success': str(success)
        }
        
        self.increment_counter('DocumentReference.Decoding.Count', dimensions)
        
        success_value = 1.0 if success else 0.0
        self.put_metric('DocumentReference.Decoding.SuccessRate', success_value, 'None', dimensions)
        
        logger.info("DocumentReference decoding metrics recorded",
                   document_id=document_id,
                   content_type=content_type,
                   success=success)
    
    def record_api_upload(self, content_type: str, file_size_mb: float, 
                         success: bool, duration_ms: float):
        """Record API upload metrics"""
        dimensions = {
            'ContentType': content_type,
            'Success': str(success)
        }
        
        # Upload count
        self.increment_counter('API.Upload.Count', dimensions)
        
        # Upload duration
        self.record_duration('API.Upload.Duration', duration_ms, dimensions)
        
        # File size
        self.put_metric('API.Upload.FileSize', file_size_mb, 'None', dimensions)
        
        # Success rate
        success_value = 1.0 if success else 0.0
        self.put_metric('API.Upload.SuccessRate', success_value, 'None', dimensions)
        
        logger.info("API upload metrics recorded", 
                   content_type=content_type,
                   file_size_mb=file_size_mb,
                   success=success, 
                   duration_ms=duration_ms)
    
    def record_error(self, error_type: str, component: str, document_id: Optional[str] = None):
        """Record error metrics"""
        dimensions = {
            'ErrorType': error_type,
            'Component': component
        }
        
        self.increment_counter('Errors.Count', dimensions)
        
        logger.error("Error metric recorded", 
                    error_type=error_type,
                    component=component,
                    document_id=document_id)
    
    @contextmanager
    def time_operation(self, operation_name: str, dimensions: Optional[Dict[str, str]] = None):
        """Context manager to time operations"""
        start_time = time.time()
        success = False
        
        try:
            yield
            success = True
        except Exception as e:
            logger.error(f"Operation {operation_name} failed", error=str(e))
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            
            # Record timing
            self.record_duration(f'{operation_name}.Duration', duration_ms, dimensions)
            
            # Record success/failure
            success_value = 1.0 if success else 0.0
            self.put_metric(f'{operation_name}.SuccessRate', success_value, 'None', dimensions)


# Global metrics instance
_metrics_instance = None

def get_metrics() -> CloudWatchMetrics:
    """Get global CloudWatch metrics instance"""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = CloudWatchMetrics()
    return _metrics_instance


# Convenience functions
def record_format_detection_success(detected_format: str, duration_ms: float, document_id: str):
    """Record successful format detection"""
    get_metrics().record_format_detection(detected_format, True, duration_ms, document_id)

def record_format_detection_failure(duration_ms: float, document_id: str):
    """Record failed format detection"""
    get_metrics().record_format_detection('UNKNOWN', False, duration_ms, document_id)

def record_fhir_extraction_success(duration_ms: float, document_id: str, 
                                  payor: str, cpt_count: int, icd_count: int):
    """Record successful FHIR extraction"""
    get_metrics().record_fhir_extraction(True, duration_ms, document_id, payor, cpt_count, icd_count)

def record_fhir_extraction_failure(duration_ms: float, document_id: str):
    """Record failed FHIR extraction"""
    get_metrics().record_fhir_extraction(False, duration_ms, document_id)

def record_api_upload_success(content_type: str, file_size_mb: float, duration_ms: float):
    """Record successful API upload"""
    get_metrics().record_api_upload(content_type, file_size_mb, True, duration_ms)

def record_api_upload_failure(content_type: str, file_size_mb: float, duration_ms: float):
    """Record failed API upload"""
    get_metrics().record_api_upload(content_type, file_size_mb, False, duration_ms)
