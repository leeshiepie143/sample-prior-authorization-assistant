"""
Lambda handler for the Medical Record Reviewer module.

This module provides the AWS Lambda entry point for clinical assessment,
evidence mapping, and gap analysis functionality.
"""

import json
from typing import Dict, Any

from reviewer.evidence_mapper import ClinicalEvidenceMapper, EvidenceQualityAssessor
from reviewer.compliance_engine import ComplianceAssessmentEngine, ComplianceAggregator, AssessmentContext
from reviewer.gap_analyzer import GapAnalysisEngine
from common.models import (
    ClinicalCriterion, 
    AssessmentResult, 
    GapAnalysis,
    ExtractedData,
    SelectedPolicy
)
from common.exceptions import AssessmentError, PriorAuthException
from common.logging_config import get_logger, get_audit_logger
from common.decorators import handle_processing_errors
from common.step_functions_utils import ContextAwareErrorHandler
from common.serialization import create_serializable_response
from common.utils import generate_assessment_id

logger = get_logger(__name__)
audit_logger = get_audit_logger()


@handle_processing_errors
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for medical record review operations.
    
    Expected event structure:
    {
        "action": "review_records" | "map_evidence" | "assess_compliance" | "analyze_gaps",
        "medical_records": "string",  # Medical record content
        "clinical_criteria": [...],  # List of ClinicalCriterion objects
        "extracted_data": {...},  # ExtractedData object
        "selected_policy": {...}  # SelectedPolicy object
    }
    """
    
    # Initialize context-aware error handler
    error_handler = ContextAwareErrorHandler(event)
    
    logger.info("Medical Record Reviewer handler invoked", 
               action=event.get('action'),
               request_id=context.aws_request_id if context else None)
    
    try:
        action = event.get('action', 'review_records')
        
        # Auto-detect action for Step Functions workflow
        if not action and error_handler.is_step_functions:  # nosemgrep: is-function-without-parentheses — is_step_functions is a boolean property, not a method
            # In Step Functions workflow, default to review_records
            action = 'review_records'
            logger.info("Auto-detected action for Step Functions workflow", action=action)
        
        if action == 'review_records':
            result = handle_complete_review(event, context)
        elif action == 'map_evidence':
            result = handle_evidence_mapping(event, context)
        elif action == 'assess_compliance':
            result = handle_compliance_assessment(event, context)
        elif action == 'analyze_gaps':
            result = handle_gap_analysis(event, context)
        else:
            raise ValueError(f"Unknown action: {action}")
        
        # Return success response based on context (with proper serialization)
        serializable_result = create_serializable_response(result)
        return error_handler.create_success_response(serializable_result)
    
    except PriorAuthException as e:
        logger.error("Processing failed with known error", error=str(e))
        return error_handler.handle_error(e, e.retry_able)
    
    except Exception as e:
        logger.error("Processing failed with unexpected error", error=str(e))
        return error_handler.handle_error(e, True)


def handle_complete_review(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle complete medical record review workflow"""
    
    # Extract and validate parameters from Step Functions workflow format
    # The actual structure from Step Functions is:
    # - extraction_result.Payload.extraction_result
    # - selector_result.Payload.body (JSON string)
    
    extraction_result = event.get('extraction_result', {})
    selector_result = event.get('selector_result', {})
    
    # Extract data from the Payload structure
    extractor_payload = extraction_result.get('Payload', {})
    selector_payload = selector_result.get('Payload', {})
    
    # Get extracted data from extractor
    extracted_data_dict = extractor_payload.get('extraction_result', {})
    
    # Parse selector result - handle both old format (body as JSON string) and new format (direct data)
    if 'body' in selector_payload:
        # Old format: selector_result.Payload.body (JSON string)
        selector_body_str = selector_payload.get('body', '{}')
        if isinstance(selector_body_str, str):
            selector_data = json.loads(selector_body_str)
        else:
            selector_data = selector_body_str
    else:
        # New format: selector_result.Payload (direct data from IntelligentPolicySelector)
        selector_data = selector_payload
    
    # Extract required parameters
    selected_policy_dict = selector_data.get('selected_policy', {})
    clinical_criteria_data = selected_policy_dict.get('applicable_criteria', [])
    
    # For medical_records, use the raw text from the extracted data
    medical_records = extracted_data_dict.get('raw_text', '')
    
    # Validate required parameters
    if not all([medical_records, extracted_data_dict, selected_policy_dict]):
        missing = []
        if not medical_records: missing.append('medical_records')
        if not extracted_data_dict: missing.append('extracted_data')
        if not selected_policy_dict: missing.append('selected_policy')
        
        # Log the actual event structure for debugging
        logger.error("Parameter validation failed", 
                    missing_params=missing,
                    event_keys=list(event.keys()),
                    extraction_keys=list(extraction_result.keys()) if extraction_result else [],
                    selector_keys=list(selector_result.keys()) if selector_result else [],
                    extractor_payload_keys=list(extractor_payload.keys()) if extractor_payload else [],
                    selector_payload_keys=list(selector_payload.keys()) if selector_payload else [])
        
        raise ValueError("medical_records, clinical_criteria, extracted_data, and selected_policy are required")
    
    logger.info("Parameters validated successfully", 
               criteria_count=len(clinical_criteria_data),
               has_medical_records=bool(medical_records),
               policy_id=selected_policy_dict.get('policy_id'),
               extracted_data_keys=list(extracted_data_dict.keys()) if isinstance(extracted_data_dict, dict) else type(extracted_data_dict).__name__)
    
    # Convert to objects
    try:
        clinical_criteria = [
            ClinicalCriterion.from_dict(criterion_dict) 
            for criterion_dict in clinical_criteria_data
        ]
        extracted_data = ExtractedData.from_dict(extracted_data_dict)
        selected_policy = SelectedPolicy.from_dict(selected_policy_dict)
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Create assessment context
    assessment_context = AssessmentContext(
        patient_age_range=extracted_data.patient_info.age_range,
        patient_gender=extracted_data.patient_info.gender,
        primary_diagnosis=extracted_data.patient_info.primary_diagnosis,
        comorbidities=extracted_data.patient_info.comorbidities,
        payor=extracted_data.payor_name,
        service_type=extracted_data.service_type,
        icd_codes=extracted_data.icd_codes,
        cpt_codes=extracted_data.cpt_codes
    )
    
    # Step 1: Map evidence to criteria
    evidence_mapper = ClinicalEvidenceMapper()
    evidence_mapping = evidence_mapper.map_evidence_to_criteria(
        medical_records, clinical_criteria, extracted_data.document_id
    )
    
    # Step 2: Assess compliance
    compliance_engine = ComplianceAssessmentEngine()
    criterion_assessments = compliance_engine.assess_criteria_compliance(
        clinical_criteria, evidence_mapping, assessment_context
    )
    
    # Step 3: Calculate overall compliance
    overall_compliance = ComplianceAggregator.calculate_overall_compliance(
        criterion_assessments, clinical_criteria
    )
    
    # Step 4: Analyze gaps and generate recommendations
    gap_analyzer = GapAnalysisEngine()
    gap_analysis = gap_analyzer.analyze_documentation_gaps(
        criterion_assessments, clinical_criteria, evidence_mapping, assessment_context
    )
    
    # Step 5: Assess evidence quality
    evidence_quality = EvidenceQualityAssessor.assess_evidence_quality(
        evidence_mapping, clinical_criteria
    )
    
    # Create final assessment result
    assessment_result = AssessmentResult(
        assessment_id=generate_assessment_id(),
        document_id=extracted_data.document_id,
        overall_compliance=overall_compliance['overall_status'],
        criteria_results=criterion_assessments,
        gap_analysis=gap_analysis,
        recommendations=gap_analysis.recommendations,
        approval_likelihood=0.0,  # Deprecated - no longer used
        processing_time_seconds=0.0  # Will be calculated by orchestrator
    )
    
    # Log successful assessment
    audit_logger.log_assessment_result(
        assessment_id=assessment_result.assessment_id,
        document_id=assessment_result.document_id,
        overall_compliance=assessment_result.overall_compliance,
        approval_likelihood=assessment_result.approval_likelihood
    )
    
    # Create serializable response
    response_data = {
        'status': 'review_completed',
        'assessment_result': assessment_result.to_dict(),
        'overall_compliance': overall_compliance,
        'evidence_quality': evidence_quality,
        'processing_summary': {
            'criteria_assessed': len(criterion_assessments),
            'evidence_matches_found': sum(len(matches) for matches in evidence_mapping.values()),
            'gaps_identified': len(gap_analysis.critical_gaps) + len(gap_analysis.missing_evidence),
            'recommendations_generated': len(gap_analysis.recommendations)
        }
    }
    
    # Use serialization utilities to handle datetime objects
    from common.serialization import create_serializable_response
    serializable_data = create_serializable_response(response_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps(serializable_data)
    }


