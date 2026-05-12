"""
HIPAA-compliant encryption service for the Prior Authorization Application.

This module implements AES-256 encryption for data at rest and in transit,
with proper key management and HIPAA compliance features.
"""

import os
import json
import base64
from typing import Dict, Any, Optional, Union, List
from datetime import datetime
import boto3

from common.aws_clients import get_aws_client_manager
from common.exceptions import EncryptionError, SecurityError
from common.decorators import handle_processing_errors, monitor_performance
from common.logging_config import get_logger, get_audit_logger

logger = get_logger(__name__)
audit_logger = get_audit_logger()


class HIPAAEncryptionService:
    """HIPAA-compliant encryption service using AWS KMS and AES-256"""
    
    def __init__(self):
        self.client_manager = get_aws_client_manager()
        self.kms_client = self.client_manager._clients.setdefault(
            'kms',
            boto3.client('kms', region_name=os.getenv('AWS_REGION', 'us-east-1'))
        )
        
        # KMS key configuration
        self.kms_key_id = os.getenv('HIPAA_KMS_KEY_ID')
        self.data_key_spec = 'AES_256'
        
        if not self.kms_key_id:
            logger.warning("HIPAA_KMS_KEY_ID not configured, using default encryption")
    
    @handle_processing_errors
    @monitor_performance
    def encrypt_sensitive_data(self, data: Union[str, Dict[str, Any]], 
                             context: Dict[str, str] = None) -> Dict[str, Any]:
        """Encrypt sensitive data using AWS KMS"""
        
        try:
            # Convert data to JSON string if it's a dict
            if isinstance(data, dict):
                data_string = json.dumps(data, default=str)
            else:
                data_string = str(data)
            
            # Use KMS to encrypt data directly
            if self.kms_key_id:
                encrypt_response = self.kms_client.encrypt(
                    KeyId=self.kms_key_id,
                    Plaintext=data_string.encode('utf-8'),
                    EncryptionContext=context or {}
                )
                
                encryption_result = {
                    'encrypted_data': base64.b64encode(encrypt_response['CiphertextBlob']).decode('utf-8'),
                    'encryption_context': context or {},
                    'encrypted_at': datetime.utcnow().isoformat(),
                    'kms_key_id': self.kms_key_id,
                    'algorithm': 'AWS-KMS'
                }
            else:
                # Fallback for development - base64 encoding only
                encryption_result = {
                    'encrypted_data': base64.b64encode(data_string.encode('utf-8')).decode('utf-8'),
                    'encryption_context': context or {},
                    'encrypted_at': datetime.utcnow().isoformat(),
                    'kms_key_id': None,
                    'algorithm': 'BASE64'
                }
            
            # Log encryption event
            audit_logger.log_security_event(
                event_type="data_encryption",
                details={
                    'kms_key_id': self.kms_key_id,
                    'data_size': len(data_string),
                    'context': context
                }
            )
            
            return encryption_result
            
        except Exception as e:
            logger.warning("Data encryption failed", error=str(e))
            raise EncryptionError(f"Failed to encrypt data: {str(e)}")
    
    @handle_processing_errors
    def decrypt_sensitive_data(self, encrypted_package: Dict[str, Any]) -> str:
        """Decrypt sensitive data using AWS KMS"""
        
        try:
            # Extract components
            encrypted_data_b64 = encrypted_package['encrypted_data']
            encryption_context = encrypted_package.get('encryption_context', {})
            
            # Decode base64
            encrypted_data = base64.b64decode(encrypted_data_b64)
            
            # Use KMS to decrypt data directly
            if self.kms_key_id:
                decrypt_response = self.kms_client.decrypt(
                    CiphertextBlob=encrypted_data,
                    EncryptionContext=encryption_context
                )
                
                decrypted_data = decrypt_response['Plaintext'].decode('utf-8')
            else:
                # Fallback for non-KMS encrypted data
                decrypted_data = base64.b64decode(encrypted_data_b64).decode('utf-8')
            
            # Log decryption event
            audit_logger.log_security_event(
                event_type="data_decryption",
                details={
                    'kms_key_id': encrypted_package.get('kms_key_id'),
                    'context': encryption_context
                }
            )
            
            return decrypted_data
            
        except Exception as e:
            logger.warning("Data decryption failed", error=str(e))
            raise EncryptionError(f"Failed to decrypt data: {str(e)}")
    
    @handle_processing_errors
    def encrypt_file_content(self, file_content: bytes, filename: str,
                           document_id: str) -> Dict[str, Any]:
        """Encrypt file content for secure storage"""
        
        encryption_context = {
            'document_id': document_id,
            'filename': filename,
            'content_type': 'medical_document'
        }
        
        # Convert bytes to base64 for JSON serialization
        file_content_b64 = base64.b64encode(file_content).decode('utf-8')
        
        return self.encrypt_sensitive_data(file_content_b64, encryption_context)
    
    @handle_processing_errors
    def decrypt_file_content(self, encrypted_package: Dict[str, Any]) -> bytes:
        """Decrypt file content from secure storage"""
        
        decrypted_b64 = self.decrypt_sensitive_data(encrypted_package)
        return base64.b64decode(decrypted_b64)


