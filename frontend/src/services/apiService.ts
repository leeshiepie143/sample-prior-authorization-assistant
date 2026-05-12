import axios, { AxiosInstance, AxiosResponse, AxiosError } from 'axios';

// API Configuration
const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || '';
const API_VERSION = 'v1';

// Types
export interface APIResponse<T = any> {
  data: T;
  message?: string;
  success: boolean;
}

export interface DocumentUploadResponse {
  document_id: string;
  status: string;
  execution_arn: string;
  started_at: string;
  message: string;
}

export interface DocumentStatus {
  document_id: string;
  status: 'processing' | 'completed' | 'failed' | 'error' | 'not_found' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'TIMED_OUT' | 'ABORTED' | 'POLICY_EXTRACTION_INITIATED' | 'policy_extraction_initiated';
  statusCode?: number;
  progress: {
    percentage: number;
    current_step: string;
    status: string;
  };
  started_at: string;
  last_updated: string;
  completed_at?: string;
  failed_at?: string;
  duration_seconds?: number;
  execution_arn?: string;
  error?: string;
  message?: string;
  payor_name?: string;
  extraction_initiated?: boolean;
  policy_extraction_arn?: string;
}

export interface AssessmentResult {
  document_id: string;
  title?: string;  // Policy title at top level
  assessment_result: {
    assessment_id: string;
    overall_compliance: 'compliant' | 'non_compliant' | 'partially_compliant';
    criteria_results: CriterionAssessment[];
    gap_analysis: GapAnalysis;
    recommendations: string[];
    approval_likelihood: number;
    processing_time_seconds: number;
    assessed_at: string;
  };
  policy_information: {
    selected_policy_id: string;
    payor: string;
    relevance_score: number;
  };
  policy_metadata?: {
    source_url: string;
    s3_uri: string;
    policy_title: string;
    effective_date: string;
  };
  processing_summary: {
    extraction_confidence: number;
    policy_selection_confidence: number;
    overall_compliance: string;
    approval_likelihood: number;
    criteria_assessed: number;
    gaps_identified: number;
  };
  completed_at: string;
  duration_seconds: number;
}

export interface CriterionAssessment {
  criterion_id: string;
  status: 'met' | 'not_met' | 'partially_met';
  supporting_evidence: string[];
  confidence_score: number;
  clinical_rationale: string;
  gaps_identified: string[];
  recommendations: string[];
  assessed_at: string;
  // Additional fields from the actual API response
  description?: string;
  required_evidence?: string[];
  clinical_indicators?: string[];
  exclusion_criteria?: string[];
  priority?: 'critical' | 'standard' | 'optional';
}

export interface GapAnalysis {
  missing_evidence: string[];
  critical_gaps: string[];
  recommendations: string[];
  priority_actions: string[];
  estimated_approval_likelihood: number;
}

class APIService {
  private api: AxiosInstance;

