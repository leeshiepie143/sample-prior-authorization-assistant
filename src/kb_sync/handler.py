"""
KB Sync Trigger Lambda Handler

Initiates Bedrock Knowledge Base synchronization with retry logic.
Async operation - does not wait for sync completion.
"""

import boto3
import os
import time
from typing import Dict, Any
import structlog

# Import existing modules
import sys
sys.path.append('/opt/python')  # Lambda layer path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from metadata_extractor.kb_sync_trigger import trigger_kb_sync

logger = structlog.get_logger(__name__)

# Initialize Bedrock Agent client
bedrock_agent_client = boto3.client('bedrock-agent')

# Environment variables
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID')
DATA_SOURCE_ID = os.environ.get('DATA_SOURCE_ID')
MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for triggering Knowledge Base sync.
    
    Implements retry logic with exponential backoff:
    - Attempt 1: Immediate
    - Attempt 2: Wait 2 seconds
    - Attempt 3: Wait 4 seconds
    
    Expected input:
    {
        "knowledge_base_id": "<YOUR_KB_ID>",  # Optional, uses env var if not provided
        "data_source_id": "<YOUR_DS_ID>"     # Optional, uses env var if not provided
    }
    
    Returns:
    {
        "statusCode": 200,
        "status": "started" | "skipped" | "failed",
        "job_id": "abc123",  # If started
        "reason": "sync_in_progress",  # If skipped
        "error": "error message",  # If failed
        "attempts": 1,
        "timestamp": "2024-11-11T14:30:00Z"
    }
    """
    logger.info(
        "KB sync trigger invoked",
        request_id=context.aws_request_id if context else None,
        event_type=type(event).__name__,
        event_preview=str(event)[:200]  # Log first 200 chars of event for debugging
    )
    
    # Handle case where event is a list (from Map state output) or empty dict
    # If event is empty dict or list, use environment variables
    if isinstance(event, list) or not event:
        kb_id = KNOWLEDGE_BASE_ID
        ds_id = DATA_SOURCE_ID
    else:
        # Extract input parameters (use env vars as fallback)
        kb_id = event.get('knowledge_base_id', KNOWLEDGE_BASE_ID)
        ds_id = event.get('data_source_id', DATA_SOURCE_ID)
    
    if not kb_id or not ds_id:
        logger.error(
            "Missing Knowledge Base or Data Source ID",
            kb_id=kb_id,
            ds_id=ds_id
        )
        return {
            'statusCode': 400,
            'status': 'failed',
            'error': 'Missing Knowledge Base or Data Source ID'
        }
    
    # Retry loop with exponential backoff
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(
            "Attempting KB sync",
            attempt=attempt,
            max_retries=MAX_RETRIES,
            kb_id=kb_id
        )
        
        try:
            # Trigger sync using existing module
            result = trigger_kb_sync(
                bedrock_agent_client,
                knowledge_base_id=kb_id,
                data_source_id=ds_id
            )
            
            # Check result status
            if result['status'] == 'started':
                logger.info(
                    "KB sync started successfully",
                    job_id=result['job_id'],
                    attempt=attempt
                )
                return {
                    'statusCode': 200,
                    'status': 'started',
                    'job_id': result['job_id'],
                    'attempts': attempt,
                    'timestamp': _get_timestamp()
                }
            
            elif result['status'] == 'skipped':
                logger.info(
                    "KB sync skipped - another sync in progress",
                    reason=result.get('reason'),
                    attempt=attempt
                )
                return {
                    'statusCode': 200,
                    'status': 'skipped',
                    'reason': result.get('reason', 'sync_in_progress'),
                    'attempts': attempt,
                    'timestamp': _get_timestamp()
                }
            
            elif result['status'] == 'failed':
                last_error = result.get('error', 'Unknown error')
                logger.warning(
                    "KB sync attempt failed",
                    attempt=attempt,
                    error=last_error
                )
                
                # If this is not the last attempt, wait before retrying
                if attempt < MAX_RETRIES:
                    backoff_time = INITIAL_BACKOFF * (2 ** (attempt - 1))
                    logger.info(
                        "Waiting before retry",
                        backoff_seconds=backoff_time
                    )
                    time.sleep(backoff_time)
                    continue
                
                # Last attempt failed
                logger.error(
                    "KB sync failed after all retries",
                    attempts=MAX_RETRIES,
                    error=last_error
                )
                return {
                    'statusCode': 500,
                    'status': 'failed',
                    'error': last_error,
                    'attempts': attempt,
                    'timestamp': _get_timestamp()
                }
        
        except Exception as e:
            last_error = str(e)
            logger.error(
                "Unexpected error during KB sync attempt",
                attempt=attempt,
                error=last_error,
                error_type=type(e).__name__
            )
            
            # If this is not the last attempt, wait before retrying
            if attempt < MAX_RETRIES:
                backoff_time = INITIAL_BACKOFF * (2 ** (attempt - 1))
                logger.info(
                    "Waiting before retry after exception",
                    backoff_seconds=backoff_time
                )
                time.sleep(backoff_time)
                continue
            
            # Last attempt failed
            logger.error(
                "KB sync failed after all retries with exception",
                attempts=MAX_RETRIES,
                error=last_error
            )
            return {
                'statusCode': 500,
                'status': 'failed',
                'error': last_error,
                'attempts': attempt,
                'timestamp': _get_timestamp()
            }
    
    # Should not reach here, but just in case
    return {
        'statusCode': 500,
        'status': 'failed',
        'error': last_error or 'Unknown error after retries',
        'attempts': MAX_RETRIES,
        'timestamp': _get_timestamp()
    }


def _get_timestamp() -> str:
    """Get current timestamp in ISO 8601 format"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
