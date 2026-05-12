"""
General utility functions for the Prior Authorization Application.

This module provides common utility functions used across different
modules for data processing, formatting, and helper operations.
"""

import uuid
import hashlib
import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import re

from .models import ProcessingStatus


def generate_document_id() -> str:
    """Generate a unique document ID"""
    return str(uuid.uuid4())


def generate_assessment_id() -> str:
    """Generate a unique assessment ID"""
    return f"assessment_{uuid.uuid4().hex[:12]}"


def generate_evidence_id() -> str:
    """Generate a unique evidence ID"""
    return f"evidence_{uuid.uuid4().hex[:8]}"


def anonymize_patient_id(original_id: str) -> str:
    """Create anonymized patient ID from original identifier"""
    # Use SHA-256 hash and take first 12 characters
    hash_object = hashlib.sha256(original_id.encode())
    return f"patient_{hash_object.hexdigest()[:12]}"


def create_age_range(birth_date: Union[str, datetime]) -> str:
    """Create age range from birth date for privacy"""
    if isinstance(birth_date, str):
        try:
            birth_date = datetime.fromisoformat(birth_date.replace('Z', '+00:00'))
        except ValueError:
            # Try common date formats
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                try:
                    birth_date = datetime.strptime(birth_date, fmt)
                    break
                except ValueError:
                    continue
            else:
                return "unknown"
    
    # Calculate age
    today = datetime.now(timezone.utc)
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    
    # Create age ranges for privacy
    if age < 18:
        return "0-17"
    elif age < 30:
        return "18-29"
    elif age < 40:
        return "30-39"
    elif age < 50:
        return "40-49"
    elif age < 60:
        return "50-59"
    elif age < 70:
        return "60-69"
    elif age < 80:
        return "70-79"
    else:
        return "80+"


def extract_medical_codes_from_text(text: str) -> Dict[str, List[str]]:
    """Extract CPT and ICD codes from text using regex patterns"""
    
    # CPT code pattern (5 digits, optional modifier)
    cpt_pattern = re.compile(r'\b(\d{5}(?:-[A-Z0-9]{2})?)\b')
    
    # ICD-10 pattern (letter followed by 2 digits, optional decimal and more)
    icd_pattern = re.compile(r'\b([A-Z]\d{2}(?:\.[A-Z0-9]{1,4})?)\b')
    
    cpt_codes = list(set(cpt_pattern.findall(text)))
    icd_codes = list(set(icd_pattern.findall(text)))
    
    return {
        'cpt_codes': cpt_codes,
        'icd_codes': icd_codes
    }


def extract_payor_from_text(text: str) -> Optional[str]:
    """Extract payor name from text using common patterns"""
    
    # Common payor patterns
    payor_patterns = [
        r'\b(Aetna)\b',
        r'\b(Anthem)\b',
        r'\b(Blue Cross Blue Shield|BCBS)\b',
        r'\b(Cigna)\b',
        r'\b(Humana)\b',
        r'\b(Kaiser Permanente|Kaiser)\b',
        r'\b(Medicare)\b',
        r'\b(Medicaid)\b',
        r'\b(United Healthcare|UnitedHealth)\b',
        r'\b(Molina)\b',
        r'\b(Centene)\b',
        r'\b(WellCare)\b'
    ]
    
    text_upper = text.upper()
    
    for pattern in payor_patterns:
        match = re.search(pattern, text_upper, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def calculate_processing_progress(current_step: str) -> int:
    """Calculate processing progress percentage based on current step"""
    
    step_progress = {
        'uploaded': 10,
        'extracting': 30,
        'policy_retrieval': 50,
        'policy_selection': 70,
        'medical_review': 90,
        'completed': 100,
        'failed': 0
    }
    
    return step_progress.get(current_step, 0)


def format_currency(amount: float) -> str:
    """Format currency amount for display"""
    return f"${amount:,.2f}"


def format_datetime(dt: datetime) -> str:
    """Format datetime for consistent display"""
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to specified length with suffix"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def clean_text(text: str) -> str:
    """Clean and normalize text content"""
    if not text:
        return ""
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    
    # Remove special characters that might interfere with processing
    text = re.sub(r'[^\w\s\-\.\,\;\:\!\?\(\)]', '', text)
    
    return text


def extract_key_value_pairs(text: str) -> Dict[str, str]:
    """Extract key-value pairs from structured text"""
    
    pairs = {}
    
    # Pattern for "Key: Value" format
    kv_pattern = re.compile(r'([A-Za-z\s]+):\s*([^\n\r]+)')
    
    matches = kv_pattern.findall(text)
    for key, value in matches:
        clean_key = key.strip().lower().replace(' ', '_')
        clean_value = value.strip()
        if clean_value:
            pairs[clean_key] = clean_value
    
    return pairs


def calculate_confidence_score(factors: Dict[str, float], weights: Dict[str, float] = None) -> float:
    """Calculate weighted confidence score from multiple factors"""
    
    if not factors:
        return 0.0
    
    if weights is None:
        # Equal weights if not specified
        weights = {key: 1.0 for key in factors.keys()}
    
    total_weighted_score = 0.0
    total_weight = 0.0
    
    for factor, score in factors.items():
        weight = weights.get(factor, 1.0)
        total_weighted_score += score * weight
        total_weight += weight
    
    if total_weight == 0:
        return 0.0
    
    confidence = total_weighted_score / total_weight
    return max(0.0, min(1.0, confidence))  # Clamp between 0 and 1


def encode_base64(data: Union[str, bytes]) -> str:
    """Encode data to base64 string"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.b64encode(data).decode('utf-8')


def decode_base64(encoded_data: str) -> bytes:
    """Decode base64 string to bytes"""
    return base64.b64decode(encoded_data)


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """Safely load JSON with default fallback"""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any, default: Any = None) -> str:
    """Safely dump JSON with default serialization"""
    try:
        return json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(default or {})


def merge_dictionaries(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple dictionaries, with later ones taking precedence"""
    result = {}
    for d in dicts:
        if isinstance(d, dict):
            result.update(d)
    return result


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """Flatten nested dictionary"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def remove_duplicates(lst: List[Any], key_func: callable = None) -> List[Any]:
    """Remove duplicates from list, optionally using key function"""
    if key_func is None:
        return list(dict.fromkeys(lst))  # Preserves order
    
    seen = set()
    result = []
    for item in lst:
        key = key_func(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def is_valid_uuid(uuid_string: str) -> bool:
    """Check if string is a valid UUID"""
    if uuid_string is None or not isinstance(uuid_string, str):
        return False
    try:
        uuid.UUID(uuid_string)
        return True
    except (ValueError, TypeError):
        return False


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        max_name_length = 255 - len(ext) - 1 if ext else 255
        filename = f"{name[:max_name_length]}.{ext}" if ext else name[:255]
    
    return filename or "unnamed_file"