  constructor() {
    this.api = axios.create({
      baseURL: API_BASE_URL,  // Remove /api/v1 prefix to match API Gateway structure
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.setupInterceptors();
  }

  private setupInterceptors() {
    // Request interceptor to add auth token
    this.api.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('auth_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => {
        return Promise.reject(error);
      }
    );

    // Response interceptor for error handling
    this.api.interceptors.response.use(
      (response: AxiosResponse) => {
        return response;
      },
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          // Token expired or invalid
          localStorage.removeItem('auth_token');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  // Document Upload
  async uploadDocument(file: File): Promise<DocumentUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('filename', file.name);

    const response = await this.api.post<DocumentUploadResponse>('/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 60000, // 1 minute for file upload
    });

    return response.data;
  }

  // Alternative upload method using base64
  async uploadDocumentBase64(file: File): Promise<DocumentUploadResponse> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const base64Content = (reader.result as string).split(',')[1];
          
          const uploadData = {
            file_content: base64Content,
            filename: file.name,
            content_type: file.type,
          };

          const response = await this.api.post<DocumentUploadResponse>('/documents/upload', uploadData);
          resolve(response.data);
        } catch (error) {
          reject(error);
        }
      };
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.readAsDataURL(file);
    });
  }

  // Get Document Status
  async getDocumentStatus(documentId: string): Promise<DocumentStatus> {
    try {
      const response = await this.api.get<any>(`/documents/${documentId}/status`);
      const data = response.data;
      
      // Check if this is a 202 response (policy extraction initiated) in the body
      if (data.statusCode === 202 || data.status === 'policy_extraction_initiated') {
        // Return a special status indicating policy extraction is in progress
        return {
          document_id: documentId,
          status: 'POLICY_EXTRACTION_INITIATED' as any,
          statusCode: 202,
          payor_name: data.payor_name,
          extraction_initiated: data.extraction_initiated,
          policy_extraction_arn: data.policy_extraction_arn,
          progress: {
            percentage: 0,
            current_step: 'policy_extraction',
            status: data.message || 'Policy extraction has been initiated'
          },
          started_at: data.started_at || new Date().toISOString(),
          last_updated: data.last_updated || new Date().toISOString(),
          error: data.message,
          message: data.message
        } as any;
      }
      
      return data;
    } catch (error: any) {
      // Check if this is a 202 response (policy extraction initiated) in HTTP status
      if (error.response?.status === 202) {
        const data = error.response.data;
        // Return a special status indicating policy extraction is in progress
        return {
          document_id: documentId,
          status: 'POLICY_EXTRACTION_INITIATED' as any,
          statusCode: 202,
          payor_name: data.payor_name,
          extraction_initiated: data.extraction_initiated,
          policy_extraction_arn: data.policy_extraction_arn,
          progress: {
            percentage: 0,
            current_step: 'policy_extraction',
            status: data.message || 'Policy extraction has been initiated'
          },
          started_at: data.started_at || new Date().toISOString(),
          last_updated: data.last_updated || new Date().toISOString(),
          error: data.message,
          message: data.message
        } as any;
      }
      throw error;
    }
  }

  // Get Assessment Results
  async getAssessmentResults(documentId: string): Promise<AssessmentResult> {
    const response = await this.api.get<AssessmentResult>(`/results/${documentId}`);
    return response.data;
  }

  // Execute Workflow Directly
  async executeWorkflow(file: File, workflowType: string = 'standard'): Promise<DocumentUploadResponse> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const base64Content = (reader.result as string).split(',')[1];
          
          const workflowData = {
            file_content: base64Content,
            filename: file.name,
            content_type: file.type,
            workflow_type: workflowType,
          };

          const response = await this.api.post<DocumentUploadResponse>('/workflow/execute', workflowData);
          resolve(response.data);
        } catch (error) {
          reject(error);
        }
      };
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.readAsDataURL(file);
    });
  }

  // Health Check
  async healthCheck(): Promise<{ status: string; service: string; timestamp: string }> {
    const response = await this.api.get('/health');
    return response.data;
  }

  // Utility method to handle API errors
  handleError(error: AxiosError): string {
    if (error.response) {
      // Server responded with error status
      const errorData = error.response.data as any;
      return errorData.error || errorData.message || 'An error occurred';
    } else if (error.request) {
      // Request was made but no response received
      return 'Network error - please check your connection';
    } else {
      // Something else happened
      return error.message || 'An unexpected error occurred';
    }
  }

  // Polling utility for status updates
  async pollDocumentStatus(
    documentId: string,
    onUpdate: (status: DocumentStatus) => void,
    interval: number = 2000,
    maxAttempts: number = 150 // 5 minutes with 2-second intervals
  ): Promise<DocumentStatus> {
    let attempts = 0;
    
    return new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          attempts++;
          const status = await this.getDocumentStatus(documentId);
          onUpdate(status);

          // Check if processing is complete
          if (status.status === 'SUCCEEDED' || status.status === 'FAILED' || 
              status.status === 'TIMED_OUT' || status.status === 'ABORTED') {
            resolve(status);
            return;
          }

          // Check if max attempts reached
          if (attempts >= maxAttempts) {
            reject(new Error('Polling timeout - processing is taking longer than expected'));
            return;
          }

          // Continue polling
          setTimeout(poll, interval);
        } catch (error) {
          reject(error);
        }
      };

      poll();
    });
  }
}

// Create and export singleton instance
export const apiService = new APIService();
export default apiService;