"""
Bedrock Knowledge Base infrastructure setup and management.

This module handles the creation, configuration, and management of
Amazon Bedrock Knowledge Base with OpenSearch Serverless for
payor policy document storage and retrieval.
"""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

from common.aws_clients import get_aws_client_manager
from common.exceptions import AWSServiceError, ConfigurationError
from common.decorators import handle_processing_errors, monitor_performance, retry_with_backoff
from common.logging_config import get_logger
from common.utils import generate_document_id

logger = get_logger(__name__)


class BedrockKnowledgeBaseManager:
    """Manages Bedrock Knowledge Base infrastructure and configuration"""
    
    def __init__(self):
        self.client_manager = get_aws_client_manager()
        self.bedrock_agent_client = self.client_manager.get_bedrock_agent_client()
        self.opensearch_client = self._get_opensearch_client()
        self.s3_client = self.client_manager.get_s3_client()
        
        # Configuration from environment
        self.policies_bucket = os.getenv('POLICIES_BUCKET')
        self.knowledge_base_name = os.getenv('KNOWLEDGE_BASE_NAME', 'prior-auth-policies-kb')
        self.opensearch_collection_name = os.getenv('OPENSEARCH_COLLECTION', 'prior-auth-policies')
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        
        if not self.policies_bucket:
            raise ConfigurationError("POLICIES_BUCKET environment variable is required")
    
    def _get_opensearch_client(self):
        """Get OpenSearch Serverless client"""
        return self.client_manager._clients.setdefault(
            'opensearch_serverless',
            self.client_manager.get_aws_client_manager().region.client('opensearchserverless')
        )
    
    @handle_processing_errors
    @monitor_performance
    def create_knowledge_base_infrastructure(self) -> Dict[str, str]:
        """Create complete knowledge base infrastructure"""
        
        logger.info("Creating Bedrock Knowledge Base infrastructure")
        
        # Step 1: Create OpenSearch Serverless collection
        collection_arn = self._create_opensearch_collection()
        
        # Step 2: Create vector index
        index_name = self._create_vector_index(collection_arn)
        
        # Step 3: Create IAM role for Knowledge Base
        kb_role_arn = self._create_knowledge_base_role()
        
        # Step 4: Create Knowledge Base
        kb_id = self._create_knowledge_base(collection_arn, index_name, kb_role_arn)
        
        # Step 5: Create data source
        data_source_id = self._create_data_source(kb_id)
        
        infrastructure_info = {
            'knowledge_base_id': kb_id,
            'data_source_id': data_source_id,
            'collection_arn': collection_arn,
            'index_name': index_name,
            'role_arn': kb_role_arn,
            'policies_bucket': self.policies_bucket
        }
        
        logger.info("Knowledge Base infrastructure created successfully", **infrastructure_info)
        
        return infrastructure_info
    
    @retry_with_backoff(max_attempts=3)
    def _create_opensearch_collection(self) -> str:
        """Create OpenSearch Serverless collection for vector storage"""
        
        try:
            # Check if collection already exists
            try:
                response = self.opensearch_client.batch_get_collection(
                    names=[self.opensearch_collection_name]
                )
                if response.get('collectionDetails'):
                    collection_arn = response['collectionDetails'][0]['arn']
                    logger.info("OpenSearch collection already exists", arn=collection_arn)
                    return collection_arn
            except Exception:  # nosec B110
                pass  # Collection doesn't exist, create it
            
            # Create security policy
            security_policy = {
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{self.opensearch_collection_name}"]
                    }
                ],
                "AWSOwnedKey": True
            }
            
            try:
                self.opensearch_client.create_security_policy(
                    name=f"{self.opensearch_collection_name}-security-policy",
                    type='encryption',
                    policy=json.dumps(security_policy)
                )
            except Exception as e:
                if "already exists" not in str(e):
                    raise
            
            # Create network policy
            network_policy = [
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": [f"collection/{self.opensearch_collection_name}"]
                        },
                        {
                            "ResourceType": "dashboard",
                            "Resource": [f"collection/{self.opensearch_collection_name}"]
                        }
                    ],
                    "AllowFromPublic": True
                }
            ]
            
            try:
                self.opensearch_client.create_security_policy(
                    name=f"{self.opensearch_collection_name}-network-policy",
                    type='network',
                    policy=json.dumps(network_policy)
                )
            except Exception as e:
                if "already exists" not in str(e):
                    raise
            
            # Create collection
            response = self.opensearch_client.create_collection(
                name=self.opensearch_collection_name,
                type='VECTORSEARCH',
                description='Vector collection for prior authorization policies'
            )
            
            collection_arn = response['createCollectionDetail']['arn']
            
            logger.info("OpenSearch collection created", 
                       name=self.opensearch_collection_name,
                       arn=collection_arn)
            
            return collection_arn
            
        except Exception as e:
            logger.warning("Failed to create OpenSearch collection", error=str(e))
            raise AWSServiceError(f"Failed to create OpenSearch collection: {str(e)}")
    
    def _create_vector_index(self, collection_arn: str) -> str:
        """Create vector index in OpenSearch collection"""
        
        index_name = "policy-vectors"
        
        # Vector index mapping for medical policy documents
        index_mapping = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 512
                }
            },
            "mappings": {
                "properties": {
                    "vector_field": {
                        "type": "knn_vector",
                        "dimension": 1024,  # Titan Embeddings V2 dimension
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib",
                            "parameters": {
                                "ef_construction": 512,
                                "m": 16
                            }
                        }
                    },
                    "text_field": {
                        "type": "text"
                    },
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "payor": {"type": "keyword"},
                            "service_codes": {"type": "keyword"},
                            "clinical_area": {"type": "keyword"},
                            "effective_date": {"type": "date"},
                            "policy_version": {"type": "keyword"},
                            "document_type": {"type": "keyword"}
                        }
                    }
                }
            }
        }
        
        logger.info("Vector index configuration prepared", 
                   index_name=index_name,
                   dimension=1536)
        
        return index_name
    
    def _create_knowledge_base_role(self) -> str:
        """Create IAM role for Knowledge Base with necessary permissions"""
        
        iam_client = self.client_manager._clients.setdefault(
            'iam',
            self.client_manager.get_aws_client_manager().region.client('iam')
        )
        
        role_name = f"BedrockKnowledgeBaseRole-{self.knowledge_base_name}"
        
        # Trust policy for Bedrock
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "bedrock.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        # Permissions policy
        permissions_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:ListBucket"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{self.policies_bucket}",
                        f"arn:aws:s3:::{self.policies_bucket}/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "aoss:APIAccessAll"
                    ],
                    "Resource": f"arn:aws:aoss:{self.region}:*:collection/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel"
                    ],
                    "Resource": "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0"
                }
            ]
        }
        
        try:
            # Create role
            response = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Role for Bedrock Knowledge Base {self.knowledge_base_name}"
            )
            
            role_arn = response['Role']['Arn']
            
            # Attach permissions policy
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{role_name}-Policy",
                PolicyDocument=json.dumps(permissions_policy)
            )
            
            logger.info("Knowledge Base IAM role created", 
                       role_name=role_name,
                       role_arn=role_arn)
            
            return role_arn
            
        except iam_client.exceptions.EntityAlreadyExistsException:
            # Role already exists, get its ARN
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response['Role']['Arn']
            logger.info("Knowledge Base IAM role already exists", role_arn=role_arn)
            return role_arn
            
        except Exception as e:
            logger.warning("Failed to create Knowledge Base role", error=str(e))
            raise AWSServiceError(f"Failed to create Knowledge Base role: {str(e)}")
    
    @retry_with_backoff(max_attempts=3)
    def _create_knowledge_base(self, collection_arn: str, index_name: str, role_arn: str) -> str:
        """Create Bedrock Knowledge Base"""
        
        try:
            # Check if knowledge base already exists
            try:
                response = self.bedrock_agent_client.list_knowledge_bases()
                for kb in response.get('knowledgeBaseSummaries', []):
                    if kb['name'] == self.knowledge_base_name:
                        logger.info("Knowledge Base already exists", 
                                   kb_id=kb['knowledgeBaseId'])
                        return kb['knowledgeBaseId']
            except Exception:  # nosec B110
                pass
            
            # Knowledge Base configuration with Titan Embeddings V2
            kb_config = {
                'type': 'VECTOR',
                'vectorKnowledgeBaseConfiguration': {
                    'embeddingModelArn': f'arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0'
                }
            }
            
            # Storage configuration for OpenSearch Serverless
            storage_config = {
                'type': 'OPENSEARCH_SERVERLESS',
                'opensearchServerlessConfiguration': {
                    'collectionArn': collection_arn,
                    'vectorIndexName': index_name,
                    'fieldMapping': {
                        'vectorField': 'vector_field',
                        'textField': 'text_field',
                        'metadataField': 'metadata'
                    }
                }
            }
            
            response = self.bedrock_agent_client.create_knowledge_base(
                name=self.knowledge_base_name,
                description='Knowledge base for prior authorization policies',
                roleArn=role_arn,
                knowledgeBaseConfiguration=kb_config,
                storageConfiguration=storage_config
            )
            
            kb_id = response['knowledgeBase']['knowledgeBaseId']
            
            logger.info("Bedrock Knowledge Base created",
                       kb_id=kb_id,
                       name=self.knowledge_base_name)
            
            return kb_id
            
        except Exception as e:
            logger.warning("Failed to create Knowledge Base", error=str(e))
            raise AWSServiceError(f"Failed to create Knowledge Base: {str(e)}")
    
    @retry_with_backoff(max_attempts=3)
    def _create_data_source(self, knowledge_base_id: str) -> str:
        """Create S3 data source for Knowledge Base"""
        
        try:
            data_source_config = {
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': f'arn:aws:s3:::{self.policies_bucket}',
                    'inclusionPrefixes': ['policies/'],
                    'chunkingConfiguration': {
                        'chunkingStrategy': 'FIXED_SIZE',
                        'fixedSizeChunkingConfiguration': {
                            'maxTokens': 300,  # Optimized for precise semantic matching
                            'overlapPercentage': 20
                        }
                    }
                }
            }
            
            response = self.bedrock_agent_client.create_data_source(
                knowledgeBaseId=knowledge_base_id,
                name=f"{self.knowledge_base_name}-s3-source",
                description='S3 data source for policy documents',
                dataSourceConfiguration=data_source_config
            )
            
            data_source_id = response['dataSource']['dataSourceId']
            
            logger.info("Data source created",
                       data_source_id=data_source_id,
                       kb_id=knowledge_base_id)
            
            return data_source_id
            
        except Exception as e:
            logger.warning("Failed to create data source", error=str(e))
            raise AWSServiceError(f"Failed to create data source: {str(e)}")
    
    @handle_processing_errors
    def get_knowledge_base_info(self) -> Optional[Dict[str, Any]]:
        """Get existing knowledge base information"""
        
        try:
            response = self.bedrock_agent_client.list_knowledge_bases()
            
            for kb in response.get('knowledgeBaseSummaries', []):
                if kb['name'] == self.knowledge_base_name:
                    kb_id = kb['knowledgeBaseId']
                    
                    # Get detailed information
                    detail_response = self.bedrock_agent_client.get_knowledge_base(
                        knowledgeBaseId=kb_id
                    )
                    
                    return {
                        'knowledge_base_id': kb_id,
                        'name': kb['name'],
                        'status': kb['status'],
                        'created_at': kb.get('createdAt'),
                        'updated_at': kb.get('updatedAt'),
                        'details': detail_response['knowledgeBase']
                    }
            
            return None
            
        except Exception as e:
            logger.warning("Failed to get knowledge base info", error=str(e))
            raise AWSServiceError(f"Failed to get knowledge base info: {str(e)}")
    
    @handle_processing_errors
    def setup_s3_bucket_structure(self) -> None:
        """Set up S3 bucket structure for policy documents"""
        
        try:
            # Create folder structure
            folders = [
                'policies/',
                'policies/payors/',
                'policies/payors/aetna/',
                'policies/payors/cigna/',
                'policies/payors/humana/',
                'policies/payors/bcbs/',
                'policies/payors/medicare/',
                'policies/payors/medicaid/',
                'policies/metadata/',
                'policies/templates/'
            ]
            
            for folder in folders:
                self.s3_client.put_object(
                    Bucket=self.policies_bucket,
                    Key=folder,
                    Body=b''
                )
            
            # Create metadata index file
            metadata_index = {
                'created_at': datetime.utcnow().isoformat(),
                'structure_version': '1.0',
                'description': 'Prior authorization policies knowledge base',
                'payors': ['aetna', 'cigna', 'humana', 'bcbs', 'medicare', 'medicaid'],
                'clinical_areas': ['cardiology', 'orthopedics', 'radiology', 'oncology', 'neurology']
            }
            
            self.s3_client.put_object(
                Bucket=self.policies_bucket,
                Key='policies/metadata/index.json',
                Body=json.dumps(metadata_index, indent=2),
                ContentType='application/json'
            )
            
            logger.info("S3 bucket structure created", bucket=self.policies_bucket)
            
        except Exception as e:
            logger.warning("Failed to setup S3 bucket structure", error=str(e))
            raise AWSServiceError(f"Failed to setup S3 bucket structure: {str(e)}") 
   
    @handle_processing_errors
    @monitor_performance
    def setup_complete_infrastructure(self) -> Dict[str, Any]:
        """Set up complete knowledge base infrastructure from scratch"""
        
        logger.info("Starting complete knowledge base infrastructure setup")
        
        try:
            # Step 1: Set up S3 bucket structure
            logger.info("Setting up S3 bucket structure")
            self.setup_s3_bucket_structure()
            
            # Step 2: Create knowledge base infrastructure
            logger.info("Creating Bedrock Knowledge Base infrastructure")
            infrastructure_info = self.create_knowledge_base_infrastructure()
            
            # Step 3: Validate setup
            logger.info("Validating knowledge base setup")
            validation_result = self.validate_infrastructure()
            
            setup_result = {
                'status': 'completed',
                'infrastructure': infrastructure_info,
                'validation': validation_result,
                'setup_completed_at': datetime.utcnow().isoformat(),
                's3_bucket': self.policies_bucket,
                'region': self.region
            }
            
            logger.info("Knowledge base infrastructure setup completed successfully",
                       kb_id=infrastructure_info['knowledge_base_id'],
                       bucket=self.policies_bucket)
            
            return setup_result
            
        except Exception as e:
            logger.warning("Failed to setup complete infrastructure", error=str(e))
            raise AWSServiceError(f"Failed to setup complete infrastructure: {str(e)}")
    
    @handle_processing_errors
    def validate_infrastructure(self) -> Dict[str, Any]:
        """Validate that all infrastructure components are properly configured"""
        
        validation_results = {
            'knowledge_base': False,
            'opensearch_collection': False,
            's3_bucket': False,
            'iam_role': False,
            'data_source': False,
            'overall_status': 'failed'
        }
        
        try:
            # Check Knowledge Base
            kb_info = self.get_knowledge_base_info()
            if kb_info and kb_info.get('status') == 'ACTIVE':
                validation_results['knowledge_base'] = True
                logger.info("Knowledge Base validation passed", kb_id=kb_info['knowledge_base_id'])
            
            # Check S3 bucket
            try:
                self.s3_client.head_bucket(Bucket=self.policies_bucket)
                # Check if folder structure exists
                response = self.s3_client.list_objects_v2(
                    Bucket=self.policies_bucket,
                    Prefix='policies/',
                    MaxKeys=1
                )
                if 'Contents' in response or 'CommonPrefixes' in response:
                    validation_results['s3_bucket'] = True
                    logger.info("S3 bucket validation passed", bucket=self.policies_bucket)
            except Exception as e:
                logger.warning("S3 bucket validation failed", error=str(e))
            
            # Check OpenSearch collection
            try:
                response = self.opensearch_client.batch_get_collection(
                    names=[self.opensearch_collection_name]
                )
                if response.get('collectionDetails'):
                    collection = response['collectionDetails'][0]
                    if collection.get('status') == 'ACTIVE':
                        validation_results['opensearch_collection'] = True
                        logger.info("OpenSearch collection validation passed")
            except Exception as e:
                logger.warning("OpenSearch collection validation failed", error=str(e))
            
            # Overall status
            if all([
                validation_results['knowledge_base'],
                validation_results['s3_bucket'],
                validation_results['opensearch_collection']
            ]):
                validation_results['overall_status'] = 'passed'
            elif any([
                validation_results['knowledge_base'],
                validation_results['s3_bucket']
            ]):
                validation_results['overall_status'] = 'partial'
            
            validation_results['validated_at'] = datetime.utcnow().isoformat()
            
            logger.info("Infrastructure validation completed",
                       overall_status=validation_results['overall_status'])
            
            return validation_results
            
        except Exception as e:
            logger.error("Failed to validate infrastructure", error=str(e))
            validation_results['error'] = str(e)
            return validation_results
    
    @handle_processing_errors
    def get_infrastructure_status(self) -> Dict[str, Any]:
        """Get current status of all infrastructure components"""
        
        try:
            status_info = {
                'knowledge_base': None,
                'opensearch_collection': None,
                's3_bucket': None,
                'last_checked': datetime.utcnow().isoformat()
            }
            
            # Knowledge Base status
            kb_info = self.get_knowledge_base_info()
            if kb_info:
                status_info['knowledge_base'] = {
                    'id': kb_info['knowledge_base_id'],
                    'name': kb_info['name'],
                    'status': kb_info['status'],
                    'created_at': kb_info.get('created_at'),
                    'updated_at': kb_info.get('updated_at')
                }
            
            # OpenSearch collection status
            try:
                response = self.opensearch_client.batch_get_collection(
                    names=[self.opensearch_collection_name]
                )
                if response.get('collectionDetails'):
                    collection = response['collectionDetails'][0]
                    status_info['opensearch_collection'] = {
                        'name': collection['name'],
                        'arn': collection['arn'],
                        'status': collection['status'],
                        'created_date': collection.get('createdDate')
                    }
            except Exception as e:
                status_info['opensearch_collection'] = {'error': str(e)}
            
            # S3 bucket status
            try:
                self.s3_client.head_bucket(Bucket=self.policies_bucket)
                
                # Get bucket policy count
                response = self.s3_client.list_objects_v2(
                    Bucket=self.policies_bucket,
                    Prefix='policies/'
                )
                
                policy_count = len(response.get('Contents', []))
                
                status_info['s3_bucket'] = {
                    'name': self.policies_bucket,
                    'status': 'accessible',
                    'policy_document_count': policy_count
                }
            except Exception as e:
                status_info['s3_bucket'] = {'error': str(e)}
            
            return status_info
            
        except Exception as e:
            logger.error("Failed to get infrastructure status", error=str(e))
            return {'error': str(e), 'last_checked': datetime.utcnow().isoformat()}
    
    @handle_processing_errors
    def cleanup_infrastructure(self, confirm: bool = False) -> Dict[str, Any]:
        """Clean up knowledge base infrastructure (use with caution)"""
        
        if not confirm:
            return {
                'status': 'cancelled',
                'message': 'Cleanup cancelled - confirmation required',
                'note': 'Set confirm=True to proceed with cleanup'
            }
        
        cleanup_results = {
            'knowledge_base_deleted': False,
            'data_source_deleted': False,
            'opensearch_collection_deleted': False,
            'iam_role_deleted': False,
            'errors': []
        }
        
        try:
            # Get current infrastructure info
            kb_info = self.get_knowledge_base_info()
            
            if kb_info:
                kb_id = kb_info['knowledge_base_id']
                
                try:
                    # Delete data sources first
                    response = self.bedrock_agent_client.list_data_sources(
                        knowledgeBaseId=kb_id
                    )
                    
                    for data_source in response.get('dataSourceSummaries', []):
                        self.bedrock_agent_client.delete_data_source(
                            knowledgeBaseId=kb_id,
                            dataSourceId=data_source['dataSourceId']
                        )
                        cleanup_results['data_source_deleted'] = True
                        logger.info("Data source deleted", 
                                   data_source_id=data_source['dataSourceId'])
                    
                    # Delete knowledge base
                    self.bedrock_agent_client.delete_knowledge_base(
                        knowledgeBaseId=kb_id
                    )
                    cleanup_results['knowledge_base_deleted'] = True
                    logger.info("Knowledge base deleted", kb_id=kb_id)
                    
                except Exception as e:
                    cleanup_results['errors'].append(f"Knowledge base cleanup: {str(e)}")
            
            # Delete OpenSearch collection
            try:
                self.opensearch_client.delete_collection(
                    name=self.opensearch_collection_name
                )
                cleanup_results['opensearch_collection_deleted'] = True
                logger.info("OpenSearch collection deleted")
            except Exception as e:
                cleanup_results['errors'].append(f"OpenSearch cleanup: {str(e)}")
            
            cleanup_results['cleanup_completed_at'] = datetime.utcnow().isoformat()
            cleanup_results['status'] = 'completed' if not cleanup_results['errors'] else 'partial'
            
            logger.info("Infrastructure cleanup completed",
                       status=cleanup_results['status'],
                       errors_count=len(cleanup_results['errors']))
            
            return cleanup_results
            
        except Exception as e:
            logger.error("Failed to cleanup infrastructure", error=str(e))
            cleanup_results['errors'].append(f"General cleanup error: {str(e)}")
            cleanup_results['status'] = 'failed'
            return cleanup_results


# Convenience functions for easy access
def setup_knowledge_base_infrastructure() -> Dict[str, Any]:
    """Convenience function to set up complete knowledge base infrastructure"""
    manager = BedrockKnowledgeBaseManager()
    return manager.setup_complete_infrastructure()


def get_knowledge_base_status() -> Dict[str, Any]:
    """Convenience function to get knowledge base infrastructure status"""
    manager = BedrockKnowledgeBaseManager()
    return manager.get_infrastructure_status()


def validate_knowledge_base_setup() -> Dict[str, Any]:
    """Convenience function to validate knowledge base setup"""
    manager = BedrockKnowledgeBaseManager()
    return manager.validate_infrastructure()

