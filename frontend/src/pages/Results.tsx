import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Typography,
  Button,
  Space,
  Alert,
  Spin,
  Progress
} from 'antd';
import {
  FileTextOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  InfoCircleOutlined,
  TrophyOutlined,
  BulbOutlined,
  UploadOutlined
} from '@ant-design/icons';
import { useQuery } from 'react-query';
import { apiService, CriterionAssessment } from '../services/apiService';
import { useNotification } from '../contexts/NotificationContext';

const { Paragraph } = Typography;

// Helper function to extract string values from various object formats
const extractStringValue = (value: any): string => {
  if (!value) return '';
  if (typeof value === 'string') return value;
  
  // Handle DynamoDB format: {type: 'String', stringValue: 'actual_value'}
  if (typeof value === 'object' && value.stringValue) {
    return value.stringValue;
  }
  
  // Handle Bedrock format: {value: 'actual_value', includeForEmbedding: true}
  if (typeof value === 'object' && value.value) {
    return extractStringValue(value.value); // Recursive in case nested
  }
  
  // Handle other object types - convert to JSON string
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  
  return String(value);
};

const Results: React.FC = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const { showError } = useNotification();


  // Query for assessment results
  const {
    data: results,
    isLoading,
    error
  } = useQuery(
    ['assessmentResults', documentId],
    () => apiService.getAssessmentResults(documentId!),
    {
      enabled: !!documentId,
      onError: (error: any) => {
        showError('Failed to Load Results', apiService.handleError(error));
      }
    }
  );





  const getCriterionTitle = (criterionId: string): string => {
    // Parse criterion ID to provide meaningful descriptions
    if (criterionId.startsWith('cpt_')) {
      const cptCode = criterionId.replace('cpt_', '');
      return `CPT Code ${cptCode} Medical Necessity`;
    } else if (criterionId.startsWith('icd_')) {
      const icdCode = criterionId.replace('icd_', '');
      return `Diagnosis Code ${icdCode} Documentation`;
    } else if (criterionId.includes('general_medical_necessity')) {
      return 'General Medical Necessity Requirements';
    } else if (criterionId.includes('prior_authorization')) {
      return 'Prior Authorization Requirements';
    } else if (criterionId.includes('clinical_')) {
      return 'Clinical Documentation Requirements';
    } else {
      // Fallback: make the ID more readable
      return criterionId
        .replace(/_/g, ' ')
        .replace(/\b\w/g, l => l.toUpperCase());
    }
  };

  const getOverallStatusInfo = (status: string, metCriteria: number, totalCriteria: number) => {
    switch (status) {
      case 'compliant':
        return {
          color: 'success',
          text: 'Compliant',
          description: `All medical necessity criteria are met. ${metCriteria} of ${totalCriteria} criteria met.`
        };
      case 'partially_compliant':
        return {
          color: 'warning',
          text: 'Partially Compliant',
          description: `Some criteria are met, but additional documentation may be needed. ${metCriteria} of ${totalCriteria} criteria met.`
        };
      case 'non_compliant':
        return {
          color: 'error',
          text: 'Non-Compliant',
          description: `Medical necessity criteria are not sufficiently met. ${metCriteria} of ${totalCriteria} criteria met.`
        };
      default:
        return {
          color: 'default',
          text: 'Unknown',
          description: 'Unable to determine compliance status.'
        };
    }
  };

  const [expandedCriteria, setExpandedCriteria] = useState<Set<string>>(new Set());
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());

  const toggleCriterion = (criterionId: string) => {
    const newExpanded = new Set(expandedCriteria);
    if (newExpanded.has(criterionId)) {
      newExpanded.delete(criterionId);
    } else {
      newExpanded.add(criterionId);
    }
    setExpandedCriteria(newExpanded);
  };

  const toggleSection = (sectionId: string) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(sectionId)) {
      newExpanded.delete(sectionId);
    } else {
      newExpanded.add(sectionId);
    }
    setExpandedSections(newExpanded);
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'met':
        return <CheckCircleOutlined style={{
          color: '#73d13d',
          fontSize: '20px',
          filter: 'drop-shadow(0 0 6px rgba(115, 209, 61, 0.4))'
        }} />;
      case 'not_met':
        return <ExclamationCircleOutlined style={{
          color: '#ff7875',
          fontSize: '20px',
          filter: 'drop-shadow(0 0 6px rgba(255, 120, 117, 0.4))'
        }} />;
      case 'partially_met':
        return <InfoCircleOutlined style={{
          color: '#ffa940',
          fontSize: '20px',
          filter: 'drop-shadow(0 0 6px rgba(255, 169, 64, 0.4))'
        }} />;
      default:
        return <InfoCircleOutlined style={{ color: '#6f42c1', fontSize: '20px' }} />;
    }
  };

  const renderCriterionSwimLane = (criterion: CriterionAssessment) => {
    const isExpanded = expandedCriteria.has(criterion.criterion_id);
    const statusClass = criterion.status.replace('_', '-');

    return (
      <div key={criterion.criterion_id} className={`criterion-swim-lane ${statusClass} ${isExpanded ? 'expanded' : ''}`}>
        {/* Swim Lane Header - Always Visible */}
        <div
          className="swim-lane-header"
          onClick={() => toggleCriterion(criterion.criterion_id)}
        >
          <div className="swim-lane-status-icon">
            {getStatusIcon(criterion.status)}
          </div>

          <div className="swim-lane-content">
            <div className="swim-lane-title">
              {/* nosemgrep: jsx-not-internationalized */}
              Criterion {criterion.criterion_id.replace('crit_', '')}
            </div>
            <div className="swim-lane-subtitle">
              {(criterion as any).description || 'No description available'}
            </div>
          </div>

          <div className="swim-lane-meta">
            <div className="confidence-score">
              {Math.round(criterion.confidence_score * 100)}%
            </div>
            <div className="expand-indicator">
              {isExpanded ? '−' : '+'}
            </div>
          </div>
        </div>

        {/* Expandable Details */}
        {isExpanded && (
          <div className="swim-lane-details">
            {/* Clinical Rationale */}
            {criterion.clinical_rationale && (
              <div className="detail-section">
                <div className="detail-header">
                  <BulbOutlined className="detail-icon" />
                  {/* nosemgrep: jsx-not-internationalized */}
                  <span className="detail-title">Clinical Rationale</span>
                </div>
                <div className="detail-content">
                  {criterion.clinical_rationale}
                </div>
              </div>
            )}

            {/* Supporting Evidence */}
            {criterion.supporting_evidence.length > 0 && (
              <div className="detail-section">
                <div className="detail-header">
                  <CheckCircleOutlined className="detail-icon" />
                  {/* nosemgrep: jsx-not-internationalized */}
                  <span className="detail-title">Supporting Evidence Found</span>
                </div>
                <div className="detail-content">
                  <ul className="evidence-list">
                    {criterion.supporting_evidence.map((evidence, idx) => (
                      <li key={idx} className="evidence-item found">
                        {evidence}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {/* Gaps Identified */}
            {criterion.gaps_identified.length > 0 && (
              <div className="detail-section">
                <div className="detail-header">
                  <ExclamationCircleOutlined className="detail-icon" />
                  {/* nosemgrep: jsx-not-internationalized */}
                  <span className="detail-title">Gaps Identified</span>
                </div>
                <div className="detail-content">
                  <ul className="evidence-list">
                    {criterion.gaps_identified.map((gap, idx) => (
                      <li key={idx} className="evidence-item missing">
                        {gap}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {/* Recommendations */}
            {criterion.recommendations.length > 0 && (
              <div className="detail-section">
                <div className="detail-header">
                  <BulbOutlined className="detail-icon" />
                  {/* nosemgrep: jsx-not-internationalized */}
                  <span className="detail-title">Recommendations</span>
                </div>
                <div className="detail-content">
                  <ul className="evidence-list">
                    {criterion.recommendations.map((rec, idx) => (
                      <li key={idx} className="evidence-item recommendation">
                        {rec}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  if (isLoading) {
    return (
      <div className="page-container" style={{ textAlign: 'center', padding: '60px 0' }}>
        <Spin size="large" />
        {/* nosemgrep: jsx-not-internationalized */}
        <Paragraph style={{ marginTop: 16 }}>Loading assessment results...</Paragraph>
      </div>
    );
  }

  if (error || !results) {
    return (
      <div className="page-container">
        <Alert
          message="Results Not Available"
          description="Unable to load assessment results. The document may still be processing or an error occurred."
          type="warning"
          showIcon
          action={
            <Space>
              <Button onClick={() => navigate('/upload')}>
                {/* nosemgrep: jsx-not-internationalized */}
                Upload New Document
              </Button>
              <Button type="primary" onClick={() => navigate('/upload')}>
                {/* nosemgrep: jsx-not-internationalized */}
                Upload New Document
              </Button>
            </Space>
          }
        />
      </div>
    );
  }

  // Calculate met criteria count
  const metCriteria = results.assessment_result.criteria_results.filter(
    (c: CriterionAssessment) => c.status === 'met'
  ).length;
  const totalCriteria = results.assessment_result.criteria_results.length;
  
  const overallStatus = getOverallStatusInfo(
    results.assessment_result.overall_compliance,
    metCriteria,
    totalCriteria
  );
  
  // Calculate average confidence score from all criteria assessments
  const averageConfidence = results.assessment_result.criteria_results.length > 0
    ? Math.round(
        (results.assessment_result.criteria_results.reduce(
          (sum: number, c: CriterionAssessment) => sum + c.confidence_score,
          0
        ) / results.assessment_result.criteria_results.length) * 100
      )
    : 0;



  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <div className="page-header-info">
            <h1 className="page-title">
              <FileTextOutlined className="page-title-icon" />
              Assessment Results
            </h1>
            <p className="page-description">
              {/* nosemgrep: jsx-not-internationalized */}
              Detailed medical necessity assessment and recommendations for your Prior Authorization request.
            </p>
          </div>
          <div className="page-actions">
            <Button
              type="primary"
              icon={<UploadOutlined />}
              onClick={() => navigate('/upload')}
              style={{
                background: 'linear-gradient(135deg, #6f42c1, #007acc)',
                border: 'none',
                boxShadow: '0 2px 8px rgba(111, 66, 193, 0.4)',
                borderRadius: '6px'
              }}
            >
              {/* nosemgrep: jsx-not-internationalized */}
              Upload New Document
            </Button>
          </div>
        </div>
      </div>

      <div className="content-section">
        {/* Overall Status Box */}
        <div className="compact-summary overall-status-box">
          {/* Assessment Status Row */}
          <div className="summary-row assessment-status">
            <div className="status-item primary">
              <div className={`status-icon ${overallStatus.color}`}>
                {overallStatus.color === 'success' ? <CheckCircleOutlined /> :
                  overallStatus.color === 'error' ? <ExclamationCircleOutlined /> :
                    <InfoCircleOutlined />}
              </div>
              <div className="status-content">
                <div className="status-label">{/* nosemgrep: jsx-not-internationalized */}Overall Status</div>
                <div className="status-value">{overallStatus.text}</div>
                <div className="status-description">{overallStatus.description}</div>
              </div>
            </div>

            <div className="status-item">
              <div className={`status-icon ${averageConfidence >= 80 ? 'success' : averageConfidence >= 60 ? 'warning' : 'error'}`}>
                <TrophyOutlined />
              </div>
              <div className="status-content">
                <div className="status-label">{/* nosemgrep: jsx-not-internationalized */}Review Confidence</div>
                <div className="status-value approval-percentage">{averageConfidence}%</div>
                <Progress
                  percent={averageConfidence}
                  strokeColor={
                    averageConfidence >= 80 ? '#52c41a' :
                      averageConfidence >= 60 ? '#ffa940' : '#ff7875'
                  }
                  trailColor="rgba(255, 255, 255, 0.1)"
                  strokeWidth={6}
                  showInfo={false}
                  size="small"
                />
              </div>
            </div>
          </div>

        </div>

        {/* Extracted Information Section */}
        <div className="content-section section-group">
          <div className="section-group-header">
            <h2 className="section-group-title">
              <FileTextOutlined className="section-icon" />
              Extracted Information
            </h2>
            <p className="section-group-description">
              {/* nosemgrep: jsx-not-internationalized */}
              Key information extracted from your uploaded document
            </p>
          </div>
          <div className="criteria-swim-lanes">
            {/* Patient Details Section */}
            <div className={`criterion-swim-lane info-lane ${expandedSections.has('patient-details') ? 'expanded' : ''}`}>
              <div className="swim-lane-header" onClick={() => toggleSection('patient-details')}>
                <div className="swim-lane-status-icon">
                  <InfoCircleOutlined style={{ 
                    color: '#6f42c1', 
                    fontSize: '20px',
                    filter: 'drop-shadow(0 0 6px rgba(111, 66, 193, 0.4))'
                  }} />
                </div>
                <div className="swim-lane-content">
                  <div className="swim-lane-title">{/* nosemgrep: jsx-not-internationalized */}Patient Details</div>
                  <div className="swim-lane-subtitle">
                    {/* nosemgrep: jsx-not-internationalized */}
                    Patient demographics and identification information
                  </div>
                </div>
                <div className="swim-lane-meta">
                  <div className="expand-indicator">
                    {expandedSections.has('patient-details') ? '−' : '+'}
                  </div>
                </div>
              </div>
              {expandedSections.has('patient-details') && (
                <div className="swim-lane-details">
                  <div className="detail-section">
                    <div className="detail-content">
                      <div className="extracted-data-grid">
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Name:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.patient_details?.name || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Date of Birth:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.patient_details?.dob || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Gender:</span>
                          <span className="data-value">{(results as any).extracted_data?.patient_info?.gender || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}MRN:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.patient_details?.mrn || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Address:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.patient_details?.address || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Phone:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.patient_details?.phone || 'N/A'}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Coverage Details Section */}
            <div className={`criterion-swim-lane info-lane ${expandedSections.has('coverage-details') ? 'expanded' : ''}`}>
              <div className="swim-lane-header" onClick={() => toggleSection('coverage-details')}>
                <div className="swim-lane-status-icon">
                  <InfoCircleOutlined style={{ 
                    color: '#6f42c1', 
                    fontSize: '20px',
                    filter: 'drop-shadow(0 0 6px rgba(111, 66, 193, 0.4))'
                  }} />
                </div>
                <div className="swim-lane-content">
                  <div className="swim-lane-title">{/* nosemgrep: jsx-not-internationalized */}Coverage Details</div>
                  <div className="swim-lane-subtitle">
                    {/* nosemgrep: jsx-not-internationalized */}
                    Insurance coverage and plan information
                  </div>
                </div>
                <div className="swim-lane-meta">
                  <div className="expand-indicator">
                    {expandedSections.has('coverage-details') ? '−' : '+'}
                  </div>
                </div>
              </div>
              {expandedSections.has('coverage-details') && (
                <div className="swim-lane-details">
                  <div className="detail-section">
                    <div className="detail-content">
                      <div className="extracted-data-grid">
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Payor Name:</span>
                          <span className="data-value">{results.policy_information.payor || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Plan Name:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.coverage_details?.plan_name || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Plan Type:</span>
                          <span className="data-value">{(results as any).extracted_data?.plan_type || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Coverage State:</span>
                          <span className="data-value">{(results as any).extracted_data?.coverage_state?.toUpperCase() || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Member ID:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.coverage_details?.member_id || 'N/A'}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Requested Service Details Section */}
            <div className={`criterion-swim-lane info-lane ${expandedSections.has('service-details') ? 'expanded' : ''}`}>
              <div className="swim-lane-header" onClick={() => toggleSection('service-details')}>
                <div className="swim-lane-status-icon">
                  <InfoCircleOutlined style={{ 
                    color: '#6f42c1', 
                    fontSize: '20px',
                    filter: 'drop-shadow(0 0 6px rgba(111, 66, 193, 0.4))'
                  }} />
                </div>
                <div className="swim-lane-content">
                  <div className="swim-lane-title">{/* nosemgrep: jsx-not-internationalized */}Requested Service Details</div>
                  <div className="swim-lane-subtitle">
                    {/* nosemgrep: jsx-not-internationalized */}
                    Service codes, diagnoses, and treatment information
                  </div>
                </div>
                <div className="swim-lane-meta">
                  <div className="expand-indicator">
                    {expandedSections.has('service-details') ? '−' : '+'}
                  </div>
                </div>
              </div>
              {expandedSections.has('service-details') && (
                <div className="swim-lane-details">
                  <div className="detail-section">
                    <div className="detail-content">
                      <div className="extracted-data-grid">
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Service Codes:</span>
                          <span className="data-value">
                            {(results as any).extracted_data?.cpt_codes?.join(', ') || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Service Descriptions:</span>
                          <span className="data-value">
                            {(results as any).extracted_data?.structured_fields?.service_details?.all_cpt_descriptions?.join('; ') || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Diagnosis Codes:</span>
                          <span className="data-value">
                            {(results as any).extracted_data?.icd_codes?.join(', ') || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Diagnosis Descriptions:</span>
                          <span className="data-value">
                            {(results as any).extracted_data?.structured_fields?.diagnosis_details?.diagnosis_descriptions?.join('; ') || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Treatment Start Date:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.service_details?.treatment_start_date || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Treatment End Date:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.service_details?.treatment_end_date || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Service Location:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.service_details?.service_location || 'N/A'}</span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Provider Name:</span>
                          <span className="data-value">{(results as any).extracted_data?.structured_fields?.service_details?.provider || 'N/A'}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Selected Policy Details Section */}
            <div className={`criterion-swim-lane info-lane ${expandedSections.has('policy-details') ? 'expanded' : ''}`}>
              <div className="swim-lane-header" onClick={() => toggleSection('policy-details')}>
                <div className="swim-lane-status-icon">
                  <InfoCircleOutlined style={{ 
                    color: '#6f42c1', 
                    fontSize: '20px',
                    filter: 'drop-shadow(0 0 6px rgba(111, 66, 193, 0.4))'
                  }} />
                </div>
                <div className="swim-lane-content">
                  <div className="swim-lane-title">{/* nosemgrep: jsx-not-internationalized */}Selected Policy Details</div>
                  <div className="swim-lane-subtitle">
                    {/* nosemgrep: jsx-not-internationalized */}
                    Policy documents and source information
                  </div>
                </div>
                <div className="swim-lane-meta">
                  <div className="expand-indicator">
                    {expandedSections.has('policy-details') ? '−' : '+'}
                  </div>
                </div>
              </div>
              {expandedSections.has('policy-details') && (
                <div className="swim-lane-details">
                  <div className="detail-section">
                    <div className="detail-content">
                      <div className="extracted-data-grid">
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Policy Title:</span>
                          <span className="data-value">
                            {extractStringValue((results as any).title || (results as any).policy_metadata?.title || (results as any).selected_policy?.policy_title) || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Relevance Score:</span>
                          <span className="data-value" style={{ 
                            color: results.policy_information.relevance_score >= 0.8 ? '#52c41a' : 
                                   results.policy_information.relevance_score >= 0.6 ? '#ffa940' : '#ff7875',
                            fontWeight: 600
                          }}>
                            {results.policy_information.relevance_score 
                              ? `${Math.round(results.policy_information.relevance_score * 100)}%` 
                              : 'N/A'}
                          </span>
                        </div>
                        <div className="data-item">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Payor:</span>
                          <span className="data-value">
                            {extractStringValue(results.policy_information.payor) || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Uploaded Patient Document:</span>
                          <span className="data-value">
                            {extractStringValue((results as any).extracted_data?.document_s3_uri) || 'N/A'}
                          </span>
                        </div>
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Selected Policy Source URL:</span>
                          <span className="data-value">
                            {(() => {
                              const urlString = extractStringValue((results as any).policy_metadata?.source_url);
                              return urlString ? (
                                <a 
                                  href={urlString} 
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                  className="policy-link"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {urlString}
                                </a>
                              ) : 'N/A';
                            })()}
                          </span>
                        </div>
                        <div className="data-item full-width">
                          <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}Selected Policy S3 URI:</span>
                          <span className="data-value">
                            {extractStringValue((results as any).policy_metadata?.s3_uri) || 'N/A'}
                          </span>
                        </div>
                        {(results as any).policy_metadata?.selection_rationale && (
                          <div className="data-item full-width">
                            <span className="data-label">{/* nosemgrep: jsx-not-internationalized */}AI Selection Rationale:</span>
                            <span className="data-value" style={{ fontStyle: 'italic', color: '#666' }}>
                              {extractStringValue((results as any).policy_metadata.selection_rationale)}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Detailed Criteria Assessment */}
        <div className="content-section section-group">
          <div className="section-group-header">
            <h2 className="section-group-title">
              <CheckCircleOutlined className="section-icon" />
              Detailed Criteria Assessment
            </h2>
            <p className="section-group-description">
              {/* nosemgrep: jsx-not-internationalized */}
              Each medical necessity criterion has been evaluated based on the provided documentation.
              Review the assessment details and recommendations below.
            </p>
          </div>

          <div className="criteria-swim-lanes">
            {results.assessment_result.criteria_results.map((criterion) =>
              renderCriterionSwimLane(criterion)
            )}
          </div>
        </div>
      </div>

      {/* Actionable Recommendations Section */}
      {results.assessment_result.gap_analysis && (
        <div className="content-section section-group recommendations-section">
          <div className="section-group-header">
            <h2 className="section-group-title">
              <BulbOutlined className="section-icon" />
              Actionable Recommendations
            </h2>
            <p className="section-group-description">
              {/* nosemgrep: jsx-not-internationalized */}
              Review these priority actions and missing evidence to improve your approval likelihood.
            </p>
          </div>

          <div className="criteria-swim-lanes">
            {/* Priority Actions Swim Lane */}
            {results.assessment_result.gap_analysis.priority_actions.length > 0 && (
              <div className={`criterion-swim-lane not-met ${expandedSections.has('priority-actions') ? 'expanded' : ''}`}>
                <div className="swim-lane-header" onClick={() => toggleSection('priority-actions')}>
                  <div className="swim-lane-status-icon">
                    <ExclamationCircleOutlined style={{
                      color: '#ffa940',
                      fontSize: '20px',
                      filter: 'drop-shadow(0 0 6px rgba(255, 169, 64, 0.4))'
                    }} />
                  </div>
                  <div className="swim-lane-content">
                    <div className="swim-lane-title">{/* nosemgrep: jsx-not-internationalized */}Priority Actions</div>
                    <div className="swim-lane-subtitle">
                      {/* nosemgrep: jsx-not-internationalized */}
                      Address these items first to maximize approval likelihood
                    </div>
                  </div>
                  <div className="swim-lane-meta">
                    <div className="confidence-score">{/* nosemgrep: jsx-not-internationalized */}High</div>
                    <div className="expand-indicator">
                      {expandedSections.has('priority-actions') ? '−' : '+'}
                    </div>
                  </div>
                </div>
                {expandedSections.has('priority-actions') && (
                  <div className="swim-lane-details">
                    <div className="detail-section">
                      <div className="detail-content">
                        <ul className="evidence-list">
                          {results.assessment_result.gap_analysis.priority_actions.map((action, index) => (
                            <li key={index} className="evidence-item recommendation">
                              {action}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Missing Evidence Swim Lane */}
            {results.assessment_result.gap_analysis.missing_evidence.length > 0 && (
              <div className={`criterion-swim-lane not-met ${expandedSections.has('missing-evidence') ? 'expanded' : ''}`}>
                <div className="swim-lane-header" onClick={() => toggleSection('missing-evidence')}>
                  <div className="swim-lane-status-icon">
                    <ExclamationCircleOutlined style={{
                      color: '#ff7875',
                      fontSize: '20px',
                      filter: 'drop-shadow(0 0 6px rgba(255, 120, 117, 0.4))'
                    }} />
                  </div>
                  <div className="swim-lane-content">
                    <div className="swim-lane-title">{/* nosemgrep: jsx-not-internationalized */}Missing Evidence</div>
                    <div className="swim-lane-subtitle">
                      {/* nosemgrep: jsx-not-internationalized */}
                      Documentation gaps that need to be addressed
                    </div>
                  </div>
                  <div className="swim-lane-meta">
                    <div className="confidence-score">{/* nosemgrep: jsx-not-internationalized */}Critical</div>
                    <div className="expand-indicator">
                      {expandedSections.has('missing-evidence') ? '−' : '+'}
                    </div>
                  </div>
                </div>
                {expandedSections.has('missing-evidence') && (
                  <div className="swim-lane-details">
                    <div className="detail-section">
                      <div className="detail-content">
                        <ul className="evidence-list">
                          {results.assessment_result.gap_analysis.missing_evidence.map((evidence, index) => (
                            <li key={index} className="evidence-item missing">
                              {evidence}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}


    </div>
  );
};

export default Results;