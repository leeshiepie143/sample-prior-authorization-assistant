import axios from 'axios';
import { 
  uploadDocument, 
  getDocumentStatus, 
  getDocumentResults,
  executeWorkflow,
  checkHealth
} from '../../services/apiService';

// Mock axios
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

// Mock auth service
jest.mock('../../services/authService', () => ({
  getAuthToken: jest.fn(() => 'mock-jwt-token'),
  isAuthenticated: jest.fn(() => true)
}));

describe('API Service', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    
    // Setup default axios mock
    mockedAxios.create.mockReturnValue(mockedAxios);
    mockedAxios.interceptors = {
      request: { use: jest.fn() },
      response: { use: jest.fn() }
    } as any;
  });

  describe('uploadDocument', () => {
    test('uploads document successfully', async () => {
      const mockResponse = {
        data: {
          document_id: 'test-doc-123',
          status: 'uploaded',
          execution_arn: 'arn:aws:states:us-east-1:123456789012:execution:test:exec1',
          message: 'Document uploaded successfully'
        }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const testFile = new File(['test content'], 'test-document.pdf', {
        type: 'application/pdf'
      });

      const result = await uploadDocument(testFile);

      expect(mockedAxios.post).toHaveBeenCalledWith(
        '/api/v1/documents/upload',
        expect.any(FormData),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'multipart/form-data'
          })
        })
      );

      expect(result).toEqual(mockResponse.data);
    });

    test('handles upload progress callback', async () => {
      const mockResponse = {
        data: { document_id: 'test-doc-123', status: 'uploaded' }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const testFile = new File(['test content'], 'test-document.pdf', {
        type: 'application/pdf'
      });

      const progressCallback = jest.fn();

      await uploadDocument(testFile, progressCallback);

      expect(mockedAxios.post).toHaveBeenCalledWith(
        '/api/v1/documents/upload',
        expect.any(FormData),
        expect.objectContaining({
          onUploadProgress: expect.any(Function)
        })
      );
    });

    test('handles upload error', async () => {
      const errorResponse = {
        response: {
          status: 400,
          data: {
            error: 'Invalid file format',
            error_code: 'VALIDATION_ERROR'
          }
        }
      };

      mockedAxios.post.mockRejectedValue(errorResponse);

      const testFile = new File(['test content'], 'invalid-file.txt', {
        type: 'text/plain'
      });

      await expect(uploadDocument(testFile)).rejects.toThrow('Invalid file format');
    });

    test('handles network error', async () => {
      mockedAxios.post.mockRejectedValue(new Error('Network Error'));

      const testFile = new File(['test content'], 'test-document.pdf', {
        type: 'application/pdf'
      });

      await expect(uploadDocument(testFile)).rejects.toThrow('Network Error');
    });
  });

  describe('getDocumentStatus', () => {
    test('gets document status successfully', async () => {
      const mockResponse = {
        data: {
          document_id: 'test-doc-123',
          status: 'RUNNING',
          progress: {
            percentage: 45,
            current_step: 'PolicySelection'
          },
          started_at: '2024-01-20T10:00:00Z',
          last_updated: '2024-01-20T10:05:00Z'
        }
      };

      mockedAxios.get.mockResolvedValue(mockResponse);

      const result = await getDocumentStatus('test-doc-123');

      expect(mockedAxios.get).toHaveBeenCalledWith('/api/v1/documents/test-doc-123/status');
      expect(result).toEqual(mockResponse.data);
    });

    test('handles document not found', async () => {
      const errorResponse = {
        response: {
          status: 404,
          data: {
            error: 'Document not found: test-doc-123',
            error_code: 'DOCUMENT_NOT_FOUND'
          }
        }
      };

      mockedAxios.get.mockRejectedValue(errorResponse);

      await expect(getDocumentStatus('test-doc-123')).rejects.toThrow('Document not found');
    });
  });

  describe('getDocumentResults', () => {
    test('gets document results successfully', async () => {
      const mockResponse = {
        data: {
          document_id: 'test-doc-123',
          assessment_result: {
            overall_compliance: 'compliant',
            approval_likelihood: 0.85,
            criteria_results: []
          },
          policy_information: {
            policy_id: 'TEST-POLICY-001',
            payor: 'Test Insurance'
          },
          processing_summary: {
            criteria_assessed: 5,
            gaps_identified: 1
          },
          completed_at: '2024-01-20T10:10:00Z',
          duration_seconds: 300
        }
      };

      mockedAxios.get.mockResolvedValue(mockResponse);

      const result = await getDocumentResults('test-doc-123');

      expect(mockedAxios.get).toHaveBeenCalledWith('/api/v1/documents/test-doc-123/results');
      expect(result).toEqual(mockResponse.data);
    });

    test('handles processing still in progress', async () => {
      const errorResponse = {
        response: {
          status: 202,
          data: {
            error: 'Processing still in progress',
            error_code: 'PROCESSING_IN_PROGRESS'
          }
        }
      };

      mockedAxios.get.mockRejectedValue(errorResponse);

      await expect(getDocumentResults('test-doc-123')).rejects.toThrow('Processing still in progress');
    });
  });

  describe('executeWorkflow', () => {
    test('executes workflow successfully', async () => {
      const mockResponse = {
        data: {
          execution_id: 'workflow-exec-123',
          execution_arn: 'arn:aws:states:us-east-1:123456789012:execution:test:exec1',
          workflow_type: 'standard',
          started_at: '2024-01-20T10:00:00Z',
          status: 'started'
        }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const workflowData = {
        file_content: 'base64-encoded-content',
        filename: 'test-document.pdf',
        content_type: 'application/pdf',
        workflow_type: 'standard'
      };

      const result = await executeWorkflow(workflowData);

      expect(mockedAxios.post).toHaveBeenCalledWith('/api/v1/workflow/execute', workflowData);
      expect(result).toEqual(mockResponse.data);
    });

    test('handles workflow execution error', async () => {
      const errorResponse = {
        response: {
          status: 500,
          data: {
            error: 'Workflow execution failed',
            error_code: 'WORKFLOW_ERROR'
          }
        }
      };

      mockedAxios.post.mockRejectedValue(errorResponse);

      const workflowData = {
        file_content: 'invalid-content',
        filename: 'test-document.pdf'
      };

      await expect(executeWorkflow(workflowData)).rejects.toThrow('Workflow execution failed');
    });
  });

  describe('checkHealth', () => {
    test('checks health successfully', async () => {
      const mockResponse = {
        data: {
          status: 'healthy',
          service: 'prior-authorization-api',
          version: '1.0.0',
          timestamp: '2024-01-20T10:00:00Z',
          workflow_service: 'available'
        }
      };

      mockedAxios.get.mockResolvedValue(mockResponse);

      const result = await checkHealth();

      expect(mockedAxios.get).toHaveBeenCalledWith('/api/v1/health');
      expect(result).toEqual(mockResponse.data);
    });

    test('handles health check failure', async () => {
      const errorResponse = {
        response: {
          status: 503,
          data: {
            status: 'unhealthy',
            service: 'prior-authorization-api',
            error: 'Service unavailable'
          }
        }
      };

      mockedAxios.get.mockRejectedValue(errorResponse);

      await expect(checkHealth()).rejects.toThrow();
    });
  });

  describe('API Configuration', () => {
    test('includes authentication headers', async () => {
      const mockResponse = { data: { status: 'healthy' } };
      mockedAxios.get.mockResolvedValue(mockResponse);

      await checkHealth();

      // Verify that axios was configured with interceptors
      expect(mockedAxios.interceptors.request.use).toHaveBeenCalled();
    });

    test('handles authentication errors', async () => {
      const errorResponse = {
        response: {
          status: 401,
          data: {
            error: 'Unauthorized',
            error_code: 'AUTHENTICATION_ERROR'
          }
        }
      };

      mockedAxios.get.mockRejectedValue(errorResponse);

      await expect(checkHealth()).rejects.toThrow('Unauthorized');
    });

    test('handles rate limiting', async () => {
      const errorResponse = {
        response: {
          status: 429,
          data: {
            error: 'Rate limit exceeded',
            error_code: 'RATE_LIMIT_ERROR'
          },
          headers: {
            'retry-after': '60'
          }
        }
      };

      mockedAxios.get.mockRejectedValue(errorResponse);

      await expect(checkHealth()).rejects.toThrow('Rate limit exceeded');
    });
  });

  describe('Error Handling', () => {
    test('handles timeout errors', async () => {
      const timeoutError = {
        code: 'ECONNABORTED',
        message: 'timeout of 30000ms exceeded'
      };

      mockedAxios.post.mockRejectedValue(timeoutError);

      const testFile = new File(['test content'], 'test-document.pdf', {
        type: 'application/pdf'
      });

      await expect(uploadDocument(testFile)).rejects.toThrow('timeout');
    });

    test('handles server errors', async () => {
      const serverError = {
        response: {
          status: 500,
          data: {
            error: 'Internal server error',
            error_code: 'INTERNAL_ERROR'
          }
        }
      };

      mockedAxios.get.mockRejectedValue(serverError);

      await expect(getDocumentStatus('test-doc-123')).rejects.toThrow('Internal server error');
    });

    test('handles malformed responses', async () => {
      const malformedResponse = {
        data: null
      };

      mockedAxios.get.mockResolvedValue(malformedResponse);

      const result = await checkHealth();
      expect(result).toBeNull();
    });
  });
});