"""
Validation utilities for medical codes and healthcare data.

This module provides validation functions for CPT codes, ICD codes,
and other healthcare-specific data formats used in prior authorization.
"""

import re
from typing import List, Dict, Any, Optional
from datetime import datetime, date

from .exceptions import MedicalCodeValidationError, DataValidationError


class MedicalCodeValidator:
    """Validator for medical codes (CPT, ICD, etc.)"""
    
    # CPT code patterns
    CPT_PATTERN = re.compile(r'^\d{5}(-[A-Z0-9]{2})?$')  # 5 digits, optional modifier
    
    # ICD-10-CM patterns
    ICD10_PATTERN = re.compile(r'^[A-Z]\d{2}(\.[A-Z0-9]{1,4})?$')
    
    # Common payor names for validation
    VALID_PAYORS = {
        'aetna', 'anthem', 'bcbs', 'blue cross blue shield', 'cigna', 
        'humana', 'kaiser', 'medicare', 'medicaid', 'united healthcare',
        'unitedhealth', 'molina', 'centene', 'wellcare'
    }
    
    @classmethod
    def validate_cpt_code(cls, cpt_code: str) -> bool:
        """Validate CPT code format"""
        if not cpt_code or not isinstance(cpt_code, str):
            return False
        
        cpt_code = cpt_code.strip().upper()
        return bool(cls.CPT_PATTERN.match(cpt_code))
    
    @classmethod
    def validate_cpt_codes(cls, cpt_codes: List[str]) -> List[str]:
        """Validate list of CPT codes and return invalid ones"""
        invalid_codes = []
        for code in cpt_codes:
            if not cls.validate_cpt_code(code):
                invalid_codes.append(code)
        return invalid_codes
    
    @classmethod
    def validate_icd_code(cls, icd_code: str) -> bool:
        """Validate ICD-10 code format"""
        if not icd_code or not isinstance(icd_code, str):
            return False
        
        icd_code = icd_code.strip().upper()
        return bool(cls.ICD10_PATTERN.match(icd_code))
    
    @classmethod
    def validate_icd_codes(cls, icd_codes: List[str]) -> List[str]:
        """Validate list of ICD codes and return invalid ones"""
        invalid_codes = []
        for code in icd_codes:
            if not cls.validate_icd_code(code):
                invalid_codes.append(code)
        return invalid_codes
    
    @classmethod
    def validate_payor_name(cls, payor_name: str) -> bool:
        """Validate payor name against known payors"""
        if not payor_name or not isinstance(payor_name, str):
            return False
        
        payor_lower = payor_name.lower().strip()
        
        # Check exact matches first
        if payor_lower in cls.VALID_PAYORS:
            return True
        
        # Check partial matches for common variations
        for valid_payor in cls.VALID_PAYORS:
            if valid_payor in payor_lower or payor_lower in valid_payor:
                return True
        
        return False
    
    @classmethod
    def normalize_payor_name(cls, payor_name: str) -> str:
        """Normalize payor name to standard format"""
        if not payor_name:
            return payor_name
        
        payor_lower = payor_name.lower().strip()
        
        # Map common variations to standard names
        payor_mapping = {
            'bcbs': 'Blue Cross Blue Shield',
            'blue cross blue shield': 'Blue Cross Blue Shield',
            'united healthcare': 'United Healthcare',
            'unitedhealth': 'United Healthcare',
            'aetna': 'Aetna',
            'cigna': 'Cigna',
            'humana': 'Humana',
            'kaiser': 'Kaiser Permanente',
            'medicare': 'Medicare',
            'medicaid': 'Medicaid'
        }
        
        for key, standard_name in payor_mapping.items():
            if key in payor_lower:
                return standard_name
        
        # Return title case if no mapping found
        return payor_name.title()


class PatientDataValidator:
    """Validator for patient demographic and clinical data"""
    
    VALID_GENDERS = {'male', 'female', 'other', 'unknown'}
    
    @classmethod
    def validate_age_range(cls, age_range: str) -> bool:
        """Validate age range format (e.g., '60-70')"""
        if not age_range or not isinstance(age_range, str):
            return False
        
        pattern = re.compile(r'^\d{1,3}-\d{1,3}$')
        if not pattern.match(age_range):
            return False
        
        # Check that range makes sense
        start, end = map(int, age_range.split('-'))
        return 0 <= start <= end <= 120
    
    @classmethod
    def validate_gender(cls, gender: str) -> bool:
        """Validate gender value"""
        if not gender or not isinstance(gender, str):
            return False
        
        return gender.lower() in cls.VALID_GENDERS
    
    @classmethod
    def validate_patient_id(cls, patient_id: str) -> bool:
        """Validate patient ID format (should be anonymized)"""
        if not patient_id or not isinstance(patient_id, str):
            return False
        
        # Patient ID should be alphanumeric and at least 6 characters
        pattern = re.compile(r'^[A-Za-z0-9]{6,}$')
        return bool(pattern.match(patient_id))


