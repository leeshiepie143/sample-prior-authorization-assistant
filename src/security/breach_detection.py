"""
Data breach detection and notification system for HIPAA compliance.

This module monitors for potential data breaches, unauthorized access patterns,
and security incidents that require immediate notification.
"""

import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from common.exceptions import SecurityError
from common.logging_config import get_logger
from common.decorators import handle_processing_errors
from common.aws_clients import get_dynamodb_service, get_sns_service, get_ses_service
from .audit_service import AuditLogger, AuditEventType, AccessResult

logger = get_logger(__name__)


class BreachSeverity(Enum):
    """Severity levels for potential breaches"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BreachType(Enum):
    """Types of potential breaches"""
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    DATA_EXFILTRATION = "data_exfiltration"
    SYSTEM_COMPROMISE = "system_compromise"
    INSIDER_THREAT = "insider_threat"
    CONFIGURATION_ERROR = "configuration_error"
    EXTERNAL_ATTACK = "external_attack"
    PRIVILEGE_ESCALATION = "privilege_escalation"


@dataclass
class BreachAlert:
    """Data breach alert structure"""
    alert_id: str
    breach_type: BreachType
    severity: BreachSeverity
    detected_at: str
    description: str
    affected_resources: List[str]
    indicators: Dict[str, Any]
    recommended_actions: List[str]
    notification_sent: bool = False
    investigation_status: str = "pending"


class BreachDetectionEngine:
    """Engine for detecting potential data breaches"""
    
    def __init__(self):
        self.audit_logger = AuditLogger()
        self.dynamodb_service = get_dynamodb_service()
        self.sns_service = get_sns_service()
        self.ses_service = get_ses_service()
        
        self.alerts_table = os.getenv('BREACH_ALERTS_TABLE', 'prior-auth-breach-alerts')
        self.notification_topic = os.getenv('BREACH_NOTIFICATION_TOPIC')
        self.security_team_email = os.getenv('SECURITY_TEAM_EMAIL')
        
        # Detection thresholds
        self.failed_login_threshold = int(os.getenv('FAILED_LOGIN_THRESHOLD', '5'))
        self.bulk_access_threshold = int(os.getenv('BULK_ACCESS_THRESHOLD', '50'))
        self.unusual_hours_start = int(os.getenv('UNUSUAL_HOURS_START', '22'))  # 10 PM
        self.unusual_hours_end = int(os.getenv('UNUSUAL_HOURS_END', '6'))      # 6 AM
    
    @handle_processing_errors
    def analyze_audit_events(self, events: List[Dict[str, Any]]) -> List[BreachAlert]:
        """Analyze audit events for potential breaches"""
        
        alerts = []
        
        try:
            # Group events by user and time
            user_events = self._group_events_by_user(events)
            
            for user_id, user_events_list in user_events.items():
                # Check for suspicious patterns
                alerts.extend(self._detect_failed_login_attempts(user_id, user_events_list))
                alerts.extend(self._detect_bulk_data_access(user_id, user_events_list))
                alerts.extend(self._detect_unusual_access_patterns(user_id, user_events_list))
                alerts.extend(self._detect_privilege_escalation(user_id, user_events_list))
            
            # Check for system-wide anomalies
            alerts.extend(self._detect_system_anomalies(events))
            
            # Process and store alerts
            for alert in alerts:
                self._process_breach_alert(alert)
            
            return alerts
            
        except Exception as e:
            logger.warning("Failed to analyze audit events for breaches", error=str(e))
            raise SecurityError(f"Breach detection analysis failed: {str(e)}")
    
    def _group_events_by_user(self, events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group events by user ID"""
        
        user_events = {}
        for event in events:
            user_id = event.get('user_id')
            if user_id:
                if user_id not in user_events:
                    user_events[user_id] = []
                user_events[user_id].append(event)
        
        return user_events
    
    def _detect_failed_login_attempts(self, user_id: str, events: List[Dict[str, Any]]) -> List[BreachAlert]:
        """Detect excessive failed login attempts"""
        
        alerts = []
        
        # Count failed login attempts in the last hour
        current_time = datetime.utcnow()
        one_hour_ago = current_time - timedelta(hours=1)
        
        failed_logins = [
            event for event in events
            if (event.get('event_type') == AuditEventType.USER_LOGIN.value and
                event.get('result') == AccessResult.FAILURE.value and
                datetime.fromisoformat(event.get('timestamp', '').replace('Z', '+00:00')) > one_hour_ago)
        ]
        
        if len(failed_logins) >= self.failed_login_threshold:
            alert = BreachAlert(
                alert_id=f"failed_login_{user_id}_{int(current_time.timestamp())}",
                breach_type=BreachType.UNAUTHORIZED_ACCESS,
                severity=BreachSeverity.HIGH if len(failed_logins) > 10 else BreachSeverity.MEDIUM,
                detected_at=current_time.isoformat(),
                description=f"Excessive failed login attempts detected for user {user_id}",
                affected_resources=[user_id],
                indicators={
                    'failed_attempts': len(failed_logins),
                    'time_window': '1 hour',
                    'source_ips': list(set(event.get('source_ip') for event in failed_logins if event.get('source_ip')))
                },
                recommended_actions=[
                    f"Lock user account {user_id}",
                    "Investigate source IP addresses",
                    "Review authentication logs",
                    "Consider implementing account lockout policy"
                ]
            )
            alerts.append(alert)
        
        return alerts
    
    def _detect_bulk_data_access(self, user_id: str, events: List[Dict[str, Any]]) -> List[BreachAlert]:
        """Detect bulk data access patterns"""
        
        alerts = []
        
        # Count document access events in the last hour
        current_time = datetime.utcnow()
        one_hour_ago = current_time - timedelta(hours=1)
        
        access_events = [
            event for event in events
            if (event.get('event_type') in [AuditEventType.DOCUMENT_ACCESS.value, AuditEventType.DOCUMENT_DOWNLOAD.value] and
                event.get('result') == AccessResult.SUCCESS.value and
                datetime.fromisoformat(event.get('timestamp', '').replace('Z', '+00:00')) > one_hour_ago)
        ]
        
        if len(access_events) >= self.bulk_access_threshold:
            alert = BreachAlert(
                alert_id=f"bulk_access_{user_id}_{int(current_time.timestamp())}",
                breach_type=BreachType.DATA_EXFILTRATION,
                severity=BreachSeverity.HIGH,
                detected_at=current_time.isoformat(),
                description=f"Bulk data access detected for user {user_id}",
                affected_resources=list(set(event.get('resource_id') for event in access_events if event.get('resource_id'))),
                indicators={
                    'access_count': len(access_events),
                    'time_window': '1 hour',
                    'unique_documents': len(set(event.get('resource_id') for event in access_events if event.get('resource_id')))
                },
                recommended_actions=[
                    f"Investigate user {user_id} activity",
                    "Review accessed documents for sensitivity",
                    "Check for data export activities",
                    "Consider temporary access restriction"
                ]
            )
            alerts.append(alert)
        
        return alerts
    
    def _detect_unusual_access_patterns(self, user_id: str, events: List[Dict[str, Any]]) -> List[BreachAlert]:
        """Detect unusual access patterns (time, location, etc.)"""
        
        alerts = []
        
        # Check for access during unusual hours
        unusual_hour_events = []
        for event in events:
            try:
                event_time = datetime.fromisoformat(event.get('timestamp', '').replace('Z', '+00:00'))
                hour = event_time.hour
                
                if (hour >= self.unusual_hours_start or hour <= self.unusual_hours_end):
                    unusual_hour_events.append(event)
            except:  # nosec B112
                continue
        
        if len(unusual_hour_events) > 5:  # More than 5 events during unusual hours
            alert = BreachAlert(
                alert_id=f"unusual_hours_{user_id}_{int(datetime.utcnow().timestamp())}",
                breach_type=BreachType.INSIDER_THREAT,
                severity=BreachSeverity.MEDIUM,
                detected_at=datetime.utcnow().isoformat(),
                description=f"Unusual access hours detected for user {user_id}",
                affected_resources=[user_id],
                indicators={
                    'unusual_hour_events': len(unusual_hour_events),
                    'time_range': f"{self.unusual_hours_start}:00 - {self.unusual_hours_end}:00"
                },
                recommended_actions=[
                    f"Verify legitimate business need for after-hours access by {user_id}",
                    "Review accessed resources during unusual hours",
                    "Consider implementing time-based access controls"
                ]
            )
            alerts.append(alert)
        
        # Check for access from multiple IP addresses
        ip_addresses = set(event.get('source_ip') for event in events if event.get('source_ip'))
        if len(ip_addresses) > 3:  # Access from more than 3 different IPs
            alert = BreachAlert(
                alert_id=f"multiple_ips_{user_id}_{int(datetime.utcnow().timestamp())}",
                breach_type=BreachType.UNAUTHORIZED_ACCESS,
                severity=BreachSeverity.MEDIUM,
                detected_at=datetime.utcnow().isoformat(),
                description=f"Access from multiple IP addresses detected for user {user_id}",
                affected_resources=[user_id],
                indicators={
                    'ip_count': len(ip_addresses),
                    'ip_addresses': list(ip_addresses)
                },
                recommended_actions=[
                    f"Verify all IP addresses are legitimate for user {user_id}",
                    "Check for compromised credentials",
                    "Consider implementing IP-based access controls"
                ]
            )
            alerts.append(alert)
        
        return alerts
    
    def _detect_privilege_escalation(self, user_id: str, events: List[Dict[str, Any]]) -> List[BreachAlert]:
        """Detect potential privilege escalation"""
        
        alerts = []
        
        # Check for configuration changes by non-admin users
        config_changes = [
            event for event in events
            if (event.get('event_type') == AuditEventType.CONFIGURATION_CHANGE.value and
                event.get('user_role') not in ['admin', 'system_admin'])
        ]
        
        if config_changes:
            alert = BreachAlert(
                alert_id=f"privilege_escalation_{user_id}_{int(datetime.utcnow().timestamp())}",
                breach_type=BreachType.PRIVILEGE_ESCALATION,
                severity=BreachSeverity.HIGH,
                detected_at=datetime.utcnow().isoformat(),
                description=f"Potential privilege escalation detected for user {user_id}",
                affected_resources=[user_id],
                indicators={
                    'config_changes': len(config_changes),
                    'user_role': events[0].get('user_role') if events else 'unknown'
                },
                recommended_actions=[
                    f"Immediately review permissions for user {user_id}",
                    "Audit recent configuration changes",
                    "Check for unauthorized role modifications",
                    "Consider temporary access suspension"
                ]
            )
            alerts.append(alert)
        
        return alerts
    
    def _detect_system_anomalies(self, events: List[Dict[str, Any]]) -> List[BreachAlert]:
        """Detect system-wide anomalies"""
        
        alerts = []
        
        # Check for high error rates
        error_events = [
            event for event in events
            if event.get('result') == AccessResult.ERROR.value
        ]
        
        error_rate = len(error_events) / len(events) if events else 0
        
        if error_rate > 0.2:  # More than 20% error rate
            alert = BreachAlert(
                alert_id=f"high_error_rate_{int(datetime.utcnow().timestamp())}",
                breach_type=BreachType.SYSTEM_COMPROMISE,
                severity=BreachSeverity.HIGH if error_rate > 0.5 else BreachSeverity.MEDIUM,
                detected_at=datetime.utcnow().isoformat(),
                description="High system error rate detected",
                affected_resources=['system'],
                indicators={
                    'error_rate': f"{error_rate:.2%}",
                    'total_events': len(events),
                    'error_events': len(error_events)
                },
                recommended_actions=[
                    "Investigate system health and performance",
                    "Check for potential DDoS or attack patterns",
                    "Review system logs for anomalies",
                    "Consider implementing rate limiting"
                ]
            )
            alerts.append(alert)
        
        return alerts
    
    @handle_processing_errors
    def _process_breach_alert(self, alert: BreachAlert) -> None:
        """Process and store breach alert"""
        
        try:
            # Store alert in DynamoDB
            self.dynamodb_service.put_item(
                table_name=self.alerts_table,
                item={
                    'alert_id': alert.alert_id,
                    'breach_type': alert.breach_type.value,
                    'severity': alert.severity.value,
                    'detected_at': alert.detected_at,
                    'description': alert.description,
                    'affected_resources': alert.affected_resources,
                    'indicators': alert.indicators,
                    'recommended_actions': alert.recommended_actions,
                    'notification_sent': alert.notification_sent,
                    'investigation_status': alert.investigation_status,
                    'ttl': int((datetime.utcnow() + timedelta(days=365)).timestamp())  # 1 year retention
                }
            )
            
            # Send notifications for high/critical severity
            if alert.severity in [BreachSeverity.HIGH, BreachSeverity.CRITICAL]:
                self._send_breach_notification(alert)
            
            # Log the alert
            self.audit_logger.log_security_event(
                event_type='breach_alert_generated',
                details={
                    'alert_id': alert.alert_id,
                    'breach_type': alert.breach_type.value,
                    'severity': alert.severity.value,
                    'affected_resources': alert.affected_resources
                },
                risk_level='high'
            )
            
        except Exception as e:
            logger.warning("Failed to process breach alert", error=str(e))
            raise
    
    def _send_breach_notification(self, alert: BreachAlert) -> None:
        """Send breach notification to security team"""
        
        try:
            notification_message = {
                'alert_id': alert.alert_id,
                'breach_type': alert.breach_type.value,
                'severity': alert.severity.value,
                'detected_at': alert.detected_at,
                'description': alert.description,
                'affected_resources': alert.affected_resources,
                'indicators': alert.indicators,
                'recommended_actions': alert.recommended_actions
            }
            
            # Send SNS notification
            if self.notification_topic:
                self.sns_service.publish(
                    topic_arn=self.notification_topic,
                    message=json.dumps(notification_message, indent=2),
                    subject=f"SECURITY ALERT: {alert.breach_type.value.upper()} - {alert.severity.value.upper()}"
                )
            
            # Send email notification
            if self.security_team_email:
                self._send_email_notification(alert, notification_message)
            
            # Update notification status
            self.dynamodb_service.update_item(
                table_name=self.alerts_table,
                key={'alert_id': alert.alert_id},
                update_expression='SET notification_sent = :sent, notification_sent_at = :sent_at',
                expression_attribute_values={
                    ':sent': True,
                    ':sent_at': datetime.utcnow().isoformat()
                }
            )
            
        except Exception as e:
            logger.error("Failed to send breach notification", error=str(e))
    
    def _send_email_notification(self, alert: BreachAlert, notification_data: Dict[str, Any]) -> None:
        """Send email notification for breach alert"""
        
        try:
            subject = f"🚨 SECURITY ALERT: {alert.breach_type.value.replace('_', ' ').title()} Detected"
            
            html_body = f"""
            <html>
            <body>
                <h2 style="color: {'#d32f2f' if alert.severity == BreachSeverity.CRITICAL else '#f57c00'};">
                    Security Alert - {alert.severity.value.upper()}
                </h2>
                
                <h3>Alert Details</h3>
                <ul>
                    <li><strong>Alert ID:</strong> {alert.alert_id}</li>
                    <li><strong>Breach Type:</strong> {alert.breach_type.value.replace('_', ' ').title()}</li>
                    <li><strong>Severity:</strong> {alert.severity.value.upper()}</li>
                    <li><strong>Detected At:</strong> {alert.detected_at}</li>
                </ul>
                
                <h3>Description</h3>
                <p>{alert.description}</p>
                
                <h3>Affected Resources</h3>
                <ul>
                    {''.join(f'<li>{resource}</li>' for resource in alert.affected_resources)}
                </ul>
                
                <h3>Indicators</h3>
                <ul>
                    {''.join(f'<li><strong>{k}:</strong> {v}</li>' for k, v in alert.indicators.items())}
                </ul>
                
                <h3>Recommended Actions</h3>
                <ol>
                    {''.join(f'<li>{action}</li>' for action in alert.recommended_actions)}
                </ol>
                
                <hr>
                <p><em>This is an automated security alert from the Prior Authorization System.</em></p>
            </body>
            </html>
            """
            
            self.ses_service.send_email(
                source=os.getenv('SYSTEM_EMAIL', 'noreply@priorauth.com'),
                destination={'ToAddresses': [self.security_team_email]},
                message={
                    'Subject': {'Data': subject},
                    'Body': {
                        'Html': {'Data': html_body},
                        'Text': {'Data': json.dumps(notification_data, indent=2)}
                    }
                }
            )
            
        except Exception as e:
            logger.error("Failed to send email notification", error=str(e))
    
    @handle_processing_errors
    def get_active_alerts(self, severity: BreachSeverity = None) -> List[Dict[str, Any]]:
        """Get active breach alerts"""
        
        try:
            if severity:
                response = self.dynamodb_service.scan(
                    table_name=self.alerts_table,
                    filter_expression='investigation_status = :status AND severity = :severity',
                    expression_attribute_values={
                        ':status': 'pending',
                        ':severity': severity.value
                    }
                )
            else:
                response = self.dynamodb_service.scan(
                    table_name=self.alerts_table,
                    filter_expression='investigation_status = :status',
                    expression_attribute_values={':status': 'pending'}
                )
            
            return response.get('Items', [])
            
        except Exception as e:
            logger.warning("Failed to get active alerts", error=str(e))
            raise SecurityError(f"Failed to retrieve active alerts: {str(e)}")


