"""
API Gateway handler for Prior Authorization System.
Handles document uploads and triggers Step Functions workflow.
Version: 1.0.2 - Extract title from selected_policy.policy_title
"""

import json
import uuid
import os
import boto3
import base64
import traceback
import time
from datetime import datetime
from typing import Dict, Any

# Import CloudWatch metrics (with fallback if not available)
try:
    import sys
    sys.path.insert(0, '/opt/python')  # Lambda layer path
    from common.cloudwatch_metrics import get_metrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    print("CloudWatch metrics module not available")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler for API Gateway requests"""
    
    try:
        # Extract request information
        http_method = event.get('httpMethod', '')
        path = event.get('path', '')
        body = event.get('body', '')
        headers = event.get('headers', {})
        
        print(f"Received {http_method} request to {path}")
        print(f"Request body length: {len(body) if body else 0}")
        
        # Handle CORS preflight
        if http_method == 'OPTIONS':
            return create_cors_response(200, '')
        
        # Handle document upload
        if http_method == 'POST' and '/documents/upload' in path:
            return handle_document_upload(body, headers)
        
        # Handle document status
        if http_method == 'GET' and '/documents/' in path and '/status' in path:
            # Path format: /documents/{document_id}/status
            path_parts = path.split('/')
            if len(path_parts) >= 3:
                document_id = path_parts[-2]  # Get document_id (second to last part)
                return handle_document_status(document_id)
        
        # Handle document info (without /status)
        if http_method == 'GET' and '/documents/' in path and '/status' not in path and '/upload' not in path:
            # Path format: /documents/{document_id}
            document_id = path.split('/')[-1]
            return handle_document_status(document_id)
        
        # Handle results
        if http_method == 'GET' and '/results/' in path:
            document_id = path.split('/')[-1]
            return handle_results(document_id)
        
        # Handle workflow start
        if http_method == 'POST' and '/workflow/start' in path:
            return handle_workflow_start(body, headers)
        
        # Default response
        return create_cors_response(404, json.dumps({
            'error': 'Endpoint not found',
            'path': path,
            'method': http_method
        }))
        
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return create_cors_response(500, json.dumps({
            'error': 'Internal server error',
            'message': str(e)
        }))


def handle_document_upload(body: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Handle document upload requests"""
    
    start_time = time.time()
    content_type = None
    file_size_mb = 0
    
    try:
        # Parse request body
        if body:
            request_data = json.loads(body)
        else:
            request_data = {}
        
        # Get file data from frontend (base64 upload)
        file_content = request_data.get('file_content')  # base64 encoded
        filename = request_data.get('filename')
        content_type = request_data.get('content_type', 'application/pdf')
        
        print(f"Received upload request - filename: {filename}, content_type: {content_type}")
        print(f"File content length: {len(file_content) if file_content else 0}")
        print(f"Environment variables - DOCUMENTS_BUCKET: {os.environ.get('DOCUMENTS_BUCKET')}")
        print(f"Environment variables - STATE_MACHINE_ARN: {os.environ.get('STATE_MACHINE_ARN')}")
        
        # Validate content type
        allowed_content_types = ['application/pdf', 'application/json']
        if content_type not in allowed_content_types:
            return create_cors_response(400, json.dumps({
                'error': 'Invalid content type',
                'message': f'Content type must be one of: {", ".join(allowed_content_types)}',
                'received': content_type
            }))
        
        # Generate document ID
        document_id = str(uuid.uuid4())
        
        # If we have file content, upload to S3 and start workflow
        if file_content and filename:
            try:
                # Upload to S3
                s3_client = boto3.client('s3')
                bucket_name = os.environ.get('DOCUMENTS_BUCKET')
                
                if not bucket_name:
                    return create_cors_response(500, json.dumps({
                        'error': 'Documents bucket not configured'
                    }))
                
                # Create S3 object key
                object_key = f"documents/{document_id}/{filename}"
                
                # Decode base64 and upload to S3
                file_bytes = base64.b64decode(file_content)
                file_size_mb = len(file_bytes) / (1024 * 1024)
                
                # Validate file size based on content type
                if content_type == 'application/json':
                    max_size_mb = 10
                    if file_size_mb > max_size_mb:
                        return create_cors_response(400, json.dumps({
                            'error': 'File too large',
                            'message': f'JSON files must be less than {max_size_mb}MB',
                            'file_size_mb': round(file_size_mb, 2)
                        }))
                    
                    # Validate JSON format
                    try:
                        json_content = json.loads(file_bytes.decode('utf-8'))
                        print(f"JSON validation successful - resourceType: {json_content.get('resourceType', 'N/A')}")
                    except json.JSONDecodeError as json_err:
                        return create_cors_response(400, json.dumps({
                            'error': 'Invalid JSON format',
                            'message': 'The uploaded file is not valid JSON',
                            'details': str(json_err)
                        }))
                    except UnicodeDecodeError:
                        return create_cors_response(400, json.dumps({
                            'error': 'Invalid JSON encoding',
                            'message': 'The uploaded file must be UTF-8 encoded JSON'
                        }))
                
                elif content_type == 'application/pdf':
                    max_size_mb = 25
                    if file_size_mb > max_size_mb:
                        return create_cors_response(400, json.dumps({
                            'error': 'File too large',
                            'message': f'PDF files must be less than {max_size_mb}MB',
                            'file_size_mb': round(file_size_mb, 2)
                        }))
                
                print(f"File size validation passed: {round(file_size_mb, 2)}MB")
                
                # Determine file extension based on content type
                file_extension = '.json' if content_type == 'application/json' else '.pdf'
                if not filename.endswith(file_extension):
                    filename = filename + file_extension
                
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=object_key,
                    Body=file_bytes,
                    ContentType=content_type,
                    Metadata={
                        'document_id': document_id,
                        'original_filename': filename,
                        'uploaded_at': datetime.utcnow().isoformat()
                    }
                )
                
                print(f"Document uploaded to S3: s3://{bucket_name}/{object_key}")
                
                # Start Step Functions execution
                stepfunctions = boto3.client('stepfunctions')
                state_machine_arn = os.environ.get('STATE_MACHINE_ARN')
                
                if state_machine_arn:
                    # Prepare input for Step Functions
                    workflow_input = {
                        'document_id': document_id,
                        'bucket_name': bucket_name,
                        'object_key': object_key,
                        'filename': filename,
                        'content_type': content_type,
                        'started_at': datetime.utcnow().isoformat() + 'Z'
                    }
                    
                    # Start execution
                    execution_response = stepfunctions.start_execution(
                        stateMachineArn=state_machine_arn,
                        name=f"execution-{document_id}-{int(datetime.utcnow().timestamp())}",
                        input=json.dumps(workflow_input)
                    )
                    
                    print(f"Started Step Functions execution: {execution_response['executionArn']}")
                    
                    # Response matching frontend expectations
                    response_data = {
                        'document_id': document_id,
                        'status': 'uploaded',
                        'execution_arn': execution_response['executionArn'],
                        'started_at': execution_response['startDate'].isoformat() + 'Z',
                        'message': 'Document uploaded successfully and processing started'
                    }
                else:
                    response_data = {
                        'document_id': document_id,
                        'status': 'uploaded',
                        'message': 'Document uploaded successfully (workflow not configured)',
                        'started_at': datetime.utcnow().isoformat() + 'Z'
                    }
                
                # Record successful upload metrics
                duration_ms = (time.time() - start_time) * 1000
                if METRICS_AVAILABLE:
                    try:
                        get_metrics().record_api_upload(content_type, file_size_mb, True, duration_ms)
                    except Exception as metrics_error:
                        print(f"Failed to record metrics: {metrics_error}")
                    
            except Exception as upload_error:
                # Record failed upload metrics
                duration_ms = (time.time() - start_time) * 1000
                if METRICS_AVAILABLE:
                    try:
                        get_metrics().record_api_upload(content_type or 'unknown', file_size_mb, False, duration_ms)
                        get_metrics().record_error('UploadException', 'APIHandler')
                    except Exception as metrics_error:
                        print(f"Failed to record metrics: {metrics_error}")
                
                print(f"Failed to upload or start workflow: {str(upload_error)}")
                print(f"Traceback: {traceback.format_exc()}")
                return create_cors_response(500, json.dumps({
                    'error': 'Failed to upload document or start workflow',
                    'message': str(upload_error),
                    'traceback': traceback.format_exc()
                }))
        else:
            return create_cors_response(400, json.dumps({
                'error': 'Missing required fields: file_content and filename'
            }))
        
        return create_cors_response(200, json.dumps(response_data))
        
    except json.JSONDecodeError:
        return create_cors_response(400, json.dumps({
            'error': 'Invalid JSON in request body'
        }))
    except Exception as e:
        print(f"Error processing upload: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return create_cors_response(500, json.dumps({
            'error': 'Failed to process upload',
            'message': str(e),
            'traceback': traceback.format_exc()
        }))