def handle_evidence_mapping(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle evidence mapping only"""
    
    medical_records = event.get('medical_records')
    clinical_criteria_data = event.get('clinical_criteria', [])
    document_id = event.get('document_id', 'unknown')
    
    if not all([medical_records, clinical_criteria_data]):
        raise ValueError("medical_records and clinical_criteria are required")
    
    # Convert to objects
    try:
        clinical_criteria = [
            ClinicalCriterion.from_dict(criterion_dict) 
            for criterion_dict in clinical_criteria_data
        ]
    except Exception as e:
        raise ValueError(f"Invalid clinical_criteria format: {str(e)}")
    
    # Perform evidence mapping
    evidence_mapper = ClinicalEvidenceMapper()
    evidence_mapping = evidence_mapper.map_evidence_to_criteria(
        medical_records, clinical_criteria, document_id
    )
    
    # Assess evidence quality
    evidence_quality = EvidenceQualityAssessor.assess_evidence_quality(
        evidence_mapping, clinical_criteria
    )
    
    # Convert evidence mapping to serializable format
    serializable_mapping = {}
    for criterion_id, matches in evidence_mapping.items():
        serializable_mapping[criterion_id] = [
            {
                'criterion_id': match.criterion_id,
                'evidence_text': match.evidence_text,
                'match_type': match.match_type.value,
                'confidence_score': match.confidence_score,
                'source_section': match.source_section,
                'clinical_reasoning': match.clinical_reasoning,
                'supporting_quotes': match.supporting_quotes or []
            }
            for match in matches
        ]
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'evidence_mapping_completed',
            'evidence_mapping': serializable_mapping,
            'evidence_quality': evidence_quality,
            'mapping_summary': {
                'total_criteria': len(clinical_criteria),
                'criteria_with_evidence': evidence_quality['criteria_with_evidence'],
                'total_evidence_matches': sum(len(matches) for matches in evidence_mapping.values())
            }
        })
    }


def handle_compliance_assessment(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle compliance assessment only"""
    
    clinical_criteria_data = event.get('clinical_criteria', [])
    evidence_mapping_data = event.get('evidence_mapping', {})
    assessment_context_data = event.get('assessment_context', {})
    
    if not all([clinical_criteria_data, evidence_mapping_data, assessment_context_data]):
        raise ValueError("clinical_criteria, evidence_mapping, and assessment_context are required")
    
    # Convert to objects
    try:
        clinical_criteria = [
            ClinicalCriterion.from_dict(criterion_dict) 
            for criterion_dict in clinical_criteria_data
        ]
        
        assessment_context = AssessmentContext(
            patient_age_range=assessment_context_data.get('patient_age_range', 'unknown'),
            patient_gender=assessment_context_data.get('patient_gender', 'unknown'),
            primary_diagnosis=assessment_context_data.get('primary_diagnosis', ''),
            comorbidities=assessment_context_data.get('comorbidities', []),
            payor=assessment_context_data.get('payor', ''),
            service_type=assessment_context_data.get('service_type', ''),
            icd_codes=assessment_context_data.get('icd_codes', []),
            cpt_codes=assessment_context_data.get('cpt_codes', [])
        )
        
        # Convert evidence mapping (simplified for this handler)
        evidence_mapping = {}  # Would need to reconstruct EvidenceMatch objects
        
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Perform compliance assessment
    compliance_engine = ComplianceAssessmentEngine()
    criterion_assessments = compliance_engine.assess_criteria_compliance(
        clinical_criteria, evidence_mapping, assessment_context
    )
    
    # Calculate overall compliance
    overall_compliance = ComplianceAggregator.calculate_overall_compliance(
        criterion_assessments, clinical_criteria
    )
    
    # Create serializable response
    response_data = {
        'status': 'compliance_assessment_completed',
        'criterion_assessments': [assessment.to_dict() for assessment in criterion_assessments],
        'overall_compliance': overall_compliance
    }
    
    # Use serialization utilities to handle datetime objects
    from common.serialization import create_serializable_response
    serializable_data = create_serializable_response(response_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps(serializable_data)
    }


def handle_gap_analysis(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle gap analysis only"""
    
    criterion_assessments_data = event.get('criterion_assessments', [])
    clinical_criteria_data = event.get('clinical_criteria', [])
    assessment_context_data = event.get('assessment_context', {})
    
    if not all([criterion_assessments_data, clinical_criteria_data, assessment_context_data]):
        raise ValueError("criterion_assessments, clinical_criteria, and assessment_context are required")
    
    # Convert to objects (simplified conversion)
    try:
        clinical_criteria = [
            ClinicalCriterion.from_dict(criterion_dict) 
            for criterion_dict in clinical_criteria_data
        ]
        
        assessment_context = AssessmentContext(
            patient_age_range=assessment_context_data.get('patient_age_range', 'unknown'),
            patient_gender=assessment_context_data.get('patient_gender', 'unknown'),
            primary_diagnosis=assessment_context_data.get('primary_diagnosis', ''),
            comorbidities=assessment_context_data.get('comorbidities', []),
            payor=assessment_context_data.get('payor', ''),
            service_type=assessment_context_data.get('service_type', ''),
            icd_codes=assessment_context_data.get('icd_codes', []),
            cpt_codes=assessment_context_data.get('cpt_codes', [])
        )
        
        # Note: This is a simplified conversion - in practice would need full CriterionAssessment objects
        criterion_assessments = []  # Would convert from criterion_assessments_data
        
    except Exception as e:
        raise ValueError(f"Invalid input data format: {str(e)}")
    
    # Perform gap analysis
    gap_analyzer = GapAnalysisEngine()
    gap_analysis = gap_analyzer.analyze_documentation_gaps(
        criterion_assessments, clinical_criteria, {}, assessment_context
    )
    
    # Create serializable response
    response_data = {
        'status': 'gap_analysis_completed',
        'gap_analysis': gap_analysis.to_dict()
    }
    
    # Use serialization utilities to handle datetime objects
    from common.serialization import create_serializable_response
    serializable_data = create_serializable_response(response_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps(serializable_data)
    }


# Health check endpoint
def health_check(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Health check endpoint for the Lambda function"""
    
    # Test core components
    try:
        evidence_mapper = ClinicalEvidenceMapper()
        compliance_engine = ComplianceAssessmentEngine()
        gap_analyzer = GapAnalysisEngine()
        
        component_status = {
            'evidence_mapper': 'healthy',
            'compliance_engine': 'healthy',
            'gap_analyzer': 'healthy'
        }
        
    except Exception as e:
        component_status = {
            'error': str(e)
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'healthy',
            'service': 'medical-record-reviewer',
            'components': component_status,
            'timestamp': context.aws_request_id if context else 'local'
        })
    }