class DocumentValidator:
    """Validator for document-related data"""
    
    SUPPORTED_FORMATS = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.tiff'}
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    @classmethod
    def validate_document_format(cls, filename: str) -> bool:
        """Validate document file format"""
        if not filename or not isinstance(filename, str):
            return False
        
        # Extract file extension
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        return f'.{extension}' in cls.SUPPORTED_FORMATS
    
    @classmethod
    def validate_document_size(cls, file_size: int) -> bool:
        """Validate document file size"""
        return 0 < file_size <= cls.MAX_FILE_SIZE
    
    @classmethod
    def validate_document_id(cls, document_id: str) -> bool:
        """Validate document ID format"""
        if not document_id or not isinstance(document_id, str):
            return False
        
        # Document ID should be UUID-like or alphanumeric
        uuid_pattern = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
        alphanumeric_pattern = re.compile(r'^[A-Za-z0-9_-]{8,}$')
        
        return bool(uuid_pattern.match(document_id) or alphanumeric_pattern.match(document_id))


class AssessmentValidator:
    """Validator for assessment and compliance data"""
    
    VALID_COMPLIANCE_STATUSES = {'compliant', 'non_compliant', 'partially_compliant'}
    VALID_CRITERION_STATUSES = {'met', 'not_met', 'partially_met'}
    
    @classmethod
    def validate_confidence_score(cls, score: float) -> bool:
        """Validate confidence score (0.0 to 1.0)"""
        return isinstance(score, (int, float)) and 0.0 <= score <= 1.0
    
    @classmethod
    def validate_compliance_status(cls, status: str) -> bool:
        """Validate overall compliance status"""
        return status in cls.VALID_COMPLIANCE_STATUSES
    
    @classmethod
    def validate_criterion_status(cls, status: str) -> bool:
        """Validate criterion assessment status"""
        return status in cls.VALID_CRITERION_STATUSES
    
    @classmethod
    def validate_approval_likelihood(cls, likelihood: float) -> bool:
        """Validate approval likelihood score"""
        return cls.validate_confidence_score(likelihood)


def validate_extracted_data(data: Dict[str, Any]) -> List[str]:
    """Validate extracted data and return list of validation errors"""
    errors = []
    
    # Validate required fields
    required_fields = ['document_id', 'cpt_codes', 'icd_codes', 'payor_name', 'patient_info']
    for field in required_fields:
        if field not in data or not data[field]:
            errors.append(f"Missing required field: {field}")
    
    # Validate document ID
    if 'document_id' in data and not DocumentValidator.validate_document_id(data['document_id']):
        errors.append("Invalid document ID format")
    
    # Validate CPT codes
    if 'cpt_codes' in data and isinstance(data['cpt_codes'], list):
        invalid_cpts = MedicalCodeValidator.validate_cpt_codes(data['cpt_codes'])
        if invalid_cpts:
            errors.append(f"Invalid CPT codes: {', '.join(invalid_cpts)}")
    
    # Validate ICD codes
    if 'icd_codes' in data and isinstance(data['icd_codes'], list):
        invalid_icds = MedicalCodeValidator.validate_icd_codes(data['icd_codes'])
        if invalid_icds:
            errors.append(f"Invalid ICD codes: {', '.join(invalid_icds)}")
    
    # Validate payor name
    if 'payor_name' in data and not MedicalCodeValidator.validate_payor_name(data['payor_name']):
        errors.append("Invalid or unrecognized payor name")
    
    # Validate extraction confidence
    if 'extraction_confidence' in data and not AssessmentValidator.validate_confidence_score(data['extraction_confidence']):
        errors.append("Invalid extraction confidence score")
    
    # Validate patient info
    if 'patient_info' in data and isinstance(data['patient_info'], dict):
        patient_errors = validate_patient_info(data['patient_info'])
        errors.extend(patient_errors)
    
    return errors


def validate_patient_info(patient_info: Dict[str, Any]) -> List[str]:
    """Validate patient information and return list of validation errors"""
    errors = []
    
    # Validate patient ID
    if 'patient_id' in patient_info and not PatientDataValidator.validate_patient_id(patient_info['patient_id']):
        errors.append("Invalid patient ID format")
    
    # Validate age range
    if 'age_range' in patient_info and not PatientDataValidator.validate_age_range(patient_info['age_range']):
        errors.append("Invalid age range format")
    
    # Validate gender
    if 'gender' in patient_info and not PatientDataValidator.validate_gender(patient_info['gender']):
        errors.append("Invalid gender value")
    
    return errors


def validate_assessment_result(result: Dict[str, Any]) -> List[str]:
    """Validate assessment result and return list of validation errors"""
    errors = []
    
    # Validate overall compliance
    if 'overall_compliance' in result and not AssessmentValidator.validate_compliance_status(result['overall_compliance']):
        errors.append("Invalid overall compliance status")
    
    # Validate approval likelihood
    if 'approval_likelihood' in result and not AssessmentValidator.validate_approval_likelihood(result['approval_likelihood']):
        errors.append("Invalid approval likelihood score")
    
    # Validate criteria results
    if 'criteria_results' in result and isinstance(result['criteria_results'], list):
        for i, criterion in enumerate(result['criteria_results']):
            if isinstance(criterion, dict):
                if 'status' in criterion and not AssessmentValidator.validate_criterion_status(criterion['status']):
                    errors.append(f"Invalid criterion status at index {i}")
                if 'confidence_score' in criterion and not AssessmentValidator.validate_confidence_score(criterion['confidence_score']):
                    errors.append(f"Invalid confidence score at index {i}")
    
    return errors
