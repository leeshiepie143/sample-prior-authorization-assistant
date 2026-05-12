"""
Policy selection validation and confidence scoring service.

This module provides comprehensive validation of policy selection decisions,
confidence scoring, and fallback mechanisms for edge cases and policy gaps.
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, date
from dataclasses import dataclass
from enum import Enum

from common.models import ExtractedData, SelectedPolicy, ClinicalCriterion
from common.exceptions import PolicySelectionError, DataValidationError
from common.decorators import handle_processing_errors, monitor_performance
from common.logging_config import get_logger, get_audit_logger
from common.utils import calculate_confidence_score
from common.validators import MedicalCodeValidator, AssessmentValidator
from knowledge.policy_retrieval import PolicySearchResult

logger = get_logger(__name__)
audit_logger = get_audit_logger()


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Represents a validation issue found during policy selection"""
    severity: ValidationSeverity
    category: str
    message: str
    field: Optional[str] = None
    recommendation: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of policy selection validation"""
    is_valid: bool
    confidence_score: float
    overall_quality: float
    issues: List[ValidationIssue]
    validation_summary: Dict[str, Any]


class PolicySelectionValidator:
    """Comprehensive validator for policy selection decisions"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.audit_logger = get_audit_logger()
    
    @handle_processing_errors
    @monitor_performance
    def validate_policy_selection(self, selected_policy: SelectedPolicy, 
                                extracted_data: ExtractedData,
                                candidate_policies: List[PolicySearchResult] = None) -> ValidationResult:
        """Perform comprehensive validation of policy selection"""
        
        self.logger.info("Validating policy selection",
                        policy_id=selected_policy.policy_id,
                        payor=selected_policy.payor)
        
        validation_issues = []
        
        # Core validation checks
        validation_issues.extend(self._validate_payor_match(selected_policy, extracted_data))
        validation_issues.extend(self._validate_policy_completeness(selected_policy))
        validation_issues.extend(self._validate_clinical_criteria(selected_policy, extracted_data))
        validation_issues.extend(self._validate_policy_recency(selected_policy))
        validation_issues.extend(self._validate_code_coverage(selected_policy, extracted_data))
        validation_issues.extend(self._validate_service_alignment(selected_policy, extracted_data))
        
        # Advanced validation checks
        if candidate_policies:
            validation_issues.extend(self._validate_selection_optimality(
                selected_policy, candidate_policies, extracted_data
            ))
        
        # Calculate confidence and quality scores
        confidence_score = self._calculate_confidence_score(selected_policy, extracted_data, validation_issues)
        quality_score = self._calculate_quality_score(selected_policy, extracted_data, validation_issues)
        
        # Determine overall validity
        critical_issues = [issue for issue in validation_issues if issue.severity == ValidationSeverity.CRITICAL]
        is_valid = len(critical_issues) == 0 and confidence_score >= 0.5
        
        # Create validation summary
        validation_summary = self._create_validation_summary(
            selected_policy, extracted_data, validation_issues, confidence_score, quality_score
        )
        
        # Log validation results
        self.audit_logger.log_processing_step(
            document_id=extracted_data.document_id,
            step_name="policy_validation",
            status="completed" if is_valid else "failed"
        )
        
        self.logger.info("Policy validation completed",
                        policy_id=selected_policy.policy_id,
                        is_valid=is_valid,
                        confidence_score=confidence_score,
                        issues_count=len(validation_issues))
        
        return ValidationResult(
            is_valid=is_valid,
            confidence_score=confidence_score,
            overall_quality=quality_score,
            issues=validation_issues,
            validation_summary=validation_summary
        )
    
    def _validate_payor_match(self, selected_policy: SelectedPolicy, 
                            extracted_data: ExtractedData) -> List[ValidationIssue]:
        """Validate payor matching between policy and extracted data"""
        
        issues = []
        
        # Exact payor match check
        if selected_policy.payor.lower() != extracted_data.payor_name.lower():
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="payor_mismatch",
                message=f"Policy payor '{selected_policy.payor}' does not match extracted payor '{extracted_data.payor_name}'",
                field="payor",
                recommendation="Verify payor information or select a different policy"
            ))
        
        # Payor name validation
        if not MedicalCodeValidator.validate_payor_name(selected_policy.payor):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="payor_validation",
                message=f"Payor name '{selected_policy.payor}' is not recognized as a standard payor",
                field="payor",
                recommendation="Verify payor name spelling and format"
            ))
        
        return issues
    
    def _validate_policy_completeness(self, selected_policy: SelectedPolicy) -> List[ValidationIssue]:
        """Validate completeness of policy information"""
        
        issues = []
        
        # Required fields check
        required_fields = {
            'policy_id': selected_policy.policy_id,
            'policy_title': selected_policy.policy_title,
            'payor': selected_policy.payor,
            'effective_date': selected_policy.effective_date
        }
        
        for field_name, field_value in required_fields.items():
            if not field_value or (isinstance(field_value, str) and not field_value.strip()):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    category="missing_required_field",
                    message=f"Required field '{field_name}' is missing or empty",
                    field=field_name,
                    recommendation=f"Ensure {field_name} is properly populated"
                ))
        
        # Policy title quality check
        if selected_policy.policy_title and len(selected_policy.policy_title) < 10:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="policy_title_quality",
                message="Policy title appears to be too short or incomplete",
                field="policy_title",
                recommendation="Verify policy title completeness"
            ))
        
        return issues
    
    def _validate_clinical_criteria(self, selected_policy: SelectedPolicy, 
                                  extracted_data: ExtractedData) -> List[ValidationIssue]:
        """Validate clinical criteria quality and completeness"""
        
        issues = []
        
        # Criteria existence check
        if not selected_policy.applicable_criteria:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="no_clinical_criteria",
                message="Selected policy has no applicable clinical criteria",
                field="applicable_criteria",
                recommendation="Select a policy with defined medical necessity criteria"
            ))
            return issues
        
        # Minimum criteria count
        if len(selected_policy.applicable_criteria) < 2:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="insufficient_criteria",
                message=f"Policy has only {len(selected_policy.applicable_criteria)} clinical criteria (minimum 2 recommended)",
                field="applicable_criteria",
                recommendation="Consider selecting a policy with more comprehensive criteria"
            ))
        
        # Criteria quality checks
        for i, criterion in enumerate(selected_policy.applicable_criteria):
            criterion_issues = self._validate_individual_criterion(criterion, i)
            issues.extend(criterion_issues)
        
        # Criteria relevance to extracted data
        relevant_criteria = self._count_relevant_criteria(selected_policy.applicable_criteria, extracted_data)
        if relevant_criteria == 0:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="criteria_relevance",
                message="No clinical criteria appear relevant to the extracted medical data",
                field="applicable_criteria",
                recommendation="Select a policy with criteria matching the medical case"
            ))
        elif relevant_criteria < len(selected_policy.applicable_criteria) * 0.5:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="low_criteria_relevance",
                message=f"Only {relevant_criteria} out of {len(selected_policy.applicable_criteria)} criteria appear relevant",
                field="applicable_criteria",
                recommendation="Consider selecting a more targeted policy"
            ))
        
        return issues
    
    def _validate_individual_criterion(self, criterion: ClinicalCriterion, index: int) -> List[ValidationIssue]:
        """Validate individual clinical criterion"""
        
        issues = []
        
        # Description quality
        if not criterion.description or len(criterion.description) < 10:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="criterion_description_quality",
                message=f"Criterion {index + 1} has insufficient description",
                field=f"criteria[{index}].description",
                recommendation="Ensure criterion has clear, detailed description"
            ))
        
        # Evidence requirements
        if not criterion.required_evidence:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="no_evidence_requirements",
                message=f"Criterion {index + 1} has no specified evidence requirements",
                field=f"criteria[{index}].required_evidence",
                recommendation="Define specific evidence requirements for criterion"
            ))
        
        # Clinical indicators
        if not criterion.clinical_indicators:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="no_clinical_indicators",
                message=f"Criterion {index + 1} has no clinical indicators specified",
                field=f"criteria[{index}].clinical_indicators",
                recommendation="Consider adding clinical indicators for better guidance"
            ))
        
        # Priority validation
        if criterion.priority not in ['critical', 'standard', 'optional']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="invalid_priority",
                message=f"Criterion {index + 1} has invalid priority '{criterion.priority}'",
                field=f"criteria[{index}].priority",
                recommendation="Set priority to 'critical', 'standard', or 'optional'"
            ))
        
        return issues
    
    def _validate_policy_recency(self, selected_policy: SelectedPolicy) -> List[ValidationIssue]:
        """Validate policy recency and currency"""
        
        issues = []
        
        try:
            effective_date = date.fromisoformat(selected_policy.effective_date)
            days_old = (date.today() - effective_date).days
            
            if days_old > 1095:  # 3 years
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="outdated_policy",
                    message=f"Policy is {days_old} days old and may be outdated",
                    field="effective_date",
                    recommendation="Verify policy is still current or find a more recent version"
                ))
            elif days_old > 1825:  # 5 years
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    category="very_outdated_policy",
                    message=f"Policy is {days_old} days old and likely outdated",
                    field="effective_date",
                    recommendation="Find a current version of the policy"
                ))
        
        except (ValueError, TypeError):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="invalid_effective_date",
                message="Policy effective date is invalid or missing",
                field="effective_date",
                recommendation="Verify and correct the policy effective date"
            ))
        
        return issues
    
    def _validate_code_coverage(self, selected_policy: SelectedPolicy, 
                              extracted_data: ExtractedData) -> List[ValidationIssue]:
        """Validate medical code coverage by the selected policy"""
        
        issues = []
        
        # Extract codes mentioned in criteria
        policy_codes = set()
        for criterion in selected_policy.applicable_criteria:
            # Look for codes in criterion description and evidence
            text_to_search = f"{criterion.description} {' '.join(criterion.required_evidence)}"
            
            # Find CPT codes
            import re
            cpt_matches = re.findall(r'\b(\d{5}(?:-[A-Z0-9]{2})?)\b', text_to_search)
            policy_codes.update(cpt_matches)
            
            # Find ICD codes
            icd_matches = re.findall(r'\b([A-Z]\d{2}(?:\.[A-Z0-9]{1,4})?)\b', text_to_search)
            policy_codes.update(icd_matches)
        
        # Check CPT code coverage
        extracted_cpts = set(extracted_data.cpt_codes)
        covered_cpts = policy_codes & extracted_cpts
        
        if extracted_cpts and not covered_cpts:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="no_cpt_coverage",
                message="Policy criteria do not explicitly mention any of the requested CPT codes",
                field="applicable_criteria",
                recommendation="Verify policy covers the requested procedures"
            ))
        
        # Check ICD code coverage
        extracted_icds = set(extracted_data.icd_codes)
        covered_icds = policy_codes & extracted_icds
        
        if extracted_icds and not covered_icds:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="no_icd_coverage",
                message="Policy criteria do not explicitly mention any of the diagnosis codes",
                field="applicable_criteria",
                recommendation="Verify policy covers the patient's diagnosis"
            ))
        
        return issues
    
    def _validate_service_alignment(self, selected_policy: SelectedPolicy, 
                                  extracted_data: ExtractedData) -> List[ValidationIssue]:
        """Validate alignment between policy and requested service type"""
        
        issues = []
        
        # Check if service type is mentioned in policy title or criteria
        service_mentioned = False
        
        # Check policy title
        if extracted_data.service_type.lower() in selected_policy.policy_title.lower():
            service_mentioned = True
        
        # Check criteria descriptions
        if not service_mentioned:
            for criterion in selected_policy.applicable_criteria:
                if extracted_data.service_type.lower() in criterion.description.lower():
                    service_mentioned = True
                    break
        
        if not service_mentioned:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="service_type_alignment",
                message=f"Service type '{extracted_data.service_type}' not clearly addressed in policy",
                field="policy_title",
                recommendation="Verify policy is appropriate for the requested service type"
            ))
        
        return issues
    
    def _validate_selection_optimality(self, selected_policy: SelectedPolicy,
                                     candidate_policies: List[PolicySearchResult],
                                     extracted_data: ExtractedData) -> List[ValidationIssue]:
        """Validate if the selected policy is optimal among candidates"""
        
        issues = []
        
        if len(candidate_policies) <= 1:
            return issues  # No alternatives to compare
        
        # Find the selected policy in candidates
        selected_candidate = None
        for candidate in candidate_policies:
            if candidate.policy_id == selected_policy.policy_id:
                selected_candidate = candidate
                break
        
        if not selected_candidate:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="selection_consistency",
                message="Selected policy not found among candidate policies",
                recommendation="Verify policy selection consistency"
            ))
            return issues
        
        # Check if selected policy has the highest relevance score
        higher_scored_policies = [
            p for p in candidate_policies 
            if p.relevance_score > selected_candidate.relevance_score
        ]
        
        if higher_scored_policies:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="suboptimal_selection",
                message=f"Selected policy has relevance score {selected_candidate.relevance_score:.3f}, but {len(higher_scored_policies)} policies have higher scores",
                recommendation="Consider reviewing the selection algorithm or criteria"
            ))
        
        return issues
    
    def _count_relevant_criteria(self, criteria: List[ClinicalCriterion], 
                               extracted_data: ExtractedData) -> int:
        """Count criteria that appear relevant to the extracted data"""
        
        relevant_count = 0
        
        # Keywords that indicate relevance
        relevance_keywords = (
            extracted_data.cpt_codes + 
            extracted_data.icd_codes + 
            [extracted_data.service_type.lower()] +
            extracted_data.patient_info.primary_diagnosis.lower().split()
        )
        
        for criterion in criteria:
            criterion_text = f"{criterion.description} {' '.join(criterion.required_evidence)}".lower()
            
            # Check if any relevance keywords appear in criterion
            if any(keyword.lower() in criterion_text for keyword in relevance_keywords if keyword):
                relevant_count += 1
        
        return relevant_count
    
    def _calculate_confidence_score(self, selected_policy: SelectedPolicy, 
                                  extracted_data: ExtractedData,
                                  validation_issues: List[ValidationIssue]) -> float:
        """Calculate confidence score for policy selection"""
        
        confidence_factors = {}
        
        # Base confidence from policy relevance score
        confidence_factors['policy_relevance'] = selected_policy.relevance_score
        
        # Payor match confidence
        payor_match = selected_policy.payor.lower() == extracted_data.payor_name.lower()
        confidence_factors['payor_match'] = 1.0 if payor_match else 0.0
        
        # Criteria quality confidence
        criteria_count = len(selected_policy.applicable_criteria)
        confidence_factors['criteria_quality'] = min(1.0, criteria_count / 5.0)  # Normalize to 5 criteria
        
        # Policy recency confidence
        confidence_factors['policy_recency'] = self._calculate_recency_confidence(selected_policy.effective_date)
        
        # Validation issues impact
        critical_issues = len([i for i in validation_issues if i.severity == ValidationSeverity.CRITICAL])
        warning_issues = len([i for i in validation_issues if i.severity == ValidationSeverity.WARNING])
        
        validation_penalty = (critical_issues * 0.3) + (warning_issues * 0.1)
        confidence_factors['validation_quality'] = max(0.0, 1.0 - validation_penalty)
        
        # Calculate weighted confidence score
        weights = {
            'policy_relevance': 0.3,
            'payor_match': 0.25,
            'criteria_quality': 0.2,
            'policy_recency': 0.15,
            'validation_quality': 0.1
        }
        
        return calculate_confidence_score(confidence_factors, weights)
    
    def _calculate_quality_score(self, selected_policy: SelectedPolicy, 
                               extracted_data: ExtractedData,
                               validation_issues: List[ValidationIssue]) -> float:
        """Calculate overall quality score for policy selection"""
        
        quality_factors = {}
        
        # Completeness score
        required_fields = [selected_policy.policy_id, selected_policy.policy_title, 
                          selected_policy.payor, selected_policy.effective_date]
        completeness = sum(1 for field in required_fields if field and str(field).strip()) / len(required_fields)
        quality_factors['completeness'] = completeness
        
        # Criteria richness
        criteria_richness = min(1.0, len(selected_policy.applicable_criteria) / 3.0)
        quality_factors['criteria_richness'] = criteria_richness
        
        # Evidence specificity
        total_evidence = sum(len(c.required_evidence) for c in selected_policy.applicable_criteria)
        evidence_score = min(1.0, total_evidence / 10.0)  # Normalize to 10 evidence items
        quality_factors['evidence_specificity'] = evidence_score
        
        # Issue severity impact
        critical_issues = len([i for i in validation_issues if i.severity == ValidationSeverity.CRITICAL])
        warning_issues = len([i for i in validation_issues if i.severity == ValidationSeverity.WARNING])
        
        issue_penalty = (critical_issues * 0.4) + (warning_issues * 0.2)
        quality_factors['issue_impact'] = max(0.0, 1.0 - issue_penalty)
        
        return calculate_confidence_score(quality_factors)
    
    def _calculate_recency_confidence(self, effective_date_str: str) -> float:
        """Calculate confidence based on policy recency"""
        
        try:
            effective_date = date.fromisoformat(effective_date_str)
            days_old = (date.today() - effective_date).days
            
            if days_old <= 365:  # 1 year
                return 1.0
            elif days_old <= 730:  # 2 years
                return 0.8
            elif days_old <= 1095:  # 3 years
                return 0.6
            else:
                return 0.3
        
        except (ValueError, TypeError):
            return 0.5  # Unknown date gets medium confidence
    
    def _create_validation_summary(self, selected_policy: SelectedPolicy,
                                 extracted_data: ExtractedData,
                                 validation_issues: List[ValidationIssue],
                                 confidence_score: float,
                                 quality_score: float) -> Dict[str, Any]:
        """Create comprehensive validation summary"""
        
        # Categorize issues by severity
        issues_by_severity = {
            'critical': [i for i in validation_issues if i.severity == ValidationSeverity.CRITICAL],
            'warning': [i for i in validation_issues if i.severity == ValidationSeverity.WARNING],
            'info': [i for i in validation_issues if i.severity == ValidationSeverity.INFO]
        }
        
        # Calculate coverage metrics
        total_cpts = len(extracted_data.cpt_codes)
        total_icds = len(extracted_data.icd_codes)
        relevant_criteria = self._count_relevant_criteria(selected_policy.applicable_criteria, extracted_data)
        
        return {
            'validation_timestamp': datetime.utcnow().isoformat(),
            'policy_info': {
                'policy_id': selected_policy.policy_id,
                'payor': selected_policy.payor,
                'relevance_score': selected_policy.relevance_score,
                'criteria_count': len(selected_policy.applicable_criteria)
            },
            'scores': {
                'confidence_score': confidence_score,
                'quality_score': quality_score,
                'relevance_score': selected_policy.relevance_score
            },
            'coverage_analysis': {
                'total_cpt_codes': total_cpts,
                'total_icd_codes': total_icds,
                'relevant_criteria': relevant_criteria,
                'criteria_relevance_ratio': relevant_criteria / max(1, len(selected_policy.applicable_criteria))
            },
            'validation_issues': {
                'total_issues': len(validation_issues),
                'critical_count': len(issues_by_severity['critical']),
                'warning_count': len(issues_by_severity['warning']),
                'info_count': len(issues_by_severity['info']),
                'issues_by_category': self._group_issues_by_category(validation_issues)
            },
            'recommendations': self._generate_recommendations(validation_issues, confidence_score)
        }
    
    def _group_issues_by_category(self, validation_issues: List[ValidationIssue]) -> Dict[str, int]:
        """Group validation issues by category"""
        
        category_counts = {}
        for issue in validation_issues:
            category_counts[issue.category] = category_counts.get(issue.category, 0) + 1
        
        return category_counts
    
    def _generate_recommendations(self, validation_issues: List[ValidationIssue], 
                                confidence_score: float) -> List[str]:
        """Generate actionable recommendations based on validation results"""
        
        recommendations = []
        
        # Critical issue recommendations
        critical_issues = [i for i in validation_issues if i.severity == ValidationSeverity.CRITICAL]
        if critical_issues:
            recommendations.append("Address critical validation issues before proceeding with medical record review")
        
        # Low confidence recommendations
        if confidence_score < 0.5:
            recommendations.append("Consider selecting an alternative policy due to low confidence score")
        elif confidence_score < 0.7:
            recommendations.append("Review policy selection carefully due to moderate confidence score")
        
        # Specific category recommendations
        categories = set(issue.category for issue in validation_issues)
        
        if 'payor_mismatch' in categories:
            recommendations.append("Verify payor information accuracy before proceeding")
        
        if 'no_clinical_criteria' in categories:
            recommendations.append("Select a policy with defined medical necessity criteria")
        
        if 'outdated_policy' in categories:
            recommendations.append("Verify policy currency or find a more recent version")
        
        # General recommendations
        if len(validation_issues) > 5:
            recommendations.append("Consider alternative policy selection due to multiple validation issues")
        
        return recommendations

