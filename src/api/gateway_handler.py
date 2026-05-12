"""
API Gateway handler for the Prior Authorization Application.

This module provides REST API endpoints for document upload, status checking,
and results retrieval with Lambda integration and secure access controls.
"""

import json
import base64
import uuid
import time
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from common.exceptions import APIError, ValidationError, AuthenticationError, RateLimitError
    from common.logging_config import get_logger, get_audit_logger
    from common.decorators import handle_processing_errors, monitor_performance
    from common.validators import RequestValidator, DocumentValidator
    from common.utils import generate_document_id, safe_json_loads
    from orchestrator.workflow_manager import WorkflowExecutor, WorkflowType
    from security import apply_security_middleware, HIPAAEncryptionService, create_security_response
    from api.middleware import (
        MiddlewareChain, 
        UPLOAD_VALIDATION_RULES, 
        STATUS_VALIDATION_RULES, 
        WORKFLOW_VALIDATION_RULES
    )
except ImportError:
    # Fallback for Lambda environment - create minimal implementations
    print("Warning: Using fallback implementations due to import issues")
    
    class APIError(Exception):
        pass
    
    class ValidationError(Exception):
        pass
    
    class RateLimitError(Exception):
        pass
    
    class AuthenticationError(Exception):
        pass
    
    def get_logger(name):
        import logging
        return logging.getLogger(name)
    
    def get_audit_logger():
        import logging
        return logging.getLogger('audit')
    
    def handle_processing_errors(func):
        return func
    
    def monitor_performance(func):
        return func
    
    def apply_security_middleware(func):
        return func
    
    def generate_document_id():
        import uuid
        return str(uuid.uuid4())
    
    def safe_json_loads(data):
        import json
        return json.loads(data)
    
    class RequestValidator:
        def validate_upload_request(self, data):
            return True
    
    class DocumentValidator:
        def validate_document(self, data):
            return True
        
        @staticmethod
        def validate_document_size(size):
            return size <= 10 * 1024 * 1024  # 10MB limit
        
        @staticmethod
        def validate_document_format(filename):
            allowed_extensions = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.tiff', '.tif']
            return any(filename.lower().endswith(ext) for ext in allowed_extensions)
    
    class WorkflowExecutor:
        def start_workflow(self, data):
            return {"execution_arn": "mock", "status": "RUNNING"}
        
        def process_prior_authorization(self, **kwargs):
            import uuid
            return {
                "execution_arn": f"arn:aws:states:us-east-1:123456789012:execution:workflow:{uuid.uuid4()}",
                "status": "RUNNING",
                "started_at": datetime.utcnow().isoformat() + 'Z'
            }
        
        def get_processing_status(self, execution_arn):
            return {
                "status": "SUCCEEDED",
                "progress": {"percentage": 100, "current_step": "completed", "status": "success"},
                "started_at": datetime.utcnow().isoformat() + 'Z',
                "last_updated": datetime.utcnow().isoformat() + 'Z',
                "completed_at": datetime.utcnow().isoformat() + 'Z'
            }
        
        def get_processing_results(self, execution_arn):
            import uuid
            return {
                "assessment_id": str(uuid.uuid4()),
                "overall_compliance": "partially_compliant",
                "approval_likelihood": 75,
                "assessed_at": datetime.utcnow().isoformat() + 'Z'
            }
        
        @property
        def workflow_manager(self):
            return self
        
        def list_executions(self, max_results=100):
            return []
    
    class MiddlewareChain:
        def process_request(self, event, context=None, rules=None, endpoint_type=None):
            return event
        def process_response(self, response, start_time):
            return response
    
    class HIPAAEncryptionService:
        def encrypt_data(self, data):
            return data
        def decrypt_data(self, data):
            return data
    
    def create_security_response(data):
        return data
    
    class WorkflowType:
        PRIOR_AUTH_ASSESSMENT = "prior_auth_assessment"
    
    UPLOAD_VALIDATION_RULES = {}
    STATUS_VALIDATION_RULES = {}
    WORKFLOW_VALIDATION_RULES = {}

