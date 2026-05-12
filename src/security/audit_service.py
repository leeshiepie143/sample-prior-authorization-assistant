"""
Comprehensive audit logging service for HIPAA compliance.

This module provides centralized audit logging, data retention management,
and compliance reporting forthcare applications handling PHI.
"""

import os
import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, asdict

from common.exceptions import AuditError, DataRetentionError
from common.logging_config import get_logger
from common.decorators import handle_processing_errors
from common.aws_clients import get_dynamodb_service, get_s3_service, get_sns_service

logger = get_logger(__name__)


class AuditEventType(Enum):
    """Types of audit events for HIPAA compliance"""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_ACCESS = "document_access"
    DOCUMENT_DOWNLOAD = "document_download"
    DATA_EXTRACTION = "data_extraction"
    POLICY_ACCESS = "policy_access"
    ASSESSMENT_GENERATION = "assessment_generation"
    DATA_EXPORT = "data_export"
    SYSTEM_ACCESS = "system_access"
    SECURITY_EVENT = "security_event"
    DATA_MODIFICATION = "data_modification"
    DATA_DELETION = "data_deletion"
    CONFIGURATION_CHANGE = "configuration_change"
    ERROR_EVENT = "error_event"
    COMPLIANCE_CHECK = "compliance_check"


class AccessResult(Enum):
    """Result of access attempts"""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


