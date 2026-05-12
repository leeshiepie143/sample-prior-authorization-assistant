import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from 'react-query';
import App from '../App';
import { AuthProvider } from '../contexts/AuthContext';
import { NotificationProvider } from '../contexts/NotificationContext';

// Mock the auth context
const mockAuthContext = {
  isAuthenticated: true,
  loading: false,
  user: {
    id: 'test-user-123',
    role: 'provider',
    organization: 'test-org'
  },
  login: jest.fn(),
  logout: jest.fn(),
  token: 'mock-jwt-token'
};

jest.mock('../contexts/AuthContext', () => ({
  ...jest.requireActual('../contexts/AuthContext'),
  useAuth: () => mockAuthContext
}));

// Mock components to avoid complex rendering
jest.mock('../components/Layout/AppHeader', () => {
  return function MockAppHeader() {
    return <div data-testid="app-header">App Header</div>;
  };
});

jest.mock('../components/Layout/AppSidebar', () => {
  return function MockAppSidebar() {
    return <div data-testid="app-sidebar">App Sidebar</div>;
  };
});

jest.mock('../pages/Dashboard', () => {
  return function MockDashboard() {
    return <div data-testid="dashboard-page">Dashboard</div>;
  };
});

jest.mock('../pages/Upload', () => {
  return function MockUpload() {
    return <div data-testid="upload-page">Upload</div>;
  };
});

jest.mock('../pages/DocumentStatus', () => {
  return function MockDocumentStatus() {
    return <div data-testid="status-page">Document Status</div>;
  };
});

jest.mock('../pages/Results', () => {
  return function MockResults() {
    return <div data-testid="results-page">Results</div>;
  };
});

jest.mock('../pages/Login', () => {
  return function MockLogin() {
    return <div data-testid="login-page">Login</div>;
  };
});

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
        <AuthProvider>
          <NotificationProvider>
            {component}
          </NotificationProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('App Component', () => {
  beforeEach(() => {
    // Reset mocks
    jest.clearAllMocks();
  });

  test('renders authenticated app layout', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('app-header')).toBeInTheDocument();
      expect(screen.getByTestId('app-sidebar')).toBeInTheDocument();
    });
  });

  test('shows loading state when auth is loading', () => {
    // Mock loading state
    const loadingAuthContext = {
      ...mockAuthContext,
      loading: true
    };

    jest.doMock('../contexts/AuthContext', () => ({
      ...jest.requireActual('../contexts/AuthContext'),
      useAuth: () => loadingAuthContext
    }));

    renderWithProviders(<App />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('shows login page when not authenticated', () => {
    // Mock unauthenticated state
    const unauthenticatedContext = {
      ...mockAuthContext,
      isAuthenticated: false,
      loading: false
    };

    jest.doMock('../contexts/AuthContext', () => ({
      ...jest.requireActual('../contexts/AuthContext'),
      useAuth: () => unauthenticatedContext
    }));

    renderWithProviders(<App />);

    expect(screen.getByTestId('login-page')).toBeInTheDocument();
  });

  test('redirects to dashboard by default', async () => {
    // Mock window.location
    delete (window as any).location;
    window.location = { ...window.location, pathname: '/' };

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
    });
  });
});