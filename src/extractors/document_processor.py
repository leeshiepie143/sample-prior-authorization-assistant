"""
Document processing module for the Medical Records Extractor.

This module handles document upload, validation, and text extraction
using Amazon Textract for OCR and document analysis.
"""

import os
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from common.aws_clients import get_textract_service, get_s3_service
from common.models import ProcessingState, ProcessingStatus
from common.exceptions import DocumentParsingException, AWSServiceError
from common.decorators import handle_processing_errors, monitor_performance, audit_processing_step
from common.validators import DocumentValidator
from common.utils import generate_document_id, sanitize_filename, clean_text
from common.logging_config import get_logger

logger = get_logger(__name__)


class DocumentProcessor:
    """Handles document processing and text extraction"""
    
    def __init__(self):
        self.textract_service = get_textract_service()
        self.s3_service = get_s3_service()
        self.documents_bucket = os.getenv('DOCUMENTS_BUCKET')
        
        if not self.documents_bucket:
            raise ValueError("DOCUMENTS_BUCKET environment variable is required")
    
    @handle_processing_errors
    @monitor_performance
    @audit_processing_step("document_upload")
    def upload_document(self, file_content: bytes, filename: str, 
                       content_type: str = None) -> str:
        """Upload document to S3 and return document ID"""
        
        # Validate document
        if not DocumentValidator.validate_document_format(filename):
            raise DocumentParsingException(
                f"Unsupported document format: {filename}",
                document_id=None
            )
        
        if not DocumentValidator.validate_document_size(len(file_content)):
            raise DocumentParsingException(
                f"Document size exceeds maximum allowed size",
                document_id=None
            )
        
        # Generate document ID and sanitize filename
        document_id = generate_document_id()
        safe_filename = sanitize_filename(filename)
        s3_key = f"documents/{document_id}/{safe_filename}"
        
        # Determine content type
        if content_type is None:
            content_type = self._get_content_type(filename)
        
        try:
            # Upload to S3
            s3_url = self.s3_service.upload_document(
                bucket=self.documents_bucket,
                key=s3_key,
                content=file_content,
                content_type=content_type
            )
            
            logger.info("Document uploaded successfully", 
                       document_id=document_id,
                       filename=safe_filename,
                       size_bytes=len(file_content))
            
            return document_id
            
        except Exception as e:
            raise DocumentParsingException(
                f"Failed to upload document: {str(e)}",
                document_id=document_id
            )
    
    @handle_processing_errors
    @monitor_performance
    @audit_processing_step("text_extraction")
    def extract_text_from_document(self, document_id: str, object_key: Optional[str] = None) -> Dict[str, Any]:
        """Extract text from uploaded document using Textract"""
        
        try:
            # Use provided object_key or find document in S3
            if object_key:
                document_key = object_key
            else:
                document_key = self._find_document_key(document_id)
                if not document_key:
                    raise DocumentParsingException(
                        f"Document not found: {document_id}",
                        document_id=document_id
                    )
            
            # Extract text using Textract
            raw_text = self.textract_service.extract_text_from_document(
                bucket=self.documents_bucket,
                key=document_key
            )
            
            # Analyze document for structured data
            analysis_result = self.textract_service.analyze_document(
                bucket=self.documents_bucket,
                key=document_key,
                feature_types=['TABLES', 'FORMS']
            )
            
            # Process and structure the extracted data
            structured_data = self._process_textract_results(analysis_result)
            
            # Clean and normalize text
            cleaned_text = clean_text(raw_text)
            
            extraction_result = {
                'document_id': document_id,
                'raw_text': cleaned_text,
                'structured_data': structured_data,
                'extraction_metadata': {
                    'extracted_at': datetime.utcnow().isoformat(),
                    'text_length': len(cleaned_text),
                    'pages_processed': len(analysis_result.get('Blocks', [])),
                    'extraction_method': 'textract'
                }
            }
            
            logger.info("Text extraction completed",
                       document_id=document_id,
                       text_length=len(cleaned_text),
                       structured_fields=len(structured_data))
            
            return extraction_result
            
        except DocumentParsingException:
            raise
        except Exception as e:
            raise DocumentParsingException(
                f"Text extraction failed: {str(e)}",
                document_id=document_id
            )
    
    def _find_document_key(self, document_id: str) -> Optional[str]:
        """Find the S3 key for a document ID"""
        try:
            # List objects with the document ID prefix
            s3_client = self.s3_service.s3_client
            response = s3_client.list_objects_v2(
                Bucket=self.documents_bucket,
                Prefix=f"documents/{document_id}/"
            )
            
            contents = response.get('Contents', [])
            if contents:
                return contents[0]['Key']  # Return first match
            
            return None
            
        except Exception as e:
            logger.error("Failed to find document key", 
                        document_id=document_id, error=str(e))
            return None
    
    def _get_content_type(self, filename: str) -> str:
        """Determine content type from filename"""
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        
        content_types = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'tiff': 'image/tiff',
            'tif': 'image/tiff'
        }
        
        return content_types.get(extension, 'application/octet-stream')
    
    def _process_textract_results(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """Process Textract analysis results to extract structured data"""
        
        structured_data = {
            'forms': {},
            'tables': [],
            'key_value_pairs': {}
        }
        
        blocks = analysis_result.get('Blocks', [])
        
        # Create lookup maps
        block_map = {block['Id']: block for block in blocks}
        
        # Process form data (key-value pairs)
        for block in blocks:
            if block['BlockType'] == 'KEY_VALUE_SET':
                if 'KEY' in block.get('EntityTypes', []):
                    key_text = self._get_text_from_block(block, block_map)
                    value_block = self._get_value_block(block, block_map)
                    if value_block:
                        value_text = self._get_text_from_block(value_block, block_map)
                        if key_text and value_text:
                            structured_data['key_value_pairs'][key_text] = value_text
        
        # Process tables
        table_blocks = [block for block in blocks if block['BlockType'] == 'TABLE']
        for table_block in table_blocks:
            table_data = self._extract_table_data(table_block, block_map)
            if table_data:
                structured_data['tables'].append(table_data)
        
        return structured_data
    
    def _get_text_from_block(self, block: Dict[str, Any], block_map: Dict[str, Any]) -> str:
        """Extract text content from a Textract block"""
        text_parts = []
        
        if 'Relationships' in block:
            for relationship in block['Relationships']:
                if relationship['Type'] == 'CHILD':
                    for child_id in relationship['Ids']:
                        child_block = block_map.get(child_id)
                        if child_block and child_block['BlockType'] == 'WORD':
                            text_parts.append(child_block.get('Text', ''))
        
        return ' '.join(text_parts).strip()
    
    def _get_value_block(self, key_block: Dict[str, Any], block_map: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get the value block associated with a key block"""
        if 'Relationships' in key_block:
            for relationship in key_block['Relationships']:
                if relationship['Type'] == 'VALUE':
                    for value_id in relationship['Ids']:
                        return block_map.get(value_id)
        return None
    
    def _extract_table_data(self, table_block: Dict[str, Any], block_map: Dict[str, Any]) -> Optional[List[List[str]]]:
        """Extract table data from Textract table block"""
        if 'Relationships' not in table_block:
            return None
        
        # Find all cells in the table
        cells = []
        for relationship in table_block['Relationships']:
            if relationship['Type'] == 'CHILD':
                for cell_id in relationship['Ids']:
                    cell_block = block_map.get(cell_id)
                    if cell_block and cell_block['BlockType'] == 'CELL':
                        cells.append(cell_block)
        
        if not cells:
            return None
        
        # Organize cells by row and column
        table_data = {}
        for cell in cells:
            row_index = cell.get('RowIndex', 1) - 1  # Convert to 0-based
            col_index = cell.get('ColumnIndex', 1) - 1  # Convert to 0-based
            cell_text = self._get_text_from_block(cell, block_map)
            
            if row_index not in table_data:
                table_data[row_index] = {}
            table_data[row_index][col_index] = cell_text
        
        # Convert to list of lists
        if not table_data:
            return None
        
        max_row = max(table_data.keys())
        max_col = max(max(row.keys()) if row else [-1] for row in table_data.values())
        
        result = []
        for row_idx in range(max_row + 1):
            row = []
            for col_idx in range(max_col + 1):
                cell_text = table_data.get(row_idx, {}).get(col_idx, '')
                row.append(cell_text)
            result.append(row)
        
        return result if result else None


class DocumentValidationService:
    """Service for validating documents before processing"""
    
    @staticmethod
    def validate_document_content(file_content: bytes, filename: str) -> Tuple[bool, List[str]]:
        """Validate document content and return validation results"""
        errors = []
        
        # Check file size
        if not DocumentValidator.validate_document_size(len(file_content)):
            errors.append(f"File size {len(file_content)} bytes exceeds maximum allowed size")
        
        # Check file format
        if not DocumentValidator.validate_document_format(filename):
            errors.append(f"Unsupported file format: {filename}")
        
        # Check if file content is not empty
        if len(file_content) == 0:
            errors.append("File content is empty")
        
        # Basic file header validation
        if not DocumentValidationService._validate_file_header(file_content, filename):
            errors.append("File header does not match expected format")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def _validate_file_header(file_content: bytes, filename: str) -> bool:
        """Validate file header matches expected format"""
        if len(file_content) < 4:
            return False
        
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        header = file_content[:4]
        
        # Common file signatures
        signatures = {
            'pdf': [b'%PDF'],
            'jpg': [b'\xff\xd8\xff'],
            'jpeg': [b'\xff\xd8\xff'],
            'png': [b'\x89PNG'],
            'tiff': [b'II*\x00', b'MM\x00*'],
            'tif': [b'II*\x00', b'MM\x00*'],
            'doc': [b'\xd0\xcf\x11\xe0'],  # OLE compound document
            'docx': [b'PK\x03\x04']  # ZIP archive (DOCX is ZIP-based)
        }
        
        expected_signatures = signatures.get(extension, [])
        if not expected_signatures:
            return True  # Unknown format, assume valid
        
        for signature in expected_signatures:
            if file_content.startswith(signature):
                return True
        
        return False
