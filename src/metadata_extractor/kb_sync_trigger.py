"""
Knowledge Base sync trigger functionality.

Triggers Bedrock Knowledge Base sync jobs with proper conflict handling.
"""

import boto3
import os
from typing import Dict
import structlog

logger = structlog.get_logger(__name__)


def trigger_kb_sync(
    bedrock_agent_client: boto3.client,
    knowledge_base_id: str = None,
    data_source_id: str = None
) -> Dict[str, str]:
    """
    Trigger Knowledge Base sync job.
    Handles ConflictException as acceptable (another sync already running).
    
    Args:
        bedrock_agent_client: Boto3 Bedrock Agent client
        knowledge_base_id: Knowledge Base ID (from env if not provided)
        data_source_id: Data Source ID (from env if not provided)
        
    Returns:
        Dictionary with status and job_id (if started) or reason (if skipped/failed)
    """
    # Get IDs from environment if not provided
    if not knowledge_base_id:
        knowledge_base_id = os.environ.get('KNOWLEDGE_BASE_ID')
    if not data_source_id:
        data_source_id = os.environ.get('DATA_SOURCE_ID')
    
    if not knowledge_base_id or not data_source_id:
        logger.error(
            "Missing Knowledge Base or Data Source ID",
            knowledge_base_id=knowledge_base_id,
            data_source_id=data_source_id
        )
        return {
            'status': 'failed',
            'error': 'Missing Knowledge Base or Data Source ID'
        }
    
    logger.info(
        "Attempting to trigger KB sync",
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id
    )
    
    try:
        response = bedrock_agent_client.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id
        )
        
        job_id = response['ingestionJob']['ingestionJobId']
        logger.info(
            "KB sync job started successfully",
            job_id=job_id,
            knowledge_base_id=knowledge_base_id
        )
        
        return {
            'status': 'started',
            'job_id': job_id
        }
        
    except Exception as e:
        # Check if it's a ConflictException
        if type(e).__name__ == 'ConflictException' or 'ConflictException' in str(type(e)):
            # Expected: Another sync job is already running
            logger.info(
                "KB sync skipped - another sync job already in progress (expected behavior)",
                knowledge_base_id=knowledge_base_id
            )
            
            return {
                'status': 'skipped',
                'reason': 'sync_in_progress'
            }
        
        # Unexpected error
        logger.error(
            "KB sync failed with unexpected error",
            knowledge_base_id=knowledge_base_id,
            error=str(e),
            error_type=type(e).__name__
        )
        
        return {
            'status': 'failed',
            'error': str(e)
        }


def send_sync_failure_alert(
    sns_client: boto3.client,
    topic_arn: str,
    error_message: str,
    knowledge_base_id: str
) -> None:
    """
    Send SNS alert for sync failure.
    
    Args:
        sns_client: Boto3 SNS client
        topic_arn: SNS topic ARN
        error_message: Error message
        knowledge_base_id: Knowledge Base ID
    """
    try:
        sns_client.publish(
            TopicArn=topic_arn,
            Subject='Knowledge Base Sync Failed',
            Message=f"""Knowledge Base sync job failed.

Knowledge Base ID: {knowledge_base_id}
Error: {error_message}

Please investigate and retry if necessary."""
        )
        
        logger.info(
            "Sync failure alert sent",
            topic_arn=topic_arn,
            knowledge_base_id=knowledge_base_id
        )
        
    except Exception as e:
        logger.error(
            "Failed to send sync failure alert",
            error=str(e)
        )