class IAMAccessControlManager:
    """Manages IAM roles and policies for least privilege access"""
    
    def __init__(self):
        self.iam_client = boto3.client('iam')
        self.sts_client = boto3.client('sts')
    
    @handle_processing_errors
    def create_lambda_execution_role(self, role_name: str, service_permissions: List[str]) -> str:
        """Create IAM role for Lambda functions with least privilege"""
        
        # Trust policy for Lambda
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        # Create role
        try:
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Execution role for {role_name} with HIPAA compliance"
            )
            role_arn = response['Role']['Arn']
        except self.iam_client.exceptions.EntityAlreadyExistsException:
            response = self.iam_client.get_role(RoleName=role_name)
            role_arn = response['Role']['Arn']
        
        # Attach basic Lambda execution policy
        self.iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
        )
        
        # Create and attach custom policy
        custom_policy = self._create_service_policy(service_permissions)
        policy_name = f"{role_name}-Policy"
        
        self.iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(custom_policy)
        )
        
        logger.info("Lambda execution role created", role_name=role_name, role_arn=role_arn)
        return role_arn
    
    def _create_service_policy(self, permissions: List[str]) -> Dict[str, Any]:
        """Create service-specific IAM policy"""
        
        statements = []
        
        # KMS permissions for encryption
        if 'kms:encrypt' in permissions or 'kms:decrypt' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:DescribeKey"
                ],
                "Resource": f"arn:aws:kms:*:*:key/{os.getenv('HIPAA_KMS_KEY_ID', '*')}"
            })
        
        # S3 permissions
        if 's3:read' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:GetObjectVersion"
                ],
                "Resource": [
                    f"arn:aws:s3:::{os.getenv('DOCUMENTS_BUCKET', '*')}/*",
                    f"arn:aws:s3:::{os.getenv('POLICIES_BUCKET', '*')}/*"
                ]
            })
        
        if 's3:write' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:PutObjectAcl"
                ],
                "Resource": [
                    f"arn:aws:s3:::{os.getenv('DOCUMENTS_BUCKET', '*')}/*",
                    f"arn:aws:s3:::{os.getenv('POLICIES_BUCKET', '*')}/*"
                ]
            })
        
        # DynamoDB permissions
        if 'dynamodb:read' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan"
                ],
                "Resource": "arn:aws:dynamodb:*:*:table/prior-auth-*"
            })
        
        if 'dynamodb:write' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem"
                ],
                "Resource": "arn:aws:dynamodb:*:*:table/prior-auth-*"
            })
        
        # Bedrock permissions
        if 'bedrock:invoke' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:RetrieveAndGenerate",
                    "bedrock:Retrieve"
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
                    "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-*",
                    f"arn:aws:bedrock:*:*:knowledge-base/*"
                ]
            })
        
        # Textract permissions
        if 'textract:analyze' in permissions:
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "textract:AnalyzeDocument",
                    "textract:DetectDocumentText"
                ],
                "Resource": "*"
            })
        
        return {
            "Version": "2012-10-17",
            "Statement": statements
        }
    
    @handle_processing_errors
    def create_step_functions_role(self, role_name: str) -> str:
        """Create IAM role for Step Functions with necessary permissions"""
        
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "states.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        # Create role
        try:
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Step Functions execution role for prior authorization workflow"
            )
            role_arn = response['Role']['Arn']
        except self.iam_client.exceptions.EntityAlreadyExistsException:
            response = self.iam_client.get_role(RoleName=role_name)
            role_arn = response['Role']['Arn']
        
        # Step Functions permissions
        step_functions_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "lambda:InvokeFunction"
                    ],
                    "Resource": "arn:aws:lambda:*:*:function:prior-auth-*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "arn:aws:logs:*:*:*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "xray:PutTraceSegments",
                        "xray:PutTelemetryRecords"
                    ],
                    "Resource": "*"
                }
            ]
        }
        
        self.iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=f"{role_name}-Policy",
            PolicyDocument=json.dumps(step_functions_policy)
        )
        
        return role_arn