def handle_document_status(document_id: str) -> Dict[str, Any]:
    """Handle document status requests"""
    
    try:
        # Check Step Functions execution status
        stepfunctions = boto3.client('stepfunctions')
        state_machine_arn = os.environ.get('STATE_MACHINE_ARN')
        
        if not state_machine_arn:
            return create_cors_response(500, json.dumps({
                'error': 'Step Functions state machine not configured'
            }))
        
        # List executions for this document
        executions = stepfunctions.list_executions(
            stateMachineArn=state_machine_arn,
            statusFilter='RUNNING'
        )
        
        # Find execution for this document
        execution_arn = None
        for execution in executions['executions']:
            if document_id in execution['name']:
                execution_arn = execution['executionArn']
                break
        
        # If no running execution, check succeeded/failed executions
        if not execution_arn:
            all_executions = stepfunctions.list_executions(
                stateMachineArn=state_machine_arn,
                maxResults=50
            )
            
            for execution in all_executions['executions']:
                if document_id in execution['name']:
                    execution_arn = execution['executionArn']
                    break
        
        if execution_arn:
            # Get execution details
            execution_details = stepfunctions.describe_execution(
                executionArn=execution_arn
            )
            
            status = execution_details['status']
            start_date = execution_details['startDate']
            
            # Map Step Functions status to UI status
            if status == 'RUNNING':
                # Get execution history to determine current step
                history = stepfunctions.get_execution_history(
                    executionArn=execution_arn,
                    reverseOrder=True,
                    maxResults=10
                )
                
                current_step = 'extraction'
                percentage = 25
                
                # Determine current step from history
                for event in history['events']:
                    if event['type'] == 'TaskStateEntered':
                        step_name = event['stateEnteredEventDetails']['name']
                        if step_name == 'ExtractMedicalData':
                            current_step = 'extraction'
                            percentage = 25
                        elif step_name == 'SearchPolicies':
                            current_step = 'policy_search'
                            percentage = 50
                        elif step_name == 'SelectBestPolicy':
                            current_step = 'policy_selection'
                            percentage = 75
                        elif step_name == 'ReviewMedicalRecords':
                            current_step = 'assessment'
                            percentage = 90
                        break
                
                response_data = {
                    'document_id': document_id,
                    'status': 'processing',
                    'progress': {
                        'percentage': percentage,
                        'current_step': current_step,
                        'status': 'in_progress'
                    },
                    'started_at': start_date.isoformat() + 'Z',
                    'last_updated': datetime.utcnow().isoformat() + 'Z',
                    'execution_arn': execution_arn
                }
                
            elif status == 'SUCCEEDED':
                # Check if this is a policy extraction initiated success
                # Get execution history to check the final state
                try:
                    history = stepfunctions.get_execution_history(
                        executionArn=execution_arn,
                        reverseOrder=True,
                        maxResults=10
                    )
                    
                    # Check if the last state was PolicyExtractionInitiated
                    is_policy_extraction = False
                    extraction_info = None
                    
                    for event in history['events']:
                        if event['type'] == 'SucceedStateEntered':
                            state_name = event.get('stateEnteredEventDetails', {}).get('name', '')
                            if state_name == 'PolicyExtractionInitiated':
                                is_policy_extraction = True
                                # Try to get extraction info from the execution output
                                if 'output' in execution_details:
                                    try:
                                        output = json.loads(execution_details['output'])
                                        extraction_info = output.get('extraction_info', {})
                                        if extraction_info and 'Cause' in extraction_info:
                                            # Parse the exception message which contains the response data
                                            extraction_info = json.loads(extraction_info['Cause'])
                                    except:  # nosec B110
                                        pass
                                break
                    
                    if is_policy_extraction:
                        # Parse the extraction info from the execution output
                        extraction_data = {}
                        try:
                            output = json.loads(execution_details['output'])
                            extraction_info = output.get('extraction_info', {})
                            
                            if extraction_info and 'Cause' in extraction_info:
                                # The Cause contains a JSON string with errorMessage
                                cause_data = json.loads(extraction_info['Cause'])
                                if 'errorMessage' in cause_data:
                                    # errorMessage contains the actual 202 response data
                                    extraction_data = json.loads(cause_data['errorMessage'])
                                    print(f"Parsed extraction data: {extraction_data}")
                        except Exception as parse_error:
                            print(f"Error parsing extraction info: {str(parse_error)}")
                            print(f"Traceback: {traceback.format_exc()}")
                        
                        # Return 202 response for policy extraction initiated
                        response_data = {
                            'document_id': document_id,
                            'status': 'policy_extraction_initiated',
                            'statusCode': 202,
                            'message': extraction_data.get('message', 'Policy extraction has been initiated. Please check back in 5-10 minutes and retry your request.'),
                            'payor_name': extraction_data.get('payor_name', 'Unknown'),
                            'extraction_initiated': True,
                            'started_at': start_date.isoformat() + 'Z',
                            'completed_at': execution_details['stopDate'].isoformat() + 'Z',
                            'last_updated': datetime.utcnow().isoformat() + 'Z',
                            'execution_arn': execution_arn
                        }
                        
                        if extraction_data and 'execution_arn' in extraction_data:
                            response_data['policy_extraction_arn'] = extraction_data['execution_arn']
                    else:
                        # Normal successful completion
                        response_data = {
                            'document_id': document_id,
                            'status': 'completed',
                            'progress': {
                                'percentage': 100,
                                'current_step': 'completed',
                                'status': 'completed'
                            },
                            'started_at': start_date.isoformat() + 'Z',
                            'completed_at': execution_details['stopDate'].isoformat() + 'Z',
                            'last_updated': datetime.utcnow().isoformat() + 'Z',
                            'execution_arn': execution_arn
                        }
                except Exception as history_error:
                    print(f"Error checking execution history: {str(history_error)}")
                    # Default to normal success response
                    response_data = {
                        'document_id': document_id,
                        'status': 'completed',
                        'progress': {
                            'percentage': 100,
                            'current_step': 'completed',
                            'status': 'completed'
                        },
                        'started_at': start_date.isoformat() + 'Z',
                        'completed_at': execution_details['stopDate'].isoformat() + 'Z',
                        'last_updated': datetime.utcnow().isoformat() + 'Z',
                        'execution_arn': execution_arn
                    }
                
            elif status == 'FAILED':
                response_data = {
                    'document_id': document_id,
                    'status': 'failed',
                    'progress': {
                        'percentage': 0,
                        'current_step': 'error',
                        'status': 'failed'
                    },
                    'started_at': start_date.isoformat() + 'Z',
                    'failed_at': execution_details['stopDate'].isoformat() + 'Z',
                    'last_updated': datetime.utcnow().isoformat() + 'Z',
                    'execution_arn': execution_arn,
                    'error': execution_details.get('error', 'Unknown error')
                }
            else:
                response_data = {
                    'document_id': document_id,
                    'status': 'unknown',
                    'progress': {
                        'percentage': 0,
                        'current_step': 'unknown',
                        'status': status.lower()
                    },
                    'started_at': start_date.isoformat() + 'Z',
                    'last_updated': datetime.utcnow().isoformat() + 'Z',
                    'execution_arn': execution_arn
                }
        else:
            # No execution found
            response_data = {
                'document_id': document_id,
                'status': 'not_found',
                'progress': {
                    'percentage': 0,
                    'current_step': 'not_started',
                    'status': 'not_found'
                },
                'last_updated': datetime.utcnow().isoformat() + 'Z',
                'error': 'No execution found for this document ID'
            }
        
        return create_cors_response(200, json.dumps(response_data))
        
    except Exception as e:
        print(f"Error getting document status: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        
        # Fallback response
        response_data = {
            'document_id': document_id,
            'status': 'error',
            'progress': {
                'percentage': 0,
                'current_step': 'error',
                'status': 'error'
            },
            'last_updated': datetime.utcnow().isoformat() + 'Z',
            'error': f'Failed to get status: {str(e)}'
        }
        
        return create_cors_response(200, json.dumps(response_data))


def handle_results(document_id: str) -> Dict[str, Any]:
    """Handle results requests"""
    
    try:
        # Check if we have results in DynamoDB
        dynamodb = boto3.resource('dynamodb')
        results_table_name = os.environ.get('RESULTS_TABLE')
        
        if results_table_name:
            table = dynamodb.Table(results_table_name)
            
            try:
                response = table.get_item(
                    Key={'document_id': document_id}
                )
                
                if 'Item' in response:
                    # Return stored results
                    item = response['Item']
                    
                    # Convert DynamoDB item to proper format
                    response_data = {
                        'document_id': document_id,
                        'assessment_result': item.get('assessment_result', {}),
                        'stored_at': item.get('stored_at'),
                        'processing_time': item.get('processing_time')
                    }
                    
                    return create_cors_response(200, json.dumps(response_data, default=str))
                    
            except Exception as db_error:
                print(f"Error querying DynamoDB: {str(db_error)}")
        
        # If no results in DynamoDB, try to get from Step Functions execution
        stepfunctions = boto3.client('stepfunctions')
        state_machine_arn = os.environ.get('STATE_MACHINE_ARN')
        
        if state_machine_arn:
            # Find execution for this document
            executions = stepfunctions.list_executions(
                stateMachineArn=state_machine_arn,
                maxResults=50
            )
            
            execution_arn = None
            for execution in executions['executions']:
                if document_id in execution['name']:
                    execution_arn = execution['executionArn']
                    break
            
            if execution_arn:
                execution_details = stepfunctions.describe_execution(
                    executionArn=execution_arn
                )
                
                if execution_details['status'] == 'SUCCEEDED':
                    # Parse the output to get assessment results
                    output = json.loads(execution_details['output'])
                    
                    # Parse the input to get S3 location information
                    execution_input = json.loads(execution_details['input'])
                    bucket_name = execution_input.get('bucket_name', '')
                    object_key = execution_input.get('object_key', '')
                    
                    # Extract reviewer results
                    reviewer_data = None
                    selector_data = None
                    extractor_data = None
                    
                    if 'reviewer_result' in output:
                        reviewer_payload = output['reviewer_result']['Payload']
                        if isinstance(reviewer_payload, str):
                            reviewer_data = json.loads(reviewer_payload)
                        else:
                            reviewer_data = reviewer_payload
                    
                    # Extract selector results for policy information
                    if 'selector_result' in output:
                        selector_payload = output['selector_result']['Payload']
                        if isinstance(selector_payload, str):
                            selector_data = json.loads(selector_payload)
                        else:
                            selector_data = selector_payload
                    
                    # Extract extractor results for additional context
                    if 'extraction_result' in output:
                        extractor_payload = output['extraction_result']['Payload']
                        if isinstance(extractor_payload, str):
                            extractor_data = json.loads(extractor_payload)
                        else:
                            extractor_data = extractor_payload
                    
                    if reviewer_data and 'body' in reviewer_data:
                        assessment_data = json.loads(reviewer_data['body'])
                        
                        # Extract assessment result and ensure gap_analysis is properly structured
                        assessment_result = assessment_data.get('assessment_result', {})
                        
                        # If gap_analysis is empty or not properly structured, use default structure
                        if not assessment_result.get('gap_analysis') or assessment_result.get('gap_analysis') == "":
                            assessment_result['gap_analysis'] = {
                                'missing_evidence': [],
                                'critical_gaps': [],
                                'recommendations': assessment_result.get('recommendations', []),
                                'priority_actions': [],
                                'estimated_approval_likelihood': assessment_result.get('approval_likelihood', 0.0)
                            }
                        
                        # Enhance criteria results with descriptions from selector data
                        # Handle both old format (with 'body') and new format (direct data)
                        if selector_data:
                            if 'body' in selector_data:
                                # Old format: selector_data.body (JSON string)
                                selector_body = json.loads(selector_data['body']) if isinstance(selector_data['body'], str) else selector_data['body']
                            else:
                                # New format: direct data from IntelligentPolicySelector
                                selector_body = selector_data
                            
                            selected_policy = selector_body.get('selected_policy', {})
                            applicable_criteria = selected_policy.get('applicable_criteria', [])
                            
                            # Create a mapping of criterion_id to description
                            criteria_descriptions = {}
                            for criterion in applicable_criteria:
                                description = criterion.get('description', '')
                                # Create a short title from the description (first sentence or first 100 chars)
                                title = description.split('.')[0] if '.' in description else description[:100]
                                if len(title) > 100:
                                    title = title[:100] + '...'
                                
                                criteria_descriptions[criterion.get('criterion_id')] = {
                                    'title': title,
                                    'description': description,
                                    'required_evidence': criterion.get('required_evidence', []),
                                    'clinical_indicators': criterion.get('clinical_indicators', []),
                                    'priority': criterion.get('priority', 'standard')
                                }
                            
                            # Enhance each criterion result with title and description
                            criteria_results = assessment_result.get('criteria_results', [])
                            for criterion_result in criteria_results:
                                criterion_id = criterion_result.get('criterion_id')
                                if criterion_id in criteria_descriptions:
                                    # Send both title and description for UI display
                                    criterion_result['title'] = criteria_descriptions[criterion_id]['title']
                                    criterion_result['description'] = criteria_descriptions[criterion_id]['description']
                                    criterion_result['required_evidence_list'] = criteria_descriptions[criterion_id]['required_evidence']
                                    criterion_result['clinical_indicators'] = criteria_descriptions[criterion_id]['clinical_indicators']
                                    criterion_result['priority'] = criteria_descriptions[criterion_id]['priority']
                        
                        # Build comprehensive response with all required fields
                        response_data = {
                            'document_id': document_id,
                            'assessment_result': assessment_result,
                            'completed_at': execution_details['stopDate'].isoformat() + 'Z'
                        }
                        
                        # Add extracted data from extractor
                        if extractor_data and 'extraction_result' in extractor_data:
                            extraction_result = extractor_data['extraction_result']
                            response_data['extracted_data'] = extraction_result
                            
                            # Add document S3 URI from Step Functions input
                            if bucket_name and object_key:
                                response_data['extracted_data']['document_s3_uri'] = f"s3://{bucket_name}/{object_key}"
                        
                        # Add policy information from selector
                        # Handle both old format (with 'body') and new format (direct data)
                        if selector_data:
                            if 'body' in selector_data:
                                # Old format: selector_data.body (JSON string)
                                selector_body = json.loads(selector_data['body']) if isinstance(selector_data['body'], str) else selector_data['body']
                            else:
                                # New format: direct data from IntelligentPolicySelector
                                selector_body = selector_data
                            
                            selected_policy = selector_body.get('selected_policy', {})
                            
                            response_data['policy_information'] = {
                                'selected_policy_id': selected_policy.get('policy_id', 'Unknown Policy'),
                                'payor': selected_policy.get('payor', 'Unknown Payor'),
                                'relevance_score': selected_policy.get('relevance_score', 0.0)
                            }
                            
                            # Extract title from selected_policy (already set by selector)
                            policy_title = selected_policy.get('policy_title', 'N/A')
                            response_data['title'] = policy_title
                            
                            # Add policy metadata if available
                            policy_metadata = selected_policy.get('policy_metadata', {})
                            if policy_metadata:
                                response_data['policy_metadata'] = {
                                    'source_url': policy_metadata.get('source_url', ''),
                                    's3_uri': policy_metadata.get('s3_uri', ''),
                                    'policy_title': policy_title,
                                    'effective_date': policy_metadata.get('effective_date', ''),
                                    'selection_rationale': policy_metadata.get('selection_rationale', '')
                                }
                        else:
                            # Provide default policy information if selector data is missing
                            response_data['title'] = 'N/A'
                            response_data['policy_information'] = {
                                'selected_policy_id': 'Policy Not Available',
                                'payor': 'Unknown Payor',
                                'relevance_score': 0.0
                            }
                        
                        # Add processing summary from assessment data
                        processing_summary = assessment_data.get('processing_summary', {})
                        response_data['processing_summary'] = {
                            'criteria_assessed': processing_summary.get('criteria_assessed', 0),
                            'gaps_identified': processing_summary.get('gaps_identified', 0),
                            'extraction_confidence': 0.85,  # Default value
                            'policy_selection_confidence': 0.90  # Default value
                        }
                        
                        # Add extraction confidence if available
                        if extractor_data and 'extraction_result' in extractor_data:
                            extraction_result = extractor_data['extraction_result']
                            if isinstance(extraction_result, dict) and 'confidence_score' in extraction_result:
                                response_data['processing_summary']['extraction_confidence'] = extraction_result['confidence_score']
                        
                        # Add policy selection confidence if available
                        if selector_data and 'body' in selector_data:
                            selector_body = json.loads(selector_data['body']) if isinstance(selector_data['body'], str) else selector_data['body']
                            selected_policy = selector_body.get('selected_policy', {})
                            if 'relevance_score' in selected_policy:
                                response_data['processing_summary']['policy_selection_confidence'] = selected_policy['relevance_score']
                        
                        return create_cors_response(200, json.dumps(response_data, default=str))
        
        # No results found
        response_data = {
            'document_id': document_id,
            'error': 'No assessment results found',
            'status': 'not_found'
        }
        
        return create_cors_response(404, json.dumps(response_data))
        
    except Exception as e:
        print(f"Error getting results: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        
        response_data = {
            'document_id': document_id,
            'error': f'Failed to get results: {str(e)}',
            'status': 'error'
        }
        
        return create_cors_response(500, json.dumps(response_data))


def handle_workflow_start(body: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Handle workflow start requests"""
    
    try:
        if body:
            request_data = json.loads(body)
        else:
            request_data = {}
        
        # Get required parameters
        document_id = request_data.get('document_id')
        bucket_name = request_data.get('bucket_name', os.environ.get('DOCUMENTS_BUCKET'))
        object_key = request_data.get('object_key')
        
        if not document_id or not object_key:
            return create_cors_response(400, json.dumps({
                'error': 'Missing required parameters: document_id and object_key'
            }))
        
        # Start Step Functions execution
        stepfunctions = boto3.client('stepfunctions')
        state_machine_arn = os.environ.get('STATE_MACHINE_ARN')
        
        if not state_machine_arn:
            return create_cors_response(500, json.dumps({
                'error': 'Step Functions state machine not configured'
            }))
        
        # Prepare input for Step Functions
        workflow_input = {
            'document_id': document_id,
            'bucket_name': bucket_name,
            'object_key': object_key,
            'started_at': datetime.utcnow().isoformat() + 'Z'
        }
        
        # Start execution
        response = stepfunctions.start_execution(
            stateMachineArn=state_machine_arn,
            name=f"execution-{document_id}-{int(datetime.utcnow().timestamp())}",
            input=json.dumps(workflow_input)
        )
        
        response_data = {
            'execution_arn': response['executionArn'],
            'started_at': response['startDate'].isoformat() + 'Z',
            'status': 'RUNNING',
            'document_id': document_id
        }
        
        print(f"Started Step Functions execution: {response['executionArn']}")
        
        return create_cors_response(200, json.dumps(response_data))
        
    except Exception as e:
        print(f"Error starting workflow: {str(e)}")
        return create_cors_response(500, json.dumps({
            'error': 'Failed to start workflow',
            'message': str(e)
        }))


def create_cors_response(status_code: int, body: str) -> Dict[str, Any]:
    """Create a response with CORS headers"""
    
    return {
        'statusCode': status_code,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-Amz-Date, X-Api-Key, X-Amz-Security-Token',
            'Access-Control-Max-Age': '86400',
            'Content-Type': 'application/json'
        },
        'body': body
    }
