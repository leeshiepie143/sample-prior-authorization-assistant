"""
Lambda handler for policy metadata extraction.

Triggered by S3 events when policy documents are uploaded.
Extracts metadata and updates S3 object metadata, then triggers KB sync.
"""

import boto3
import json
import os
from typing import Dict, Any
import structlog

from .text_extractor import extract_text_from_document
from .metadata_extractor import extract_metadata_from_text, format_metadata_for_s3
from .s3_metadata_updater import update_s3_metadata, extract_payor_from_s3_key
from .kb_sync_trigger import trigger_kb_sync, send_sync_failure_alert

# Initialize logger
logger = structlog.get_logger(__name__)

# Initialize AWS clients
s3_client = boto3.client('s3')
textract_client = boto3.client('textract')
bedrock_client = boto3.client('bedrock-runtime')
bedrock_agent_client = boto3.client('bedrock-agent')
sns_client = boto3.client('sns')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for S3 event-triggered metadata extraction.
    
    Args:
        event: S3 event notification
        context: Lambda context
        
    Returns:
        Response dictionary with status and details
    """
    logger.info("Metadata extraction Lambda invoked", lambda_event=event)
    
    try:
        # Parse S3 event
        if 'Records' not in event or len(event['Records']) == 0:
            logger.error("Invalid event format - no Records found")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid event format'})
            }
        
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        event_name = record['eventName']
        
        # URL-decode the key (S3 events URL-encode keys)
        from urllib.parse import unquote_plus
        key = unquote_plus(key)
        
        # Skip processing if this is a CopyObject event (metadata update)
        # This prevents recursive Lambda invocations
        if 'Copy' in event_name:
            logger.info(
                "Skipping CopyObject event to prevent recursion",
                bucket=bucket,
                key=key,
                event_name=event_name
            )
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Skipped CopyObject event',
                    'event_name': event_name
                })
            }
        
        logger.info(
            "Processing policy document",
            bucket=bucket,
            key=key,
            event_name=event_name
        )
        
        # Extract payor from S3 key
        try:
            payor = extract_payor_from_s3_key(key)
        except ValueError as e:
            logger.error(
                "Failed to extract payor from S3 key",
                key=key,
                error=str(e)
            )
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Invalid S3 key format',
                    'details': str(e)
                })
            }
        
        # Step 1: Extract text from document
        try:
            text = extract_text_from_document(
                s3_client,
                textract_client,
                bucket,
                key
            )
            logger.info(
                "Text extraction completed",
                bucket=bucket,
                key=key,
                text_length=len(text)
            )
        except Exception as e:
            logger.error(
                "Text extraction failed",
                bucket=bucket,
                key=key,
                error=str(e)
            )
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': 'Text extraction failed',
                    'details': str(e)
                })
            }
        
        # Step 2: Extract metadata using Bedrock
        try:
            metadata = extract_metadata_from_text(
                bedrock_client,
                text,
                payor
            )
            logger.info(
                "Metadata extraction completed",
                payor=payor,
                procedure_codes_count=len(metadata.get('procedure_codes', [])),
                icd_codes_count=len(metadata.get('icd_codes', []))
            )
        except Exception as e:
            logger.error(
                "Metadata extraction failed",
                payor=payor,
                error=str(e)
            )
            # Continue with minimal metadata
            metadata = {
                'payor': payor,
                'procedure_codes': [],
                'icd_codes': [],
                'effective_date': None,
                'policy_number': None,
                'service_category': None
            }
        
        # Step 3: Update S3 object metadata
        try:
            s3_metadata = format_metadata_for_s3(metadata)
            update_s3_metadata(s3_client, bucket, key, s3_metadata)
            logger.info(
                "S3 metadata updated",
                bucket=bucket,
                key=key
            )
        except Exception as e:
            logger.error(
                "S3 metadata update failed",
                bucket=bucket,
                key=key,
                error=str(e)
            )
            # Continue to KB sync even if metadata update fails
        
        # Step 4: Trigger Knowledge Base sync
        sync_result = trigger_kb_sync(bedrock_agent_client)
        
        if sync_result['status'] == 'failed':
            # Send alert for unexpected failures
            alert_topic_arn = os.environ.get('ALERT_TOPIC_ARN')
            if alert_topic_arn:
                send_sync_failure_alert(
                    sns_client,
                    alert_topic_arn,
                    sync_result.get('error', 'Unknown error'),
                    os.environ.get('KNOWLEDGE_BASE_ID', 'unknown')
                )
        
        logger.info(
            "Metadata extraction completed successfully",
            bucket=bucket,
            key=key,
            payor=payor,
            sync_status=sync_result['status']
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Metadata extraction completed',
                'bucket': bucket,
                'key': key,
                'payor': payor,
                'metadata': metadata,
                'sync_status': sync_result['status']
            })
        }
        
    except Exception as e:
        logger.error(
            "Unexpected error in metadata extraction",
            error=str(e),
            error_type=type(e).__name__
        )
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Unexpected error',
                'details': str(e)
            })
        }
