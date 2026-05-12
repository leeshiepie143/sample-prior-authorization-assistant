"""
Consolidated Stack for Prior Authorization System.

This stack creates all resources in a single stack to avoid circular dependencies.
"""

import os
from pathlib import Path
from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_bedrock as bedrock,

    aws_iam as iam,
    aws_kms as kms,
    aws_lambda as lambda_,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as sfn_tasks,
    aws_apigateway as apigateway,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3deploy,
    aws_s3vectors as s3vectors,
    aws_logs as logs,
    aws_sns as sns,
    aws_cloudwatch as cloudwatch,
    BundlingOptions,
    RemovalPolicy,
    Duration,
    CfnOutput
)
from constructs import Construct
from .policy_extractor_stack import add_policy_extractor_to_consolidated_stack

# Get absolute paths for Lambda assets
STACK_DIR = Path(__file__).parent
INFRASTRUCTURE_DIR = STACK_DIR.parent
PROJECT_ROOT = INFRASTRUCTURE_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
LAYERS_DIR = PROJECT_ROOT / "layers"


class ConsolidatedStack(Stack):
    """Consolidated infrastructure stack for Prior Authorization System"""
    
    def __init__(self, scope: Construct, construct_id: str, app_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.app_config = app_config
        
        # 1. Create KMS key first
        self.kms_key = self._create_kms_key()
        
        # 2. Create IAM roles
        self.lambda_role = self._create_lambda_role()
        self.step_functions_role = self._create_step_functions_role()
        
        # 3. Create storage resources
        self.storage_resources = self._create_storage_resources()
        
        # 3.5. Create Lambda layer for dependencies
        self.python_deps_layer = self._create_python_dependencies_layer()
        
        # 4. Create Lambda functions
        self.lambda_functions = self._create_lambda_functions()
        
        # 4.5. Configure S3 event notifications for metadata extraction
        self._configure_s3_event_notifications()
        
        # 5. Create Step Functions
        self.step_function = self._create_step_function()
        
        # 6. Create API Gateway
        self.api_gateway = self._create_api_gateway()
        
        # 7. Create frontend resources
        self.frontend_resources = self._create_frontend_resources()
        
        # 8. Create monitoring resources
        self.monitoring_resources = self._create_monitoring_resources()
        
        # 9. Create policy extractor resources (Phase 1: Aetna)
        self.policy_extractor_resources = add_policy_extractor_to_consolidated_stack(
            stack=self,
            app_config=self.app_config,
            python_deps_layer=self.python_deps_layer,
            lambda_role=self.lambda_role,
            step_functions_role=self.step_functions_role,
            policies_bucket_name=self.storage_resources['policies_bucket'].bucket_name,
            knowledge_base_id=self.storage_resources['knowledge_base_id'],
            data_source_id=self.storage_resources['data_source_id']
        )
        
        # Output important values
        CfnOutput(self, "APIEndpointOutput", value=self.api_gateway.url)
        CfnOutput(self, "FrontendURLOutput", value=self.frontend_resources['frontend_url'])
        CfnOutput(self, "FrontendBucketOutput", value=self.frontend_resources['frontend_bucket'].bucket_name)
        CfnOutput(self, "DocumentsBucketOutput", value=self.storage_resources['documents_bucket'].bucket_name)
        CfnOutput(self, "PoliciesBucketOutput", value=self.storage_resources['policies_bucket'].bucket_name)
        CfnOutput(self, "KnowledgeBaseIdOutput", value=self.storage_resources['knowledge_base_id'])
        CfnOutput(self, "DataSourceIdOutput", value=self.storage_resources['data_source_id'])
    
    def _create_kms_key(self) -> kms.Key:
        """Create KMS key for HIPAA compliance"""
        
        key_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    sid="EnableRootAccess",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    actions=["kms:*"],
                    resources=["*"]
                ),
                iam.PolicyStatement(
                    sid="AllowLambdaAccess",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.ServicePrincipal("lambda.amazonaws.com")],
                    actions=[
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:DescribeKey"
                    ],
                    resources=["*"]
                )
            ]
        )
        
        return kms.Key(
            self, "PriorAuthKMSKey",
            description="KMS key for Prior Authorization System HIPAA compliance",
            policy=key_policy,
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN
        )
    
    def _create_lambda_role(self) -> iam.Role:
        """Create IAM role for Lambda functions"""
        
        return iam.Role(
            self, "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ],
            inline_policies={
                "PriorAuthPolicy": iam.PolicyDocument(
                    statements=[
                        # S3 permissions
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "s3:GetObject", 
                                "s3:PutObject", 
                                "s3:DeleteObject",
                                "s3:PutObjectTagging",
                                "s3:GetObjectTagging",
                                "s3:ListBucket"
                            ],
                            resources=[f"arn:aws:s3:::{self.app_config['app_name']}-*-{self.app_config['environment']}/*"]
                        ),
                        # S3 bucket-level permissions
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["s3:ListBucket"],
                            resources=[f"arn:aws:s3:::{self.app_config['app_name']}-*-{self.app_config['environment']}"]
                        ),
                        # DynamoDB permissions
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"],
                            resources=[f"arn:aws:dynamodb:{self.region}:{self.account}:table/{self.app_config['app_name']}-*-{self.app_config['environment']}"]
                        ),
                        # Bedrock permissions - Specific models and Knowledge Base access
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["bedrock:InvokeModel"],
                            resources=[
                                "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v1",
                                "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
                                "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",
                                "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
                                "arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0",
                                "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                                "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-sonnet-4-6",
                                "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                                "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0"
                            ]
                        ),
                        # Bedrock Knowledge Base permissions
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock:Retrieve", 
                                "bedrock:RetrieveAndGenerate",
                                "bedrock:StartIngestionJob",
                                "bedrock:GetIngestionJob",
                                "bedrock:ListIngestionJobs"
                            ],
                            resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"]
                        ),
                        # Textract permissions (sync and async)
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "textract:DetectDocumentText", 
                                "textract:AnalyzeDocument",
                                "textract:StartDocumentTextDetection",
                                "textract:GetDocumentTextDetection",
                                "textract:StartDocumentAnalysis",
                                "textract:GetDocumentAnalysis"
                            ],
                            resources=["*"]
                        ),
                        # Step Functions permissions (main workflow and policy extractor)
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["states:StartExecution", "states:ListExecutions"],
                            resources=[
                                f"arn:aws:states:{self.region}:{self.account}:stateMachine:{self.app_config['app_name']}-*",
                                f"arn:aws:states:{self.region}:{self.account}:stateMachine:{self.app_config['app_name']}-policy-extractor-{self.app_config['environment']}"
                            ]
                        ),
                        # Step Functions execution permissions (separate resource pattern)
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["states:DescribeExecution", "states:GetExecutionHistory"],
                            resources=[
                                f"arn:aws:states:{self.region}:{self.account}:execution:{self.app_config['app_name']}-*:*",
                                f"arn:aws:states:{self.region}:{self.account}:execution:{self.app_config['app_name']}-policy-extractor-{self.app_config['environment']}:*"
                            ]
                        ),
                        # KMS permissions for S3 and DynamoDB encryption
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey", "kms:ReEncrypt*"],
                            resources=[f"arn:aws:kms:{self.region}:{self.account}:key/*"]
                        ),
                        # SNS permissions for alerts
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["sns:Publish"],
                            resources=[f"arn:aws:sns:{self.region}:{self.account}:{self.app_config['app_name']}-alerts-{self.app_config['environment']}"]
                        )
                    ]
                )
            }
        )
    
    def _create_step_functions_role(self) -> iam.Role:
        """Create IAM role for Step Functions"""
        
        return iam.Role(
            self, "StepFunctionsRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaRole")
            ]
        )
    
    def _create_storage_resources(self) -> dict:
        """Create all storage resources"""
        
        resources = {}
        
        # Documents bucket
        resources['documents_bucket'] = s3.Bucket(
            self, "DocumentsBucket",
            bucket_name=f"{self.app_config['app_name']}-documents-{self.app_config['environment']}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="DeleteOldVersions",
                    noncurrent_version_expiration=Duration.days(90)
                )
            ]
        )
        
        # Policies bucket - auto-refresh via 30-day TTL
        resources['policies_bucket'] = s3.Bucket(
            self, "PoliciesBucket", 
            bucket_name=f"{self.app_config['app_name']}-policies-{self.app_config['environment']}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="AutoRefreshPolicies",
                    enabled=True,
                    expiration=Duration.days(30),
                    noncurrent_version_expiration=Duration.days(7),
                    abort_incomplete_multipart_upload_after=Duration.days(7)
                )
            ]
        )
        
        # DynamoDB tables
        resources['extraction_table'] = dynamodb.Table(
            self, "ExtractionTable",
            table_name=f"{self.app_config['app_name']}-extraction-{self.app_config['environment']}",
            partition_key=dynamodb.Attribute(name="document_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.RETAIN
        )
        
        resources['results_table'] = dynamodb.Table(
            self, "ResultsTable",
            table_name=f"{self.app_config['app_name']}-results-{self.app_config['environment']}",
            partition_key=dynamodb.Attribute(name="document_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.RETAIN
        )
        
        # Bedrock Knowledge Base for policy documents
        resources.update(self._create_bedrock_knowledge_base(resources['policies_bucket']))
        
        # Store policies bucket for later S3 event notification configuration
        resources['policies_bucket_for_events'] = resources['policies_bucket']
        
        return resources
    
    def _create_bedrock_knowledge_base(self, policies_bucket: s3.Bucket) -> dict:
        """Create Bedrock Knowledge Base with S3 Vectors storage and S3 data source"""

        kb_resources = {}
        kb_name = f"{self.app_config['app_name']}-kb-{self.app_config['environment']}"

        # --- IAM role for Bedrock Knowledge Base ---
        kb_role = iam.Role(
            self, "BedrockKnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com").with_conditions({
                "StringEquals": {"aws:SourceAccount": self.account},
                "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"}
            }),
            inline_policies={
                "BedrockKnowledgeBasePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["s3:GetObject", "s3:ListBucket"],
                            resources=[policies_bucket.bucket_arn, f"{policies_bucket.bucket_arn}/*"]
                        ),
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "s3vectors:GetIndex",
                                "s3vectors:QueryVectors",
                                "s3vectors:PutVectors",
                                "s3vectors:GetVectors",
                                "s3vectors:DeleteVectors"
                            ],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["bedrock:InvokeModel"],
                            resources=[
                                "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v1",
                                "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
                                "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",
                                "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
                                "arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0"
                            ]
                        ),
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
                            resources=[self.kms_key.key_arn]
                        )
                    ]
                )
            }
        )

        # --- S3 Vectors bucket for vector storage ---
        vector_bucket = s3vectors.CfnVectorBucket(
            self, "KBVectorBucket",
            vector_bucket_name=f"{self.app_config['app_name']}-kb-vectors-{self.app_config['environment']}"
        )

        # --- S3 Vectors index (required by CloudFormation for KB) ---
        vector_index = s3vectors.CfnIndex(
            self, "KBVectorIndex",
            index_name=f"{self.app_config['app_name']}-kb-idx-{self.app_config['environment']}",
            vector_bucket_name=vector_bucket.vector_bucket_name,
            dimension=1024,
            data_type="float32",
            distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
            )
        )
        vector_index.add_dependency(vector_bucket)

        # --- Bedrock Knowledge Base (S3 Vectors storage) ---
        knowledge_base = bedrock.CfnKnowledgeBase(
            self, "PolicyKnowledgeBase",
            name=kb_name,
            description="Knowledge Base for Prior Authorization payor policies",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=1024,
                            embedding_data_type="FLOAT32"
                        )
                    )
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=vector_index.attr_index_arn
                )
            )
        )
        knowledge_base.add_dependency(vector_index)

        # --- S3 Data Source ---
        data_source = bedrock.CfnDataSource(
            self, "PolicyDataSource",
            name=f"{self.app_config['app_name']}-policies-s3-{self.app_config['environment']}",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=policies_bucket.bucket_arn
                )
            ),
            data_deletion_policy="DELETE"
        )

        # Store references for Lambda env vars and outputs
        kb_resources['kb_role'] = kb_role
        kb_resources['knowledge_base'] = knowledge_base
        kb_resources['data_source'] = data_source
        kb_resources['vector_bucket'] = vector_bucket
        kb_resources['knowledge_base_id'] = knowledge_base.attr_knowledge_base_id
        kb_resources['data_source_id'] = data_source.attr_data_source_id
        kb_resources['collection_name'] = kb_name

        return kb_resources
    

    
    def _create_lambda_functions(self) -> dict:
        """Create all Lambda functions"""
        
        functions = {}
        
        # Common environment variables
        common_env = {
            "ENVIRONMENT": self.app_config['environment'],
            "DOCUMENTS_BUCKET": self.storage_resources['documents_bucket'].bucket_name,
            "POLICIES_BUCKET": self.storage_resources['policies_bucket'].bucket_name,
            "EXTRACTION_TABLE": self.storage_resources['extraction_table'].table_name,
            "RESULTS_TABLE": self.storage_resources['results_table'].table_name,
            "KNOWLEDGE_BASE_ID": self.storage_resources['knowledge_base_id'],
            "DATA_SOURCE_ID": self.storage_resources['data_source_id'],
            "KB_COLLECTION_NAME": self.storage_resources['collection_name'],
            "STATE_MACHINE_ARN": f"arn:aws:states:{self.region}:{self.account}:stateMachine:{self.app_config['app_name']}-workflow-{self.app_config['environment']}",
            "POLICY_EXTRACTOR_WORKFLOW_ARN": f"arn:aws:states:{self.region}:{self.account}:stateMachine:{self.app_config['app_name']}-policy-extractor-{self.app_config['environment']}",
            "SUPPORTED_PAYORS": "Aetna,Humana,Anthem"
        }
        
        # Metadata Extractor (NEW - for policy metadata extraction)
        functions['metadata_extractor'] = lambda_.Function(
            self, "MetadataExtractorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="metadata_extractor.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-metadata-extractor-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(15),
            memory_size=512,
            environment={
                **common_env,
                "ALERT_TOPIC_ARN": f"arn:aws:sns:{self.region}:{self.account}:{self.app_config['app_name']}-alerts-{self.app_config['environment']}"
            },
            layers=[self.python_deps_layer]
        )
        
        # Payor Validator (NEW - for early payor validation)
        functions['payor_validator'] = lambda_.Function(
            self, "PayorValidatorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="payor_validator.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-payor-validator-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # Medical Records Extractor
        functions['extractor'] = lambda_.Function(
            self, "ExtractorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="extractors.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-extractor-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # Policy Knowledge (OLD - kept for backward compatibility during migration)
        functions['knowledge'] = lambda_.Function(
            self, "KnowledgeFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="knowledge.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-knowledge-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # Intelligent Policy Selector (NEW - replaces knowledge + selector)
        functions['intelligent_selector'] = lambda_.Function(
            self, "IntelligentPolicySelectorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="intelligent_policy_selector.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-intelligent-selector-{self.app_config['environment']}",
            description="KB-powered intelligent policy selection with metadata filtering",
            role=self.lambda_role,
            timeout=Duration.minutes(3),  # 3 min timeout with metadata filtering for faster queries
            memory_size=1024,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # Extract Clinical Criteria (NEW - separated from policy selection)
        # This function extracts criteria AND merges them into selected_policy
        functions['extract_criteria'] = lambda_.Function(
            self, "ExtractClinicalCriteriaFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="extract_clinical_criteria.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-extract-criteria-{self.app_config['environment']}",
            description="Extract clinical criteria and merge into selected policy",
            role=self.lambda_role,
            timeout=Duration.minutes(10),  # Longer timeout for Bedrock processing
            memory_size=1024,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # Policy Selector (OLD - kept for backward compatibility during migration)
        functions['selector'] = lambda_.Function(
            self, "SelectorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="selector.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-selector-{self.app_config['environment']}",
            description="Policy selection and criteria extraction - v2 (OLD)",
            role=self.lambda_role,
            timeout=Duration.minutes(10),
            memory_size=1024,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # Medical Record Reviewer
        functions['reviewer'] = lambda_.Function(
            self, "ReviewerFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="reviewer.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-reviewer-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(15),
            memory_size=2048,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        # API Gateway handler
        functions['api'] = lambda_.Function(
            self, "APIFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="api.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            function_name=f"{self.app_config['app_name']}-api-{self.app_config['environment']}",
            role=self.lambda_role,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=common_env,
            layers=[self.python_deps_layer]
        )
        
        return functions
    
    def _configure_s3_event_notifications(self) -> None:
        """Configure S3 event notifications to trigger metadata extractor"""
        
        # DISABLED: S3 event notifications cause recursive Lambda invocations
        # The metadata update (copy_object) triggers another Lambda execution
        # TODO: Re-enable after fixing the recursive trigger issue
        pass
        
        # from aws_cdk import aws_s3_notifications as s3n
        # 
        # policies_bucket = self.storage_resources['policies_bucket']
        # metadata_extractor = self.lambda_functions['metadata_extractor']
        # 
        # # Configure event notifications for all supported file types
        # for suffix in ['.pdf', '.html', '.htm', '.txt']:
        #     policies_bucket.add_event_notification(
        #         s3.EventType.OBJECT_CREATED,
        #         s3n.LambdaDestination(metadata_extractor),
        #         s3.NotificationKeyFilter(suffix=suffix)
        #     )
    
    def _create_python_dependencies_layer(self) -> lambda_.LayerVersion:
        """Create Lambda layer for Python dependencies"""
        
        return lambda_.LayerVersion(
            self, "PythonDependenciesLayer",
            layer_version_name=f"{self.app_config['app_name']}-python-deps-{self.app_config['environment']}",
            code=lambda_.Code.from_asset(str(LAYERS_DIR / "python-deps")),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
            description="Python dependencies for Prior Authorization System",
            removal_policy=RemovalPolicy.RETAIN
        )
    
    def _create_step_function(self) -> sfn.StateMachine:
        """Create Step Functions state machine"""
        
        # Define tasks with proper error handling and retry logic
        extractor_task = sfn_tasks.LambdaInvoke(
            self, "ExtractMedicalData",
            lambda_function=self.lambda_functions['extractor'],
            result_path="$.extraction_result",
            retry_on_service_exceptions=False
        ).add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=2,
            backoff_rate=2.0
        ).add_catch(
            sfn.Fail(self, "ExtractorFailed", 
                    cause="Medical data extraction failed",
                    error="ExtractorError"),
            errors=["States.ALL"],
            result_path="$.error"
        )
        
        # Payor validation task (NEW)
        # Create a Succeed state for policy extraction initiated
        policy_extraction_initiated = sfn.Succeed(
            self, "PolicyExtractionInitiated",
            comment="Policy extraction workflow initiated - user should retry in 5-10 minutes"
        )
        
        payor_validator_task = sfn_tasks.LambdaInvoke(
            self, "ValidatePayor",
            lambda_function=self.lambda_functions['payor_validator'],
            result_path="$.payor_validation_result",
            retry_on_service_exceptions=False
        ).add_catch(
            policy_extraction_initiated,
            errors=["PolicyExtractionInitiatedException"],
            result_path="$.extraction_info"
        ).add_catch(
            sfn.Fail(self, "PayorNotFoundError",
                    cause="No policies available for the specified payor",
                    error="PayorNotFound"),
            errors=["States.ALL"],
            result_path="$.error"
        )
        
        # Intelligent Policy Selection (NEW - replaces SearchPolicies + SelectBestPolicy)
        intelligent_selector_task = sfn_tasks.LambdaInvoke(
            self, "IntelligentPolicySelection",
            lambda_function=self.lambda_functions['intelligent_selector'],
            result_path="$.selector_result",
            retry_on_service_exceptions=False
        ).add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=2,
            backoff_rate=2.0
        ).add_catch(
            sfn.Fail(self, "IntelligentSelectorFailed",
                    cause="Intelligent policy selection failed",
                    error="IntelligentSelectorError"),
            errors=["States.ALL"],
            result_path="$.error"
        )
        
        # Extract Clinical Criteria (NEW - separated from policy selection)
        # This replaces selector_result with complete policy including criteria
        extract_criteria_task = sfn_tasks.LambdaInvoke(
            self, "ExtractClinicalCriteria",
            lambda_function=self.lambda_functions['extract_criteria'],
            result_path="$.selector_result",  # Replace selector_result with complete policy
            retry_on_service_exceptions=False
        ).add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=2,
            backoff_rate=2.0
        ).add_catch(
            sfn.Fail(self, "ExtractCriteriaFailed",
                    cause="Clinical criteria extraction failed",
                    error="ExtractCriteriaError"),
            errors=["States.ALL"],
            result_path="$.error"
        )
        
        # OLD APPROACH (kept for backward compatibility during migration)
        # knowledge_task = sfn_tasks.LambdaInvoke(
        #     self, "SearchPolicies",
        #     lambda_function=self.lambda_functions['knowledge'],
        #     result_path="$.knowledge_result",
        #     retry_on_service_exceptions=False
        # ).add_retry(
        #     errors=["States.TaskFailed"],
        #     interval=Duration.seconds(2),
        #     max_attempts=2,
        #     backoff_rate=2.0
        # ).add_catch(
        #     sfn.Fail(self, "KnowledgeFailed",
        #             cause="Policy search failed",
        #             error="KnowledgeError"),
        #     errors=["States.ALL"],
        #     result_path="$.error"
        # )
        # 
        # selector_task = sfn_tasks.LambdaInvoke(
        #     self, "SelectBestPolicy",
        #     lambda_function=self.lambda_functions['selector'],
        #     result_path="$.selector_result",
        #     retry_on_service_exceptions=False
        # ).add_retry(
        #     errors=["States.TaskFailed"],
        #     interval=Duration.seconds(2),
        #     max_attempts=2,
        #     backoff_rate=2.0
        # ).add_catch(
        #     sfn.Fail(self, "SelectorFailed",
        #             cause="Policy selection failed",
        #             error="SelectorError"),
        #     errors=["States.ALL"],
        #     result_path="$.error"
        # )
        
        reviewer_task = sfn_tasks.LambdaInvoke(
            self, "ReviewMedicalRecords",
            lambda_function=self.lambda_functions['reviewer'],
            result_path="$.reviewer_result",
            retry_on_service_exceptions=False
        ).add_retry(
            errors=["States.TaskFailed"],
            interval=Duration.seconds(2),
            max_attempts=2,
            backoff_rate=2.0
        ).add_catch(
            sfn.Fail(self, "ReviewerFailed",
                    cause="Medical record review failed",
                    error="ReviewerError"),
            errors=["States.ALL"],
            result_path="$.error"
        )
        
        # Define workflow with intelligent policy selection and criteria extraction
        definition = extractor_task.next(
            payor_validator_task.next(
                intelligent_selector_task.next(
                    extract_criteria_task.next(reviewer_task)
                )
            )
        )
        
        # OLD WORKFLOW (kept for reference during migration)
        # definition = extractor_task.next(
        #     payor_validator_task.next(
        #         knowledge_task.next(
        #             selector_task.next(reviewer_task)
        #         )
        #     )
        # )
        
        return sfn.StateMachine(
            self, "WorkflowStateMachine",
            state_machine_name=f"{self.app_config['app_name']}-workflow-{self.app_config['environment']}",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            role=self.step_functions_role,
            timeout=Duration.hours(1)
        )
    
    def _create_api_gateway(self) -> apigateway.RestApi:
        """Create API Gateway"""
        
        api = apigateway.RestApi(
            self, "PriorAuthAPI",
            rest_api_name=f"{self.app_config['app_name']}-api-{self.app_config['environment']}",
            description="Prior Authorization System API",
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key"]
            )
        )
        
        # Create integration
        integration = apigateway.LambdaIntegration(self.lambda_functions['api'])
        
        # CORS options for all methods
        cors_options = apigateway.CorsOptions(
            allow_origins=["*"],  # In production, specify your CloudFront domain
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"]
        )
        
        # Add resources and methods
        documents = api.root.add_resource("documents", 
            default_cors_preflight_options=cors_options)
        
        # Add upload endpoint: POST /documents/upload
        upload = documents.add_resource("upload",
            default_cors_preflight_options=cors_options)
        upload.add_method("POST", integration)
        
        # Also keep the original POST /documents for compatibility
        documents.add_method("POST", integration)
        
        document = documents.add_resource("{document_id}",
            default_cors_preflight_options=cors_options)
        document.add_method("GET", integration)
        
        # Add status endpoint: GET /documents/{document_id}/status
        status = document.add_resource("status",
            default_cors_preflight_options=cors_options)
        status.add_method("GET", integration)
        
        results = api.root.add_resource("results",
            default_cors_preflight_options=cors_options)
        result = results.add_resource("{document_id}",
            default_cors_preflight_options=cors_options)
        result.add_method("GET", integration)
        
        workflow = api.root.add_resource("workflow",
            default_cors_preflight_options=cors_options)
        start = workflow.add_resource("start",
            default_cors_preflight_options=cors_options)
        start.add_method("POST", integration)
        
        return api
    
    def _create_frontend_resources(self) -> dict:
        """Create frontend resources"""
        
        resources = {}
        
        # Frontend S3 bucket (private, accessed via CloudFront)
        resources['frontend_bucket'] = s3.Bucket(
            self, "FrontendBucket",
            bucket_name=f"{self.app_config['app_name']}-frontend-{self.app_config['environment']}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )
        
        # Origin Access Identity for CloudFront
        oai = cloudfront.OriginAccessIdentity(
            self, "FrontendOAI",
            comment=f"OAI for {self.app_config['app_name']} frontend"
        )
        
        # Grant CloudFront access to the bucket
        resources['frontend_bucket'].grant_read(oai)
        
        # CloudFront distribution
        resources['distribution'] = cloudfront.Distribution(
            self, "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    resources['frontend_bucket'],
                    origin_access_identity=oai
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(30)
                )
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            enabled=True,
            comment=f"CloudFront distribution for {self.app_config['app_name']} frontend"
        )
        
        # Deploy frontend build
        # Commented out temporarily - frontend build not needed for Lambda-only deployment
        # s3deploy.BucketDeployment(
        #     self, "FrontendDeployment",
        #     sources=[s3deploy.Source.asset("../frontend/build")],
        #     destination_bucket=resources['frontend_bucket'],
        #     distribution=resources['distribution'],
        #     distribution_paths=["/*"],
        #     prune=True,
        #     retain_on_delete=False
        # )
        
        # Store frontend URL
        resources['frontend_url'] = f"https://{resources['distribution'].distribution_domain_name}"
        
        return resources
    
    def _create_monitoring_resources(self) -> dict:
        """Create monitoring resources"""
        
        resources = {}
        
        # SNS topic for alerts
        resources['alerts_topic'] = sns.Topic(
            self, "AlertsTopic",
            topic_name=f"{self.app_config['app_name']}-alerts-{self.app_config['environment']}"
        )
        
        # CloudWatch dashboard
        dashboard = cloudwatch.Dashboard(
            self, "PriorAuthDashboard",
            dashboard_name=f"{self.app_config['app_name']}-dashboard-{self.app_config['environment']}"
        )
        
        # Add widgets for Lambda functions
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Lambda Invocations",
                left=[
                    self.lambda_functions['extractor'].metric_invocations(),
                    self.lambda_functions['metadata_extractor'].metric_invocations(),
                    self.lambda_functions['payor_validator'].metric_invocations(),
                    self.lambda_functions['intelligent_selector'].metric_invocations(),
                    self.lambda_functions['reviewer'].metric_invocations()
                ],
                width=12
            )
        )
        
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Lambda Errors",
                left=[
                    self.lambda_functions['extractor'].metric_errors(),
                    self.lambda_functions['metadata_extractor'].metric_errors(),
                    self.lambda_functions['payor_validator'].metric_errors(),
                    self.lambda_functions['intelligent_selector'].metric_errors(),
                    self.lambda_functions['reviewer'].metric_errors()
                ],
                width=12
            )
        )
        
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Lambda Duration",
                left=[
                    self.lambda_functions['extractor'].metric_duration(),
                    self.lambda_functions['metadata_extractor'].metric_duration(),
                    self.lambda_functions['payor_validator'].metric_duration(),
                    self.lambda_functions['intelligent_selector'].metric_duration(),
                    self.lambda_functions['reviewer'].metric_duration()
                ],
                width=12
            )
        )
        
        # Add widget for Step Functions executions
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Step Functions Executions",
                left=[
                    self.step_function.metric_started(),
                    self.step_function.metric_succeeded(),
                    self.step_function.metric_failed()
                ],
                width=12
            )
        )
        
        resources['dashboard'] = dashboard
        
        return resources

