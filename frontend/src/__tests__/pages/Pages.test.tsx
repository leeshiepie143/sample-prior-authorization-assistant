import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from 'react-query';
import Dashboard from '../../pages/Dashboard';
import DocumentStatus from '../../pages/DocumentStatus';
import Results from '../../pages/Results';
import Login from '../../pages/Login';
import * as apiService from '../../services/apiService';
import * as authService from '../../services/authService';

// Mock API services
jest.mock('../../services/apiService');
jest.mock('../../services/authService');
const mockApiService = apiService as jest.Mocked<typeof apiService>;
const mockAuthService = authService as jest.Mocked<typeof authService>;

// Mock antd components
jest.mock('antd', () => ({
  ...jest.requireActual('antd'),
  Card: ({ children, title, extra, loading }: any) => (
    <div data-testid="card" data-loading={loading}>
      {title && <h3>{title}</h3>}
      {extra && <div data-testid="card-extra">{extra}</div>}
      {children}
    </div>
  ),
  Row: ({ children }: any) => <div data-testid="row">{children}</div>,
  Col: ({ children }: any) => <div data-testid="col">{children}</div>,
  Statistic: ({ title, value, prefix, suffix }: any) => (
    <div data-testid="statistic">
      <div data-testid="statistic-title">{title}</div>
      <div data-testid="statistic-value">
        {prefix}{value}{suffix}
      </div>
    </div>
  ),
  Table: ({ columns, dataSource, loading, pagination }: any) => (
    <div data-testid="table" data-loading={loading}>
      {dataSource?.map((item: any, index: number) => (
        <div key={index} data-testid={`table-row-${index}`}>
          {JSON.stringify(item)}
        </div>
      ))}
    </div>
  ),
  Button: ({ children, onClick, loading, type, htmlType }: any) => (
    <button 
      data-testid="button" 
      onClick={onClick} 
      disabled={loading}
      data-type={type}
      type={htmlType}
    >
      {loading ? 'Loading...' : children}
    </button>
  ),
  Form: ({ children, onFinish }: any) => (
    <form data-testid="form" onSubmit={(e) => { e.preventDefault(); onFinish && onFinish({}); }}>
      {children}
    </form>
  ),
  Input: ({ placeholder, onChange, type }: any) => (
    <input 
      data-testid="input" 
      placeholder={placeholder}
      onChange={(e) => onChange && onChange(e)}
      type={type}
    />
  ),
  Alert: ({ message, type, showIcon }: any) => (
    <div data-testid={`alert-${type}`} data-show-icon={showIcon}>
      {message}
    </div>
  ),
  Steps: ({ current, items }: any) => (
    <div data-testid="steps" data-current={current}>
      {items?.map((item: any, index: number) => (
        <div key={index} data-testid={`step-${index}`}>
          {item.title}
        </div>
      ))}
    </div>
  ),
  Progress: ({ percent, status }: any) => (
    <div data-testid="progress" data-percent={percent} data-status={status}>
      Progress: {percent}%
    </div>
  ),
  Tag: ({ children, color }: any) => (
    <span data-testid="tag" data-color={color}>{children}</span>
  ),
  Typography: {
    Title: ({ children, level }: any) => React.createElement(`h${level}`, {}, children),
    Text: ({ children, type }: any) => <span data-type={type}>{children}</span>,
    Paragraph: ({ children }: any) => <p>{children}</p>
  },
  Space: ({ children }: any) => <div data-testid="space">{children}</div>,
  Spin: ({ children, spinning }: any) => (
    <div data-testid="spin" data-spinning={spinning}>
      {children}
    </div>
  )
}));

// Mock react-router-dom
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
  useParams: () => ({ documentId: 'test-doc-123' }),
  useSearchParams: () => [new URLSearchParams('?documentId=test-doc-123'), jest.fn()]
}));

// Mock Chart.js
jest.mock('react-chartjs-2', () => ({
  Line: ({ data }: any) => <div data-testid="line-chart">Line Chart</div>,
  Bar: ({ data }: any) => <div data-testid="bar-chart">Bar Chart</div>,
  Doughnut: ({ data }: any) => <div data-testid="doughnut-chart">Doughnut Chart</div>
}));

