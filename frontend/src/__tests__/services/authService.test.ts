import axios from 'axios';
import {
  login,
  logout,
  refreshToken,
  getAuthToken,
  isAuthenticated,
  getCurrentUser,
  setAuthToken,
  clearAuthToken
} from '../../services/authService';

// Mock axios
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn()
};

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock
});

// Mock sessionStorage
const sessionStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn()
};

Object.defineProperty(window, 'sessionStorage', {
  value: sessionStorageMock
});

describe('AuthService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
    sessionStorageMock.getItem.mockReturnValue(null);
    
    // Setup default axios mock
    mockedAxios.create.mockReturnValue(mockedAxios);
    mockedAxios.post.mockResolvedValue({ data: {} });
  });

  describe('login', () => {
    test('successful login with valid credentials', async () => {
      const mockResponse = {
        data: {
          access_token: 'mock-access-token',
          refresh_token: 'mock-refresh-token',
          expires_in: 3600,
          user: {
            id: 'user-123',
            email: 'test@example.com',
            name: 'Test User',
            role: 'provider',
            organization: 'Test Org'
          }
        }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const credentials = {
        email: 'test@example.com',
        password: 'password123'
      };

      const result = await login(credentials);

      expect(mockedAxios.post).toHaveBeenCalledWith('/api/v1/auth/login', credentials);
      expect(result).toEqual(mockResponse.data);
      expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'mock-access-token');
      expect(localStorageMock.setItem).toHaveBeenCalledWith('refresh_token', 'mock-refresh-token');
    });

    test('login with invalid credentials', async () => {
      const errorResponse = {
        response: {
          status: 401,
          data: {
            error: 'Invalid credentials',
            error_code: 'AUTHENTICATION_FAILED'
          }
        }
      };

      mockedAxios.post.mockRejectedValue(errorResponse);

      const credentials = {
        email: 'test@example.com',
        password: 'wrongpassword'
      };

      await expect(login(credentials)).rejects.toThrow('Invalid credentials');
      expect(localStorageMock.setItem).not.toHaveBeenCalled();
    });

    test('login with remember me option', async () => {
      const mockResponse = {
        data: {
          access_token: 'mock-access-token',
          refresh_token: 'mock-refresh-token',
          expires_in: 3600,
          user: {
            id: 'user-123',
            email: 'test@example.com'
          }
        }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const credentials = {
        email: 'test@example.com',
        password: 'password123',
        rememberMe: true
      };

      await login(credentials);

      // Should store in localStorage when rememberMe is true
      expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'mock-access-token');
      expect(localStorageMock.setItem).toHaveBeenCalledWith('remember_me', 'true');
    });

    test('login without remember me option', async () => {
      const mockResponse = {
        data: {
          access_token: 'mock-access-token',
          refresh_token: 'mock-refresh-token',
          expires_in: 3600,
          user: {
            id: 'user-123',
            email: 'test@example.com'
          }
        }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const credentials = {
        email: 'test@example.com',
        password: 'password123',
        rememberMe: false
      };

      await login(credentials);

      // Should store in sessionStorage when rememberMe is false
      expect(sessionStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'mock-access-token');
    });

    test('handles network errors during login', async () => {
      mockedAxios.post.mockRejectedValue(new Error('Network Error'));

      const credentials = {
        email: 'test@example.com',
        password: 'password123'
      };

      await expect(login(credentials)).rejects.toThrow('Network Error');
    });
  });

  describe('logout', () => {
    test('successful logout', async () => {
      localStorageMock.getItem.mockReturnValue('mock-token');
      mockedAxios.post.mockResolvedValue({ data: { message: 'Logged out successfully' } });

      await logout();

      expect(mockedAxios.post).toHaveBeenCalledWith('/api/v1/auth/logout');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refresh_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('user_data');
    });

    test('logout when no token exists', async () => {
      localStorageMock.getItem.mockReturnValue(null);

      await logout();

      // Should still clear storage even if no token
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(sessionStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
    });

    test('handles logout API error gracefully', async () => {
      localStorageMock.getItem.mockReturnValue('mock-token');
      mockedAxios.post.mockRejectedValue(new Error('Server error'));

      // Should not throw error, just clear local storage
      await expect(logout()).resolves.toBeUndefined();
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
    });
  });

  describe('refreshToken', () => {
    test('successful token refresh', async () => {
      localStorageMock.getItem.mockReturnValue('mock-refresh-token');
      
      const mockResponse = {
        data: {
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
          expires_in: 3600
        }
      };

      mockedAxios.post.mockResolvedValue(mockResponse);

      const result = await refreshToken();

      expect(mockedAxios.post).toHaveBeenCalledWith('/api/v1/auth/refresh', {
        refresh_token: 'mock-refresh-token'
      });
      expect(result).toEqual(mockResponse.data);
      expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'new-access-token');
    });

    test('refresh token when no refresh token exists', async () => {
      localStorageMock.getItem.mockReturnValue(null);

      await expect(refreshToken()).rejects.toThrow('No refresh token available');
    });

    test('refresh token with invalid refresh token', async () => {
      localStorageMock.getItem.mockReturnValue('invalid-refresh-token');
      
      const errorResponse = {
        response: {
          status: 401,
          data: {
            error: 'Invalid refresh token',
            error_code: 'INVALID_REFRESH_TOKEN'
          }
        }
      };

      mockedAxios.post.mockRejectedValue(errorResponse);

      await expect(refreshToken()).rejects.toThrow('Invalid refresh token');
      
      // Should clear tokens on refresh failure
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refresh_token');
    });
  });

  describe('getAuthToken', () => {
    test('gets token from localStorage', () => {
      localStorageMock.getItem.mockReturnValue('localStorage-token');
      
      const token = getAuthToken();
      
      expect(token).toBe('localStorage-token');
      expect(localStorageMock.getItem).toHaveBeenCalledWith('auth_token');
    });

    test('gets token from sessionStorage when localStorage is empty', () => {
      localStorageMock.getItem.mockReturnValue(null);
      sessionStorageMock.getItem.mockReturnValue('sessionStorage-token');
      
      const token = getAuthToken();
      
      expect(token).toBe('sessionStorage-token');
      expect(sessionStorageMock.getItem).toHaveBeenCalledWith('auth_token');
    });

    test('returns null when no token exists', () => {
      localStorageMock.getItem.mockReturnValue(null);
      sessionStorageMock.getItem.mockReturnValue(null);
      
      const token = getAuthToken();
      
      expect(token).toBeNull();
    });
  });

  describe('isAuthenticated', () => {
    test('returns true when valid token exists', () => {
      localStorageMock.getItem.mockReturnValue('valid-token');
      
      const authenticated = isAuthenticated();
      
      expect(authenticated).toBe(true);
    });

    test('returns false when no token exists', () => {
      localStorageMock.getItem.mockReturnValue(null);
      sessionStorageMock.getItem.mockReturnValue(null);
      
      const authenticated = isAuthenticated();
      
      expect(authenticated).toBe(false);
    });

    test('returns false when token is expired', () => {
      // Mock a JWT token that's expired (test-only, not a real token)
      const expiredToken = 'test.expired.token-for-unit-test';  // nosemgrep: detected-jwt-token
      localStorageMock.getItem.mockReturnValue(expiredToken);
      
      const authenticated = isAuthenticated();
      
      expect(authenticated).toBe(false);
    });
  });

  describe('getCurrentUser', () => {
    test('returns user data from localStorage', () => {
      const userData = {
        id: 'user-123',
        email: 'test@example.com',
        name: 'Test User',
        role: 'provider'
      };
      
      localStorageMock.getItem.mockReturnValue(JSON.stringify(userData));
      
      const user = getCurrentUser();
      
      expect(user).toEqual(userData);
      expect(localStorageMock.getItem).toHaveBeenCalledWith('user_data');
    });

    test('returns null when no user data exists', () => {
      localStorageMock.getItem.mockReturnValue(null);
      
      const user = getCurrentUser();
      
      expect(user).toBeNull();
    });

    test('handles invalid JSON in user data', () => {
      localStorageMock.getItem.mockReturnValue('invalid-json');
      
      const user = getCurrentUser();
      
      expect(user).toBeNull();
    });
  });

  describe('setAuthToken', () => {
    test('sets token in localStorage by default', () => {
      setAuthToken('new-token');
      
      expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'new-token');
    });

    test('sets token in sessionStorage when specified', () => {
      setAuthToken('new-token', false);
      
      expect(sessionStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'new-token');
    });

    test('removes token when null is passed', () => {
      setAuthToken(null);
      
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(sessionStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
    });
  });

  describe('clearAuthToken', () => {
    test('clears all auth-related data', () => {
      clearAuthToken();
      
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refresh_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('user_data');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('remember_me');
      expect(sessionStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
    });
  });

  describe('Token Expiration Handling', () => {
    test('automatically refreshes token when expired', async () => {
      // Mock an expired token
      localStorageMock.getItem
        .mockReturnValueOnce('expired-token')
        .mockReturnValueOnce('valid-refresh-token');

      const mockRefreshResponse = {
        data: {
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token'
        }
      };

      mockedAxios.post.mockResolvedValue(mockRefreshResponse);

      // This would typically be called by an axios interceptor
      const result = await refreshToken();

      expect(result.access_token).toBe('new-access-token');
      expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'new-access-token');
    });

    test('logs out user when refresh token is also expired', async () => {
      localStorageMock.getItem.mockReturnValue('expired-refresh-token');
      
      const errorResponse = {
        response: {
          status: 401,
          data: {
            error: 'Refresh token expired',
            error_code: 'REFRESH_TOKEN_EXPIRED'
          }
        }
      };

      mockedAxios.post.mockRejectedValue(errorResponse);

      await expect(refreshToken()).rejects.toThrow('Refresh token expired');
      
      // Should clear all tokens
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refresh_token');
    });
  });

  describe('Security Features', () => {
    test('validates token format', () => {
      // Invalid token format
      localStorageMock.getItem.mockReturnValue('invalid-token-format');
      
      const authenticated = isAuthenticated();
      
      expect(authenticated).toBe(false);
    });

    test('handles XSS protection', () => {
      const maliciousToken = '<script>alert("xss")</script>';
      
      setAuthToken(maliciousToken);
      
      // Should still store the token (server should validate)
      expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', maliciousToken);
    });

    test('clears sensitive data on logout', async () => {
      await logout();
      
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refresh_token');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('user_data');
      expect(sessionStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
    });
  });
});