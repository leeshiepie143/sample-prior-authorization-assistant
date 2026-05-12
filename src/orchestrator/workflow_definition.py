"""
Step Functions workflow definition for the Prior Authorization processing system.

This module defines the state machine with sequential processing through all 5 modules,
error handling, retry logic, and progress tracking throughout workflow execution.
"""

import json
from typing import Dict, Any, List
from datetime import datetime

from common.logging_config import get_logger

logger = get_logger(__name__)


class WorkflowDefinition:
    """Defines the Step Functions state machine for prior authorization processing"""
    
    @staticmethod
    def create_state_machine_definition(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Create the complete state machine definition"""
        
        return {
            "Comment": "Prior Authorization Processing Workflow - Sequential processing through all 5 modules with comprehensive error handling",
            "StartAt": "InitializeProcessing",
            "States": {
                
                # Initialize Processing
                "InitializeProcessing": {
                    "Type": "Pass",
                    "Comment": "Initialize processing state and validate input",
                    "Parameters": {
                        "workflow_id.$": "$$.Execution.Name",
                        "started_at.$": "$$.State.EnteredTime",
                        "input.$": "$",
                        "processing_status": "initialized"
                    },
                    "Next": "ValidateInput"
                },
                
                # Input Validation
                "ValidateInput": {
                    "Type": "Task",
                    "Comment": "Validate input parameters and document format",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('validator', 'prior-auth-validator'),
                        "Payload": {
                            "action": "validate_input",
                            "input.$": "$.input"
                        }
                    },
                    "ResultPath": "$.validation_result",
                    "Retry": WorkflowDefinition._get_standard_retry_config(),
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandleValidationError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "ExtractMedicalData"
                },
                
                # Step 1: Medical Records Extraction
                "ExtractMedicalData": {
                    "Type": "Task",
                    "Comment": "Extract medical data from uploaded documents using Textract and Bedrock",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('extractor', 'prior-auth-medical-extractor'),
                        "Payload": {
                            "action": "upload_and_extract",
                            "file_content.$": "$.input.file_content",
                            "filename.$": "$.input.filename",
                            "content_type.$": "$.input.content_type"
                        }
                    },
                    "ResultPath": "$.extraction_result",
                    "TimeoutSeconds": 900,  # 15 minutes
                    "Retry": [
                        {
                            "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException"],
                            "IntervalSeconds": 2,
                            "MaxAttempts": 3,
                            "BackoffRate": 2.0
                        },
                        {
                            "ErrorEquals": ["States.TaskFailed"],
                            "IntervalSeconds": 5,
                            "MaxAttempts": 2,
                            "BackoffRate": 2.0
                        }
                    ],
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandleExtractionError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "ValidatePayor"
                },
                
                # Step 1.5: Payor Validation (NEW)
                "ValidatePayor": {
                    "Type": "Task",
                    "Comment": "Validate that policies exist for the extracted payor",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('payor_validator', 'prior-auth-payor-validator'),
                        "Payload.$": "$"
                    },
                    "ResultPath": "$.payor_validation_result",
                    "TimeoutSeconds": 30,
                    "Retry": WorkflowDefinition._get_standard_retry_config(),
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandlePayorValidationError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "CheckPayorValidation"
                },
                
                # Check Payor Validation Result
                "CheckPayorValidation": {
                    "Type": "Choice",
                    "Comment": "Check if payor validation passed",
                    "Choices": [
                        {
                            "Variable": "$.payor_validation_result.Payload.payor_valid",
                            "BooleanEquals": True,
                            "Next": "SearchPolicies"
                        },
                        {
                            "Variable": "$.payor_validation_result.Payload.statusCode",
                            "NumericEquals": 404,
                            "Next": "HandlePayorNotFound"
                        }
                    ],
                    "Default": "HandlePayorValidationError"
                },
                
                # Handle Payor Not Found
                "HandlePayorNotFound": {
                    "Type": "Pass",
                    "Comment": "Handle payor not found error",
                    "Parameters": {
                        "error_type": "payor_not_found",
                        "error_message.$": "$.payor_validation_result.Payload.message",
                        "payor_name.$": "$.payor_validation_result.Payload.payor_name",
                        "normalized_payor.$": "$.payor_validation_result.Payload.normalized_payor",
                        "processing_status": "failed",
                        "failed_at.$": "$.State.EnteredTime",
                        "retry_able": False,
                        "step_failed": "payor_validation"
                    },
                    "Next": "ProcessingFailed"
                },
                
                # Step 2: Policy Knowledge Base Search
                "SearchPolicies": {
                    "Type": "Task",
                    "Comment": "Search for relevant policies in the knowledge base",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('knowledge', 'prior-auth-policy-knowledge'),
                        "Payload": {
                            "action": "search_policies",
                            "search_query": {
                                "payor.$": "$.extraction_result.Payload.extraction_result.payor_name",
                                "cpt_codes.$": "$.extraction_result.Payload.extraction_result.cpt_codes",
                                "icd_codes.$": "$.extraction_result.Payload.extraction_result.icd_codes",
                                "service_type.$": "$.extraction_result.Payload.extraction_result.service_type",
                                "patient_age_range.$": "$.extraction_result.Payload.extraction_result.patient_info.age_range",
                                "patient_gender.$": "$.extraction_result.Payload.extraction_result.patient_info.gender"
                            },
                            "max_results": 5
                        }
                    },
                    "ResultPath": "$.policy_search_result",
                    "TimeoutSeconds": 300,  # 5 minutes
                    "Retry": WorkflowDefinition._get_standard_retry_config(),
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandlePolicySearchError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "SelectBestPolicy"
                },
                
                # Step 3: Policy Selection
                "SelectBestPolicy": {
                    "Type": "Task",
                    "Comment": "Select the most relevant policy and extract clinical criteria",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('selector', 'prior-auth-policy-selector'),
                        "Payload": {
                            "action": "select_policy",
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "candidate_policies.$": "$.policy_search_result.Payload.search_results",
                            "max_candidates": 5
                        }
                    },
                    "ResultPath": "$.policy_selection_result",
                    "TimeoutSeconds": 600,  # 10 minutes
                    "Retry": WorkflowDefinition._get_standard_retry_config(),
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandlePolicySelectionError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "ValidatePolicySelection"
                },
                
                # Policy Selection Validation
                "ValidatePolicySelection": {
                    "Type": "Task",
                    "Comment": "Validate the policy selection quality and confidence",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('selector', 'prior-auth-policy-selector'),
                        "Payload": {
                            "action": "validate_selection",
                            "selected_policy.$": "$.policy_selection_result.Payload.selected_policy",
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "candidate_policies.$": "$.policy_search_result.Payload.search_results"
                        }
                    },
                    "ResultPath": "$.validation_result",
                    "Retry": WorkflowDefinition._get_standard_retry_config(),
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandleValidationError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "CheckPolicyValidation"
                },
                
                # Check Policy Validation Results
                "CheckPolicyValidation": {
                    "Type": "Choice",
                    "Comment": "Check if policy selection validation passed",
                    "Choices": [
                        {
                            "Variable": "$.validation_result.Payload.validation_result.is_valid",
                            "BooleanEquals": True,
                            "Next": "ReviewMedicalRecords"
                        },
                        {
                            "Variable": "$.validation_result.Payload.validation_result.confidence_score",
                            "NumericLessThan": 0.5,
                            "Next": "HandleLowConfidencePolicy"
                        }
                    ],
                    "Default": "ReviewMedicalRecords"
                },
                
                # Handle Low Confidence Policy Selection
                "HandleLowConfidencePolicy": {
                    "Type": "Pass",
                    "Comment": "Handle low confidence policy selection",
                    "Parameters": {
                        "warning": "Policy selection has low confidence",
                        "confidence_score.$": "$.validation_result.Payload.validation_result.confidence_score",
                        "proceed_with_caution": True
                    },
                    "ResultPath": "$.low_confidence_warning",
                    "Next": "ReviewMedicalRecords"
                },
                
                # Step 4: Medical Record Review
                "ReviewMedicalRecords": {
                    "Type": "Task",
                    "Comment": "Review medical records against clinical criteria and generate assessment",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('reviewer', 'prior-auth-medical-reviewer'),
                        "Payload": {
                            "action": "review_records",
                            "medical_records.$": "$.extraction_result.Payload.extraction_result.raw_text",
                            "clinical_criteria.$": "$.policy_selection_result.Payload.selected_policy.applicable_criteria",
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "selected_policy.$": "$.policy_selection_result.Payload.selected_policy"
                        }
                    },
                    "ResultPath": "$.review_result",
                    "TimeoutSeconds": 1200,  # 20 minutes
                    "Retry": [
                        {
                            "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException"],
                            "IntervalSeconds": 3,
                            "MaxAttempts": 2,
                            "BackoffRate": 2.0
                        },
                        {
                            "ErrorEquals": ["States.TaskFailed"],
                            "IntervalSeconds": 10,
                            "MaxAttempts": 1,
                            "BackoffRate": 1.0
                        }
                    ],
                    "Catch": [
                        {
                            "ErrorEquals": ["States.ALL"],
                            "Next": "HandleReviewError",
                            "ResultPath": "$.error"
                        }
                    ],
                    "Next": "GenerateFinalResults"
                },
                
                # Generate Final Results
                "GenerateFinalResults": {
                    "Type": "Pass",
                    "Comment": "Compile final assessment results and processing summary",
                    "Parameters": {
                        "workflow_id.$": "$.workflow_id",
                        "processing_status": "completed",
                        "completed_at.$": "$$.State.EnteredTime",
                        "document_id.$": "$.extraction_result.Payload.extraction_result.document_id",
                        "assessment_result.$": "$.review_result.Payload.assessment_result",
                        "policy_information": {
                            "selected_policy_id.$": "$.policy_selection_result.Payload.selected_policy.policy_id",
                            "payor.$": "$.policy_selection_result.Payload.selected_policy.payor",
                            "relevance_score.$": "$.policy_selection_result.Payload.selected_policy.relevance_score"
                        },
                        "processing_summary": {
                            "extraction_confidence.$": "$.extraction_result.Payload.extraction_result.extraction_confidence",
                            "policy_selection_confidence.$": "$.policy_selection_result.Payload.validation.quality_metrics.overall_quality",
                            "overall_compliance.$": "$.review_result.Payload.overall_compliance.overall_status",
                            "approval_likelihood.$": "$.review_result.Payload.assessment_result.approval_likelihood",
                            "criteria_assessed.$": "$.review_result.Payload.processing_summary.criteria_assessed",
                            "gaps_identified.$": "$.review_result.Payload.processing_summary.gaps_identified"
                        },
                        "warnings.$": "$.low_confidence_warning"
                    },
                    "Next": "ProcessingComplete"
                },
                
                # Processing Complete
                "ProcessingComplete": {
                    "Type": "Succeed",
                    "Comment": "Prior authorization processing completed successfully"
                },
                
                # Error Handlers
                "HandleValidationError": {
                    "Type": "Pass",
                    "Comment": "Handle input validation errors",
                    "Parameters": {
                        "error_type": "validation_error",
                        "error_message.$": "$.error.Cause",
                        "processing_status": "failed",
                        "failed_at.$": "$$.State.EnteredTime",
                        "retry_able": False
                    },
                    "Next": "ProcessingFailed"
                },
                
                "HandleExtractionError": {
                    "Type": "Pass",
                    "Comment": "Handle medical data extraction errors",
                    "Parameters": {
                        "error_type": "extraction_error",
                        "error_message.$": "$.error.Cause",
                        "processing_status": "failed",
                        "failed_at.$": "$$.State.EnteredTime",
                        "retry_able": True,
                        "step_failed": "medical_extraction"
                    },
                    "Next": "ProcessingFailed"
                },
                
                "HandlePolicySearchError": {
                    "Type": "Pass",
                    "Comment": "Handle policy search errors",
                    "Parameters": {
                        "error_type": "policy_search_error",
                        "error_message.$": "$.error.Cause",
                        "processing_status": "failed",
                        "failed_at.$": "$$.State.EnteredTime",
                        "retry_able": True,
                        "step_failed": "policy_search",
                        "partial_results": {
                            "extraction_completed": True,
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result"
                        }
                    },
                    "Next": "ProcessingFailed"
                },
                
                "HandlePolicySelectionError": {
                    "Type": "Pass",
                    "Comment": "Handle policy selection errors",
                    "Parameters": {
                        "error_type": "policy_selection_error",
                        "error_message.$": "$.error.Cause",
                        "processing_status": "failed",
                        "failed_at.$": "$$.State.EnteredTime",
                        "retry_able": True,
                        "step_failed": "policy_selection",
                        "partial_results": {
                            "extraction_completed": True,
                            "policy_search_completed": True,
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "candidate_policies.$": "$.policy_search_result.Payload.search_results"
                        }
                    },
                    "Next": "ProcessingFailed"
                },
                
                "HandleReviewError": {
                    "Type": "Pass",
                    "Comment": "Handle medical record review errors",
                    "Parameters": {
                        "error_type": "review_error",
                        "error_message.$": "$.error.Cause",
                        "processing_status": "failed",
                        "failed_at.$": "$$.State.EnteredTime",
                        "retry_able": True,
                        "step_failed": "medical_review",
                        "partial_results": {
                            "extraction_completed": True,
                            "policy_selection_completed": True,
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "selected_policy.$": "$.policy_selection_result.Payload.selected_policy"
                        }
                    },
                    "Next": "ProcessingFailed"
                },
                
                # Processing Failed
                "ProcessingFailed": {
                    "Type": "Fail",
                    "Comment": "Prior authorization processing failed"
                }
            }
        }
    
    @staticmethod
    def _get_standard_retry_config() -> List[Dict[str, Any]]:
        """Get standard retry configuration for Lambda tasks"""
        return [
            {
                "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"],
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2.0
            },
            {
                "ErrorEquals": ["States.TaskFailed"],
                "IntervalSeconds": 5,
                "MaxAttempts": 2,
                "BackoffRate": 2.0
            }
        ]
    
    @staticmethod
    def create_express_workflow_definition(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Create an express workflow for faster processing with reduced durability"""
        
        # Get the standard definition
        standard_definition = WorkflowDefinition.create_state_machine_definition(lambda_arns)
        
        # Modify for express workflow
        express_definition = standard_definition.copy()
        express_definition["Comment"] = "Prior Authorization Express Workflow - Optimized for speed"
        
        # Reduce timeouts for express workflow
        for state_name, state_config in express_definition["States"].items():
            if state_config.get("Type") == "Task" and "TimeoutSeconds" in state_config:
                # Reduce timeouts by 50% for express workflow
                state_config["TimeoutSeconds"] = max(60, state_config["TimeoutSeconds"] // 2)
        
        return express_definition
    
    @staticmethod
    def create_parallel_workflow_definition(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Create a workflow with parallel processing where possible"""
        
        return {
            "Comment": "Prior Authorization Parallel Workflow - Optimized for concurrent processing",
            "StartAt": "InitializeProcessing",
            "States": {
                
                "InitializeProcessing": {
                    "Type": "Pass",
                    "Comment": "Initialize processing state",
                    "Parameters": {
                        "workflow_id.$": "$$.Execution.Name",
                        "started_at.$": "$$.State.EnteredTime",
                        "input.$": "$"
                    },
                    "Next": "ExtractMedicalData"
                },
                
                "ExtractMedicalData": {
                    "Type": "Task",
                    "Comment": "Extract medical data from documents",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('extractor', 'prior-auth-medical-extractor'),
                        "Payload": {
                            "action": "upload_and_extract",
                            "file_content.$": "$.input.file_content",
                            "filename.$": "$.input.filename"
                        }
                    },
                    "ResultPath": "$.extraction_result",
                    "Retry": WorkflowDefinition._get_standard_retry_config(),
                    "Next": "ParallelPolicyProcessing"
                },
                
                "ParallelPolicyProcessing": {
                    "Type": "Parallel",
                    "Comment": "Process policy search and validation in parallel",
                    "Branches": [
                        {
                            "StartAt": "SearchPolicies",
                            "States": {
                                "SearchPolicies": {
                                    "Type": "Task",
                                    "Resource": "arn:aws:states:::lambda:invoke",
                                    "Parameters": {
                                        "FunctionName": lambda_arns.get('knowledge', 'prior-auth-policy-knowledge'),
                                        "Payload": {
                                            "action": "search_policies",
                                            "search_query": {
                                                "payor.$": "$.extraction_result.Payload.extraction_result.payor_name",
                                                "cpt_codes.$": "$.extraction_result.Payload.extraction_result.cpt_codes",
                                                "icd_codes.$": "$.extraction_result.Payload.extraction_result.icd_codes",
                                                "service_type.$": "$.extraction_result.Payload.extraction_result.service_type"
                                            }
                                        }
                                    },
                                    "End": true
                                }
                            }
                        },
                        {
                            "StartAt": "ValidateExtraction",
                            "States": {
                                "ValidateExtraction": {
                                    "Type": "Pass",
                                    "Comment": "Validate extraction quality",
                                    "Parameters": {
                                        "validation_status": "completed",
                                        "extraction_confidence.$": "$.extraction_result.Payload.extraction_result.extraction_confidence"
                                    },
                                    "End": true
                                }
                            }
                        }
                    ],
                    "ResultPath": "$.parallel_results",
                    "Next": "SelectBestPolicy"
                },
                
                "SelectBestPolicy": {
                    "Type": "Task",
                    "Comment": "Select best policy from search results",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('selector', 'prior-auth-policy-selector'),
                        "Payload": {
                            "action": "select_policy",
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "candidate_policies.$": "$.parallel_results[0].Payload.search_results"
                        }
                    },
                    "ResultPath": "$.policy_selection_result",
                    "Next": "ReviewMedicalRecords"
                },
                
                "ReviewMedicalRecords": {
                    "Type": "Task",
                    "Comment": "Review medical records against criteria",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('reviewer', 'prior-auth-medical-reviewer'),
                        "Payload": {
                            "action": "review_records",
                            "medical_records.$": "$.extraction_result.Payload.extraction_result.raw_text",
                            "clinical_criteria.$": "$.policy_selection_result.Payload.selected_policy.applicable_criteria",
                            "extracted_data.$": "$.extraction_result.Payload.extraction_result",
                            "selected_policy.$": "$.policy_selection_result.Payload.selected_policy"
                        }
                    },
                    "ResultPath": "$.review_result",
                    "Next": "ProcessingComplete"
                },
                
                "ProcessingComplete": {
                    "Type": "Succeed",
                    "Comment": "Processing completed successfully"
                }
            }
        }


class WorkflowTemplates:
    """Pre-defined workflow templates for different use cases"""
    
    @staticmethod
    def get_standard_workflow(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Standard workflow with full error handling and validation"""
        return WorkflowDefinition.create_state_machine_definition(lambda_arns)
    
    @staticmethod
    def get_express_workflow(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Express workflow optimized for speed"""
        return WorkflowDefinition.create_express_workflow_definition(lambda_arns)
    
    @staticmethod
    def get_parallel_workflow(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Parallel workflow for concurrent processing"""
        return WorkflowDefinition.create_parallel_workflow_definition(lambda_arns)
    
    @staticmethod
    def get_development_workflow(lambda_arns: Dict[str, str]) -> Dict[str, Any]:
        """Simplified workflow for development and testing"""
        
        return {
            "Comment": "Development Workflow - Simplified for testing",
            "StartAt": "ExtractMedicalData",
            "States": {
                "ExtractMedicalData": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('extractor', 'prior-auth-medical-extractor'),
                        "Payload": {
                            "action": "upload_and_extract",
                            "file_content.$": "$.file_content",
                            "filename.$": "$.filename"
                        }
                    },
                    "Next": "SearchPolicies"
                },
                "SearchPolicies": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": lambda_arns.get('knowledge', 'prior-auth-policy-knowledge'),
                        "Payload": {
                            "action": "search_policies",
                            "search_query": {
                                "payor.$": "$.Payload.extraction_result.payor_name",
                                "cpt_codes.$": "$.Payload.extraction_result.cpt_codes",
                                "icd_codes.$": "$.Payload.extraction_result.icd_codes",
                                "service_type.$": "$.Payload.extraction_result.service_type"
                            }
                        }
                    },
                    "Next": "ProcessingComplete"
                },
                "ProcessingComplete": {
                    "Type": "Succeed"
                }
            }
        }

