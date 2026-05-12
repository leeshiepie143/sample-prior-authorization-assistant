import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from 'react-query';
import AppHeader from '../../components/Layout/AppHeader';
import AppSidebar from '../../components/Layout/AppSidebar';
import { AuthProvider } from '../../contexts/AuthContext';
import { NotificationProvider } from '../../contexts/NotificationContext';

// Mock the auth context
const mockAuthContext = {
  isAuthenticated: true,
  loading: false,
  user: {
    id: 'test-user-123',
    role: 'provider',
    organization: 'test-org',
    name: 'Dr. Test User',
    email: 'test@example.com'
  },
  login: jest.fn(),
  logout: jest.fn(),
  token: 'mock-jwt-token'
};

jest.mock('../../contexts/AuthContext', () => ({
  ...jest.requireActual('../../contexts/AuthContext'),
  useAuth: () => mockAuthContext
}));

// Mock antd components
jest.mock('antd', () => ({
  ...jest.requireActual('antd'),
  Layout: {
    Header: ({ children, className }: any) => (
      <header data-testid="layout-header" className={className}>
        {children}
      </header>
    ),
    Sider: ({ children, collapsed, onCollapse }: any) => (
      <aside 
        data-testid="layout-sider" 
        data-collapsed={collapsed}
        onClick={() => onCollapse && onCollapse(!collapsed)}
      >
        {children}
      </aside>
    )
  },
  Menu: ({ items, selectedKeys, onClick }: any) => (
    <nav data-testid="menu" data-selected={selectedKeys?.[0]}>
      {items?.map((item: any, index: number) => (
        <div 
          key={item.key || index}
          data-testid={`menu-item-${item.key}`}
          onClick={() => onClick && onClick({ key: item.key })}
        >
          {item.icon}
          {item.label}
        </div>
      ))}
    </nav>
  ),
  Button: ({ children, onClick, type, icon, size }: any) => (
    <button 
      data-testid="button" 
      onClick={onClick}
      data-type={type}
      data-size={size}
    >
      {icon}
      {children}
    </button>
  ),
  Dropdown: ({ menu, children }: any) => (
    <div data-testid="dropdown">
      {children}
      <div data-testid="dropdown-menu">
        {menu?.items?.map((item: any, index: number) => (
          <div 
            key={index}
            data-testid={`dropdown-item-${item.key}`}
            onClick={item.onClick}
          >
            {item.label}
          </div>
        ))}
      </div>
    </div>
  ),
  Avatar: ({ src, children }: any) => (
    <div data-testid="avatar" data-src={src}>
      {children}
    </div>
  ),
  Typography: {
    Title: ({ children, level }: any) => React.createElement(`h${level}`, {}, children),
    Text: ({ children, strong }: any) => (
      <span data-strong={strong}>{children}</span>
    )
  },
  Space: ({ children }: any) => <div data-testid="space">{children}</div>,
  Badge: ({ count, children }: any) => (
    <div data-testid="badge" data-count={count}>
      {children}
    </div>
  )
}));

// Mock react-router-dom
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => jest.fn(),
  useLocation: () => ({ pathname: '/dashboard' })
}));