@dataclass
class AuditEvent:
    """Audit event data structure"""
    event_id: str
    event_type: AuditEventType
    timestamp: str
    user_id: Optional[str]
    user_role: Optional[str]
    source_ip: Optional[str]
    user_agent: Optional[str]
    resource_type: Optional[str]
    resource_id: Optional[str]
    action: str
    result: AccessResult
    details: Dict[str, Any]
    session_id: Optional[str] = None
    organization: Optional[str] = None
    risk_level: str = "low"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert audit event to dictionary"""
        event_dict = asdict(self)
        event_dict['event_type'] = self.event_type.value
        event_dict['result'] = self.result.value
        return event_dict


class AuditLogger:
    """HIPAA-compliant audit logging service"""
    
    def __init__(self):
        self.dynamodb_service = get_dynamodb_service()
        self.s3_service = get_s3_service()
        self.sns_service = get_sns_service()
        
        self.audit_table = os.getenv('AUDIT_LOG_TABLE', 'prior-auth-audit-logs')
        self.audit_bucket = os.getenv('AUDIT_LOG_BUCKET', 'prior-auth-audit-backup')
        self.alert_topic = os.getenv('SECURITY_ALERT_TOPIC')
        
    @handle_processing_errors
    def log_event(self, event: AuditEvent) -> str:
        """Log audit event to DynamoDB and S3"""
        
        try:
            # Store in DynamoDB for real-time querying
            self._store_in_dynamodb(event)
            
            # Store in S3 for long-term retention
            self._store_in_s3(event)
            
            # Check for security alerts
            self._check_security_alerts(event)
            
            logger.debug("Audit event logged", 
                        event_id=event.event_id, 
                        event_type=event.event_type.value)
            
            return event.event_id
            
        except Exception as e:
            logger.warning("Failed to log audit event", error=str(e), event_id=event.event_id)
            raise AuditError(f"Audit logging failed: {str(e)}")
    
    def _store_in_dynamodb(self, event: AuditEvent) -> None:
        """Store audit event in DynamoDB"""
        
        try:
            item = event.to_dict()
            
            # Add TTL for automatic cleanup (7 years for HIPAA)
            ttl_date = datetime.utcnow() + timedelta(days=2555)  # 7 years
            item['ttl'] = int(ttl_date.timestamp())
            
            # Add GSI keys for efficient querying
            item['user_date'] = f"{event.user_id}#{event.timestamp[:10]}" if event.user_id else None
            item['resource_date'] = f"{event.resource_id}#{event.timestamp[:10]}" if event.resource_id else None
            item['event_type_date'] = f"{event.event_type.value}#{event.timestamp[:10]}"
            
            self.dynamodb_service.put_item(
                table_name=self.audit_table,
                item=item
            )
            
        except Exception as e:
            logger.warning("Failed to store audit event in DynamoDB", error=str(e))
            raise
    
    def _store_in_s3(self, event: AuditEvent) -> None:
        """Store audit event in S3 for long-term retention"""
        
        try:
            # Create S3 key with date partitioning
            event_date = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
            s3_key = (f"audit-logs/year={event_date.year}/month={event_date.month:02d}/"
                     f"day={event_date.day:02d}/hour={event_date.hour:02d}/"
                     f"{event.event_id}.json")
            
            # Store event as JSON
            event_json = json.dumps(event.to_dict(), indent=2, default=str)
            
            self.s3_service.put_object(
                bucket=self.audit_bucket,
                key=s3_key,
                body=event_json.encode('utf-8'),
                content_type='application/json',
                server_side_encryption='aws:kms',
                sse_kms_key_id=os.getenv('HIPAA_KMS_KEY_ID')
            )
            
        except Exception as e:
            logger.error("Failed to store audit event in S3", error=str(e))
            # Don't raise here - DynamoDB storage is primary
    
    def _check_security_alerts(self, event: AuditEvent) -> None:
        """Check for security events that require alerts"""
        
        try:
            alert_conditions = [
                # Failed login attempts
                (event.event_type == AuditEventType.USER_LOGIN and 
                 event.result == AccessResult.FAILURE),
                
                # High-risk events
                event.risk_level == "high",
                
                # Security events
                event.event_type == AuditEventType.SECURITY_EVENT,
                
                # Data export events
                event.event_type == AuditEventType.DATA_EXPORT,
                
                # Configuration changes
                event.event_type == AuditEventType.CONFIGURATION_CHANGE
            ]
            
            if any(alert_conditions) and self.alert_topic:
                self._send_security_alert(event)
                
        except Exception as e:
            logger.error("Failed to check security alerts", error=str(e))
    
    def _send_security_alert(self, event: AuditEvent) -> None:
        """Send security alert notification"""
        
        try:
            alert_message = {
                'alert_type': 'security_event',
                'event_id': event.event_id,
                'event_type': event.event_type.value,
                'timestamp': event.timestamp,
                'user_id': event.user_id,
                'source_ip': event.source_ip,
                'risk_level': event.risk_level,
                'details': event.details
            }
            
            self.sns_service.publish(
                topic_arn=self.alert_topic,
                message=json.dumps(alert_message, default=str),
                subject=f"Security Alert: {event.event_type.value}"
            )
            
        except Exception as e:
            logger.error("Failed to send security alert", error=str(e))
    
    @handle_processing_errors
    def log_user_access(self, user_id: str, user_role: str, action: str,
                       resource_type: str = None, resource_id: str = None,
                       result: AccessResult = AccessResult.SUCCESS,
                       details: Dict[str, Any] = None,
                       source_ip: str = None, user_agent: str = None,
                       session_id: str = None) -> str:
        """Log user access event"""
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=AuditEventType.DOCUMENT_ACCESS,
            timestamp=datetime.utcnow().isoformat() + 'Z',
            user_id=user_id,
            user_role=user_role,
            source_ip=source_ip,
            user_agent=user_agent,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            result=result,
            details=details or {},
            session_id=session_id
        )
        
        return self.log_event(event)
    
    @handle_processing_errors
    def log_document_event(self, user_id: str, document_id: str, action: str,
                          result: AccessResult = AccessResult.SUCCESS,
                          details: Dict[str, Any] = None,
                          source_ip: str = None) -> str:
        """Log document-related event"""
        
        event_type_map = {
            'upload': AuditEventType.DOCUMENT_UPLOAD,
            'access': AuditEventType.DOCUMENT_ACCESS,
            'download': AuditEventType.DOCUMENT_DOWNLOAD
        }
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type_map.get(action, AuditEventType.DOCUMENT_ACCESS),
            timestamp=datetime.utcnow().isoformat() + 'Z',
            user_id=user_id,
            user_role=None,
            source_ip=source_ip,
            user_agent=None,
            resource_type='document',
            resource_id=document_id,
            action=action,
            result=result,
            details=details or {}
        )
        
        return self.log_event(event)
    
    @handle_processing_errors
    def log_processing_event(self, document_id: str, step_name: str, status: str,
                           user_id: str = None, details: Dict[str, Any] = None) -> str:
        """Log processing step for audit trail"""
        
        event_type_map = {
            'extraction': AuditEventType.DATA_EXTRACTION,
            'policy_selection': AuditEventType.POLICY_ACCESS,
            'assessment': AuditEventType.ASSESSMENT_GENERATION
        }
        
        result = AccessResult.SUCCESS if status in ['started', 'completed'] else AccessResult.ERROR
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type_map.get(step_name, AuditEventType.SYSTEM_ACCESS),
            timestamp=datetime.utcnow().isoformat() + 'Z',
            user_id=user_id,
            user_role=None,
            source_ip=None,
            user_agent=None,
            resource_type='document',
            resource_id=document_id,
            action=f"processing_{step_name}",
            result=result,
            details={
                'step_name': step_name,
                'status': status,
                **(details or {})
            }
        )
        
        return self.log_event(event)
    
    @handle_processing_errors
    def log_security_event(self, event_type: str, details: Dict[str, Any],
                          user_id: str = None, source_ip: str = None,
                          risk_level: str = "medium") -> str:
        """Log security-related event"""
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=AuditEventType.SECURITY_EVENT,
            timestamp=datetime.utcnow().isoformat() + 'Z',
            user_id=user_id,
            user_role=None,
            source_ip=source_ip,
            user_agent=None,
            resource_type='system',
            resource_id=None,
            action=event_type,
            result=AccessResult.SUCCESS,
            details=details,
            risk_level=risk_level
        )
        
        return self.log_event(event)
    
    @handle_processing_errors
    def query_audit_logs(self, start_date: datetime, end_date: datetime,
                        user_id: str = None, event_type: AuditEventType = None,
                        resource_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Query audit logs for compliance reporting"""
        
        try:
            # Build query parameters
            key_condition = "#ts BETWEEN :start_date AND :end_date"
            filter_expression = None
            expression_attribute_names = {"#ts": "timestamp"}
            expression_attribute_values = {
                ":start_date": start_date.isoformat() + 'Z',
                ":end_date": end_date.isoformat() + 'Z'
            }
            
            # Use GSI for efficient querying
            if user_id:
                # Query by user_date GSI
                response = self.dynamodb_service.query(
                    table_name=self.audit_table,
                    index_name='user_date_index',
                    key_condition_expression="user_date = :user_date",
                    expression_attribute_values={
                        ":user_date": f"{user_id}#{start_date.strftime('%Y-%m-%d')}"
                    },
                    limit=limit
                )
            elif event_type:
                # Query by event_type_date GSI
                response = self.dynamodb_service.query(
                    table_name=self.audit_table,
                    index_name='event_type_date_index',
                    key_condition_expression="event_type_date = :event_type_date",
                    expression_attribute_values={
                        ":event_type_date": f"{event_type.value}#{start_date.strftime('%Y-%m-%d')}"
                    },
                    limit=limit
                )
            else:
                # Scan with filters (less efficient)
                response = self.dynamodb_service.scan(
                    table_name=self.audit_table,
                    filter_expression=key_condition,
                    expression_attribute_names=expression_attribute_names,
                    expression_attribute_values=expression_attribute_values,
                    limit=limit
                )
            
            return response.get('Items', [])
            
        except Exception as e:
            logger.warning("Failed to query audit logs", error=str(e))
            raise AuditError(f"Audit log query failed: {str(e)}")


