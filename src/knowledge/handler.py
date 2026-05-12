"""
Lambda handler for the Payor Policy Knowledge module.

This module provides the AWS Lambda entry point for policy management,
ingestion, and retrieval functionality.
"""

import json
import base64
from typing import Dict, Any

from knowledge.knowledge_base_setup import BedrockKnowledgeBaseManager
from knowledge.policy_ingestion import PolicyDocumentProcessor, PolicyIndexingService
from knowledge.policy_retrieval import PolicyRetrievalService, SearchQuery
from common.exceptions import AWSServiceError, PolicySelectionError, PriorAuthException
from common.logging_config import get_logger, get_audit_logger
from common.decorators import handle_processing_errors
from common.step_functions_utils import ContextAwareErrorHandler

logger = get_logger(__name__)
audit_logger = get_audit_logger()


@handle_processing_errors
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for policy knowledge operations.
    
    Expected event structure:
    {
        "action": "setup_kb" | "validate_infrastructure" | "get_infrastructure_status" | 
                 "ingest_policy" | "search_policies" | "get_policy" | "sync_kb",
        "knowledge_base_id": "string",  # Optional, for existing KB
        "force_setup": boolean,  # Optional, for setup_kb to force recreation
        "policy_data": {...},  # For ingest_policy
        "search_query": {...},  # For search_policies
        "policy_id": "string"  # For get_policy
    }
    """
    
    # Initialize context-aware error handler
    error_handler = ContextAwareErrorHandler(event)
    
    logger.info("Policy Knowledge handler invoked", 
               action=event.get('action'),
               request_id=context.aws_request_id if context else None)
    
    try:
        action = event.get('action')
        
        # Auto-detect action for Step Functions workflow
        if not action and error_handler.is_step_functions:  # nosemgrep: is-function-without-parentheses — is_step_functions is a boolean property, not a method
            # In Step Functions workflow, default to search_policies
            action = 'search_policies'
            logger.info("Auto-detected action for Step Functions workflow", action=action)
        
        if action == 'setup_kb':
            result = handle_setup_knowledge_base(event, context)
        elif action == 'validate_infrastructure':
            result = handle_validate_infrastructure(event, context)
        elif action == 'get_infrastructure_status':
            result = handle_get_infrastructure_status(event, context)
        elif action == 'ingest_policy':
            result = handle_ingest_policy(event, context)
        elif action == 'search_policies':
            result = handle_search_policies(event, context)
        elif action == 'get_policy':
            result = handle_get_policy(event, context)
        elif action == 'sync_kb':
            result = handle_sync_knowledge_base(event, context)
        else:
            raise ValueError(f"Unknown action: {action}")
        
        # Return success response based on context
        return error_handler.create_success_response(result)
    
    except PriorAuthException as e:
        logger.error("Processing failed with known error", error=str(e))
        return error_handler.handle_error(e, e.retry_able)
    
    except Exception as e:
        logger.error("Processing failed with unexpected error", error=str(e))
        return error_handler.handle_error(e, True)


def handle_setup_knowledge_base(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle Knowledge Base infrastructure setup"""
    
    logger.info("Setting up Knowledge Base infrastructure")
    
    kb_manager = BedrockKnowledgeBaseManager()
    
    # Check if force setup is requested
    force_setup = event.get('force_setup', False)
    
    if not force_setup:
        # Check if KB already exists
        existing_kb = kb_manager.get_knowledge_base_info()
        if existing_kb and existing_kb.get('status') == 'ACTIVE':
            logger.info("Knowledge Base already exists", kb_id=existing_kb['knowledge_base_id'])
            
            # Get current infrastructure status
            status_info = kb_manager.get_infrastructure_status()
            
            return {
                'status': 'exists',
                'knowledge_base_info': existing_kb,
                'infrastructure_status': status_info
            }
    
    # Set up complete infrastructure using the comprehensive method
    setup_result = kb_manager.setup_complete_infrastructure()
    
    return {
        'status': 'setup_completed',
        'setup_result': setup_result
    }