# Utility functions
def analyze_recent_events(hours: int = 24) -> List[BreachAlert]:
    """Analyze recent audit events for potential breaches"""
    
    detector = BreachDetectionEngine()
    audit_logger = AuditLogger()
    
    # Get recent events
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    events = audit_logger.query_audit_logs(start_time, end_time, limit=1000)
    
    return detector.analyze_audit_events(events)


def get_security_dashboard() -> Dict[str, Any]:
    """Get security dashboard data"""
    
    detector = BreachDetectionEngine()
    
    # Get active alerts by severity
    critical_alerts = detector.get_active_alerts(BreachSeverity.CRITICAL)
    high_alerts = detector.get_active_alerts(BreachSeverity.HIGH)
    medium_alerts = detector.get_active_alerts(BreachSeverity.MEDIUM)
    low_alerts = detector.get_active_alerts(BreachSeverity.LOW)
    
    return {
        'alert_summary': {
            'critical': len(critical_alerts),
            'high': len(high_alerts),
            'medium': len(medium_alerts),
            'low': len(low_alerts),
            'total': len(critical_alerts) + len(high_alerts) + len(medium_alerts) + len(low_alerts)
        },
        'recent_alerts': (critical_alerts + high_alerts)[:10],  # Most recent critical/high alerts
        'last_updated': datetime.utcnow().isoformat()
    }

