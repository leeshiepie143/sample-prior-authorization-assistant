"""
Text extraction from policy documents in various formats.

Supports PDF (via AWS Textract), HTML, and plain text files.
"""

import boto3
from bs4 import BeautifulSoup
import time
from typing import Tuple
import structlog

logger = structlog.get_logger(__name__)


def extract_text_from_document(
    s3_client: boto3.client,
    textract_client: boto3.client,
    bucket: str,
    key: str
) -> str:
    """
    Extract text from PDF, HTML, or text file.
    
    Args:
        s3_client: Boto3 S3 client
        textract_client: Boto3 Textract client
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Extracted text content
        
    Raises:
        ValueError: If file format is unsupported
        Exception: If text extraction fails
    """
    # Determine file type from extension
    file_extension = key.lower().split('.')[-1]
    
    logger.info(
        "Extracting text from document",
        bucket=bucket,
        key=key,
        file_extension=file_extension
    )
    
    if file_extension == 'pdf':
        # Use AWS Textract for PDF extraction
        return extract_text_from_pdf_with_textract(
            s3_client, textract_client, bucket, key
        )
    
    elif file_extension in ['html', 'htm']:
        # Extract text from HTML
        return extract_text_from_html(s3_client, bucket, key)
    
    elif file_extension == 'txt':
        # Read text file directly
        return extract_text_from_txt(s3_client, bucket, key)
    
    else:
        raise ValueError(f"Unsupported file format: {file_extension}")


def extract_text_from_html(
    s3_client: boto3.client,
    bucket: str,
    key: str
) -> str:
    """
    Extract text from HTML file.
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Extracted text content
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read()
    
    soup = BeautifulSoup(content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    text = soup.get_text(separator='\n', strip=True)
    
    logger.info(
        "Extracted text from HTML",
        bucket=bucket,
        key=key,
        text_length=len(text)
    )
    
    return text


def extract_text_from_txt(
    s3_client: boto3.client,
    bucket: str,
    key: str
) -> str:
    """
    Extract text from plain text file.
    
    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Extracted text content
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read()
    text = content.decode('utf-8')
    
    logger.info(
        "Extracted text from TXT",
        bucket=bucket,
        key=key,
        text_length=len(text)
    )
    
    return text


def extract_text_from_pdf_with_textract(
    s3_client: boto3.client,
    textract_client: boto3.client,
    bucket: str,
    key: str
) -> str:
    """
    Extract text from PDF using AWS Textract.
    Uses synchronous API for single-page PDFs and asynchronous API for multi-page PDFs.
    
    Args:
        s3_client: Boto3 S3 client
        textract_client: Boto3 Textract client
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Extracted text content
    """
    # Get PDF metadata to determine page count
    response = s3_client.head_object(Bucket=bucket, Key=key)
    file_size = response['ContentLength']
    
    # Heuristic: Files < 5MB likely single page, use sync API
    # For larger files or if sync fails, use async API
    use_sync = file_size < 5 * 1024 * 1024  # 5MB threshold
    
    logger.info(
        "Starting PDF text extraction",
        bucket=bucket,
        key=key,
        file_size=file_size,
        use_sync=use_sync
    )
    
    try:
        if use_sync:
            # Try synchronous detection first (faster for single-page docs)
            return extract_text_sync(textract_client, bucket, key)
    except Exception as e:
        # Check if it's InvalidParameterException or any other error
        error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
        if error_code == 'InvalidParameterException':
            # Document too large for sync API, fall back to async
            logger.info("Document too large for sync API, using async")
        else:
            # Log and fall back to async for any other error
            logger.warning(
                "Sync extraction failed, using async",
                error=str(e)
            )
    
    # Use asynchronous detection for multi-page documents
    return extract_text_async(textract_client, bucket, key)


def extract_text_sync(
    textract_client: boto3.client,
    bucket: str,
    key: str
) -> str:
    """
    Synchronous Textract extraction for single-page PDFs.
    
    Args:
        textract_client: Boto3 Textract client
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Extracted text content
    """
    response = textract_client.detect_document_text(
        Document={
            'S3Object': {
                'Bucket': bucket,
                'Name': key
            }
        }
    )
    
    # Extract text from blocks
    text_lines = []
    for block in response['Blocks']:
        if block['BlockType'] == 'LINE':
            text_lines.append(block['Text'])
    
    text = '\n'.join(text_lines)
    
    logger.info(
        "Sync text extraction completed",
        bucket=bucket,
        key=key,
        text_length=len(text),
        blocks_count=len(response['Blocks'])
    )
    
    return text


def extract_text_async(
    textract_client: boto3.client,
    bucket: str,
    key: str,
    max_wait_seconds: int = 300
) -> str:
    """
    Asynchronous Textract extraction for multi-page PDFs.
    
    Args:
        textract_client: Boto3 Textract client
        bucket: S3 bucket name
        key: S3 object key
        max_wait_seconds: Maximum time to wait for job completion
        
    Returns:
        Extracted text content
        
    Raises:
        TimeoutError: If job exceeds max wait time
        Exception: If job fails
    """
    # Start async job
    response = textract_client.start_document_text_detection(
        DocumentLocation={
            'S3Object': {
                'Bucket': bucket,
                'Name': key
            }
        }
    )
    
    job_id = response['JobId']
    logger.info(
        "Started Textract async job",
        job_id=job_id,
        bucket=bucket,
        key=key
    )
    
    # Poll for completion
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise TimeoutError(
                f"Textract job {job_id} exceeded {max_wait_seconds}s timeout"
            )
        
        response = textract_client.get_document_text_detection(JobId=job_id)
        status = response['JobStatus']
        
        logger.debug(
            "Textract job status",
            job_id=job_id,
            status=status,
            elapsed_seconds=int(elapsed)
        )
        
        if status == 'SUCCEEDED':
            break
        elif status == 'FAILED':
            error_msg = response.get('StatusMessage', 'Unknown error')
            raise Exception(f"Textract job {job_id} failed: {error_msg}")
        
        # Wait before polling again
        time.sleep(5)  # nosemgrep: arbitrary-sleep
    
    # Collect all pages of results
    text_lines = []
    next_token = None
    
    # First, get the initial response (already have it from status check)
    for block in response['Blocks']:
        if block['BlockType'] == 'LINE':
            text_lines.append(block['Text'])
    
    next_token = response.get('NextToken')
    
    # Continue with pagination if needed
    while next_token:
        response = textract_client.get_document_text_detection(
            JobId=job_id,
            NextToken=next_token
        )
        
        # Extract text from blocks
        for block in response['Blocks']:
            if block['BlockType'] == 'LINE':
                text_lines.append(block['Text'])
        
        # Check for more pages
        next_token = response.get('NextToken')
    
    text = '\n'.join(text_lines)
    
    logger.info(
        "Async text extraction completed",
        job_id=job_id,
        bucket=bucket,
        key=key,
        text_length=len(text),
        lines_count=len(text_lines)
    )
    
    return text
