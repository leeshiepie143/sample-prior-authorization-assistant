import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from 'react-query';
import Upload from '../../pages/Upload';
import * as apiService from '../../services/apiService';

// Mock the API service
jest.mock('../../services/apiService');
const mockApiService = apiService as jest.Mocked<typeof apiService>;

// Mock antd components to avoid complex rendering
jest.mock('antd', () => ({
  ...jest.requireActual('antd'),
  Upload: {
    Dragger: ({ children, onChange, ...props }: any) => (
      <div data-testid="upload-dragger" {...props}>
        <input
          data-testid="file-input"
          type="file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file && onChange) {
              onChange({
                file: {
                  ...file,
                  uid: 'test-file-uid',
                  name: file.name,
                  status: 'uploading'
                },
                fileList: [file]
              });
            }
          }}
        />
        {children}
      </div>
    )
  },
  Button: ({ children, onClick, loading, ...props }: any) => (
    <button data-testid="upload-button" onClick={onClick} disabled={loading} {...props}>
      {loading ? 'Uploading...' : children}
    </button>
  ),
  Progress: ({ percent }: any) => (
    <div data-testid="upload-progress">Progress: {percent}%</div>
  ),
  Alert: ({ message, type }: any) => (
    <div data-testid={`alert-${type}`}>{message}</div>
  ),
  Card: ({ children, title }: any) => (
    <div data-testid="upload-card">
      {title && <h3>{title}</h3>}
      {children}
    </div>
  ),
  Typography: {
    Title: ({ children, level }: any) => React.createElement(`h${level}`, {}, children),
    Text: ({ children }: any) => <span>{children}</span>
  }
}));

const renderWithQueryClient = (component: React.ReactElement) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false }
    }
  });

  return render(
    <QueryClientProvider client={queryClient}>
      {component}
    </QueryClientProvider>
  );
};

describe('Upload Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders upload interface', () => {
    renderWithQueryClient(<Upload />);

    expect(screen.getByText('Upload Prior Authorization Document')).toBeInTheDocument();
    expect(screen.getByTestId('upload-dragger')).toBeInTheDocument();
    expect(screen.getByTestId('upload-button')).toBeInTheDocument();
  });

  test('handles file selection', async () => {
    renderWithQueryClient(<Upload />);

    const fileInput = screen.getByTestId('file-input');
    const testFile = new File(['test content'], 'test-document.pdf', {
      type: 'application/pdf'
    });

    await userEvent.upload(fileInput, testFile);

    await waitFor(() => {
      expect(screen.getByText('test-document.pdf')).toBeInTheDocument();
    });
  });

  test('validates file type', async () => {
    renderWithQueryClient(<Upload />);

    const fileInput = screen.getByTestId('file-input');
    const invalidFile = new File(['test content'], 'test-document.txt', {
      type: 'text/plain'
    });

    await userEvent.upload(fileInput, invalidFile);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/Invalid file type/)).toBeInTheDocument();
    });
  });

  test('validates file size', async () => {
    renderWithQueryClient(<Upload />);

    const fileInput = screen.getByTestId('file-input');
    // Create a large file (mock size)
    const largeFile = new File(['x'.repeat(11 * 1024 * 1024)], 'large-document.pdf', {
      type: 'application/pdf'
    });
    Object.defineProperty(largeFile, 'size', { value: 11 * 1024 * 1024 });

    await userEvent.upload(fileInput, largeFile);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/File size exceeds maximum/)).toBeInTheDocument();
    });
  });

  test('handles successful upload', async () => {
    // Mock successful API response
    mockApiService.uploadDocument.mockResolvedValue({
      document_id: 'test-doc-123',
      status: 'uploaded',
      execution_arn: 'arn:aws:states:us-east-1:123456789012:execution:test:exec1',
      message: 'Document uploaded successfully'
    });

    renderWithQueryClient(<Upload />);

    // Select file
    const fileInput = screen.getByTestId('file-input');
    const testFile = new File(['test content'], 'test-document.pdf', {
      type: 'application/pdf'
    });

    await userEvent.upload(fileInput, testFile);

    // Click upload button
    const uploadButton = screen.getByTestId('upload-button');
    await userEvent.click(uploadButton);

    await waitFor(() => {
      expect(mockApiService.uploadDocument).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'test-document.pdf',
          type: 'application/pdf'
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId('alert-success')).toBeInTheDocument();
      expect(screen.getByText(/Document uploaded successfully/)).toBeInTheDocument();
    });
  });

  test('handles upload error', async () => {
    // Mock API error
    mockApiService.uploadDocument.mockRejectedValue(new Error('Upload failed'));

    renderWithQueryClient(<Upload />);

    // Select file
    const fileInput = screen.getByTestId('file-input');
    const testFile = new File(['test content'], 'test-document.pdf', {
      type: 'application/pdf'
    });

    await userEvent.upload(fileInput, testFile);

    // Click upload button
    const uploadButton = screen.getByTestId('upload-button');
    await userEvent.click(uploadButton);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/Upload failed/)).toBeInTheDocument();
    });
  });

  test('shows upload progress', async () => {
    // Mock upload with progress
    let progressCallback: ((progress: number) => void) | undefined;
    mockApiService.uploadDocument.mockImplementation((file, onProgress) => {
      progressCallback = onProgress;
      return new Promise((resolve) => {
        setTimeout(() => {
          if (progressCallback) {
            progressCallback(50);
            setTimeout(() => {
              if (progressCallback) progressCallback(100);
              resolve({
                document_id: 'test-doc-123',
                status: 'uploaded',
                execution_arn: 'test-arn',
                message: 'Success'
              });
            }, 100);
          }
        }, 100);
      });
    });

    renderWithQueryClient(<Upload />);

    // Select file and upload
    const fileInput = screen.getByTestId('file-input');
    const testFile = new File(['test content'], 'test-document.pdf', {
      type: 'application/pdf'
    });

    await userEvent.upload(fileInput, testFile);
    
    const uploadButton = screen.getByTestId('upload-button');
    await userEvent.click(uploadButton);

    // Check for progress indicator
    await waitFor(() => {
      expect(screen.getByText('Uploading...')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId('upload-progress')).toBeInTheDocument();
    });
  });

  test('disables upload button when no file selected', () => {
    renderWithQueryClient(<Upload />);

    const uploadButton = screen.getByTestId('upload-button');
    expect(uploadButton).toBeDisabled();
  });

  test('enables upload button when file is selected', async () => {
    renderWithQueryClient(<Upload />);

    const fileInput = screen.getByTestId('file-input');
    const testFile = new File(['test content'], 'test-document.pdf', {
      type: 'application/pdf'
    });

    await userEvent.upload(fileInput, testFile);

    await waitFor(() => {
      const uploadButton = screen.getByTestId('upload-button');
      expect(uploadButton).not.toBeDisabled();
    });
  });

  test('clears file selection', async () => {
    renderWithQueryClient(<Upload />);

    // Select file
    const fileInput = screen.getByTestId('file-input');
    const testFile = new File(['test content'], 'test-document.pdf', {
      type: 'application/pdf'
    });

    await userEvent.upload(fileInput, testFile);

    await waitFor(() => {
      expect(screen.getByText('test-document.pdf')).toBeInTheDocument();
    });

    // Clear file (this would typically be done via a clear button)
    fireEvent.change(fileInput, { target: { files: [] } });

    await waitFor(() => {
      expect(screen.queryByText('test-document.pdf')).not.toBeInTheDocument();
    });
  });
});