const renderWithProviders = (component: React.ReactElement) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false }
    }
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {component}
      </BrowserRouter>
    </QueryClientProvider>
  );
};

// Sample test data
const sampleDashboardData = {
  recent_documents: [
    {
      document_id: 'doc-001',
      filename: 'prior-auth-001.pdf',
      status: 'completed',
      uploaded_at: '2024-01-20T10:00:00Z',
      approval_likelihood: 0.85
    },
    {
      document_id: 'doc-002',
      filename: 'prior-auth-002.pdf',
      status: 'processing',
      uploaded_at: '2024-01-20T11:00:00Z',
      approval_likelihood: null
    }
  ],
  statistics: {
    total_documents: 150,
    approved_documents: 120,
    pending_documents: 25,
    denied_documents: 5,
    average_processing_time: 45
  }
};

const sampleDocumentStatus = {
  document_id: 'test-doc-123',
  status: 'RUNNING',
  progress: {
    percentage: 65,
    current_step: 'PolicySelection',
    steps_completed: 3,
    total_steps: 5
  },
  started_at: '2024-01-20T10:00:00Z',
  estimated_completion: '2024-01-20T10:15:00Z'
};

const sampleResults = {
  document_id: 'test-doc-123',
  assessment_result: {
    overall_compliance: 'compliant',
    approval_likelihood: 0.88,
    criteria_results: [
      {
        criterion_id: 'cardiac_001',
        status: 'met',
        confidence_score: 0.92,
        supporting_evidence: ['Stress test positive', 'Clinical symptoms present'],
        clinical_rationale: 'Strong evidence of medical necessity'
      }
    ]
  },
  gap_analysis: {
    gaps_identified: [],
    recommendations: [
      {
        action_type: 'approve',
        description: 'Recommend approval based on strong evidence',
        priority: 'high'
      }
    ],
    approval_likelihood: 0.88
  }
};

describe('Dashboard Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders dashboard with statistics', async () => {
    mockApiService.getDashboardData.mockResolvedValue(sampleDashboardData);

    renderWithProviders(<Dashboard />);

    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    
    await waitFor(() => {
      expect(screen.getByText('Total Documents')).toBeInTheDocument();
      expect(screen.getByText('150')).toBeInTheDocument();
    });
  });

  test('displays recent documents table', async () => {
    mockApiService.getDashboardData.mockResolvedValue(sampleDashboardData);

    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText('Recent Documents')).toBeInTheDocument();
      expect(screen.getByTestId('table')).toBeInTheDocument();
    });
  });

  test('shows processing statistics', async () => {
    mockApiService.getDashboardData.mockResolvedValue(sampleDashboardData);

    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText('Approved')).toBeInTheDocument();
      expect(screen.getByText('120')).toBeInTheDocument();
      expect(screen.getByText('Pending')).toBeInTheDocument();
      expect(screen.getByText('25')).toBeInTheDocument();
    });
  });

  test('handles dashboard data loading error', async () => {
    mockApiService.getDashboardData.mockRejectedValue(new Error('Failed to load dashboard'));

    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/Failed to load dashboard/)).toBeInTheDocument();
    });
  });

  test('shows loading state', () => {
    mockApiService.getDashboardData.mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<Dashboard />);

    expect(screen.getByTestId('spin')).toHaveAttribute('data-spinning', 'true');
  });

  test('navigates to document details on row click', async () => {
    mockApiService.getDashboardData.mockResolvedValue(sampleDashboardData);

    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      const tableRow = screen.getByTestId('table-row-0');
      fireEvent.click(tableRow);
    });

    expect(mockNavigate).toHaveBeenCalledWith('/results/doc-001');
  });
});