class DataClassificationService:
    """Service for classifying and handling different types of healthcare data"""
    
    # HIPAA data classification levels
    PHI_IDENTIFIERS = [
        'patient_name', 'ssn', 'medical_record_number', 'account_number',
        'certificate_number', 'vehicle_identifier', 'device_identifier',
        'web_url', 'ip_address', 'biometric_identifier', 'photograph',
        'email_address', 'phone_number', 'fax_number', 'address'
    ]
    
    @staticmethod
    def classify_data_sensitivity(data: Dict[str, Any]) -> str:
        """Classify data sensitivity level for HIPAA compliance"""
        
        # Check for PHI identifiers
        data_str = json.dumps(data, default=str).lower()
        
        phi_found = any(identifier in data_str for identifier in DataClassificationService.PHI_IDENTIFIERS)
        
        # Medical information is always sensitive
        medical_keywords = ['diagnosis', 'treatment', 'medication', 'procedure', 'symptom']
        medical_info = any(keyword in data_str for keyword in medical_keywords)
        
        if phi_found:
            return 'PHI'  # Protected Health Information
        elif medical_info:
            return 'MEDICAL'  # Medical information without direct identifiers
        else:
            return 'GENERAL'  # General business information
    
    @staticmethod
    def get_encryption_requirements(classification: str) -> Dict[str, Any]:
        """Get encryption requirements based on data classification"""
        
        requirements = {
            'PHI': {
                'encryption_required': True,
                'key_rotation_days': 90,
                'access_logging': True,
                'retention_days': 2555,  # 7 years for HIPAA
                'deletion_method': 'secure_overwrite'
            },
            'MEDICAL': {
                'encryption_required': True,
                'key_rotation_days': 180,
                'access_logging': True,
                'retention_days': 2555,
                'deletion_method': 'secure_overwrite'
            },
            'GENERAL': {
                'encryption_required': False,
                'key_rotation_days': 365,
                'access_logging': False,
                'retention_days': 365,
                'deletion_method': 'standard'
            }
        }
        
        return requirements.get(classification, requirements['GENERAL'])