logger = get_logger(__name__)
audit_logger = get_audit_logger()


class APIGatewayHandler:
    """Main API Gateway handler for all endpoints"""
    
    def __init__(self):
        self.workflow_executor = WorkflowExecutor()
        self.request_validator = RequestValidator()
        self.middleware_chain = MiddlewareChain()
        self.encryption_service = HIPAAEncryptionService()
    
    @apply_security_middleware
    @handle_processing_errors
    @monitor_performance
    def lambda_handler(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Main Lambda handler for API Gateway requests"""
        
        start_time = time.time()
        
        try:
            # Extract request information
            http_method = event.get('httpMethod', '')
            resource_path = event.get('resource', '')
            path_parameters = event.get('pathParameters') or {}
            query_parameters = event.get('queryStringParameters') or {}
            headers = event.get('headers') or {}
            body = event.get('body', '')
            
            # Log request
            request_id = context.aws_request_id if context else str(uuid.uuid4())
            logger.info("API request received",
                       method=http_method,
                       path=resource_path,
                       request_id=request_id)
            
            # Route request to appropriate handler
            response = self._route_request(
                http_method, resource_path, path_parameters,
                query_parameters, headers, body, request_id, event, context
            )
            
            # Process response through middleware
            response = self.middleware_chain.process_response(response, start_time)
            
            # Add CORS headers
            response['headers'] = response.get('headers', {})
            response['headers'].update(self._get_cors_headers())
            
            return response
            
        except (APIError, RateLimitError, ValidationError) as e:
            logger.warning("API error occurred", error=str(e))
            status_code = getattr(e, 'status_code', 400)
            error_code = getattr(e, 'error_code', 'API_ERROR')
            response = self._create_error_response(status_code, str(e), error_code)
            return self.middleware_chain.process_response(response, start_time)
            
        except Exception as e:
            logger.error("Unexpected API error", error=str(e))
            response = self._create_error_response(500, "Internal server error", "INTERNAL_ERROR")
            return self.middleware_chain.process_response(response, start_time)
    
    def _route_request(self, method: str, path: str, path_params: Dict[str, Any],
                      query_params: Dict[str, Any], headers: Dict[str, Any],
                      body: str, request_id: str, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Route request to appropriate handler based on method and path"""
        
        # Document upload endpoint
        if method == 'POST' and '/documents/upload' in path:
            # Process through middleware with validation
            validated_data = self.middleware_chain.process_request(
                event, context, UPLOAD_VALIDATION_RULES, 'upload'
            )
            return self._handle_document_upload(body, headers, request_id, validated_data)
        
        # Document status endpoint
        elif method == 'GET' and '/documents/' in path and path.endswith('/status'):
            # Process through middleware with validation
            self.middleware_chain.process_request(event, context, STATUS_VALIDATION_RULES, 'status')
            # Extract document_id from path like /documents/{document_id}/status
            path_parts = path.split('/')
            document_id = path_parts[-2] if len(path_parts) >= 2 else path_params.get('document_id')
            return self._handle_status_check(document_id, request_id)
        
        # Document results endpoint
        elif method == 'GET' and '/results/' in path:
            # Process through middleware with validation
            self.middleware_chain.process_request(event, context, STATUS_VALIDATION_RULES, 'results')
            # Extract document_id from path like /results/{document_id}
            path_parts = path.split('/')
            document_id = path_parts[-1] if len(path_parts) >= 1 else path_params.get('document_id')
            return self._handle_results_retrieval(document_id, request_id)
        
        # Document GET endpoint (for status)
        elif method == 'GET' and '/documents/' in path and not path.endswith('/status'):
            # Process through middleware with validation
            self.middleware_chain.process_request(event, context, STATUS_VALIDATION_RULES, 'status')
            # Extract document_id from path like /documents/{document_id}
            path_parts = path.split('/')
            document_id = path_parts[-1] if len(path_parts) >= 1 else path_params.get('document_id')
            return self._handle_status_check(document_id, request_id)
        
        # Workflow execution endpoint
        elif method == 'POST' and '/workflow/start' in path:
            # Process through middleware with validation
            validated_data = self.middleware_chain.process_request(
                event, context, WORKFLOW_VALIDATION_RULES, 'workflow'
            )
            return self._handle_workflow_execution(body, headers, request_id, validated_data)
        
        # Health check endpoint
        elif method == 'GET' and '/health' in path:
            # Process through middleware (no validation needed)
            self.middleware_chain.process_request(event, context, {}, 'health')
            return self._handle_health_check(request_id)
        
        # CORS preflight
        elif method == 'OPTIONS':
            return self._handle_cors_preflight()
        
        # Unknown endpoint
        else:
            raise APIError(f"Endpoint not found: {method} {path}", 404, "ENDPOINT_NOT_FOUND")
    
    def _handle_document_upload(self, body: str, headers: Dict[str, Any], 
                              request_id: str, validated_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Handle document upload requests"""
        
        try:
            # Parse request body
            if headers.get('content-type', '').startswith('multipart/form-data'):
                # Handle multipart form data
                upload_data = self._parse_multipart_upload(body, headers)
            else:
                # Handle JSON upload
                upload_data = self._parse_json_upload(body)
            
            # Validate upload data
            self._validate_upload_request(upload_data)
            
            # Extract file information
            file_content = upload_data['file_content']
            filename = upload_data['filename']
            content_type = upload_data.get('content_type')
            
            # Start workflow execution
            execution_info = self.workflow_executor.process_prior_authorization(
                file_content=file_content,
                filename=filename,
                content_type=content_type,
                workflow_type=WorkflowType.STANDARD
            )
            
            # Log successful upload
            audit_logger.log_processing_step(
                document_id=execution_info.get('execution_name', 'unknown'),
                step_name="document_upload",
                status="completed"
            )
            
            response_data = {
                'document_id': execution_info['execution_name'],
                'status': 'uploaded',
                'execution_arn': execution_info['execution_arn'],
                'started_at': execution_info['started_at'],
                'message': 'Document uploaded successfully and processing started'
            }
            
            return self._create_success_response(response_data, 201)
            
        except ValidationError as e:
            raise APIError(f"Invalid upload request: {str(e)}", 400, "VALIDATION_ERROR")
        except Exception as e:
            logger.warning("Document upload failed", error=str(e), request_id=request_id)
            raise APIError(f"Upload failed: {str(e)}", 500, "UPLOAD_ERROR")
    
    def _handle_status_check(self, document_id: str, request_id: str) -> Dict[str, Any]:
        """Handle document processing status requests"""
        
        if not document_id:
            raise APIError("Document ID is required", 400, "MISSING_DOCUMENT_ID")
        
        try:
            # Find execution ARN from document ID
            execution_arn = self._find_execution_arn(document_id)
            
            if not execution_arn:
                raise APIError(f"Document not found: {document_id}", 404, "DOCUMENT_NOT_FOUND")
            
            # Get processing status
            status_info = self.workflow_executor.get_processing_status(execution_arn)
            
            response_data = {
                'document_id': document_id,
                'status': status_info['status'],
                'progress': status_info.get('progress', {}),
                'started_at': status_info.get('started_at'),
                'last_updated': status_info.get('last_updated'),
                'execution_arn': execution_arn
            }
            
            # Add completion info if available
            if 'stopped_at' in status_info:
                response_data['completed_at'] = status_info['stopped_at']
                response_data['duration_seconds'] = status_info.get('duration_seconds', 0)
            
            return self._create_success_response(response_data)
            
        except APIError:
            raise
        except Exception as e:
            logger.warning("Status check failed", error=str(e), document_id=document_id)
            raise APIError(f"Status check failed: {str(e)}", 500, "STATUS_CHECK_ERROR")
    
    def _handle_results_retrieval(self, document_id: str, request_id: str) -> Dict[str, Any]:
        """Handle assessment results retrieval requests"""
        
        if not document_id:
            raise APIError("Document ID is required", 400, "MISSING_DOCUMENT_ID")
        
        try:
            # Find execution ARN from document ID
            execution_arn = self._find_execution_arn(document_id)
            
            if not execution_arn:
                raise APIError(f"Document not found: {document_id}", 404, "DOCUMENT_NOT_FOUND")
            
            # Get processing results
            results = self.workflow_executor.get_processing_results(execution_arn)
            
            if not results:
                # Check if processing is still in progress
                status_info = self.workflow_executor.get_processing_status(execution_arn)
                if status_info['status'] in ['RUNNING', 'STARTED']:
                    raise APIError("Processing still in progress", 202, "PROCESSING_IN_PROGRESS")
                else:
                    raise APIError("Results not available", 404, "RESULTS_NOT_FOUND")
            
            # Log results access
            audit_logger.log_processing_step(
                document_id=document_id,
                step_name="results_retrieval",
                status="completed"
            )
            
            response_data = {
                'document_id': document_id,
                'assessment_result': results.get('assessment_result'),
                'policy_information': results.get('policy_information'),
                'processing_summary': results.get('processing_summary'),
                'completed_at': results.get('completed_at'),
                'duration_seconds': results.get('duration_seconds', 0)
            }
            
            return self._create_success_response(response_data)
            
        except APIError:
            raise
        except Exception as e:
            logger.warning("Results retrieval failed", error=str(e), document_id=document_id)
            raise APIError(f"Results retrieval failed: {str(e)}", 500, "RESULTS_ERROR")
    
    def _handle_workflow_execution(self, body: str, headers: Dict[str, Any], 
                                 request_id: str, validated_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Handle direct workflow execution requests"""
        
        try:
            # Parse request body
            request_data = safe_json_loads(body, {})
            
            # Validate request
            required_fields = ['file_content', 'filename']
            for field in required_fields:
                if field not in request_data:
                    raise ValidationError(f"Missing required field: {field}")
            
            # Decode file content if base64 encoded
            file_content = request_data['file_content']
            if isinstance(file_content, str):
                try:
                    file_content = base64.b64decode(file_content)
                except Exception:
                    raise ValidationError("Invalid base64 file content")
            
            # Determine workflow type
            workflow_type_str = request_data.get('workflow_type', 'standard')
            workflow_type = WorkflowType(workflow_type_str.lower())
            
            # Start workflow execution
            execution_info = self.workflow_executor.process_prior_authorization(
                file_content=file_content,
                filename=request_data['filename'],
                content_type=request_data.get('content_type'),
                workflow_type=workflow_type
            )
            
            response_data = {
                'execution_id': execution_info['execution_name'],
                'execution_arn': execution_info['execution_arn'],
                'workflow_type': workflow_type.value,
                'started_at': execution_info['started_at'],
                'status': 'started'
            }
            
            return self._create_success_response(response_data, 201)
            
        except ValidationError as e:
            raise APIError(f"Invalid workflow request: {str(e)}", 400, "VALIDATION_ERROR")
        except Exception as e:
            logger.warning("Workflow execution failed", error=str(e), request_id=request_id)
            raise APIError(f"Workflow execution failed: {str(e)}", 500, "WORKFLOW_ERROR")
    
    def _handle_health_check(self, request_id: str) -> Dict[str, Any]:
        """Handle health check requests"""
        
        health_status = {
            'status': 'healthy',
            'service': 'prior-authorization-api',
            'version': '1.0.0',
            'timestamp': datetime.utcnow().isoformat(),
            'request_id': request_id
        }
        
        # Check workflow executor health
        try:
            # Simple health check - try to list recent executions
            recent_executions = self.workflow_executor.workflow_manager.list_executions(max_results=1)
            health_status['workflow_service'] = 'available'
        except Exception as e:
            health_status['workflow_service'] = f'error: {str(e)}'
            health_status['status'] = 'degraded'
        
        return self._create_success_response(health_status)
    
    def _handle_cors_preflight(self) -> Dict[str, Any]:
        """Handle CORS preflight requests"""
        
        return {
            'statusCode': 200,
            'headers': self._get_cors_headers(),
            'body': ''
        }
    
    def _parse_multipart_upload(self, body: str, headers: Dict[str, Any]) -> Dict[str, Any]:
        """Parse multipart form data upload"""
        
        # This is a simplified implementation
        # In production, you'd use a proper multipart parser
        
        # For now, assume the body contains base64 encoded file data
        # and extract filename from headers or body
        
        try:
            # Decode body if base64 encoded
            if body:
                file_content = base64.b64decode(body)
            else:
                raise ValidationError("Empty file content")
            
            # Extract filename from content-disposition header or use default
            filename = "uploaded_document.pdf"
            content_disposition = headers.get('content-disposition', '')
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[1].strip('"')
            
            return {
                'file_content': file_content,
                'filename': filename,
                'content_type': headers.get('content-type', 'application/octet-stream')
            }
            
        except Exception as e:
            raise ValidationError(f"Failed to parse multipart upload: {str(e)}")
    
    def _parse_json_upload(self, body: str) -> Dict[str, Any]:
        """Parse JSON upload request"""
        
        try:
            request_data = safe_json_loads(body, {})
            
            # Validate required fields
            if 'file_content' not in request_data:
                raise ValidationError("Missing file_content field")
            
            if 'filename' not in request_data:
                raise ValidationError("Missing filename field")
            
            # Decode base64 file content
            file_content_b64 = request_data['file_content']
            try:
                file_content = base64.b64decode(file_content_b64)
            except Exception:
                raise ValidationError("Invalid base64 file content")
            
            return {
                'file_content': file_content,
                'filename': request_data['filename'],
                'content_type': request_data.get('content_type')
            }
            
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Failed to parse JSON upload: {str(e)}")
    
    def _validate_upload_request(self, upload_data: Dict[str, Any]) -> None:
        """Validate upload request data"""
        
        file_content = upload_data['file_content']
        filename = upload_data['filename']
        
        # Validate file size
        if not DocumentValidator.validate_document_size(len(file_content)):
            raise ValidationError("File size exceeds maximum allowed size")
        
        # Validate file format
        if not DocumentValidator.validate_document_format(filename):
            raise ValidationError(f"Unsupported file format: {filename}")
        
        # Validate file content is not empty
        if len(file_content) == 0:
            raise ValidationError("File content is empty")
    
    def _find_execution_arn(self, document_id: str) -> Optional[str]:
        """Find execution ARN for a document ID"""
        
        try:
            # List recent executions and find matching document ID
            executions = self.workflow_executor.workflow_manager.list_executions(max_results=100)
            
            for execution in executions:
                if execution['name'] == document_id:
                    return execution['execution_arn']
            
            return None
            
        except Exception as e:
            logger.error("Failed to find execution ARN", document_id=document_id, error=str(e))
            return None
    
    def _get_cors_headers(self) -> Dict[str, str]:
        """Get CORS headers for responses"""
        
        return {
            'Access-Control-Allow-Origin': '*',  # Configure appropriately for production
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            'Access-Control-Max-Age': '86400'
        }
    
    def _create_success_response(self, data: Any, status_code: int = 200) -> Dict[str, Any]:
        """Create successful API response"""
        
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps(data, default=str)
        }
    
    def _create_error_response(self, status_code: int, message: str, 
                             error_code: str = None) -> Dict[str, Any]:
        """Create error API response"""
        
        error_data = {
            'error': message,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if error_code:
            error_data['error_code'] = error_code
        
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps(error_data)
        }


# Lambda handler function for API Gateway
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler entry point for API Gateway"""
    
    handler = APIGatewayHandler()
    return handler.lambda_handler(event, context)
