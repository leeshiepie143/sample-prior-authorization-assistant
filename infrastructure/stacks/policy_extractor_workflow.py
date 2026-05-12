"""
Policy Extractor Workflow Definition

Step Functions state machine for orchestrating multi-payor policy extraction process.
Supports Aetna, Humana, and Anthem payors with Choice state routing.
"""

from aws_cdk import (
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_lambda as lambda_,
    Duration,
    Stack
)
from constructs import Construct
from typing import Dict


class PolicyExtractorWorkflow(Construct):
    """
    Step Functions workflow for multi-payor policy extraction.
    
    Workflow steps:
    1. ChoosePayorScraper - Choice state to route based on payor name
    2a. ScrapeAetnaPolicies - Scrape and upload to S3, return S3 keys
    2b. ScrapeHumanaPolicies - Scrape and upload to S3, return S3 keys
    2c. ScrapeAnthemPolicies - Scrape and upload to S3, return S3 keys
    3. ProcessPolicies - Map state to process each policy S3 key in parallel
       3a. ExtractMetadata - Read from S3, extract metadata with Bedrock
       3b. UploadMetadata - Create .metadata.json file in S3
    4. TriggerKBSync - Trigger Knowledge Base synchronization
    """
    
    def __init__(
        self,
        scope: Construct,
        id: str,
        aetna_scraper_function: lambda_.IFunction,
        humana_scraper_function: lambda_.IFunction,
        anthem_scraper_function: lambda_.IFunction,
        metadata_extractor_function: lambda_.IFunction,
        metadata_uploader_function: lambda_.IFunction,
        kb_sync_trigger_function: lambda_.IFunction,
        app_config: dict = None,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)
        
        # Task 1a: Scrape Aetna policies (uploads to S3, returns S3 keys)
        scrape_aetna_task = tasks.LambdaInvoke(
            self, "ScrapeAetnaPolicies",
            lambda_function=aetna_scraper_function,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
            comment="Scrape policies from Aetna website (uploads directly to S3)"
        )
        scrape_aetna_task.add_retry(
            errors=["States.TaskFailed", "States.Timeout"],
            interval=Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2.0
        )
        
        # Task: Scrape Humana policies (only if function provided)
        scrape_humana_task = None
        if humana_scraper_function is not None:
            scrape_humana_task = tasks.LambdaInvoke(
                self, "ScrapeHumanaPolicies",
                lambda_function=humana_scraper_function,
                output_path="$.Payload",
                retry_on_service_exceptions=True,
                comment="Scrape policies from Humana website (uploads directly to S3)"
            )
            scrape_humana_task.add_retry(
                errors=["States.TaskFailed", "States.Timeout"],
                interval=Duration.seconds(2),
                max_attempts=3,
                backoff_rate=2.0
            )
        
        # Task: Scrape Anthem policies (only if function provided)
        scrape_anthem_task = None
        if anthem_scraper_function is not None:
            scrape_anthem_task = tasks.LambdaInvoke(
                self, "ScrapeAnthemPolicies",
                lambda_function=anthem_scraper_function,
                output_path="$.Payload",
                retry_on_service_exceptions=True,
                comment="Scrape policies from Anthem website (uploads directly to S3)"
            )
            scrape_anthem_task.add_retry(
                errors=["States.TaskFailed", "States.Timeout"],
                interval=Duration.seconds(2),
                max_attempts=3,
                backoff_rate=2.0
            )
        
        # Task: Extract metadata from policy (reads from S3, calls Bedrock)
        extract_metadata_task = tasks.LambdaInvoke(
            self, "ExtractMetadata",
            lambda_function=metadata_extractor_function,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
            comment="Extract metadata from policy content using Bedrock"
        )
        extract_metadata_task.add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2.0
        )
        
        # Task: Upload metadata to S3 (creates .metadata.json file)
        upload_metadata_task = tasks.LambdaInvoke(
            self, "UploadToS3",
            lambda_function=metadata_uploader_function,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
            comment="Upload metadata file to S3"
        )
        upload_metadata_task.add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2.0
        )
        
        # Chain metadata extraction and upload
        extract_metadata_task.next(upload_metadata_task)
        
        # Map state to process each policy in parallel
        process_policies_map = sfn.Map(
            self, "ProcessPolicies",
            items_path="$.policies",
            max_concurrency=5,
            result_path="$.processed_policies",  # Store results in processed_policies
            comment="Process each policy: extract metadata and upload to S3"
        )
        process_policies_map.iterator(extract_metadata_task)
        
        # Task: Trigger Knowledge Base sync
        # Pass empty object since KB sync uses environment variables
        trigger_kb_sync_task = tasks.LambdaInvoke(
            self, "TriggerKBSync",
            lambda_function=kb_sync_trigger_function,
            payload=sfn.TaskInput.from_object({}),  # Empty object, uses env vars
            output_path="$.Payload",
            retry_on_service_exceptions=True,
            comment="Trigger Bedrock Knowledge Base synchronization"
        )
        trigger_kb_sync_task.add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2.0
        )
        
        # Connect ProcessPolicies Map to TriggerKBSync (only once!)
        process_policies_map.next(trigger_kb_sync_task)
        
        # Connect each scraper to ProcessPolicies Map
        scrape_aetna_task.next(process_policies_map)
        if scrape_humana_task is not None:
            scrape_humana_task.next(process_policies_map)
        if scrape_anthem_task is not None:
            scrape_anthem_task.next(process_policies_map)
        
        # Create unsupported payor fail state
        unsupported_payor_fail = sfn.Fail(
            self, "UnsupportedPayor",
            cause="Payor not supported",
            error="PayorNotSupported"
        )
        
        # Create Choice state to route based on payor
        choose_payor = sfn.Choice(
            self, "ChoosePayorScraper",
            comment="Route to appropriate scraper based on payor name"
        )
        
        # Add conditions for each payor (using StringMatches for partial matching)
        # Only add conditions for scrapers that exist
        choose_payor.when(
            sfn.Condition.string_matches("$.payor", "*Aetna*"),
            scrape_aetna_task
        )
        
        if scrape_humana_task is not None:
            choose_payor.when(
                sfn.Condition.string_matches("$.payor", "*Humana*"),
                scrape_humana_task
            )
        
        if scrape_anthem_task is not None:
            choose_payor.when(
                sfn.Condition.string_matches("$.payor", "*Anthem*"),
                scrape_anthem_task
            )
        
        choose_payor.otherwise(unsupported_payor_fail)
        
        # Define workflow starting with Choice state
        workflow_definition = choose_payor
        
        # Create state machine with environment-specific name to avoid conflicts
        if app_config:
            sm_name = f"{app_config['app_name']}-policy-extractor-{app_config['environment']}"
        else:
            sm_name = "policy-extractor-workflow"

        self.state_machine = sfn.StateMachine(
            self, "PolicyExtractorStateMachine",
            definition=workflow_definition,
            timeout=Duration.minutes(15),
            comment="Policy Extractor Workflow - Dynamically extracts policies from payor websites",
            state_machine_name=sm_name
        )
        
        # Export state machine ARN for reference
        self.state_machine_arn = self.state_machine.state_machine_arn