def handle_ingest_policy(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle policy document ingestion"""
    
    # Extract parameters
    policy_file_b64 = event.get('policy_file')
    filename = event.get('filename')
    payor = event.get('payor')
    policy_type = event.get('policy_type')
    
    if not all([policy_file_b64, filename, payor]):
        raise ValueError("policy_file, filename, and payor are required")
    
    # Decode file content
    try:
        file_content = base64.b64decode(policy_file_b64)
    except Exception as e:
        raise ValueError(f"Invalid base64 file content: {str(e)}")
    
    # Process policy document
    processor = PolicyDocumentProcessor()
    policy_data = processor.process_policy_document(
        file_content=file_content,
        filename=filename,
        payor=payor,
        policy_type=policy_type
    )
    
    # Index the policy
    indexing_service = PolicyIndexingService()
    index_info = indexing_service.index_policy_document(policy_data)
    
    # Log successful ingestion
    audit_logger.log_policy_access(
        policy_id=policy_data['policy_id'],
        payor=payor,
        access_type="ingest"
    )
    
    return {
        'status': 'ingested',
        'policy_id': policy_data['policy_id'],
        'index_info': index_info
    }


def handle_search_policies(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle policy search requests"""
    
    search_params = event.get('search_query', {})
    max_results = event.get('max_results', 15)
    
    # For Step Functions workflow, extract search parameters from extraction result
    if not search_params and event.get('extraction_result'):
        extraction_data = event['extraction_result']
        if isinstance(extraction_data, dict) and 'Payload' in extraction_data:
            # Handle Lambda response format
            payload = extraction_data['Payload']
            if isinstance(payload, dict) and 'extraction_result' in payload:
                extracted = payload['extraction_result']
                # Extract HCPCS and RxNorm codes from structured fields if available
                structured_fields = extracted.get('structured_fields', {})
                service_details = structured_fields.get('service_details', {})
                hcpcs_codes = service_details.get('hcpcs_codes', [])
                rxnorm_codes = service_details.get('rxnorm_codes', [])
                
                search_params = {
                    'payor': extracted.get('payor_name', ''),
                    'cpt_codes': extracted.get('cpt_codes', []),
                    'hcpcs_codes': hcpcs_codes,
                    'rxnorm_codes': rxnorm_codes,
                    'icd_codes': extracted.get('icd_codes', []),
                    'service_type': extracted.get('service_type', ''),
                    'clinical_area': None,
                    'urgency': structured_fields.get('urgency', 'routine'),
                    'patient_age_range': extracted.get('patient_info', {}).get('age_range'),
                    'patient_gender': extracted.get('patient_info', {}).get('gender')
                }
                logger.info("Extracted search parameters from workflow", 
                           search_params=search_params,
                           has_cpt=bool(search_params['cpt_codes']),
                           has_hcpcs=bool(search_params['hcpcs_codes']),
                           has_rxnorm=bool(search_params['rxnorm_codes']))
    
    # Validate required search parameters
    # Note: At least one of cpt_codes, hcpcs_codes, or rxnorm_codes must be present
    required_params = ['payor', 'icd_codes', 'service_type']
    missing_params = [param for param in required_params if not search_params.get(param)]
    
    # Check if at least one procedure/medication code type is present
    has_procedure_codes = bool(
        search_params.get('cpt_codes') or 
        search_params.get('hcpcs_codes') or 
        search_params.get('rxnorm_codes')
    )
    if not has_procedure_codes:
        missing_params.append('cpt_codes, hcpcs_codes, or rxnorm_codes')
    
    if missing_params:
        raise ValueError(f"Missing required search parameters: {missing_params}")
    
    # Create search query
    query = SearchQuery(
        payor=search_params['payor'],
        cpt_codes=search_params.get('cpt_codes', []),
        icd_codes=search_params['icd_codes'],
        service_type=search_params['service_type'],
        hcpcs_codes=search_params.get('hcpcs_codes', []),
        rxnorm_codes=search_params.get('rxnorm_codes', []),
        clinical_area=search_params.get('clinical_area'),
        urgency=search_params.get('urgency', 'routine'),
        patient_age_range=search_params.get('patient_age_range'),
        patient_gender=search_params.get('patient_gender')
    )
    
    # Perform search
    retrieval_service = PolicyRetrievalService()
    search_results = retrieval_service.search_policies(query, max_results)
    
    # Convert results to serializable format
    results_data = []
    for result in search_results:
        # Extract title from metadata (prefer title, then service-category, then policy_title)
        title = result.policy_title
        if result.metadata:
            title = result.metadata.get('title') or result.metadata.get('service-category') or title
        
        results_data.append({
            'policy_id': result.policy_id,
            'payor': result.payor,
            'policy_title': title,  # Use extracted title
            'title': title,  # Include 'title' for frontend compatibility
            'relevance_score': result.relevance_score,
            'confidence_score': result.confidence_score,
            'matched_content': result.matched_content,
            'metadata': result.metadata,
            'retrieved_at': result.retrieved_at.isoformat()
        })
    
    return {
        'status': 'success',
        'results_count': len(results_data),
        'search_results': results_data,
        'query_info': {
            'payor': query.payor,
            'cpt_codes': query.cpt_codes,
            'icd_codes': query.icd_codes,
            'service_type': query.service_type
        }
    }


def handle_get_policy(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle specific policy retrieval by ID"""
    
    policy_id = event.get('policy_id')
    if not policy_id:
        raise ValueError("policy_id is required")
    
    # Retrieve policy
    retrieval_service = PolicyRetrievalService()
    policy_data = retrieval_service.get_policy_by_id(policy_id)
    
    if not policy_data:
        return {
            'statusCode': 404,
            'body': json.dumps({
                'error': 'Policy not found',
                'policy_id': policy_id
            })
        }
    
    # Log policy access
    audit_logger.log_policy_access(
        policy_id=policy_id,
        payor=policy_data.get('metadata', {}).get('payor', 'unknown'),
        access_type="retrieve"
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'found',
            'policy_data': policy_data
        })
    }


def handle_sync_knowledge_base(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle Knowledge Base synchronization"""
    
    knowledge_base_id = event.get('knowledge_base_id')
    data_source_id = event.get('data_source_id')
    
    if not all([knowledge_base_id, data_source_id]):
        raise ValueError("knowledge_base_id and data_source_id are required")
    
    # Start sync process
    indexing_service = PolicyIndexingService()
    sync_result = indexing_service.sync_with_knowledge_base(
        knowledge_base_id, data_source_id
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'sync_started',
            'sync_result': sync_result
        })
    }