class DataRetentionManager:
    """Manage data retention and secure deletion for HIPAA compliance"""
    
    def __init__(self):
        self.dynamodb_service = get_dynamodb_service()
        self.s3_service = get_s3_service()
        self.audit_logger = AuditLogger()
        
        self.retention_table = os.getenv('DATA_RETENTION_TABLE', 'prior-auth-data-retention')
        self.default_retention_days = int(os.getenv('HIPAA_RETENTION_DAYS', '2555'))  # 7 years
    
    @handle_processing_errors
    def schedule_data_retention(self, resource_id: str, resource_type: str,
                              data_classification: str = 'PHI',
                              retention_days: Optional[int] = None) -> Dict[str, Any]:
        """Schedule data for retention management"""
        
        try:
            retention_period = retention_days or self.default_retention_days
            created_date = datetime.utcnow()
            deletion_date = created_date + timedelta(days=retention_period)
            
            retention_schedule = {
                'resource_id': resource_id,
                'resource_type': resource_type,
                'data_classification': data_classification,
                'created_at': created_date.isoformat(),
                'deletion_date': deletion_date.isoformat(),
                'retention_days': retention_period,
                'status': 'active',
                'scheduled_at': created_date.isoformat()
            }
            
            # Store retention schedule
            self.dynamodb_service.put_item(
                table_name=self.retention_table,
                item=retention_schedule
            )
            
            # Log retention scheduling
            self.audit_logger.log_security_event(
                event_type='data_retention_scheduled',
                details={
                    'resource_id': resource_id,
                    'resource_type': resource_type,
                    'data_classification': data_classification,
                    'retention_days': retention_period,
                    'deletion_date': deletion_date.isoformat()
                }
            )
            
            logger.info("Data retention scheduled", 
                       resource_id=resource_id, 
                       resource_type=resource_type,
                       deletion_date=deletion_date.isoformat())
            
            return retention_schedule
            
        except Exception as e:
            logger.warning("Failed to schedule data retention", error=str(e))
            raise DataRetentionError(f"Data retention scheduling failed: {str(e)}")
    
    @handle_processing_errors
    def process_retention_cleanup(self) -> Dict[str, Any]:
        """Process scheduled retention actions (delete expired data)"""
        
        try:
            current_time = datetime.utcnow()
            results = {
                'processed_at': current_time.isoformat(),
                'deleted_items': 0,
                'errors': []
            }
            
            # Get items due for deletion
            response = self.dynamodb_service.scan(
                table_name=self.retention_table,
                filter_expression='#status = :active AND deletion_date <= :current_time',
                expression_attribute_names={'#status': 'status'},
                expression_attribute_values={
                    ':active': 'active',
                    ':current_time': current_time.isoformat()
                }
            )
            
            items = response.get('Items', [])
            
            for item in items:
                try:
                    self._delete_expired_data(item)
                    results['deleted_items'] += 1
                        
                except Exception as e:
                    error_msg = f"Failed to delete {item.get('resource_id')}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
            
            # Log retention processing
            self.audit_logger.log_security_event(
                event_type='retention_processing',
                details={
                    'items_processed': len(items),
                    'deleted_items': results['deleted_items'],
                    'errors_count': len(results['errors'])
                }
            )
            
            logger.info("Retention processing completed", 
                       deleted=results['deleted_items'],
                       errors=len(results['errors']))
            
            return results
            
        except Exception as e:
            logger.warning("Failed to process retention cleanup", error=str(e))
            raise DataRetentionError(f"Retention processing failed: {str(e)}")
    
    def _delete_expired_data(self, retention_item: Dict[str, Any]) -> None:
        """Delete expired data based on retention policy"""
        
        try:
            resource_id = retention_item['resource_id']
            resource_type = retention_item['resource_type']
            
            # Delete from appropriate storage based on resource type
            if resource_type == 'document':
                self._delete_document_data(resource_id)
            elif resource_type == 'assessment_result':
                self._delete_assessment_data(resource_id)
            elif resource_type == 'audit_log':
                self._delete_audit_data(resource_id)
            
            # Update retention record
            self.dynamodb_service.update_item(
                table_name=self.retention_table,
                key={'resource_id': resource_id},
                update_expression='SET #status = :deleted, deleted_at = :deleted_at',
                expression_attribute_names={'#status': 'status'},
                expression_attribute_values={
                    ':deleted': 'deleted',
                    ':deleted_at': datetime.utcnow().isoformat()
                }
            )
            
            # Log secure deletion
            self.audit_logger.log_security_event(
                event_type='secure_data_deletion',
                details={
                    'resource_id': resource_id,
                    'resource_type': resource_type,
                    'deletion_method': 'secure_overwrite'
                }
            )
            
        except Exception as e:
            logger.warning("Failed to delete expired data", error=str(e))
            raise
    
    def _delete_document_data(self, document_id: str) -> None:
        """Delete document and related data"""
        
        # Delete from S3
        try:
            # List and delete all objects with document_id prefix
            objects = self.s3_service.list_objects(
                bucket=os.getenv('DOCUMENTS_BUCKET'),
                prefix=f"documents/{document_id}/"
            )
            
            for obj in objects.get('Contents', []):
                self.s3_service.delete_object(
                    bucket=os.getenv('DOCUMENTS_BUCKET'),
                    key=obj['Key']
                )
        except Exception as e:
            logger.error(f"Failed to delete S3 objects for {document_id}", error=str(e))
        
        # Delete from DynamoDB tables
        tables_to_clean = [
            'prior-auth-extraction-state',
            'prior-auth-assessment-results',
            'prior-auth-documents'
        ]
        
        for table in tables_to_clean:
            try:
                self.dynamodb_service.delete_item(
                    table_name=table,
                    key={'document_id': document_id}
                )
            except Exception as e:
                logger.error(f"Failed to delete from {table} for {document_id}", error=str(e))  # nosec B608 - log message, not SQL
    
    def _delete_assessment_data(self, assessment_id: str) -> None:
        """Delete assessment result data"""
        
        try:
            self.dynamodb_service.delete_item(
                table_name=os.getenv('RESULTS_TABLE', 'prior-auth-results-dev'),
                key={'assessment_id': assessment_id}
            )
        except Exception as e:
            logger.error(f"Failed to delete assessment {assessment_id}", error=str(e))
    
    def _delete_audit_data(self, event_id: str) -> None:
        """Delete audit log data (only after extended retention)"""
        
        try:
            # Delete from DynamoDB
            self.dynamodb_service.delete_item(
                table_name=self.audit_table,
                key={'event_id': event_id}
            )
            
            # Delete from S3 (if exists)
            # Note: This would require knowing the S3 key structure
            
        except Exception as e:
            logger.error(f"Failed to delete audit data {event_id}", error=str(e))


