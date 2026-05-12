"""
Medical Record Reviewer Module

Clinical assessment and compliance evaluation:
- Evidence mapping from medical records to policy criteria
- Compliance status assessment (Met/Not Met/Partially Met)
- Gap analysis and recommendation generation
- Clinical reasoning documentation
"""

from .evidence_mapper import (
    ClinicalEvidenceMapper,
    EvidenceQualityAssessor,
    EvidenceMatch,
    EvidenceMatchType,
    MedicalRecordSection
)
from .compliance_engine import (
    ComplianceAssessmentEngine,
    ComplianceAggregator,
    AssessmentContext,
    AssessmentDecision,
    CriterionEvaluation
)
from .gap_analyzer import (
    GapAnalysisEngine,
    DocumentationGap,
    RecommendationAction,
    GapSeverity,
    GapCategory
)
from .handler import lambda_handler, health_check

__all__ = [
    'ClinicalEvidenceMapper',
    'EvidenceQualityAssessor',
    'EvidenceMatch',
    'EvidenceMatchType',
    'MedicalRecordSection',
    'ComplianceAssessmentEngine',
    'ComplianceAggregator',
    'AssessmentContext',
    'AssessmentDecision',
    'CriterionEvaluation',
    'GapAnalysisEngine',
    'DocumentationGap',
    'RecommendationAction',
    'GapSeverity',
    'GapCategory',
    'lambda_handler',
    'health_check'
]
