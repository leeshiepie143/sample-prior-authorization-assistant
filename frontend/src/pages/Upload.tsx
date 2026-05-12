import React, { useState, useEffect } from 'react';
import { Card, Progress, Typography, Spin, Button } from 'antd';
import { UploadOutlined, FileTextOutlined, CheckCircleOutlined, ThunderboltOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import DocumentUpload from '../components/Upload/DocumentUpload';
import { apiService, DocumentUploadResponse } from '../services/apiService';
const { Title, Text } = Typography;

interface UploadStep {
  title: string;
  description: string;
  completed: boolean;
  status: 'waiting' | 'processing' | 'completed' | 'error';
  key: string;
}

interface ProcessingError {
  title: string;
  message: string;
  errorCode?: string | 'error' | 'failed' | 'FAILED' | 'NO_POLICY_FOUND' | 'POLICY_SELECTION_ERROR' | 'PAYOR_NOT_CONFIGURED' | 'EXTRACTION_ERROR' | 'TIMEOUT_ERROR' | 'NETWORK_ERROR' | 'UPLOAD_ERROR';
  details?: string;
}

const Upload: React.FC = () => {
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<DocumentUploadResponse | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [processingStatus, setProcessingStatus] = useState<any>(null);
  const [pollingEnabled, setPollingEnabled] = useState(false);
  const [processingError, setProcessingError] = useState<ProcessingError | null>(null);
  const navigate = useNavigate();

  // Polling effect for processing status
  useEffect(() => {
    let interval: NodeJS.Timeout;

    if (pollingEnabled && uploadResult) {
      interval = setInterval(async () => {
        try {
          const status = await apiService.getDocumentStatus(uploadResult.document_id);
          setProcessingStatus(status);

          // Update current step based on status
          if (status.progress?.current_step) {
            const stepMap: { [key: string]: number } = {
              'upload': 0,
              'extraction': 1,
              'policy_search': 2,
              'policy_selection': 2, // Map to policy matching
              'assessment': 3,
              'completed': 4
            };

            const stepIndex = stepMap[status.progress.current_step] || 1;
            setCurrentStep(stepIndex);
          }

          // Check if policy extraction is in progress
          if (status.status === 'policy_extraction_initiated' || status.statusCode === 202) {
            setPollingEnabled(false);
            setProcessing(false);
            setProcessingError({
              title: 'Policy Extraction In Progress',
              message: status.message || `We are currently extracting policies for ${status.payor_name || 'this payor'} from their website. This process takes 5-10 minutes. Please check back shortly and retry your request.`,
              errorCode: 'POLICY_EXTRACTION_INITIATED',
              details: 'The system will automatically download and index the required policies.'
            });
          }
          // Check if processing is complete
          else if (status.status === 'completed' || status.status === 'SUCCEEDED') {
            setPollingEnabled(false);
            setProcessing(false);
            setCurrentStep(4); // All steps complete

            // Direct redirect to results without delay
            navigate(`/results/${uploadResult.document_id}`);
          } else if (status.status === 'failed' || status.status === 'FAILED' || status.status === 'error') {
            setPollingEnabled(false);
            setProcessing(false);

            // Extract and parse error details from status
            let errorMessage: string = 'There was an error processing your document.';
            let errorTitle: string = 'Processing Failed';
            let errorCode: string = status.status;
            let errorDetails: string | undefined = status.progress?.status;

            // Parse the error message from the status
            if (status.error) {
              const errorStr = status.error;

              // Check for policy extraction initiated (HTTP 202)
              if (errorStr.includes('Policy extraction has been initiated') || errorStr.includes('extraction_initiated')) {
                errorTitle = 'Policy Extraction In Progress';
                errorMessage = 'We are currently extracting policies for this payor from their website. This process takes 5-10 minutes. Please check back shortly and retry your request.';
                errorCode = 'POLICY_EXTRACTION_INITIATED';
              }
              // Check for specific error patterns and provide user-friendly messages
              else if (errorStr.includes('No policies available') || errorStr.includes('no policies found')) {
                errorTitle = 'No Policy Found';
                errorMessage = 'We could not find a matching policy for this payor in our knowledge base. Please ensure policy documents have been uploaded for this payor.';
                errorCode = 'NO_POLICY_FOUND';
              } else if (errorStr.includes('PolicySelectionError') || errorStr.includes('SelectorError')) {
                errorTitle = 'Policy Selection Error';
                // Extract the actual error message after the error type
                const match = errorStr.match(/:\s*(.+?)(?:\n|$)/);
                if (match && match[1]) {
                  errorMessage = match[1].trim();
                } else {
                  errorMessage = 'Unable to select an appropriate policy for this request. Please verify the payor information and try again.';
                }
                errorCode = 'POLICY_SELECTION_ERROR';
              } else if (errorStr.includes('payor') || errorStr.includes('Payor')) {
                errorTitle = 'Payor Configuration Error';
                errorMessage = 'The payor specified in your document is not configured in our system. Please contact support or verify the payor information.';
                errorCode = 'PAYOR_NOT_CONFIGURED';
              } else if (errorStr.includes('extraction') || errorStr.includes('Extraction')) {
                errorTitle = 'Document Extraction Error';
                errorMessage = 'We had trouble extracting information from your document. Please ensure the document contains clear medical information and try again.';
                errorCode = 'EXTRACTION_ERROR';
              } else if (errorStr.includes('timeout') || errorStr.includes('Timeout')) {
                errorTitle = 'Processing Timeout';
                errorMessage = 'Document processing took too long and timed out. Please try uploading your document again.';
                errorCode = 'TIMEOUT_ERROR';
              } else {
                // Use the raw error message if no pattern matches
                errorMessage = errorStr;
              }
            }

            setProcessingError({
              title: errorTitle,
              message: errorMessage,
              errorCode: errorCode,
              details: errorDetails
            });
          }
        } catch (error) {
          console.error('Error polling status:', error);
          setPollingEnabled(false);
          setProcessing(false);
          setProcessingError({
            title: 'Connection Error',
            message: 'Unable to check processing status. Please try again.',
            errorCode: 'NETWORK_ERROR'
          });
        }
      }, 2000); // Poll every 2 seconds
    }

    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [pollingEnabled, uploadResult, navigate]);

  const uploadSteps: UploadStep[] = [
    {
      title: 'Document Upload',
      description: 'Uploading your Prior Authorization document',
      completed: false,
      status: 'waiting',
      key: 'upload'
    },
    {
      title: 'Document Processing',
      description: 'Extracting medical information and codes',
      completed: false,
      status: 'waiting',
      key: 'extraction'
    },
    {
      title: 'Policy Matching',
      description: 'Finding relevant medical necessity policies',
      completed: false,
      status: 'waiting',
      key: 'policy_search'
    },
    {
      title: 'Document Assessment',
      description: 'AI analyzing medical necessity criteria',
      completed: false,
      status: 'waiting',
      key: 'assessment'
    },
  ];

  const handleFileUpload = async (file: File) => {
    try {
      setUploading(false); // Skip upload progress display
      setCurrentStep(0);
      setProcessingError(null); // Clear any previous errors

      // Upload the document directly
      const result = await apiService.uploadDocumentBase64(file);
      setUploadResult(result);

      // Start processing and polling immediately
      setProcessing(true);
      setPollingEnabled(true);
      setCurrentStep(1); // Move to processing step

    } catch (error: any) {
      setUploading(false);
      const errorMessage = apiService.handleError(error);
      setProcessingError({
        title: 'Upload Failed',
        message: errorMessage,
        errorCode: 'UPLOAD_ERROR'
      });
    }
  };

  const handleRetry = () => {
    setProcessingError(null);
    setUploadResult(null);
    setProcessing(false);
    setPollingEnabled(false);
    setCurrentStep(0);
  };

  const supportedFormats = [
    'PDF documents (.pdf)',
    'Microsoft Word (.doc, .docx)',
    'Images (.jpg, .jpeg, .png, .tiff)',
  ];

  const requirements = [
    'Document must contain Prior Authorization request information',
    'Medical records should include patient demographics and clinical information',
    'CPT codes and diagnosis codes should be clearly documented',
    'File size should not exceed 10MB',
  ];

  return (
    <div className="upload-page">
      {/* Error Display */}
      {processingError && (
        <div className="error-display-section">
          <div className="error-display-card">
            <div className="error-content">
              <div className="error-message-box">
                <div className="error-message-header">
                  <ExclamationCircleOutlined className="error-message-icon" />
                  {/* nosemgrep: jsx-not-internationalized */}
                  <span className="error-message-title">We Encountered an Error</span>
                </div>
                <div className="error-message-text">
                  {processingError.message}
                </div>
                {processingError.errorCode && (
                  <div className="error-code">
                    {/* nosemgrep: jsx-not-internationalized */}
                    Error Code: {processingError.errorCode}
                  </div>
                )}
              </div>

              <div className="error-actions">
                <Button
                  type="primary"
                  size="large"
                  icon={<UploadOutlined />}
                  onClick={handleRetry}
                  className="error-retry-button"
                >
                  {/* nosemgrep: jsx-not-internationalized */}
                  Upload New Document
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!uploading && !uploadResult && !processingError && (
        <>
          {/* Main Upload Card */}
          <div className="upload-main-card">
            <div className="upload-card-header">
              <UploadOutlined className="upload-icon" />
              <div className="upload-header-text">
                {/* nosemgrep: jsx-not-internationalized */}
                <h2>Upload Your Document</h2>
                {/* nosemgrep: jsx-not-internationalized */}
                <p>Drag and drop or click to select your Prior Authorization document</p>
              </div>
            </div>

            <div className="upload-dropzone">
              <DocumentUpload onFileUpload={handleFileUpload} />
            </div>
          </div>

          {/* Info Sections */}
          <div className="upload-info-grid">
            <div className="info-section">
              <div className="info-section-header">
                <FileTextOutlined className="info-section-icon" />
                {/* nosemgrep: jsx-not-internationalized */}
                <h3>Supported Formats</h3>
              </div>
              <ul className="info-list">
                {supportedFormats.map((format, index) => (
                  <li key={index} className="info-item">
                    <span className="info-bullet"></span>
                    {format}
                  </li>
                ))}
              </ul>
            </div>

            <div className="info-section">
              <div className="info-section-header">
                <CheckCircleOutlined className="info-section-icon" />
                {/* nosemgrep: jsx-not-internationalized */}
                <h3>Document Requirements</h3>
              </div>
              <ul className="info-list">
                {requirements.map((requirement, index) => (
                  <li key={index} className="info-item">
                    <span className="info-bullet success"></span>
                    {requirement}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}



      {uploadResult && !processingError && (
        <div className="processing-section">
          <Card className="processing-card-enhanced">
            <div className="processing-header">
              <div className="processing-icon-container">
                <ThunderboltOutlined className="processing-icon" />
              </div>
              <div>
                <Title level={3} style={{ margin: 0, color: '#ffffff' }}>
                  {/* nosemgrep: jsx-not-internationalized */}
                  Processing Your Document
                </Title>
                <Text style={{ color: 'rgba(255, 255, 255, 0.8)' }}>
                  {/* nosemgrep: jsx-not-internationalized */}
                  AI-powered assessment pipeline is analyzing your document
                </Text>
              </div>
            </div>

            <div className="processing-pipeline">
              {uploadSteps.map((step, index) => {
                const isCompleted = index < currentStep;
                const isCurrent = index === currentStep && processing;

                return (
                  <div
                    key={index}
                    className={`pipeline-step ${isCompleted ? 'completed' : isCurrent ? 'current' : 'waiting'}`}
                  >
                    <div className="pipeline-step-indicator">
                      <div className="pipeline-step-number">
                        {isCompleted ? (
                          '✓'
                        ) : isCurrent ? (
                          <Spin size="small" />
                        ) : (
                          index + 1
                        )}
                      </div>
                    </div>

                    <div className="pipeline-step-content">
                      <div className="pipeline-step-title">
                        {step.title}
                        {isCurrent && <span className="processing-badge">{/* nosemgrep: jsx-not-internationalized */}Processing...</span>}
                      </div>
                      <div className="pipeline-step-description">
                        {step.description}
                      </div>

                      {processingStatus && isCurrent && (
                        <div className="pipeline-step-progress">
                          <Progress
                            percent={processingStatus.progress?.percentage || 0}
                            size="small"
                            strokeColor="#6f42c1"
                            trailColor="rgba(255, 255, 255, 0.2)"
                          />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>


          </Card>
        </div>
      )}
    </div>
  );
};

export default Upload;