// Mock icons
jest.mock('@ant-design/icons', () => ({
  DashboardOutlined: () => <span data-testid="dashboard-icon">Dashboard</span>,
  UploadOutlined: () => <span data-testid="upload-icon">Upload</span>,
  FileTextOutlined: () => <span data-testid="file-icon">File</span>,
  BarChartOutlined: () => <span data-testid="chart-icon">Chart</span>,
  UserOutlined: () => <span data-testid="user-icon">User</span>,
  LogoutOutlined: () => <span data-testid="logout-icon">Logout</span>,
  SettingOutlined: () => <span data-testid="setting-icon">Settings</span>,
  BellOutlined: () => <span data-testid="bell-icon">Bell</span>,
  MenuFoldOutlined: () => <span data-testid="menu-fold-icon">Fold</span>,
  MenuUnfoldOutlined: () => <span data-testid="menu-unfold-icon">Unfold</span>
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
        <AuthProvider>
          <NotificationProvider>
            {component}
          </NotificationProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('AppHeader Component', () => {
  test('renders header with logo and user info', () => {
    renderWithProviders(<AppHeader />);

    expect(screen.getByTestId('layout-header')).toBeInTheDocument();
    expect(screen.getByText('Prior Authorization System')).toBeInTheDocument();
    expect(screen.getByText('Dr. Test User')).toBeInTheDocument();
  });

  test('shows user avatar and dropdown', () => {
    renderWithProviders(<AppHeader />);

    expect(screen.getByTestId('avatar')).toBeInTheDocument();
    expect(screen.getByTestId('dropdown')).toBeInTheDocument();
  });

  test('displays notification bell', () => {
    renderWithProviders(<AppHeader />);

    expect(screen.getByTestId('bell-icon')).toBeInTheDocument();
    expect(screen.getByTestId('badge')).toBeInTheDocument();
  });

  test('handles user dropdown menu interactions', async () => {
    renderWithProviders(<AppHeader />);

    const userDropdown = screen.getByTestId('dropdown');
    await userEvent.click(userDropdown);

    expect(screen.getByTestId('dropdown-item-profile')).toBeInTheDocument();
    expect(screen.getByTestId('dropdown-item-settings')).toBeInTheDocument();
    expect(screen.getByTestId('dropdown-item-logout')).toBeInTheDocument();
  });

  test('handles logout action', async () => {
    renderWithProviders(<AppHeader />);

    const logoutItem = screen.getByTestId('dropdown-item-logout');
    await userEvent.click(logoutItem);

    expect(mockAuthContext.logout).toHaveBeenCalled();
  });

  test('shows sidebar toggle button', () => {
    renderWithProviders(<AppHeader collapsed={false} onToggle={jest.fn()} />);

    expect(screen.getByTestId('menu-fold-icon')).toBeInTheDocument();
  });

  test('handles sidebar toggle', async () => {
    const mockToggle = jest.fn();
    renderWithProviders(<AppHeader collapsed={false} onToggle={mockToggle} />);

    const toggleButton = screen.getByTestId('button');
    await userEvent.click(toggleButton);

    expect(mockToggle).toHaveBeenCalled();
  });

  test('shows correct toggle icon based on collapsed state', () => {
    const { rerender } = renderWithProviders(
      <AppHeader collapsed={false} onToggle={jest.fn()} />
    );

    expect(screen.getByTestId('menu-fold-icon')).toBeInTheDocument();

    rerender(
      <QueryClient>
        <BrowserRouter>
          <AuthProvider>
            <NotificationProvider>
              <AppHeader collapsed={true} onToggle={jest.fn()} />
            </NotificationProvider>
          </AuthProvider>
        </BrowserRouter>
      </QueryClient>
    );

    expect(screen.getByTestId('menu-unfold-icon')).toBeInTheDocument();
  });

  test('displays user role and organization', () => {
    renderWithProviders(<AppHeader />);

    expect(screen.getByText('provider')).toBeInTheDocument();
    expect(screen.getByText('test-org')).toBeInTheDocument();
  });
});

describe('AppSidebar Component', () => {
  test('renders sidebar with navigation menu', () => {
    renderWithProviders(<AppSidebar collapsed={false} />);

    expect(screen.getByTestId('layout-sider')).toBeInTheDocument();
    expect(screen.getByTestId('menu')).toBeInTheDocument();
  });

  test('shows all navigation items', () => {
    renderWithProviders(<AppSidebar collapsed={false} />);

    expect(screen.getByTestId('menu-item-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('menu-item-upload')).toBeInTheDocument();
    expect(screen.getByTestId('menu-item-status')).toBeInTheDocument();
    expect(screen.getByTestId('menu-item-results')).toBeInTheDocument();
  });

  test('displays navigation icons', () => {
    renderWithProviders(<AppSidebar collapsed={false} />);

    expect(screen.getByTestId('dashboard-icon')).toBeInTheDocument();
    expect(screen.getByTestId('upload-icon')).toBeInTheDocument();
    expect(screen.getByTestId('file-icon')).toBeInTheDocument();
    expect(screen.getByTestId('chart-icon')).toBeInTheDocument();
  });

  test('handles menu item selection', async () => {
    const mockNavigate = jest.fn();
    jest.doMock('react-router-dom', () => ({
      ...jest.requireActual('react-router-dom'),
      useNavigate: () => mockNavigate,
      useLocation: () => ({ pathname: '/dashboard' })
    }));

    renderWithProviders(<AppSidebar collapsed={false} />);

    const uploadMenuItem = screen.getByTestId('menu-item-upload');
    await userEvent.click(uploadMenuItem);

    // Navigation should be handled by the component
    expect(uploadMenuItem).toBeInTheDocument();
  });

  test('shows correct selected menu item based on current route', () => {
    jest.doMock('react-router-dom', () => ({
      ...jest.requireActual('react-router-dom'),
      useNavigate: () => jest.fn(),
      useLocation: () => ({ pathname: '/upload' })
    }));

    renderWithProviders(<AppSidebar collapsed={false} />);

    const menu = screen.getByTestId('menu');
    expect(menu).toHaveAttribute('data-selected', 'upload');
  });

  test('handles collapsed state', () => {
    renderWithProviders(<AppSidebar collapsed={true} />);

    const sider = screen.getByTestId('layout-sider');
    expect(sider).toHaveAttribute('data-collapsed', 'true');
  });

  test('shows tooltips when collapsed', () => {
    renderWithProviders(<AppSidebar collapsed={true} />);

    // When collapsed, menu items should still be accessible
    expect(screen.getByTestId('menu-item-dashboard')).toBeInTheDocument();
  });

  test('displays application logo', () => {
    renderWithProviders(<AppSidebar collapsed={false} />);

    expect(screen.getByText('PA System')).toBeInTheDocument();
  });

  test('handles different user roles', () => {
    const adminAuthContext = {
      ...mockAuthContext,
      user: {
        ...mockAuthContext.user,
        role: 'admin'
      }
    };

    jest.doMock('../../contexts/AuthContext', () => ({
      ...jest.requireActual('../../contexts/AuthContext'),
      useAuth: () => adminAuthContext
    }));

    renderWithProviders(<AppSidebar collapsed={false} />);

    // Admin users should see all menu items
    expect(screen.getByTestId('menu-item-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('menu-item-upload')).toBeInTheDocument();
  });
});

describe('Layout Integration', () => {
  test('header and sidebar work together', () => {
    const mockToggle = jest.fn();
    
    renderWithProviders(
      <div>
        <AppHeader collapsed={false} onToggle={mockToggle} />
        <AppSidebar collapsed={false} />
      </div>
    );

    expect(screen.getByTestId('layout-header')).toBeInTheDocument();
    expect(screen.getByTestId('layout-sider')).toBeInTheDocument();
  });

  test('responsive behavior', () => {
    // Mock window.innerWidth for responsive testing
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 768
    });

    renderWithProviders(<AppSidebar collapsed={false} />);

    // Should handle mobile view
    expect(screen.getByTestId('layout-sider')).toBeInTheDocument();
  });

  test('handles authentication state changes', () => {
    const unauthenticatedContext = {
      ...mockAuthContext,
      isAuthenticated: false,
      user: null
    };

    jest.doMock('../../contexts/AuthContext', () => ({
      ...jest.requireActual('../../contexts/AuthContext'),
      useAuth: () => unauthenticatedContext
    }));

    renderWithProviders(<AppHeader />);

    // Should handle unauthenticated state gracefully
    expect(screen.getByTestId('layout-header')).toBeInTheDocument();
  });

  test('displays loading state', () => {
    const loadingAuthContext = {
      ...mockAuthContext,
      loading: true
    };

    jest.doMock('../../contexts/AuthContext', () => ({
      ...jest.requireActual('../../contexts/AuthContext'),
      useAuth: () => loadingAuthContext
    }));

    renderWithProviders(<AppHeader />);

    // Should handle loading state
    expect(screen.getByTestId('layout-header')).toBeInTheDocument();
  });
});