describe('DocumentStatus Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders document status with progress', async () => {
    mockApiService.getDocumentStatus.mockResolvedValue(sampleDocumentStatus);

    renderWithProviders(<DocumentStatus />);

    expect(screen.getByText('Document Processing Status')).toBeInTheDocument();
    
    await waitFor(() => {
      expect(screen.getByTestId('progress')).toBeInTheDocument();
      expect(screen.getByTestId('progress')).toHaveAttribute('data-percent', '65');
    });
  });

  test('displays processing steps', async () => {
    mockApiService.getDocumentStatus.mockResolvedValue(sampleDocumentStatus);

    renderWithProviders(<DocumentStatus />);

    await waitFor(() => {
      expect(screen.getByTestId('steps')).toBeInTheDocument();
      expect(screen.getByTestId('steps')).toHaveAttribute('data-current', '3');
    });
  });

  test('shows current processing step', async () => {
    mockApiService.getDocumentStatus.mockResolvedValue(sampleDocumentStatus);

    renderWithProviders(<DocumentStatus />);

    await waitFor(() => {
      expect(screen.getByText(/PolicySelection/)).toBeInTheDocument();
    });
  });

  test('handles completed status', async () => {
    const completedStatus = {
      ...sampleDocumentStatus,
      status: 'SUCCEEDED',
      progress: { percentage: 100, current_step: 'Completed' }
    };

    mockApiService.getDocumentStatus.mockResolvedValue(completedStatus);

    renderWithProviders(<DocumentStatus />);

    await waitFor(() => {
      expect(screen.getByText('View Results')).toBeInTheDocument();
    });
  });

  test('handles failed status', async () => {
    const failedStatus = {
      ...sampleDocumentStatus,
      status: 'FAILED',
      error: 'Processing failed due to invalid document format'
    };

    mockApiService.getDocumentStatus.mockResolvedValue(failedStatus);

    renderWithProviders(<DocumentStatus />);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/Processing failed/)).toBeInTheDocument();
    });
  });

  test('auto-refreshes status', async () => {
    jest.useFakeTimers();
    mockApiService.getDocumentStatus.mockResolvedValue(sampleDocumentStatus);

    renderWithProviders(<DocumentStatus />);

    await waitFor(() => {
      expect(mockApiService.getDocumentStatus).toHaveBeenCalledTimes(1);
    });

    // Fast-forward time to trigger refresh
    jest.advanceTimersByTime(5000);

    await waitFor(() => {
      expect(mockApiService.getDocumentStatus).toHaveBeenCalledTimes(2);
    });

    jest.useRealTimers();
  });

  test('stops auto-refresh when completed', async () => {
    jest.useFakeTimers();
    
    const completedStatus = {
      ...sampleDocumentStatus,
      status: 'SUCCEEDED'
    };

    mockApiService.getDocumentStatus.mockResolvedValue(completedStatus);

    renderWithProviders(<DocumentStatus />);

    await waitFor(() => {
      expect(mockApiService.getDocumentStatus).toHaveBeenCalledTimes(1);
    });

    jest.advanceTimersByTime(10000);

    // Should not call again for completed status
    expect(mockApiService.getDocumentStatus).toHaveBeenCalledTimes(1);

    jest.useRealTimers();
  });
});

