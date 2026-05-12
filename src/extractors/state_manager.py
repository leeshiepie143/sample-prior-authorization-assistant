"""
State management for the Medical Records Extractor module.

This module handles persistence of extraction results and processing
state in DynamoDB with proper error handling and retry logic.
"""

import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from common.aws_clients import get_dynamodb_service
from common.models import ProcessingState, ProcessingStatus, ExtractedData
from common.exceptions import AWSServiceError, DataValidationError
from common.decorators import handle_processing_errors, retry_with_backoff, monitor_performance
from common.logging_config import get_logger, get_audit_logger
from common.utils import safe_json_dumps, safe_json_loads

logger = get_logger(__name__)
audit_logger = get_audit_logger()


class ExtractionStateManager:
    """Manages extraction state and results in DynamoDB"""
    
    def __init__(self):
        self.dynamodb_service = get_dynamodb_service()
    
    @handle_processing_errors
    @retry_with_backoff(max_attempts=3)
    @monitor_performance
    def save_extraction_state(self, document_id: str, step_name: str, 
                            status: ProcessingStatus, progress: int,
                            result_data: Optional[Dict[str, Any]] = None,
                            error_details: Optional[str] = None) -> None:
        """Save extraction processing state"""
        
        processing_state = ProcessingState(
            document_id=document_id,
            status=status,
            current_step=step_name,
            progress_percentage=progress,
            error_details=error_details
        )
        
        if result_data:
            processing_state.step_results[step_name] = result_data
        
        try:
            self.dynamodb_service.save_processing_state(processing_state)
            
            logger.info("Extraction state saved",
                       document_id=document_id,
                       step=step_name,
                       status=status.value,
                       progress=progress)
            
            # Log to audit trail
            audit_logger.log_processing_step(
                document_id=document_id,
                step_name=step_name,
                status=status.value
            )
            
        except Exception as e:
            logger.warning("Failed to save extraction state",
                        document_id=document_id,
                        step=step_name,
                        error=str(e))
            raise AWSServiceError(f"Failed to save extraction state: {str(e)}")
    
    @handle_processing_errors
    @monitor_performance
    def get_extraction_state(self, document_id: str, step_name: str) -> Optional[Dict[str, Any]]:
        """Get extraction processing state"""
        
        try:
            state_data = self.dynamodb_service.get_processing_state(document_id, step_name)
            
            if state_data:
                logger.info("Extraction state retrieved",
                           document_id=document_id,
                           step=step_name)
            
            return state_data
            
        except Exception as e:
            logger.warning("Failed to get extraction state",
                        document_id=document_id,
                        step=step_name,
                        error=str(e))
            raise AWSServiceError(f"Failed to get extraction state: {str(e)}")
    
    @handle_processing_errors
    @monitor_performance
    def get_all_extraction_states(self, document_id: str) -> List[Dict[str, Any]]:
        """Get all processing states for a document"""
        
        try:
            states = self.dynamodb_service.query_processing_states(document_id)
            
            logger.info("All extraction states retrieved",
                       document_id=document_id,
                       states_count=len(states))
            
            return states
            
        except Exception as e:
            logger.warning("Failed to get all extraction states",
                        document_id=document_id,
                        error=str(e))
            raise AWSServiceError(f"Failed to get all extraction states: {str(e)}")
    
    @handle_processing_errors
    @retry_with_backoff(max_attempts=3)
    def save_extraction_result(self, extracted_data: ExtractedData) -> None:
        """Save final extraction result"""
        
        try:
            # Save as a special step in processing table
            result_data = {
                'extraction_result': extracted_data.to_dict(),
                'saved_at': datetime.utcnow().isoformat()
            }
            
            processing_state = ProcessingState(
                document_id=extracted_data.document_id,
                status=ProcessingStatus.COMPLETED,
                current_step="extraction_result",
                progress_percentage=100
            )
            processing_state.step_results["extraction_result"] = result_data
            
            self.dynamodb_service.save_processing_state(processing_state)
            
            logger.info("Extraction result saved",
                       document_id=extracted_data.document_id,
                       confidence=extracted_data.extraction_confidence,
                       cpt_codes=len(extracted_data.cpt_codes),
                       icd_codes=len(extracted_data.icd_codes))
            
            # Log to audit trail
            audit_logger.log_processing_step(
                document_id=extracted_data.document_id,
                step_name="extraction_result",
                status="completed"
            )
            
        except Exception as e:
            logger.warning("Failed to save extraction result",
                        document_id=extracted_data.document_id,
                        error=str(e))
            raise AWSServiceError(f"Failed to save extraction result: {str(e)}")
    
    @handle_processing_errors
    def get_extraction_result(self, document_id: str) -> Optional[ExtractedData]:
        """Get final extraction result"""
        
        try:
            state_data = self.dynamodb_service.get_processing_state(
                document_id, "extraction_result"
            )
            
            if not state_data or 'step_results' not in state_data:
                return None
            
            result_data = state_data['step_results'].get('extraction_result', {})
            if not result_data:
                return None
            
            # Convert back to ExtractedData object
            extraction_dict = result_data.get('extraction_result', {})
            if extraction_dict:
                extracted_data = ExtractedData.from_dict(extraction_dict)
                
                logger.info("Extraction result retrieved",
                           document_id=document_id)
                
                return extracted_data
            
            return None
            
        except Exception as e:
            logger.warning("Failed to get extraction result",
                        document_id=document_id,
                        error=str(e))
            raise AWSServiceError(f"Failed to get extraction result: {str(e)}")
    
    @handle_processing_errors
    def mark_extraction_failed(self, document_id: str, step_name: str, 
                             error_message: str) -> None:
        """Mark extraction as failed with error details"""
        
        try:
            processing_state = ProcessingState(
                document_id=document_id,
                status=ProcessingStatus.FAILED,
                current_step=step_name,
                progress_percentage=0,
                error_details=error_message
            )
            
            self.dynamodb_service.save_processing_state(processing_state)
            
            logger.error("Extraction marked as failed",
                        document_id=document_id,
                        step=step_name,
                        error=error_message)
            
            # Log to audit trail
            audit_logger.log_error(
                error_type="extraction_failure",
                error_message=error_message,
                document_id=document_id,
                step_name=step_name
            )
            
        except Exception as e:
            logger.warning("Failed to mark extraction as failed",
                        document_id=document_id,
                        error=str(e))
            raise AWSServiceError(f"Failed to mark extraction as failed: {str(e)}")
    
    @handle_processing_errors
    def get_processing_summary(self, document_id: str) -> Dict[str, Any]:
        """Get processing summary for a document"""
        
        try:
            states = self.get_all_extraction_states(document_id)
            
            if not states:
                return {
                    'document_id': document_id,
                    'status': 'not_found',
                    'progress': 0,
                    'steps': []
                }
            
            # Sort states by timestamp
            sorted_states = sorted(states, key=lambda x: x.get('updated_at', ''))
            latest_state = sorted_states[-1] if sorted_states else {}
            
            # Calculate overall progress
            step_progress = {}
            for state in sorted_states:
                step_name = state.get('step_name', '')
                progress = state.get('progress_percentage', 0)
                step_progress[step_name] = progress
            
            overall_progress = max(step_progress.values()) if step_progress else 0
            
            # Check for errors
            has_errors = any(state.get('status') == 'failed' for state in sorted_states)
            
            summary = {
                'document_id': document_id,
                'status': latest_state.get('status', 'unknown'),
                'current_step': latest_state.get('step_name', ''),
                'progress': overall_progress,
                'has_errors': has_errors,
                'created_at': sorted_states[0].get('created_at') if sorted_states else None,
                'updated_at': latest_state.get('updated_at'),
                'steps': [
                    {
                        'step_name': state.get('step_name'),
                        'status': state.get('status'),
                        'progress': state.get('progress_percentage'),
                        'timestamp': state.get('updated_at'),
                        'has_error': bool(state.get('error_details'))
                    }
                    for state in sorted_states
                ]
            }
            
            logger.info("Processing summary generated",
                       document_id=document_id,
                       status=summary['status'],
                       progress=summary['progress'])
            
            return summary
            
        except Exception as e:
            logger.warning("Failed to get processing summary",
                        document_id=document_id,
                        error=str(e))
            raise AWSServiceError(f"Failed to get processing summary: {str(e)}")
    
    @handle_processing_errors
    def cleanup_old_states(self, document_id: str, keep_latest: int = 10) -> None:
        """Clean up old processing states, keeping only the latest N entries"""
        
        try:
            states = self.get_all_extraction_states(document_id)
            
            if len(states) <= keep_latest:
                return  # Nothing to clean up
            
            # Sort by timestamp and keep only the latest entries
            sorted_states = sorted(states, key=lambda x: x.get('updated_at', ''), reverse=True)
            states_to_delete = sorted_states[keep_latest:]
            
            # Delete old states
            for state in states_to_delete:
                try:
                    # Note: This would require implementing delete functionality in DynamoDBService
                    # For now, we'll just log what would be deleted
                    logger.info("Would delete old state",
                               document_id=document_id,
                               step=state.get('step_name'),
                               timestamp=state.get('updated_at'))
                except Exception as delete_error:
                    logger.warning("Failed to delete old state",
                                 document_id=document_id,
                                 step=state.get('step_name'),
                                 error=str(delete_error))
            
            logger.info("Old states cleanup completed",
                       document_id=document_id,
                       deleted_count=len(states_to_delete))
            
        except Exception as e:
            logger.error("Failed to cleanup old states",
                        document_id=document_id,
                        error=str(e))
            # Don't raise exception for cleanup failures


class ExtractionMetricsCollector:
    """Collects and stores extraction metrics for monitoring"""
    
    def __init__(self):
        self.state_manager = ExtractionStateManager()
    
    @handle_processing_errors
    def record_extraction_metrics(self, document_id: str, 
                                 extraction_time: float,
                                 confidence_score: float,
                                 codes_extracted: int,
                                 success: bool) -> None:
        """Record extraction performance metrics"""
        
        metrics = {
            'document_id': document_id,
            'extraction_time_seconds': extraction_time,
            'confidence_score': confidence_score,
            'codes_extracted': codes_extracted,
            'success': success,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        try:
            # Save metrics as a processing step
            self.state_manager.save_extraction_state(
                document_id=document_id,
                step_name="extraction_metrics",
                status=ProcessingStatus.COMPLETED,
                progress=100,
                result_data=metrics
            )
            
            logger.info("Extraction metrics recorded",
                       document_id=document_id,
                       extraction_time=extraction_time,
                       confidence=confidence_score,
                       success=success)
            
        except Exception as e:
            logger.warning("Failed to record extraction metrics",
                          document_id=document_id,
                          error=str(e))
            # Don't fail the main process for metrics collection failures