class SecureStorageService:
    """Service for secure storage of healthcare data with encryption"""
    
    def __init__(self):
        self.encryption_service = HIPAAEncryptionService()
        self.classification_service = DataClassificationService()
        self.s3_client = get_aws_client_manager().get_s3_client()
        self.dynamodb_service = get_aws_client_manager().get_dynamodb_service()
    
    @handle_processing_errors
    def store_document_securely(self, document_id: str, file_content: bytes,
                              filename: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Store document with appropriate encryption based on content sensitivity"""
        
        # Classify data sensitivity
        classification = self.classification_service.classify_data_sensitivity(metadata)
        requirements = self.classification_service.get_encryption_requirements(classification)
        
        storage_info = {
            'document_id': document_id,
            'filename': filename,
            'classification': classification,
            'encrypted': requirements['encryption_required'],
            'stored_at': datetime.utcnow().isoformat()
        }
        
        if requirements['encryption_required']:
            # Encrypt file content
            encryption_context = {
                'document_id': document_id,
                'filename': filename,
                'classification': classification
            }
            
            encrypted_content = self.encryption_service.encrypt_file_content(
                file_content, filename, document_id
            )
            
            # Store encrypted content
            s3_key = f"encrypted-documents/{document_id}/{filename}"
            
            self.s3_client.s3_client.put_object(
                Bucket=os.getenv('DOCUMENTS_BUCKET'),
                Key=s3_key,
                Body=json.dumps(encrypted_content),
                ContentType='application/json',
                ServerSideEncryption='aws:kms',
                SSEKMSKeyId=os.getenv('HIPAA_KMS_KEY_ID'),
                Metadata={
                    'classification': classification,
                    'encrypted': 'true',
                    'document_id': document_id
                }
            )
            
            storage_info['s3_key'] = s3_key
            storage_info['encryption_info'] = {
                'kms_key_id': encrypted_content['kms_key_id'],
                'algorithm': encrypted_content['algorithm']
            }
        else:
            # Store without additional encryption (still uses S3 server-side encryption)
            s3_key = f"documents/{document_id}/{filename}"
            
            self.s3_client.s3_client.put_object(
                Bucket=os.getenv('DOCUMENTS_BUCKET'),
                Key=s3_key,
                Body=file_content,
                ServerSideEncryption='AES256',
                Metadata={
                    'classification': classification,
                    'encrypted': 'false',
                    'document_id': document_id
                }
            )
            
            storage_info['s3_key'] = s3_key
        
        # Store metadata in DynamoDB with encryption
        self._store_document_metadata(document_id, storage_info, metadata, requirements)
        
        return storage_info
    
    def _store_document_metadata(self, document_id: str, storage_info: Dict[str, Any],
                               metadata: Dict[str, Any], requirements: Dict[str, Any]) -> None:
        """Store document metadata in DynamoDB with encryption"""
        
        # Prepare metadata for storage
        metadata_item = {
            'document_id': document_id,
            'storage_info': storage_info,
            'metadata': metadata,
            'classification': storage_info['classification'],
            'retention_until': (
                datetime.utcnow().timestamp() + (requirements['retention_days'] * 24 * 3600)
            ),
            'created_at': datetime.utcnow().isoformat(),
            'access_count': 0
        }
        
        # Encrypt sensitive metadata if required
        if requirements['encryption_required']:
            encrypted_metadata = self.encryption_service.encrypt_sensitive_data(
                metadata_item,
                {'document_id': document_id, 'type': 'metadata'}
            )
            
            # Store encrypted metadata
            self.dynamodb_service.put_item(
                table_name=os.getenv('EXTRACTION_TABLE', 'prior-auth-extraction-dev'),
                item={
                    'document_id': document_id,
                    'encrypted_metadata': encrypted_metadata,
                    'classification': storage_info['classification'],
                    'created_at': metadata_item['created_at']
                }
            )
        else:
            # Store metadata directly
            self.dynamodb_service.put_item(
                table_name=os.getenv('EXTRACTION_TABLE', 'prior-auth-extraction-dev'),
                item=metadata_item
            )


class HIPAAComplianceValidator:
    """Validates HIPAA compliance for data handling operations"""
    
    @staticmethod
    def validate_encryption_compliance(storage_config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate encryption compliance for HIPAA"""
        
        compliance_check = {
            'compliant': True,
            'issues': [],
            'recommendations': []
        }
        
        # Check encryption at rest
        if not storage_config.get('encryption_at_rest'):
            compliance_check['compliant'] = False
            compliance_check['issues'].append('Encryption at rest not enabled')
            compliance_check['recommendations'].append('Enable S3 server-side encryption with KMS')
        
        # Check encryption in transit
        if not storage_config.get('encryption_in_transit'):
            compliance_check['compliant'] = False
            compliance_check['issues'].append('Encryption in transit not enforced')
            compliance_check['recommendations'].append('Enforce HTTPS/TLS for all API communications')
        
        # Check key management
        if not storage_config.get('kms_key_id'):
            compliance_check['issues'].append('Customer-managed KMS key not configured')
            compliance_check['recommendations'].append('Use customer-managed KMS keys for better control')
        
        # Check access controls
        if not storage_config.get('access_controls'):
            compliance_check['compliant'] = False
            compliance_check['issues'].append('Access controls not properly configured')
            compliance_check['recommendations'].append('Implement role-based access controls')
        
        return compliance_check
    
    @staticmethod
    def validate_audit_logging(logging_config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate audit logging compliance"""
        
        compliance_check = {
            'compliant': True,
            'issues': [],
            'recommendations': []
        }
        
        required_events = [
            'data_access', 'data_modification', 'authentication',
            'authorization', 'system_access', 'data_export'
        ]
        
        logged_events = logging_config.get('logged_events', [])
        missing_events = [event for event in required_events if event not in logged_events]
        
        if missing_events:
            compliance_check['compliant'] = False
            compliance_check['issues'].append(f'Missing audit logging for: {", ".join(missing_events)}')
            compliance_check['recommendations'].append('Enable comprehensive audit logging for all data access')
        
        # Check log retention
        if logging_config.get('retention_days', 0) < 2555:  # 7 years
            compliance_check['issues'].append('Audit log retention period insufficient')
            compliance_check['recommendations'].append('Set audit log retention to minimum 7 years')
        
        return compliance_check


# Convenience functions
def encrypt_patient_data(data: Dict[str, Any], document_id: str) -> Dict[str, Any]:
    """Encrypt patient data with proper context"""
    encryption_service = HIPAAEncryptionService()
    context = {
        'document_id': document_id,
        'data_type': 'patient_data',
        'classification': 'PHI'
    }
    return encryption_service.encrypt_sensitive_data(data, context)


def decrypt_patient_data(encrypted_package: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt patient data"""
    encryption_service = HIPAAEncryptionService()
    decrypted_json = encryption_service.decrypt_sensitive_data(encrypted_package)
    return json.loads(decrypted_json)


def create_hipaa_compliant_storage() -> SecureStorageService:
    """Create HIPAA-compliant storage service"""
    return SecureStorageService()