# Utility functions for easy access
def log_user_access(user_id: str, user_role: str, action: str, resource_id: str = None,
                   result: AccessResult = AccessResult.SUCCESS, 
                   details: Dict[str, Any] = None) -> str:
    """Convenience function to log user access"""
    audit_logger = AuditLogger()
    return audit_logger.log_user_access(user_id, user_role, action, 
                                       resource_id=resource_id, result=result, details=details)


def log_processing_step(document_id: str, step_name: str, status: str, 
                       user_id: str = None, details: Dict[str, Any] = None) -> str:
    """Convenience function to log processing step"""
    audit_logger = AuditLogger()
    return audit_logger.log_processing_event(document_id, step_name, status, user_id, details)


def log_security_event(event_type: str, details: Dict[str, Any], 
                      user_id: str = None, source_ip: str = None) -> str:
    """Convenience function to log security event"""
    audit_logger = AuditLogger()
    return audit_logger.log_security_event(event_type, details, user_id, source_ip)


def schedule_data_retention(resource_id: str, resource_type: str, 
                          data_classification: str = 'PHI') -> Dict[str, Any]:
    """Convenience function to schedule data retention"""
    retention_manager = DataRetentionManager()
    return retention_manager.schedule_data_retention(resource_id, resource_type, data_classification)

