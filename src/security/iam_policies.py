"""
IAM policies and role definitions for HIPAA-compliant access controls.

This module defines IAM policies with least privilege principles for
all components of the Prior Authorization Application.
"""

import json
import os
from typing import Dict, Any, List
from datetime import datetime

from common.logging_config import get_logger

logger = get_logger(__name__)


class IAMPolicyTemplates:
    """Templates for IAM policies with least privilege access"""
    
    @staticmethod
    def get_lambda_extractor_policy() -> Dict[str, Any]:
        """IAM policy for Medical Records Extractor Lambda"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3DocumentAccess",
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectVersion"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{os.getenv('DOCUMENTS_BUCKET', 'prior-auth-documents')}/*"
                    ]
                },
                {
                    "Sid": "TextractAnalysis",
                    "Effect": "Allow",
                    "Action": [
                        "textract:AnalyzeDocument",
                        "textract:DetectDocumentText"
                    ],
                    "Resource": "*"
                },
                {
                    "Sid": "BedrockInference",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel"
                    ],
                    "Resource": [
                        "arn:aws:bedrock:*::foundation-model/amazon.nova-*"
                    ]
                },
                {
                    "Sid": "DynamoDBStateManagement",
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem",
                        "dynamodb:GetItem"
                    ],
                    "Resource": [
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('EXTRACTION_STATE_TABLE', 'prior-auth-extraction-state')}"
                    ]
                },
                {
                    "Sid": "KMSEncryption",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:DescribeKey"
                    ],
                    "Resource": [
                        f"arn:aws:kms:*:*:key/{os.getenv('HIPAA_KMS_KEY_ID', '*')}"
                    ]
                },
                {
                    "Sid": "CloudWatchLogs",
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "arn:aws:logs:*:*:log-group:/aws/lambda/prior-auth-*"
                }
            ]
        }
    
    @staticmethod
    def get_lambda_knowledge_policy() -> Dict[str, Any]:
        """IAM policy for Payor Policy Knowledge Lambda"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3PolicyAccess",
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectVersion",
                        "s3:ListBucket"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{os.getenv('POLICIES_BUCKET', 'prior-auth-policies')}",
                        f"arn:aws:s3:::{os.getenv('POLICIES_BUCKET', 'prior-auth-policies')}/*"
                    ]
                },
                {
                    "Sid": "BedrockKnowledgeBase",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:Retrieve",
                        "bedrock:RetrieveAndGenerate"
                    ],
                    "Resource": [
                        f"arn:aws:bedrock:*:*:knowledge-base/{os.getenv('KNOWLEDGE_BASE_ID', '*')}"
                    ]
                },
                {
                    "Sid": "BedrockEmbeddings",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel"
                    ],
                    "Resource": [
                        "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-*"
                    ]
                },
                {
                    "Sid": "DynamoDBPolicyMetadata",
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:GetItem",
                        "dynamodb:Query",
                        "dynamodb:Scan",
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem"
                    ],
                    "Resource": [
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('POLICY_METADATA_TABLE', 'prior-auth-policy-metadata')}"
                    ]
                },
                {
                    "Sid": "KMSEncryption",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:DescribeKey"
                    ],
                    "Resource": [
                        f"arn:aws:kms:*:*:key/{os.getenv('HIPAA_KMS_KEY_ID', '*')}"
                    ]
                }
            ]
        }
    
    @staticmethod
    def get_lambda_selector_policy() -> Dict[str, Any]:
        """IAM policy for Policy Selector Lambda"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "BedrockInference",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel",
                        "bedrock:Retrieve",
                        "bedrock:RetrieveAndGenerate"
                    ],
                    "Resource": [
                        "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
                        f"arn:aws:bedrock:*:*:knowledge-base/{os.getenv('KNOWLEDGE_BASE_ID', '*')}"
                    ]
                },
                {
                    "Sid": "DynamoDBAccess",
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:GetItem",
                        "dynamodb:Query",
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem"
                    ],
                    "Resource": [
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('POLICY_SELECTION_TABLE', 'prior-auth-policy-selection')}",
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('POLICY_METADATA_TABLE', 'prior-auth-policy-metadata')}"
                    ]
                },
                {
                    "Sid": "KMSEncryption",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:DescribeKey"
                    ],
                    "Resource": [
                        f"arn:aws:kms:*:*:key/{os.getenv('HIPAA_KMS_KEY_ID', '*')}"
                    ]
                }
            ]
        }
    
    @staticmethod
    def get_lambda_reviewer_policy() -> Dict[str, Any]:
        """IAM policy for Medical Record Reviewer Lambda"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "BedrockInference",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel"
                    ],
                    "Resource": [
                        "arn:aws:bedrock:*::foundation-model/amazon.nova-*"
                    ]
                },
                {
                    "Sid": "S3DocumentAccess",
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectVersion"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{os.getenv('DOCUMENTS_BUCKET', 'prior-auth-documents')}/*"
                    ]
                },
                {
                    "Sid": "DynamoDBAccess",
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:GetItem",
                        "dynamodb:Query",
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem"
                    ],
                    "Resource": [
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('ASSESSMENT_RESULTS_TABLE', 'prior-auth-assessment-results')}",
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('EXTRACTION_STATE_TABLE', 'prior-auth-extraction-state')}"
                    ]
                },
                {
                    "Sid": "KMSEncryption",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:DescribeKey"
                    ],
                    "Resource": [
                        f"arn:aws:kms:*:*:key/{os.getenv('HIPAA_KMS_KEY_ID', '*')}"
                    ]
                }
            ]
        }
    
    @staticmethod
    def get_api_gateway_policy() -> Dict[str, Any]:
        """IAM policy for API Gateway Lambda"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3DocumentUpload",
                    "Effect": "Allow",
                    "Action": [
                        "s3:PutObject",
                        "s3:PutObjectAcl",
                        "s3:GetObject"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{os.getenv('DOCUMENTS_BUCKET', 'prior-auth-documents')}/*"
                    ]
                },
                {
                    "Sid": "StepFunctionsExecution",
                    "Effect": "Allow",
                    "Action": [
                        "states:StartExecution",
                        "states:DescribeExecution",
                        "states:GetExecutionHistory"
                    ],
                    "Resource": [
                        f"arn:aws:states:*:*:stateMachine:{os.getenv('WORKFLOW_STATE_MACHINE', 'prior-auth-workflow')}",
                        f"arn:aws:states:*:*:execution:{os.getenv('WORKFLOW_STATE_MACHINE', 'prior-auth-workflow')}:*"
                    ]
                },
                {
                    "Sid": "DynamoDBAccess",
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:GetItem",
                        "dynamodb:Query",
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem"
                    ],
                    "Resource": [
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('ASSESSMENT_RESULTS_TABLE', 'prior-auth-assessment-results')}",
                        f"arn:aws:dynamodb:*:*:table/{os.getenv('AUDIT_LOG_TABLE', 'prior-auth-audit-logs')}"
                    ]
                },
                {
                    "Sid": "KMSEncryption",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:DescribeKey"
                    ],
                    "Resource": [
                        f"arn:aws:kms:*:*:key/{os.getenv('HIPAA_KMS_KEY_ID', '*')}"
                    ]
                }
            ]
        }
    
    @staticmethod
    def get_step_functions_policy() -> Dict[str, Any]:
        """IAM policy for Step Functions state machine"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "LambdaInvocation",
                    "Effect": "Allow",
                    "Action": [
                        "lambda:InvokeFunction"
                    ],
                    "Resource": [
                        f"arn:aws:lambda:*:*:function:{os.getenv('EXTRACTOR_FUNCTION_NAME', 'prior-auth-extractor')}",
                        f"arn:aws:lambda:*:*:function:{os.getenv('KNOWLEDGE_FUNCTION_NAME', 'prior-auth-knowledge')}",
                        f"arn:aws:lambda:*:*:function:{os.getenv('SELECTOR_FUNCTION_NAME', 'prior-auth-selector')}",
                        f"arn:aws:lambda:*:*:function:{os.getenv('REVIEWER_FUNCTION_NAME', 'prior-auth-reviewer')}"
                    ]
                },
                {
                    "Sid": "CloudWatchLogs",
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "arn:aws:logs:*:*:log-group:/aws/stepfunctions/*"
                },
                {
                    "Sid": "XRayTracing",
                    "Effect": "Allow",
                    "Action": [
                        "xray:PutTraceSegments",
                        "xray:PutTelemetryRecords"
                    ],
                    "Resource": "*"
                }
            ]
        }