# Utility endpoints
def get_policies_by_payor(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Get all policies for a specific payor"""
    
    payor = event.get('payor')
    limit = event.get('limit', 20)
    
    if not payor:
        raise ValueError("payor is required")
    
    retrieval_service = PolicyRetrievalService()
    policies = retrieval_service.get_policies_by_payor(payor, limit)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'payor': payor,
            'policies_count': len(policies),
            'policies': policies
        })
    }


def get_policies_by_clinical_area(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Get policies for a specific clinical area"""
    
    clinical_area = event.get('clinical_area')
    limit = event.get('limit', 20)
    
    if not clinical_area:
        raise ValueError("clinical_area is required")
    
    retrieval_service = PolicyRetrievalService()
    policies = retrieval_service.get_policies_by_clinical_area(clinical_area, limit)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'clinical_area': clinical_area,
            'policies_count': len(policies),
            'policies': policies
        })
    }


def handle_validate_infrastructure(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle infrastructure validation requests"""
    
    logger.info("Validating Knowledge Base infrastructure")
    
    kb_manager = BedrockKnowledgeBaseManager()
    
    # Run validation
    validation_result = kb_manager.validate_infrastructure()
    
    # Get detailed status
    status_info = kb_manager.get_infrastructure_status()
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'validation_result': validation_result,
            'infrastructure_status': status_info
        })
    }


def handle_get_infrastructure_status(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle infrastructure status requests"""
    
    logger.info("Getting Knowledge Base infrastructure status")
    
    kb_manager = BedrockKnowledgeBaseManager()
    status_info = kb_manager.get_infrastructure_status()
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'infrastructure_status': status_info
        })
    }


# Health check endpoint
def health_check(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Health check endpoint for the Lambda function"""
    
    # Check Knowledge Base connectivity
    try:
        kb_manager = BedrockKnowledgeBaseManager()
        kb_info = kb_manager.get_knowledge_base_info()
        kb_status = 'available' if kb_info else 'not_configured'
    except Exception as e:
        kb_status = f'error: {str(e)}'
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'healthy',
            'service': 'policy-knowledge',
            'knowledge_base_status': kb_status,
            'timestamp': context.aws_request_id if context else 'local'
        })
    }