describe('Results Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders assessment results', async () => {
    mockApiService.getDocumentResults.mockResolvedValue(sampleResults);

    renderWithProviders(<Results />);

    expect(screen.getByText('Assessment Results')).toBeInTheDocument();
    
    await waitFor(() => {
      expect(screen.getByText('Overall Compliance')).toBeInTheDocument();
      expect(screen.getByText('88%')).toBeInTheDocument();
    });
  });

  test('displays criteria assessments', async () => {
    mockApiService.getDocumentResults.mockResolvedValue(sampleResults);

    renderWithProviders(<Results />);

    await waitFor(() => {
      expect(screen.getByText('Criteria Assessment')).toBeInTheDocument();
      expect(screen.getByText(/Strong evidence of medical necessity/)).toBeInTheDocument();
    });
  });

  test('shows gap analysis', async () => {
    mockApiService.getDocumentResults.mockResolvedValue(sampleResults);

    renderWithProviders(<Results />);

    await waitFor(() => {
      expect(screen.getByText('Gap Analysis')).toBeInTheDocument();
      expect(screen.getByText(/Recommend approval/)).toBeInTheDocument();
    });
  });

  test('handles results not ready', async () => {
    mockApiService.getDocumentResults.mockRejectedValue({
      response: { status: 202, data: { error: 'Processing still in progress' } }
    });

    renderWithProviders(<Results />);

    await waitFor(() => {
      expect(screen.getByTestId('alert-info')).toBeInTheDocument();
      expect(screen.getByText(/still processing/)).toBeInTheDocument();
    });
  });

  test('handles results error', async () => {
    mockApiService.getDocumentResults.mockRejectedValue(new Error('Failed to load results'));

    renderWithProviders(<Results />);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/Failed to load results/)).toBeInTheDocument();
    });
  });

  test('exports results', async () => {
    mockApiService.getDocumentResults.mockResolvedValue(sampleResults);

    renderWithProviders(<Results />);

    await waitFor(() => {
      const exportButton = screen.getByText('Export Report');
      expect(exportButton).toBeInTheDocument();
    });
  });

  test('shows approval likelihood visualization', async () => {
    mockApiService.getDocumentResults.mockResolvedValue(sampleResults);

    renderWithProviders(<Results />);

    await waitFor(() => {
      expect(screen.getByTestId('doughnut-chart')).toBeInTheDocument();
    });
  });
});

describe('Login Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders login form', () => {
    renderWithProviders(<Login />);

    expect(screen.getByText('Prior Authorization System')).toBeInTheDocument();
    expect(screen.getByTestId('form')).toBeInTheDocument();
    expect(screen.getAllByTestId('input')).toHaveLength(2); // Email and password
  });

  test('handles successful login', async () => {
    const mockLoginResponse = {
      access_token: 'mock-token',
      user: { id: 'user-123', email: 'test@example.com' }
    };

    mockAuthService.login.mockResolvedValue(mockLoginResponse);

    renderWithProviders(<Login />);

    const emailInput = screen.getAllByTestId('input')[0];
    const passwordInput = screen.getAllByTestId('input')[1];
    const loginButton = screen.getByTestId('button');

    await userEvent.type(emailInput, 'test@example.com');
    await userEvent.type(passwordInput, 'password123');
    await userEvent.click(loginButton);

    await waitFor(() => {
      expect(mockAuthService.login).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123'
      });
    });

    expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
  });

  test('handles login error', async () => {
    mockAuthService.login.mockRejectedValue(new Error('Invalid credentials'));

    renderWithProviders(<Login />);

    const loginButton = screen.getByTestId('button');
    await userEvent.click(loginButton);

    await waitFor(() => {
      expect(screen.getByTestId('alert-error')).toBeInTheDocument();
      expect(screen.getByText(/Invalid credentials/)).toBeInTheDocument();
    });
  });

  test('shows loading state during login', async () => {
    mockAuthService.login.mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<Login />);

    const loginButton = screen.getByTestId('button');
    await userEvent.click(loginButton);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('validates required fields', async () => {
    renderWithProviders(<Login />);

    const loginButton = screen.getByTestId('button');
    await userEvent.click(loginButton);

    // Form validation should prevent submission
    expect(mockAuthService.login).not.toHaveBeenCalled();
  });

  test('handles remember me option', async () => {
    const mockLoginResponse = {
      access_token: 'mock-token',
      user: { id: 'user-123', email: 'test@example.com' }
    };

    mockAuthService.login.mockResolvedValue(mockLoginResponse);

    renderWithProviders(<Login />);

    // Assuming there's a remember me checkbox
    const rememberMeCheckbox = screen.queryByRole('checkbox');
    if (rememberMeCheckbox) {
      await userEvent.click(rememberMeCheckbox);
    }

    const emailInput = screen.getAllByTestId('input')[0];
    const passwordInput = screen.getAllByTestId('input')[1];
    const loginButton = screen.getByTestId('button');

    await userEvent.type(emailInput, 'test@example.com');
    await userEvent.type(passwordInput, 'password123');
    await userEvent.click(loginButton);

    await waitFor(() => {
      expect(mockAuthService.login).toHaveBeenCalled();
    });
  });
});