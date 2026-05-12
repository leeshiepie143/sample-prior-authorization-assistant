"""
Format detection module for identifying document types.

This module detects whether uploaded documents are PDF, FHIR JSON, X12 JSON,
or other formats to enable proper routing to the appropriate extractor.
"""

import json
from enum import Enum
from typing import Dict, Any, Tuple
from pathlib import Path

from common.aws_clients import get_s3_service
from common.exceptions import PriorAuthException
from common.models import DocumentFormat
from common.logging_config import get_logger

logger = get_logger(__name__)


class FormatDetectionException(PriorAuthException):
    """Raised when format detection fails"""
    def __init__(self, message: str, document_id: str = None):
        super().__init__(
            f"Format detection failed: {message}",
            document_id=document_id,
            retry_able=True
        )


class UnsupportedFormatException(PriorAuthException):
    """Raised when document format is not supported"""
    def __init__(self, format_type: str, document_id: str = None):
        super().__init__(
            f"Unsupported document format: {format_type}",
            document_id=document_id,
            retry_able=False
        )


class FormatDetector:
    """Detects document format from S3 objects"""
    
    def __init__(self):
        self.s3_service = get_s3_service()
    
    def detect_format(self, document_id: str, bucket: str, s3_key: str) -> DocumentFormat:
        """
        Detect document format from S3 object.
        
        Args:
            document_id: Document identifier
            bucket: S3 bucket name
            s3_key: S3 object key
            
        Returns:
            DocumentFormat enum value
            
        Raises:
            FormatDetectionException: If detection fails
        """
        try:
            logger.info("Detecting document format", 
                       document_id=document_id, 
                       s3_key=s3_key)
            
            # Step 1: Check file extension
            extension = self._get_file_extension(s3_key)
            logger.debug("File extension detected", extension=extension)
            
            # Step 2: Get S3 object metadata
            metadata = self._get_s3_metadata(bucket, s3_key)
            content_type = metadata.get('ContentType', '')
            logger.debug("Content-Type from S3 metadata", content_type=content_type)
            
            # Step 3: Determine format based on extension and content-type
            if extension == '.pdf' or 'application/pdf' in content_type.lower():
                format_type = DocumentFormat.PDF
            elif extension == '.json' or 'application/json' in content_type.lower():
                # For JSON files, need to analyze content to determine type
                format_type = self._detect_json_format(bucket, s3_key, document_id)
            else:
                # Unknown format - try content analysis
                format_type = self._analyze_file_content(bucket, s3_key)
            
            logger.info("Format detection completed", 
                       document_id=document_id,
                       format=format_type.value)
            
            return format_type
            
        except Exception as e:
            logger.warning("Format detection failed", 
                        document_id=document_id,
                        error=str(e))
            raise FormatDetectionException(str(e), document_id)
    
    def _get_file_extension(self, s3_key: str) -> str:
        """Extract file extension from S3 key"""
        path = Path(s3_key)
        return path.suffix.lower()
    
    def _get_s3_metadata(self, bucket: str, s3_key: str) -> Dict[str, Any]:
        """Get S3 object metadata"""
        try:
            s3_client = self.s3_service.s3_client
            response = s3_client.head_object(Bucket=bucket, Key=s3_key)
            return response
        except Exception as e:
            logger.warning("Failed to get S3 metadata", error=str(e))
            return {}
    
    def _detect_json_format(self, bucket: str, s3_key: str, document_id: str) -> DocumentFormat:
        """
        Detect JSON format type (FHIR, X12, etc.) by analyzing content.
        
        Args:
            bucket: S3 bucket name
            s3_key: S3 object key
            document_id: Document identifier
            
        Returns:
            DocumentFormat enum value
        """
        try:
            # Read first 5KB of file to check structure
            s3_client = self.s3_service.s3_client
            response = s3_client.get_object(
                Bucket=bucket,
                Key=s3_key,
                Range='bytes=0-5119'  # First 5KB
            )
            
            content = response['Body'].read().decode('utf-8', errors='ignore')
            
            # Parse JSON
            try:
                json_data = json.loads(content)
            except json.JSONDecodeError:
                # If first 5KB doesn't contain complete JSON, read full file
                logger.debug("First 5KB not valid JSON, reading full file")
                response = s3_client.get_object(Bucket=bucket, Key=s3_key)
                content = response['Body'].read().decode('utf-8')
                json_data = json.loads(content)
            
            # Check for FHIR Bundle structure
            if self.validate_fhir_structure(json_data):
                logger.info("FHIR Bundle structure detected", document_id=document_id)
                return DocumentFormat.FHIR_JSON
            
            # Check for X12 structure (future)
            if self.validate_x12_structure(json_data):
                # Determine X12 type
                x12_type = self._determine_x12_type(json_data)
                logger.info("X12 JSON structure detected", 
                           document_id=document_id,
                           x12_type=x12_type)
                return x12_type
            
            # Unknown JSON format
            logger.warning("Unknown JSON format", document_id=document_id)
            return DocumentFormat.UNKNOWN
            
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON content", 
                        document_id=document_id,
                        error=str(e))
            return DocumentFormat.UNKNOWN
        except Exception as e:
            logger.error("Error analyzing JSON content", 
                        document_id=document_id,
                        error=str(e))
            raise FormatDetectionException(f"JSON analysis failed: {str(e)}", document_id)
    
    def validate_fhir_structure(self, json_data: Dict[str, Any]) -> bool:
        """
        Validate FHIR Bundle structure.
        
        Args:
            json_data: Parsed JSON data
            
        Returns:
            True if valid FHIR Bundle structure
        """
        try:
            # Check for required FHIR Bundle fields
            if not isinstance(json_data, dict):
                return False
            
            # Must have resourceType field with value "Bundle"
            if json_data.get('resourceType') != 'Bundle':
                return False
            
            # Must have entry array (can be empty)
            if 'entry' not in json_data:
                return False
            
            # Entry must be a list
            if not isinstance(json_data['entry'], list):
                return False
            
            # If entries exist, check for at least one Claim resource
            if len(json_data['entry']) > 0:
                has_claim = any(
                    entry.get('resource', {}).get('resourceType') == 'Claim'
                    for entry in json_data['entry']
                )
                # Log warning if no Claim found, but don't reject
                if not has_claim:
                    logger.warning("FHIR Bundle has no Claim resource")
            
            logger.debug("FHIR Bundle structure validation passed")
            return True
            
        except Exception as e:
            logger.debug("FHIR structure validation failed", error=str(e))
            return False
    
    def validate_x12_structure(self, json_data: Dict[str, Any]) -> bool:
        """
        Validate X12 JSON structure (future implementation).
        
        Args:
            json_data: Parsed JSON data
            
        Returns:
            True if valid X12 JSON structure
        """
        # Future implementation for X12 278 and X12 275
        # Check for X12-specific fields like:
        # - transactionSetIdentifierCode
        # - transactionSetControlNumber
        # - etc.
        
        try:
            # Placeholder logic - check for common X12 fields
            if not isinstance(json_data, dict):
                return False
            
            # Check for X12 transaction set identifier
            if 'transactionSetIdentifierCode' in json_data:
                return True
            
            # Check for X12 interchange control header
            if 'interchangeControlHeader' in json_data:
                return True
            
            return False
            
        except Exception as e:
            logger.debug("X12 structure validation failed", error=str(e))
            return False
    
    def _determine_x12_type(self, json_data: Dict[str, Any]) -> DocumentFormat:
        """
        Determine specific X12 transaction type.
        
        Args:
            json_data: Parsed X12 JSON data
            
        Returns:
            DocumentFormat enum for specific X12 type
        """
        # Check transaction set identifier code
        transaction_code = json_data.get('transactionSetIdentifierCode', '')
        
        if transaction_code == '278':
            return DocumentFormat.X12_278_JSON
        elif transaction_code == '275':
            return DocumentFormat.X12_275_JSON
        else:
            logger.warning("Unknown X12 transaction type", 
                          transaction_code=transaction_code)
            return DocumentFormat.UNKNOWN
    
    def _analyze_file_content(self, bucket: str, s3_key: str) -> DocumentFormat:
        """
        Analyze file content when extension/content-type are inconclusive.
        
        Args:
            bucket: S3 bucket name
            s3_key: S3 object key
            
        Returns:
            DocumentFormat enum value
        """
        try:
            # Read first 1KB to check file signature
            s3_client = self.s3_service.s3_client
            response = s3_client.get_object(
                Bucket=bucket,
                Key=s3_key,
                Range='bytes=0-1023'  # First 1KB
            )
            
            content = response['Body'].read()
            
            # Check for PDF signature
            if content.startswith(b'%PDF'):
                logger.debug("PDF signature detected in content")
                return DocumentFormat.PDF
            
            # Check for JSON signature (starts with { or [)
            content_str = content.decode('utf-8', errors='ignore').strip()
            if content_str.startswith('{') or content_str.startswith('['):
                logger.debug("JSON signature detected in content")
                # Need to read full file to determine JSON type
                return self._detect_json_format(bucket, s3_key, "unknown")
            
            # Unknown format
            logger.warning("Unable to determine format from content analysis")
            return DocumentFormat.UNKNOWN
            
        except Exception as e:
            logger.error("Content analysis failed", error=str(e))
            return DocumentFormat.UNKNOWN
