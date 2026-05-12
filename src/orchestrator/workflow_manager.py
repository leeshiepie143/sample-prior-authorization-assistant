"""
Workflow management for Step Functions orchestration.

This module handles workflow execution, monitoring, and management
for the prior authorization processing system.
"""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from common.aws_clients import get_aws_client_manager
from common.exceptions import WorkflowError, AWSServiceError
from common.decorators import handle_processing_errors, monitor_performance, retry_with_backoff
from common.logging_config import get_logger, get_audit_logger
from common.utils import generate_document_id, safe_json_loads
from .workflow_definition import WorkflowDefinition, WorkflowTemplates

logger = get_logger(__name__)
audit_logger = get_audit_logger()


class WorkflowType(Enum):
    """Types of workflows available"""
    STANDARD = "standard"
    EXPRESS = "express"
    PARALLEL = "parallel"
    DEVELOPMENT = "development"


class ExecutionStatus(Enum):
    """Step Functions execution statuses"""
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ABORTED = "ABORTED"


class WorkflowManager:
    """Manages Step Functions workflow execution and monitoring"""
    
    def __init__(self):
        self.client_manager = get_aws_client_manager()
        self.stepfunctions_client = self.client_manager.get_stepfunctions_client()
        
        # Configuration from environment
        self.state_machine_arn = os.getenv('STATE_MACHINE_ARN')
        self.express_state_machine_arn = os.getenv('EXPRESS_STATE_MACHINE_ARN')
        
        # Lambda ARNs
        self.lambda_arns = {
            'extractor': os.getenv('EXTRACTOR_LAMBDA_ARN', 'prior-auth-medical-extractor'),
            'knowledge': os.getenv('KNOWLEDGE_LAMBDA_ARN', 'prior-auth-policy-knowledge'),
            'selector': os.getenv('SELECTOR_LAMBDA_ARN', 'prior-auth-policy-selector'),
            'reviewer': os.getenv('REVIEWER_LAMBDA_ARN', 'prior-auth-medical-reviewer'),
            'validator': os.getenv('VALIDATOR_LAMBDA_ARN', 'prior-auth-validator')
        }
    
    @handle_processing_errors
    @monitor_performance
    def start_workflow_execution(self, input_data: Dict[str, Any], 
                                workflow_type: WorkflowType = WorkflowType.STANDARD,
                                execution_name: str = None) -> Dict[str, Any]:
        """Start a new workflow execution"""
        
        if not execution_name:
            execution_name = f"prior-auth-{generate_document_id()[:8]}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        
        # Select appropriate state machine
        state_machine_arn = self._get_state_machine_arn(workflow_type)
        
        logger.info("Starting workflow execution",
                   execution_name=execution_name,
                   workflow_type=workflow_type.value,
                   state_machine_arn=state_machine_arn)
        
        try:
            response = self.stepfunctions_client.start_execution(
                stateMachineArn=state_machine_arn,
                name=execution_name,
                input=json.dumps(input_data)
            )
            
            execution_arn = response['executionArn']
            
            # Log workflow start
            audit_logger.log_processing_step(
                document_id=input_data.get('document_id', 'unknown'),
                step_name="workflow_start",
                status="started"
            )
            
            logger.info("Workflow execution started",
                       execution_name=execution_name,
                       execution_arn=execution_arn)
            
            return {
                'execution_arn': execution_arn,
                'execution_name': execution_name,
                'state_machine_arn': state_machine_arn,
                'started_at': response['startDate'].isoformat(),
                'workflow_type': workflow_type.value,
                'status': 'started'
            }
            
        except Exception as e:
            logger.warning("Failed to start workflow execution",
                        execution_name=execution_name,
                        error=str(e))
            raise WorkflowError(f"Failed to start workflow: {str(e)}")
    
    def _get_state_machine_arn(self, workflow_type: WorkflowType) -> str:
        """Get appropriate state machine ARN for workflow type"""
        
        if workflow_type == WorkflowType.EXPRESS and self.express_state_machine_arn:
            return self.express_state_machine_arn
        elif self.state_machine_arn:
            return self.state_machine_arn
        else:
            raise WorkflowError("No state machine ARN configured")
    
    @handle_processing_errors
    def get_execution_status(self, execution_arn: str) -> Dict[str, Any]:
        """Get current status of workflow execution"""
        
        try:
            response = self.stepfunctions_client.describe_execution(
                executionArn=execution_arn
            )
            
            execution_info = {
                'execution_arn': execution_arn,
                'name': response['name'],
                'status': response['status'],
                'started_at': response['startDate'].isoformat(),
                'state_machine_arn': response['stateMachineArn']
            }
            
            # Add completion info if available
            if 'stopDate' in response:
                execution_info['stopped_at'] = response['stopDate'].isoformat()
                execution_info['duration_seconds'] = (
                    response['stopDate'] - response['startDate']
                ).total_seconds()
            
            # Add input and output if available
            if 'input' in response:
                execution_info['input'] = safe_json_loads(response['input'], {})
            
            if 'output' in response:
                execution_info['output'] = safe_json_loads(response['output'], {})
            
            return execution_info
            
        except Exception as e:
            logger.warning("Failed to get execution status",
                        execution_arn=execution_arn,
                        error=str(e))
            raise WorkflowError(f"Failed to get execution status: {str(e)}")
    
    @handle_processing_errors
    def get_execution_history(self, execution_arn: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """Get execution history with step details"""
        
        try:
            response = self.stepfunctions_client.get_execution_history(
                executionArn=execution_arn,
                maxResults=max_results,
                reverseOrder=True  # Most recent first
            )
            
            history_events = []
            
            for event in response.get('events', []):
                event_info = {
                    'timestamp': event['timestamp'].isoformat(),
                    'type': event['type'],
                    'id': event['id']
                }
                
                # Add event-specific details
                if 'stateEnteredEventDetails' in event:
                    event_info['state_name'] = event['stateEnteredEventDetails']['name']
                    event_info['input'] = safe_json_loads(
                        event['stateEnteredEventDetails'].get('input', '{}'), {}
                    )
                
                if 'stateExitedEventDetails' in event:
                    event_info['state_name'] = event['stateExitedEventDetails']['name']
                    event_info['output'] = safe_json_loads(
                        event['stateExitedEventDetails'].get('output', '{}'), {}
                    )
                
                if 'taskFailedEventDetails' in event:
                    event_info['error'] = event['taskFailedEventDetails'].get('error')
                    event_info['cause'] = event['taskFailedEventDetails'].get('cause')
                
                history_events.append(event_info)
            
            return history_events
            
        except Exception as e:
            logger.warning("Failed to get execution history",
                        execution_arn=execution_arn,
                        error=str(e))
            raise WorkflowError(f"Failed to get execution history: {str(e)}")
    
    @handle_processing_errors
    def stop_execution(self, execution_arn: str, error: str = None, 
                      cause: str = None) -> Dict[str, Any]:
        """Stop a running workflow execution"""
        
        try:
            response = self.stepfunctions_client.stop_execution(
                executionArn=execution_arn,
                error=error or "UserRequested",
                cause=cause or "Execution stopped by user request"
            )
            
            logger.info("Workflow execution stopped",
                       execution_arn=execution_arn,
                       stopped_at=response['stopDate'].isoformat())
            
            return {
                'execution_arn': execution_arn,
                'stopped_at': response['stopDate'].isoformat(),
                'status': 'stopped'
            }
            
        except Exception as e:
            logger.warning("Failed to stop execution",
                        execution_arn=execution_arn,
                        error=str(e))
            raise WorkflowError(f"Failed to stop execution: {str(e)}")
    
    @handle_processing_errors
    def list_executions(self, state_machine_arn: str = None, 
                       status_filter: str = None,
                       max_results: int = 100) -> List[Dict[str, Any]]:
        """List workflow executions with optional filtering"""
        
        if not state_machine_arn:
            state_machine_arn = self.state_machine_arn
        
        try:
            params = {
                'stateMachineArn': state_machine_arn,
                'maxResults': max_results
            }
            
            if status_filter:
                params['statusFilter'] = status_filter
            
            response = self.stepfunctions_client.list_executions(**params)
            
            executions = []
            for execution in response.get('executions', []):
                execution_info = {
                    'execution_arn': execution['executionArn'],
                    'name': execution['name'],
                    'status': execution['status'],
                    'started_at': execution['startDate'].isoformat()
                }
                
                if 'stopDate' in execution:
                    execution_info['stopped_at'] = execution['stopDate'].isoformat()
                
                executions.append(execution_info)
            
            return executions
            
        except Exception as e:
            logger.warning("Failed to list executions", error=str(e))
            raise WorkflowError(f"Failed to list executions: {str(e)}")
    
    @handle_processing_errors
    def get_workflow_metrics(self, state_machine_arn: str = None,
                           days_back: int = 7) -> Dict[str, Any]:
        """Get workflow performance metrics"""
        
        if not state_machine_arn:
            state_machine_arn = self.state_machine_arn
        
        try:
            # Get recent executions
            executions = self.list_executions(state_machine_arn, max_results=1000)
            
            # Filter by date range
            cutoff_date = datetime.utcnow().timestamp() - (days_back * 24 * 3600)
            recent_executions = [
                exec for exec in executions
                if datetime.fromisoformat(exec['started_at']).timestamp() > cutoff_date
            ]
            
            # Calculate metrics
            total_executions = len(recent_executions)
            successful_executions = len([e for e in recent_executions if e['status'] == 'SUCCEEDED'])
            failed_executions = len([e for e in recent_executions if e['status'] == 'FAILED'])
            running_executions = len([e for e in recent_executions if e['status'] == 'RUNNING'])
            
            success_rate = (successful_executions / total_executions) if total_executions > 0 else 0.0
            
            # Calculate average duration for completed executions
            completed_executions = [e for e in recent_executions if 'stopped_at' in e]
            avg_duration = 0.0
            
            if completed_executions:
                durations = []
                for execution in completed_executions:
                    start_time = datetime.fromisoformat(execution['started_at'])
                    stop_time = datetime.fromisoformat(execution['stopped_at'])
                    duration = (stop_time - start_time).total_seconds()
                    durations.append(duration)
                
                avg_duration = sum(durations) / len(durations)
            
            metrics = {
                'period_days': days_back,
                'total_executions': total_executions,
                'successful_executions': successful_executions,
                'failed_executions': failed_executions,
                'running_executions': running_executions,
                'success_rate': success_rate,
                'failure_rate': (failed_executions / total_executions) if total_executions > 0 else 0.0,
                'average_duration_seconds': avg_duration,
                'state_machine_arn': state_machine_arn
            }
            
            logger.info("Workflow metrics calculated",
                       total_executions=total_executions,
                       success_rate=success_rate,
                       avg_duration=avg_duration)
            
            return metrics
            
        except Exception as e:
            logger.warning("Failed to get workflow metrics", error=str(e))
            raise WorkflowError(f"Failed to get workflow metrics: {str(e)}")


class WorkflowExecutor:
    """High-level workflow execution interface"""
    
    def __init__(self):
        self.workflow_manager = WorkflowManager()
    
    @handle_processing_errors
    def process_prior_authorization(self, file_content: str, filename: str,
                                  content_type: str = None,
                                  workflow_type: WorkflowType = WorkflowType.STANDARD) -> Dict[str, Any]:
        """Process a prior authorization document through the complete workflow"""
        
        # Prepare input data
        input_data = {
            'file_content': file_content,
            'filename': filename,
            'content_type': content_type,
            'processing_options': {
                'workflow_type': workflow_type.value,
                'enable_validation': True,
                'generate_detailed_report': True
            },
            'metadata': {
                'submitted_at': datetime.utcnow().isoformat(),
                'workflow_version': '1.0'
            }
        }
        
        # Start workflow execution
        execution_info = self.workflow_manager.start_workflow_execution(
            input_data=input_data,
            workflow_type=workflow_type
        )
        
        logger.info("Prior authorization processing started",
                   execution_name=execution_info['execution_name'],
                   filename=filename,
                   workflow_type=workflow_type.value)
        
        return execution_info
    
    @handle_processing_errors
    def get_processing_status(self, execution_arn: str) -> Dict[str, Any]:
        """Get detailed processing status for an execution"""
        
        # Get basic execution status
        execution_status = self.workflow_manager.get_execution_status(execution_arn)
        
        # Get execution history for detailed progress
        history = self.workflow_manager.get_execution_history(execution_arn, max_results=50)
        
        # Calculate progress
        progress_info = self._calculate_progress(history, execution_status['status'])
        
        # Combine information
        detailed_status = {
            **execution_status,
            'progress': progress_info,
            'last_updated': datetime.utcnow().isoformat()
        }
        
        return detailed_status
    
    def _calculate_progress(self, history: List[Dict[str, Any]], status: str) -> Dict[str, Any]:
        """Calculate processing progress from execution history"""
        
        # Define workflow steps and their progress percentages
        step_progress = {
            'InitializeProcessing': 5,
            'ValidateInput': 10,
            'ExtractMedicalData': 30,
            'SearchPolicies': 50,
            'SelectBestPolicy': 70,
            'ReviewMedicalRecords': 90,
            'GenerateFinalResults': 95,
            'ProcessingComplete': 100
        }
        
        current_progress = 0
        current_step = "Initializing"
        
        # Find the latest completed step
        for event in history:
            if event.get('type') == 'StateExited':
                state_name = event.get('state_name', '')
                if state_name in step_progress:
                    current_progress = step_progress[state_name]
                    current_step = state_name
        
        # Handle final statuses
        if status == 'SUCCEEDED':
            current_progress = 100
            current_step = "Completed"
        elif status == 'FAILED':
            current_step = "Failed"
        elif status == 'TIMED_OUT':
            current_step = "Timed Out"
        elif status == 'ABORTED':
            current_step = "Aborted"
        
        return {
            'percentage': current_progress,
            'current_step': current_step,
            'status': status
        }
    
    @handle_processing_errors
    def retry_failed_execution(self, failed_execution_arn: str) -> Dict[str, Any]:
        """Retry a failed execution with the same input"""
        
        try:
            # Get the failed execution details
            execution_info = self.workflow_manager.get_execution_status(failed_execution_arn)
            
            if execution_info['status'] != 'FAILED':
                raise WorkflowError("Can only retry failed executions")
            
            # Get the original input
            original_input = execution_info.get('input', {})
            
            # Start new execution with retry suffix
            original_name = execution_info['name']
            retry_name = f"{original_name}-retry-{datetime.utcnow().strftime('%H%M%S')}"
            
            # Start retry execution
            retry_execution = self.workflow_manager.start_workflow_execution(
                input_data=original_input,
                execution_name=retry_name
            )
            
            logger.info("Workflow execution retried",
                       original_execution=failed_execution_arn,
                       retry_execution=retry_execution['execution_arn'])
            
            return retry_execution
            
        except Exception as e:
            logger.warning("Failed to retry execution",
                        execution_arn=failed_execution_arn,
                        error=str(e))
            raise WorkflowError(f"Failed to retry execution: {str(e)}")
    
    @handle_processing_errors
    def get_processing_results(self, execution_arn: str) -> Optional[Dict[str, Any]]:
        """Get final processing results from completed execution"""
        
        execution_info = self.workflow_manager.get_execution_status(execution_arn)
        
        if execution_info['status'] != 'SUCCEEDED':
            logger.warning("Execution not completed successfully",
                          execution_arn=execution_arn,
                          status=execution_info['status'])
            return None
        
        # Extract results from output
        output = execution_info.get('output', {})
        
        if 'assessment_result' in output:
            return {
                'document_id': output.get('document_id'),
                'assessment_result': output['assessment_result'],
                'policy_information': output.get('policy_information', {}),
                'processing_summary': output.get('processing_summary', {}),
                'completed_at': execution_info.get('stopped_at'),
                'duration_seconds': execution_info.get('duration_seconds', 0)
            }
        
        return output
    
    @handle_processing_errors
    def cleanup_old_executions(self, days_old: int = 30) -> Dict[str, Any]:
        """Clean up old workflow executions (Note: Step Functions auto-deletes after 90 days)"""
        
        logger.info("Checking for old executions to cleanup", days_old=days_old)
        
        # Get old executions
        all_executions = self.workflow_manager.list_executions(max_results=1000)
        
        cutoff_date = datetime.utcnow().timestamp() - (days_old * 24 * 3600)
        old_executions = [
            exec for exec in all_executions
            if datetime.fromisoformat(exec['started_at']).timestamp() < cutoff_date
        ]
        
        # Note: Step Functions automatically deletes execution history after 90 days
        # This is mainly for logging and metrics
        
        cleanup_summary = {
            'total_executions_checked': len(all_executions),
            'old_executions_found': len(old_executions),
            'cleanup_date': datetime.utcnow().isoformat(),
            'note': 'Step Functions automatically deletes executions after 90 days'
        }
        
        logger.info("Execution cleanup completed",
                   old_executions=len(old_executions),
                   total_checked=len(all_executions))
        
        return cleanup_summary

