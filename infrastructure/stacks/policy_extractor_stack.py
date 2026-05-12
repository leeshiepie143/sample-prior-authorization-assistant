"""
Policy Extractor Stack

Creates Lambda functions and Step Functions workflow for dynamic policy extraction.
Follows the consolidated stack pattern with Lambda layers and proper IAM permissions.
"""

import os
from pathlib import Path
from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    Duration,
    RemovalPolicy,
    CfnOutput,
    Size
)
from constructs import Construct
from .policy_extractor_workflow import PolicyExtractorWorkflow

# Get absolute paths for Lambda assets
STACK_DIR = Path(__file__).parent
INFRASTRUCTURE_DIR = STACK_DIR.parent
PROJECT_ROOT = INFRASTRUCTURE_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"


class PolicyExtractorStack(Stack):
    """
    Stack for Policy Extractor infrastructure.
    
    Creates:
    - Aetna scraper Lambda (Docker container with Chrome/Selenium)
    - Metadata processor Lambda
    - S3 uploader Lambda
    - KB sync trigger Lambda
    - Step Functions workflow to orchestrate extraction
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        app_config: dict,
        python_deps_layer: lambda_.ILayerVersion,
        lambda_role: iam.IRole,
        step_functions_role: iam.IRole,
        policies_bucket_name: str,
        knowledge_base_id: str,
        data_source_id: str,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.app_config = app_config
        self.python_deps_layer = python_deps_layer
        self.lambda_role = lambda_role
        self.step_functions_role = step_functions_role
        self.policies_bucket_name = policies_bucket_name
        self.knowledge_base_id = knowledge_base_id
        self.data_source_id = data_source_id
        
        # Create Lambda functions
        self.lambda_functions = self._create_lambda_functions()
        
        # Create Step Functions workflow
        self.workflow = self._create_workflow()
        
        # Output important values
        CfnOutput(
            self, "AetnaScraperFunctionArn",
            value=self.lambda_functions['aetna_scraper'].function_arn,
            description="Aetna Policy Scraper Lambda ARN"
        )
        CfnOutput(
            self, "WorkflowArn",
            value=self.workflow.state_machine_arn,
            description="Policy Extractor Workflow ARN"
        )
    
    def _create_lambda_functions(self) -> dict:
        """Create all Lambda functions for policy extraction"""
        
        functions = {}
        
        # Common environment variables
        common_env = {
            "ENVIRONMENT": self.app_config['environment'],
            "POLICIES_BUCKET": self.policies_bucket_name,
            "KNOWLEDGE_BASE_ID": self.knowledge_base_id,
            "DATA_SOURCE_ID": self.data_source_id
        }
        
        # 1. Aetna Scraper Lambda (Docker container with Chrome/Selenium)
        functions['aetna_scraper'] = lambda_.DockerImageFunction(
            self, "AetnaScraperFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                str(SRC_DIR),  # Use src as build context to include common
                file="policy_extractors/aetna/Dockerfile"
            ),
            function_name=f"{self.app_config['app_name']}-aetna-scraper-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(5),
            memory_size=2048,
            ephemeral_storage_size=Size.mebibytes(1024),
            environment={
                **common_env,
                "CHROME_BIN": "/usr/bin/google-chrome",
                "CHROMEDRIVER_PATH": "/usr/local/bin/chromedriver"
            },
            description="Scrapes Aetna policies using Selenium and Chrome"
        )
        
        # 2. Metadata Processor Lambda
        functions['metadata_processor'] = lambda_.Function(
            self, "MetadataProcessorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="metadata_processor.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-metadata-processor-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(2),
            memory_size=512,
            environment=common_env,
            layers=[self.python_deps_layer],
            description="Extracts metadata from policy text using Bedrock"
        )
        
        # 3. S3 Uploader Lambda
        functions['s3_uploader'] = lambda_.Function(
            self, "S3UploaderFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="s3_uploader.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-s3-uploader-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(1),
            memory_size=256,
            environment=common_env,
            layers=[self.python_deps_layer],
            description="Uploads policy files and metadata to S3"
        )
        
        # 4. KB Sync Trigger Lambda
        functions['kb_sync_trigger'] = lambda_.Function(
            self, "KBSyncTriggerFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="kb_sync.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-kb-sync-trigger-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment=common_env,
            layers=[self.python_deps_layer],
            description="Triggers Bedrock Knowledge Base synchronization"
        )
        
        return functions
    
    def _create_workflow(self) -> sfn.StateMachine:
        """Create Step Functions workflow for policy extraction"""
        
        # Create workflow using the PolicyExtractorWorkflow construct
        workflow_construct = PolicyExtractorWorkflow(
            self, "PolicyExtractorWorkflow",
            aetna_scraper_function=self.lambda_functions['aetna_scraper'],
            metadata_extractor_function=self.lambda_functions['metadata_processor'],
            s3_uploader_function=self.lambda_functions['s3_uploader'],
            kb_sync_trigger_function=self.lambda_functions['kb_sync_trigger']
        )
        
        # Grant Step Functions role permission to invoke Lambda functions
        for function in self.lambda_functions.values():
            function.grant_invoke(self.step_functions_role)
        
        return workflow_construct.state_machine


def add_policy_extractor_to_consolidated_stack(
    stack: Stack,
    app_config: dict,
    python_deps_layer: lambda_.ILayerVersion,
    lambda_role: iam.IRole,
    step_functions_role: iam.IRole,
    policies_bucket_name: str,
    knowledge_base_id: str,
    data_source_id: str
) -> dict:
    """
    Add policy extractor resources to the consolidated stack.
    
    This function can be called from consolidated_stack.py to add
    policy extractor resources without creating a separate stack.
    
    Args:
        stack: The consolidated stack instance
        app_config: Application configuration
        python_deps_layer: Lambda layer with Python dependencies
        lambda_role: IAM role for Lambda functions
        step_functions_role: IAM role for Step Functions
        policies_bucket_name: Name of the policies S3 bucket
        knowledge_base_id: Bedrock Knowledge Base ID
        data_source_id: Bedrock Data Source ID
        
    Returns:
        Dictionary with created resources
    """
    
    resources = {}
    
    # Common environment variables
    common_env = {
        "ENVIRONMENT": app_config['environment'],
        "POLICIES_BUCKET": policies_bucket_name,
        "KNOWLEDGE_BASE_ID": knowledge_base_id,
        "DATA_SOURCE_ID": data_source_id
    }
    
    # 1. Aetna Scraper Lambda (Docker container)
    resources['aetna_scraper'] = lambda_.DockerImageFunction(
        stack, "AetnaScraperFunction",
        code=lambda_.DockerImageCode.from_image_asset(
            str(SRC_DIR),  # Use src as build context to include common
            file="policy_extractors/aetna/Dockerfile"
        ),
        function_name=f"{app_config['app_name']}-aetna-scraper-{app_config['environment']}",
        role=lambda_role,
        timeout=Duration.minutes(5),
        memory_size=2048,
        ephemeral_storage_size=Size.mebibytes(1024),
        environment={
            **common_env,
            "CHROME_BIN": "/usr/bin/google-chrome",
            "CHROMEDRIVER_PATH": "/usr/local/bin/chromedriver"
        },
        description="Scrapes Aetna policies using Selenium and Chrome"
    )
    
    # 2. Humana Scraper Lambda (Docker container with PDF extraction)
    resources['humana_scraper'] = lambda_.DockerImageFunction(
        stack, "HumanaScraperFunction",
        code=lambda_.DockerImageCode.from_image_asset(
            str(SRC_DIR),  # Use src as build context to include common
            file="policy_extractors/humana/Dockerfile"
        ),
        function_name=f"{app_config['app_name']}-humana-scraper-{app_config['environment']}",
        role=lambda_role,
        timeout=Duration.minutes(5),
        memory_size=4096,  # Increased from 2048 to prevent Chrome crashes
        ephemeral_storage_size=Size.mebibytes(2048),  # Increased from 1024 for larger downloads
        environment={
            **common_env,
            "CHROME_BIN": "/usr/bin/google-chrome",
            "CHROMEDRIVER_PATH": "/usr/local/bin/chromedriver"
        },
        description="Scrapes Humana policies using Selenium, Chrome, and PDF extraction"
    )
    
    # 3. Anthem Scraper Lambda (Docker container)
    resources['anthem_scraper'] = lambda_.DockerImageFunction(
        stack, "AnthemScraperFunction",
        code=lambda_.DockerImageCode.from_image_asset(
            str(SRC_DIR),  # Use src as build context to include common
            file="policy_extractors/anthem/Dockerfile"
        ),
        function_name=f"{app_config['app_name']}-anthem-scraper-{app_config['environment']}",
        role=lambda_role,
        timeout=Duration.minutes(5),
        memory_size=2048,
        ephemeral_storage_size=Size.mebibytes(1024),
        environment={
            **common_env,
            "CHROME_BIN": "/usr/bin/google-chrome",
            "CHROMEDRIVER_PATH": "/usr/local/bin/chromedriver"
        },
        description="Scrapes Anthem policies using Selenium and Chrome with state-specific search"
    )
    
    # 4. Metadata Processor Lambda
    resources['metadata_processor'] = lambda_.Function(
        stack, "MetadataProcessorFunction",
        runtime=lambda_.Runtime.PYTHON_3_11,
        handler="metadata_processor.handler.lambda_handler",
        code=lambda_.Code.from_asset(str(SRC_DIR)),
        function_name=f"{app_config['app_name']}-metadata-processor-{app_config['environment']}",
        role=lambda_role,
        timeout=Duration.minutes(2),
        memory_size=512,
        environment=common_env,
        layers=[python_deps_layer],
        description="Extracts metadata from policy text using Bedrock"
    )
    
    # 5. S3 Uploader Lambda
    resources['s3_uploader'] = lambda_.Function(
        stack, "S3UploaderFunction",
        runtime=lambda_.Runtime.PYTHON_3_11,
        handler="s3_uploader.handler.lambda_handler",
        code=lambda_.Code.from_asset(str(SRC_DIR)),
        function_name=f"{app_config['app_name']}-s3-uploader-{app_config['environment']}",
        role=lambda_role,
        timeout=Duration.minutes(1),
        memory_size=256,
        environment=common_env,
        layers=[python_deps_layer],
        description="Uploads policy files and metadata to S3"
    )
    
    # 6. KB Sync Trigger Lambda
    resources['kb_sync_trigger'] = lambda_.Function(
        stack, "KBSyncTriggerFunction",
        runtime=lambda_.Runtime.PYTHON_3_11,
        handler="kb_sync.handler.lambda_handler",
        code=lambda_.Code.from_asset(str(SRC_DIR)),
        function_name=f"{app_config['app_name']}-kb-sync-trigger-{app_config['environment']}",
        role=lambda_role,
        timeout=Duration.seconds(30),
        memory_size=128,
        environment=common_env,
        layers=[python_deps_layer],
        description="Triggers Bedrock Knowledge Base synchronization"
    )
    
    # 7. Create Step Functions workflow (generic name, supports all payors)
    workflow_construct = PolicyExtractorWorkflow(
        stack, "PolicyExtractorWorkflow",
        aetna_scraper_function=resources['aetna_scraper'],
        humana_scraper_function=resources['humana_scraper'],
        anthem_scraper_function=resources['anthem_scraper'],
        metadata_extractor_function=resources['metadata_processor'],
        metadata_uploader_function=resources['s3_uploader'],
        kb_sync_trigger_function=resources['kb_sync_trigger'],
        app_config=app_config
    )
    
    # Grant Step Functions role permission to invoke Lambda functions
    for function in resources.values():
        if isinstance(function, (lambda_.Function, lambda_.DockerImageFunction)):
            function.grant_invoke(step_functions_role)
    
    resources['workflow'] = workflow_construct.state_machine
    resources['workflow_arn'] = workflow_construct.state_machine_arn
    
    # Output important values
    CfnOutput(
        stack, "AetnaScraperFunctionArn",
        value=resources['aetna_scraper'].function_arn,
        description="Aetna Policy Scraper Lambda ARN"
    )
    CfnOutput(
        stack, "HumanaScraperFunctionArn",
        value=resources['humana_scraper'].function_arn,
        description="Humana Policy Scraper Lambda ARN"
    )
    CfnOutput(
        stack, "AnthemScraperFunctionArn",
        value=resources['anthem_scraper'].function_arn,
        description="Anthem Policy Scraper Lambda ARN"
    )
    CfnOutput(
        stack, "PolicyExtractorWorkflowArn",
        value=resources['workflow'].state_machine_arn,
        description="Policy Extractor Workflow ARN (supports all payors)"
    )
    
    return resources
