"""
Policy Metadata Extraction Module

This module handles automatic extraction of metadata from policy documents
uploaded to S3, including support for PDF, HTML, and text files.
"""

from .text_extractor import extract_text_from_document
from .metadata_extractor import extract_metadata_from_text, format_metadata_for_s3
from .s3_metadata_updater import update_s3_metadata, extract_payor_from_s3_key
from .kb_sync_trigger import trigger_kb_sync
from .handler import lambda_handler

__all__ = [
    'extract_text_from_document',
    'extract_metadata_from_text',
    'format_metadata_for_s3',
    'update_s3_metadata',
    'extract_payor_from_s3_key',
    'trigger_kb_sync',
    'lambda_handler'
]