def create_workflow_definition_dict() -> Dict:
    """
    Create workflow definition as a dictionary for testing.
    
    Returns the ASL (Amazon States Language) definition for multi-payor workflow.
    """
    return {
        "Comment": "Multi-Payor Policy Extractor Workflow",
        "StartAt": "ChoosePayorScraper",
        "States": {
            "ChoosePayorScraper": {
                "Type": "Choice",
                "Comment": "Route to appropriate scraper based on payor name",
                "Choices": [
                    {
                        "Variable": "$.payor",
                        "StringMatches": "*Aetna*",
                        "Next": "ScrapeAetnaPolicies"
                    },
                    {
                        "Variable": "$.payor",
                        "StringMatches": "*Humana*",
                        "Next": "ScrapeHumanaPolicies"
                    },
                    {
                        "Variable": "$.payor",
                        "StringMatches": "*Anthem*",
                        "Next": "ScrapeAnthemPolicies"
                    }
                ],
                "Default": "UnsupportedPayor"
            },
            "ScrapeAetnaPolicies": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": {
                    "FunctionName": "${AetnaScraperFunctionArn}",
                    "Payload.$": "$"
                },
                "Retry": [
                    {
                        "ErrorEquals": ["States.TaskFailed", "States.Timeout"],
                        "IntervalSeconds": 2,
                        "MaxAttempts": 3,
                        "BackoffRate": 2.0
                    }
                ],
                "OutputPath": "$.Payload",
                "Next": "ProcessPolicies"
            },
            "ScrapeHumanaPolicies": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": {
                    "FunctionName": "${HumanaScraperFunctionArn}",
                    "Payload.$": "$"
                },
                "Retry": [
                    {
                        "ErrorEquals": ["States.TaskFailed", "States.Timeout"],
                        "IntervalSeconds": 2,
                        "MaxAttempts": 3,
                        "BackoffRate": 2.0
                    }
                ],
                "OutputPath": "$.Payload",
                "Next": "ProcessPolicies"
            },
            "ScrapeAnthemPolicies": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": {
                    "FunctionName": "${AnthemScraperFunctionArn}",
                    "Payload.$": "$"
                },
                "Retry": [
                    {
                        "ErrorEquals": ["States.TaskFailed", "States.Timeout"],
                        "IntervalSeconds": 2,
                        "MaxAttempts": 3,
                        "BackoffRate": 2.0
                    }
                ],
                "OutputPath": "$.Payload",
                "Next": "ProcessPolicies"
            },
            "ProcessPolicies": {
                "Type": "Map",
                "ItemsPath": "$.policies",
                "MaxConcurrency": 5,
                "Iterator": {
                    "StartAt": "ExtractMetadata",
                    "States": {
                        "ExtractMetadata": {
                            "Type": "Task",
                            "Resource": "arn:aws:states:::lambda:invoke",
                            "Parameters": {
                                "FunctionName": "${MetadataExtractorFunctionArn}",
                                "Payload.$": "$"
                            },
                            "Retry": [
                                {
                                    "ErrorEquals": ["States.TaskFailed"],
                                    "IntervalSeconds": 2,
                                    "MaxAttempts": 3,
                                    "BackoffRate": 2.0
                                }
                            ],
                            "OutputPath": "$.Payload",
                            "Next": "UploadToS3"
                        },
                        "UploadToS3": {
                            "Type": "Task",
                            "Resource": "arn:aws:states:::lambda:invoke",
                            "Parameters": {
                                "FunctionName": "${MetadataUploaderFunctionArn}",
                                "Payload.$": "$"
                            },
                            "Retry": [
                                {
                                    "ErrorEquals": ["States.TaskFailed"],
                                    "IntervalSeconds": 2,
                                    "MaxAttempts": 3,
                                    "BackoffRate": 2.0
                                }
                            ],
                            "OutputPath": "$.Payload",
                            "End": True
                        }
                    }
                },
                "Next": "TriggerKBSync"
            },
            "TriggerKBSync": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": {
                    "FunctionName": "${KBSyncTriggerFunctionArn}",
                    "Payload.$": "$"
                },
                "Retry": [
                    {
                        "ErrorEquals": ["States.TaskFailed"],
                        "IntervalSeconds": 2,
                        "MaxAttempts": 3,
                        "BackoffRate": 2.0
                    }
                ],
                "OutputPath": "$.Payload",
                "End": True
            },
            "UnsupportedPayor": {
                "Type": "Fail",
                "Cause": "Payor not supported",
                "Error": "PayorNotSupported"
            }
        }
    }