class SecurityConfiguration:
    """Security configuration and validation for HIPAA compliance"""
    
    @staticmethod
    def get_required_environment_variables() -> List[str]:
        """Get list of required environment variables for security"""
        return [
            'HIPAA_KMS_KEY_ID',
            'DOCUMENTS_BUCKET',
            'POLICIES_BUCKET',
            'AUDIT_LOG_TABLE',
            'ENCRYPTION_KEY_ROTATION_DAYS'
        ]
    
    @staticmethod
    def validate_security_configuration() -> Dict[str, Any]:
        """Validate security configuration for HIPAA compliance"""
        
        validation_result = {
            'valid': True,
            'issues': [],
            'warnings': []
        }
        
        # Check required environment variables
        required_vars = SecurityConfiguration.get_required_environment_variables()
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            validation_result['valid'] = False
            validation_result['issues'].extend([
                f"Missing required environment variable: {var}" for var in missing_vars
            ])
        
        # Check KMS key configuration
        kms_key_id = os.getenv('HIPAA_KMS_KEY_ID')
        if kms_key_id and not kms_key_id.startswith('arn:aws:kms:'):
            validation_result['warnings'].append(
                "KMS key should be specified as full ARN for better security"
            )
        
        # Check encryption settings
        encryption_rotation = os.getenv('ENCRYPTION_KEY_ROTATION_DAYS', '90')
        try:
            rotation_days = int(encryption_rotation)
            if rotation_days > 365:
                validation_result['warnings'].append(
                    "Key rotation period exceeds recommended 365 days"
                )
        except ValueError:
            validation_result['issues'].append(
                "Invalid ENCRYPTION_KEY_ROTATION_DAYS value"
            )
        
        # Check S3 bucket configuration
        documents_bucket = os.getenv('DOCUMENTS_BUCKET')
        if documents_bucket and not documents_bucket.startswith('prior-auth-'):
            validation_result['warnings'].append(
                "Document bucket should follow naming convention 'prior-auth-*'"
            )
        
        return validation_result
    
    @staticmethod
    def get_security_headers() -> Dict[str, str]:
        """Get required security headers for API responses"""
        return {
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Content-Security-Policy': "default-src 'self'",
            'Referrer-Policy': 'strict-origin-when-cross-origin'
        }
    
    @staticmethod
    def get_cors_configuration() -> Dict[str, Any]:
        """Get CORS configuration for API Gateway"""
        return {
            'AllowOrigins': [
                os.getenv('FRONTEND_DOMAIN', 'https://localhost:3000')
            ],
            'AllowMethods': ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
            'AllowHeaders': [
                'Content-Type',
                'Authorization',
                'X-Amz-Date',
                'X-Api-Key',
                'X-Amz-Security-Token'
            ],
            'ExposeHeaders': ['X-Request-ID'],
            'MaxAge': 86400,  # 24 hours
            'AllowCredentials': True
        }


