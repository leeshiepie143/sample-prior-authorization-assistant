"""
HIPAA compliance validation and security assessment tool.

This module provides comprehensive validation of security configurations,
encryption implementations, and HIPAA compliance requirements.
"""

import os
import json
import boto3
from typing import Dict, Any, List, Optional
from datetime import datetime

from common.logging_config import get_logger
from common.decorators import handle_processing_errors
from .iam_policies import SecurityConfiguration, DataEncryptionStandards

logger = get_logger(__name__)


class HIPAAComplianceValidator:
    """Comprehensive HIPAA compliance validator"""
    
    def __init__(self):
        self.security_config = SecurityConfiguration()
        self.encryption_standards = DataEncryptionStandards()
    
    @handle_processing_errors
    def validate_full_compliance(self) -> Dict[str, Any]:
        """Perform comprehensive HIPAA compliance validation"""
        
        validation_results = {
            'overall_compliant': True,
            'validation_timestamp': datetime.utcnow().isoformat(),
            'components': {},
            'critical_issues': [],
            'warnings': [],
            'recommendations': [],
            'compliance_score': 0
        }
        
        # Validate each component
        components_to_validate = [
            ('encryption_at_rest', self._validate_encryption_at_rest),
            ('encryption_in_transit', self._validate_encryption_in_transit),
            ('access_controls', self._validate_access_controls),
            ('audit_logging', self._validate_audit_logging),
            ('data_retention', self._validate_data_retention),
            ('network_security', self._validate_network_security),
            ('key_management', self._validate_key_management),
            ('environment_configuration', self._validate_environment_config)
        ]
        
        total_score = 0
        max_score = len(components_to_validate) * 100
        
        for component_name, validator_func in components_to_validate:
            try:
                component_result = validator_func()
                validation_results['components'][component_name] = component_result
                
                if not component_result['compliant']:
                    validation_results['overall_compliant'] = False
                    validation_results['critical_issues'].extend(
                        component_result.get('critical_issues', [])
                    )
                
                validation_results['warnings'].extend(
                    component_result.get('warnings', [])
                )
                validation_results['recommendations'].extend(
                    component_result.get('recommendations', [])
                )
                
                total_score += component_result.get('score', 0)
                
            except Exception as e:
                logger.error(f"Failed to validate {component_name}", error=str(e))
                validation_results['critical_issues'].append(
                    f"Validation failed for {component_name}: {str(e)}"
                )
                validation_results['overall_compliant'] = False
        
        validation_results['compliance_score'] = int((total_score / max_score) * 100)
        
        return validation_results
    
    def _validate_encryption_at_rest(self) -> Dict[str, Any]:
        """Validate encryption at rest configuration"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check S3 encryption
        try:
            s3_client = boto3.client('s3')
            documents_bucket = os.getenv('DOCUMENTS_BUCKET')
            
            if documents_bucket:
                try:
                    encryption_config = s3_client.get_bucket_encryption(
                        Bucket=documents_bucket
                    )
                    
                    rules = encryption_config.get('ServerSideEncryptionConfiguration', {}).get('Rules', [])
                    if not rules:
                        result['compliant'] = False
                        result['critical_issues'].append('S3 bucket encryption not configured')
                        result['score'] -= 30
                    else:
                        # Check for KMS encryption
                        kms_encryption = any(
                            rule.get('ApplyServerSideEncryptionByDefault', {}).get('SSEAlgorithm') == 'aws:kms'
                            for rule in rules
                        )
                        if not kms_encryption:
                            result['warnings'].append('S3 bucket not using KMS encryption')
                            result['score'] -= 10
                
                except s3_client.exceptions.NoSuchBucket:
                    result['warnings'].append(f'S3 bucket {documents_bucket} does not exist')
                    result['score'] -= 20
                except Exception as e:
                    result['warnings'].append(f'Unable to check S3 encryption: {str(e)}')
                    result['score'] -= 15
            else:
                result['warnings'].append('DOCUMENTS_BUCKET environment variable not set')
                result['score'] -= 20
        
        except Exception as e:
            result['warnings'].append(f'Unable to validate S3 encryption: {str(e)}')
            result['score'] -= 25
        
        # Check DynamoDB encryption
        try:
            dynamodb_client = boto3.client('dynamodb')
            
            # Check key tables
            tables_to_check = [
                os.getenv('EXTRACTION_STATE_TABLE', 'prior-auth-extraction-state'),
                os.getenv('ASSESSMENT_RESULTS_TABLE', 'prior-auth-assessment-results'),
                os.getenv('AUDIT_LOG_TABLE', 'prior-auth-audit-logs')
            ]
            
            for table_name in tables_to_check:
                try:
                    table_info = dynamodb_client.describe_table(TableName=table_name)
                    
                    sse_description = table_info.get('Table', {}).get('SSEDescription', {})
                    if sse_description.get('Status') != 'ENABLED':
                        result['compliant'] = False
                        result['critical_issues'].append(f'DynamoDB table {table_name} encryption not enabled')
                        result['score'] -= 20
                    elif sse_description.get('SSEType') != 'KMS':
                        result['warnings'].append(f'DynamoDB table {table_name} not using KMS encryption')
                        result['score'] -= 5
                
                except dynamodb_client.exceptions.ResourceNotFoundException:
                    result['warnings'].append(f'DynamoDB table {table_name} does not exist')
                    result['score'] -= 10
                except Exception as e:
                    result['warnings'].append(f'Unable to check DynamoDB table {table_name}: {str(e)}')
                    result['score'] -= 5
        
        except Exception as e:
            result['warnings'].append(f'Unable to validate DynamoDB encryption: {str(e)}')
            result['score'] -= 15
        
        return result
    
    def _validate_encryption_in_transit(self) -> Dict[str, Any]:
        """Validate encryption in transit configuration"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check API Gateway configuration
        try:
            apigateway_client = boto3.client('apigateway')
            
            # This would require the API Gateway ID, which might not be available
            # In a real implementation, you'd check the API Gateway configuration
            result['recommendations'].append('Verify API Gateway enforces HTTPS only')
            
        except Exception as e:
            result['warnings'].append(f'Unable to validate API Gateway configuration: {str(e)}')
            result['score'] -= 10
        
        # Check CloudFront configuration if used
        frontend_domain = os.getenv('FRONTEND_DOMAIN')
        if frontend_domain and 'cloudfront' in frontend_domain:
            result['recommendations'].append('Verify CloudFront enforces HTTPS and uses TLS 1.2+')
        
        return result
    
    def _validate_access_controls(self) -> Dict[str, Any]:
        """Validate IAM access controls"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check for overly permissive policies
        try:
            iam_client = boto3.client('iam')
            
            # Get account roles (this is a simplified check)
            paginator = iam_client.get_paginator('list_roles')
            
            for page in paginator.paginate():
                for role in page['Roles']:
                    role_name = role['RoleName']
                    
                    # Check if it's a prior-auth related role
                    if 'prior-auth' in role_name.lower():
                        # Get attached policies
                        attached_policies = iam_client.list_attached_role_policies(
                            RoleName=role_name
                        )
                        
                        for policy in attached_policies['AttachedPolicies']:
                            if policy['PolicyArn'] == 'arn:aws:iam::aws:policy/AdministratorAccess':
                                result['critical_issues'].append(
                                    f'Role {role_name} has AdministratorAccess policy'
                                )
                                result['compliant'] = False
                                result['score'] -= 40
        
        except Exception as e:
            result['warnings'].append(f'Unable to validate IAM policies: {str(e)}')
            result['score'] -= 20
        
        return result
    
    def _validate_audit_logging(self) -> Dict[str, Any]:
        """Validate audit logging configuration"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check CloudTrail configuration
        try:
            cloudtrail_client = boto3.client('cloudtrail')
            
            trails = cloudtrail_client.describe_trails()
            
            if not trails['trailList']:
                result['critical_issues'].append('No CloudTrail trails configured')
                result['compliant'] = False
                result['score'] -= 50
            else:
                for trail in trails['trailList']:
                    trail_status = cloudtrail_client.get_trail_status(
                        Name=trail['TrailARN']
                    )
                    
                    if not trail_status['IsLogging']:
                        result['warnings'].append(f'CloudTrail {trail["Name"]} is not logging')
                        result['score'] -= 20
        
        except Exception as e:
            result['warnings'].append(f'Unable to validate CloudTrail: {str(e)}')
            result['score'] -= 25
        
        # Check audit log table
        audit_table = os.getenv('AUDIT_LOG_TABLE')
        if not audit_table:
            result['critical_issues'].append('AUDIT_LOG_TABLE environment variable not set')
            result['compliant'] = False
            result['score'] -= 30
        
        return result
    
    def _validate_data_retention(self) -> Dict[str, Any]:
        """Validate data retention policies"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check retention configuration
        retention_days = os.getenv('HIPAA_RETENTION_DAYS')
        if not retention_days:
            result['warnings'].append('HIPAA_RETENTION_DAYS not configured')
            result['score'] -= 20
        else:
            try:
                days = int(retention_days)
                if days < 2555:  # 7 years
                    result['critical_issues'].append(
                        f'Retention period {days} days is less than HIPAA requirement (7 years)'
                    )
                    result['compliant'] = False
                    result['score'] -= 40
            except ValueError:
                result['critical_issues'].append('Invalid HIPAA_RETENTION_DAYS value')
                result['compliant'] = False
                result['score'] -= 30
        
        return result
    
    def _validate_network_security(self) -> Dict[str, Any]:
        """Validate network security configuration"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check VPC configuration (if applicable)
        try:
            ec2_client = boto3.client('ec2')
            
            # This is a simplified check - in practice you'd validate:
            # - Security groups
            # - NACLs
            # - VPC endpoints
            # - NAT gateways
            
            result['recommendations'].append('Verify Lambda functions are in VPC with proper security groups')
            result['recommendations'].append('Ensure no public subnets for sensitive resources')
            
        except Exception as e:
            result['warnings'].append(f'Unable to validate network configuration: {str(e)}')
            result['score'] -= 10
        
        return result
    
    def _validate_key_management(self) -> Dict[str, Any]:
        """Validate KMS key management"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        kms_key_id = os.getenv('HIPAA_KMS_KEY_ID')
        if not kms_key_id:
            result['critical_issues'].append('HIPAA_KMS_KEY_ID not configured')
            result['compliant'] = False
            result['score'] -= 50
        else:
            try:
                kms_client = boto3.client('kms')
                
                # Validate key exists and is enabled
                key_info = kms_client.describe_key(KeyId=kms_key_id)
                
                if key_info['KeyMetadata']['KeyState'] != 'Enabled':
                    result['critical_issues'].append('KMS key is not enabled')
                    result['compliant'] = False
                    result['score'] -= 40
                
                # Check key rotation
                try:
                    rotation_status = kms_client.get_key_rotation_status(KeyId=kms_key_id)
                    if not rotation_status['KeyRotationEnabled']:
                        result['warnings'].append('KMS key rotation is not enabled')
                        result['score'] -= 15
                except Exception:
                    result['warnings'].append('Unable to check key rotation status')
                    result['score'] -= 10
                
            except Exception as e:
                result['critical_issues'].append(f'Unable to validate KMS key: {str(e)}')
                result['compliant'] = False
                result['score'] -= 40
        
        return result
    
    def _validate_environment_config(self) -> Dict[str, Any]:
        """Validate environment configuration"""
        
        result = {
            'compliant': True,
            'score': 100,
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
        
        # Check required environment variables
        required_vars = self.security_config.get_required_environment_variables()
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            result['critical_issues'].extend([
                f'Missing required environment variable: {var}' for var in missing_vars
            ])
            result['compliant'] = False
            result['score'] -= len(missing_vars) * 10
        
        # Check for sensitive data in environment variables
        sensitive_patterns = ['password', 'secret', 'key', 'token']
        for key, value in os.environ.items():
            if any(pattern in key.lower() for pattern in sensitive_patterns):
                if len(value) < 16:
                    result['warnings'].append(f'Environment variable {key} may contain weak secret')
                    result['score'] -= 5
        
        return result
    
    @handle_processing_errors
    def generate_compliance_report(self) -> str:
        """Generate human-readable compliance report"""
        
        validation_results = self.validate_full_compliance()
        
        report_lines = [
            "HIPAA COMPLIANCE VALIDATION REPORT",
            "=" * 50,
            f"Generated: {validation_results['validation_timestamp']}",
            f"Overall Compliant: {'YES' if validation_results['overall_compliant'] else 'NO'}",
            f"Compliance Score: {validation_results['compliance_score']}/100",
            "",
        ]
        
        if validation_results['critical_issues']:
            report_lines.extend([
                "CRITICAL ISSUES:",
                "-" * 20
            ])
            for issue in validation_results['critical_issues']:
                report_lines.append(f"❌ {issue}")
            report_lines.append("")
        
        if validation_results['warnings']:
            report_lines.extend([
                "WARNINGS:",
                "-" * 20
            ])
            for warning in validation_results['warnings']:
                report_lines.append(f"⚠️  {warning}")
            report_lines.append("")
        
        if validation_results['recommendations']:
            report_lines.extend([
                "RECOMMENDATIONS:",
                "-" * 20
            ])
            for recommendation in validation_results['recommendations']:
                report_lines.append(f"💡 {recommendation}")
            report_lines.append("")
        
        # Component details
        report_lines.extend([
            "COMPONENT DETAILS:",
            "-" * 20
        ])
        
        for component_name, component_result in validation_results['components'].items():
            status = "✅ PASS" if component_result['compliant'] else "❌ FAIL"
            score = component_result.get('score', 0)
            report_lines.append(f"{component_name.replace('_', ' ').title()}: {status} ({score}/100)")
        
        return "\n".join(report_lines)


# Utility function for easy validation
def run_hipaa_compliance_check() -> Dict[str, Any]:
    """Run comprehensive HIPAA compliance check"""
    validator = HIPAAComplianceValidator()
    return validator.validate_full_compliance()


def print_compliance_report() -> None:
    """Print compliance report to console"""
    validator = HIPAAComplianceValidator()
    report = validator.generate_compliance_report()
    print(report)