class DataEncryptionStandards:
    """Data encryption standards and requirements"""
    
    # HIPAA encryption requirements
    ENCRYPTION_STANDARDS = {
        'at_rest': {
            'algorithm': 'AES-256',
            'key_management': 'AWS KMS',
            'key_rotation': 90,  # days
            'required': True
        },
        'in_transit': {
            'protocol': 'TLS 1.2+',
            'cipher_suites': [
                'TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384',
                'TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256'
            ],
            'required': True
        },
        'application_level': {
            'algorithm': 'AES-256-GCM',
            'key_derivation': 'PBKDF2',
            'iterations': 100000,
            'required_for_phi': True
        }
    }
    
    @staticmethod
    def get_encryption_requirements(data_classification: str) -> Dict[str, Any]:
        """Get encryption requirements based on data classification"""
        
        base_requirements = {
            'encryption_required': False,
            'key_rotation_days': 365,
            'audit_required': False,
            'secure_deletion': False
        }
        
        if data_classification in ['PHI', 'MEDICAL']:
            base_requirements.update({
                'encryption_required': True,
                'key_rotation_days': 90,
                'audit_required': True,
                'secure_deletion': True,
                'algorithm': 'AES-256',
                'key_management': 'AWS KMS'
            })
        
        return base_requirements
    
    @staticmethod
    def validate_encryption_implementation(config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate encryption implementation against standards"""
        
        validation = {
            'compliant': True,
            'issues': [],
            'score': 100
        }
        
        # Check at-rest encryption
        if not config.get('s3_encryption_enabled'):
            validation['compliant'] = False
            validation['issues'].append('S3 encryption not enabled')
            validation['score'] -= 25
        
        if not config.get('dynamodb_encryption_enabled'):
            validation['compliant'] = False
            validation['issues'].append('DynamoDB encryption not enabled')
            validation['score'] -= 25
        
        # Check in-transit encryption
        if not config.get('api_https_only'):
            validation['compliant'] = False
            validation['issues'].append('HTTPS not enforced for API')
            validation['score'] -= 25
        
        # Check key management
        if not config.get('kms_customer_managed_keys'):
            validation['issues'].append('Customer-managed KMS keys recommended')
            validation['score'] -= 10
        
        # Check key rotation
        rotation_days = config.get('key_rotation_days', 365)
        if rotation_days > 90:
            validation['issues'].append('Key rotation period exceeds HIPAA recommendation')
            validation['score'] -= 15
        
        return validation


# Utility functions for policy management
def generate_lambda_role_policy(function_type: str) -> Dict[str, Any]:
    """Generate IAM policy for specific Lambda function type"""
    
    policy_map = {
        'extractor': IAMPolicyTemplates.get_lambda_extractor_policy,
        'knowledge': IAMPolicyTemplates.get_lambda_knowledge_policy,
        'selector': IAMPolicyTemplates.get_lambda_selector_policy,
        'reviewer': IAMPolicyTemplates.get_lambda_reviewer_policy,
        'api_gateway': IAMPolicyTemplates.get_api_gateway_policy
    }
    
    policy_generator = policy_map.get(function_type)
    if not policy_generator:
        raise ValueError(f"Unknown function type: {function_type}")
    
    return policy_generator()


def validate_hipaa_compliance() -> Dict[str, Any]:
    """Validate overall HIPAA compliance configuration"""
    
    security_validation = SecurityConfiguration.validate_security_configuration()
    
    # Additional compliance checks
    compliance_result = {
        'overall_compliant': security_validation['valid'],
        'security_configuration': security_validation,
        'encryption_standards': DataEncryptionStandards.ENCRYPTION_STANDARDS,
        'recommendations': []
    }
    
    if not security_validation['valid']:
        compliance_result['recommendations'].append(
            "Fix security configuration issues before deployment"
        )
    
    if security_validation['warnings']:
        compliance_result['recommendations'].extend([
            f"Address warning: {warning}" for warning in security_validation['warnings']
        ])
    
    return compliance_result

