import axios, { AxiosInstance } from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'https://api.priorauth.example.com';

export interface User {
  user_id: string;
  email: string;
  role: 'admin' | 'provider' | 'reviewer' | 'user';
  organization?: string;
  name: string;
}

export interface LoginResponse {
  user: User;
  token: string;
  expires_at: string;
}

class AuthService {
  private api: AxiosInstance;

  constructor() {
    this.api = axios.create({
      baseURL: `${API_BASE_URL}/auth`,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  async login(email: string, password: string): Promise<LoginResponse> {
    // For demo purposes, we'll simulate authentication
    // In production, this would make an actual API call
    
    if (email === 'demo@priorauth.com' && password === 'demo123') {
      const mockUser: User = {
        user_id: 'user_123',
        email: 'demo@priorauth.com',
        role: 'provider',
        organization: 'Demo Healthcare',
        name: 'Dr. Demo User',
      };

      const mockToken = this.generateMockToken(mockUser);

      return {
        user: mockUser,
        token: mockToken,
        expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(), // 24 hours
      };
    }

    // Simulate different user roles for demo
    const demoUsers: { [key: string]: User } = {
      'admin@priorauth.com': {
        user_id: 'admin_123',
        email: 'admin@priorauth.com',
        role: 'admin',
        organization: 'Prior Auth System',
        name: 'Admin User',
      },
      'provider@priorauth.com': {
        user_id: 'provider_123',
        email: 'provider@priorauth.com',
        role: 'provider',
        organization: 'Healthcare Clinic',
        name: 'Dr. Provider',
      },
      'reviewer@priorauth.com': {
        user_id: 'reviewer_123',
        email: 'reviewer@priorauth.com',
        role: 'reviewer',
        organization: 'Insurance Company',
        name: 'Medical Reviewer',
      },
    };

    if (password === 'demo123' && demoUsers[email]) {
      const user = demoUsers[email];
      const token = this.generateMockToken(user);

      return {
        user,
        token,
        expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
      };
    }

    throw new Error('Invalid email or password');
  }

  async validateToken(token: string): Promise<User> {
    try {
      // In production, this would validate the token with the server
      // For demo, we'll decode the mock token
      const payload = this.decodeMockToken(token);
      return payload;
    } catch (error) {
      throw new Error('Invalid token');
    }
  }

  async refreshToken(token: string): Promise<string> {
    try {
      const user = await this.validateToken(token);
      return this.generateMockToken(user);
    } catch (error) {
      throw new Error('Token refresh failed');
    }
  }

  logout(): void {
    // In production, this might notify the server about logout
    // For now, just clear local storage (handled by AuthContext)
  }

  private generateMockToken(user: User): string {
    // This is a mock token for demo purposes
    // In production, use proper JWT tokens
    const payload = {
      user_id: user.user_id,
      email: user.email,
      role: user.role,
      organization: user.organization,
      name: user.name,
      iat: Math.floor(Date.now() / 1000),
      exp: Math.floor(Date.now() / 1000) + (24 * 60 * 60), // 24 hours
    };

    return btoa(JSON.stringify(payload));
  }

  private decodeMockToken(token: string): User {
    try {
      const payload = JSON.parse(atob(token));
      
      // Check expiration
      if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
        throw new Error('Token expired');
      }

      return {
        user_id: payload.user_id,
        email: payload.email,
        role: payload.role,
        organization: payload.organization,
        name: payload.name,
      };
    } catch (error) {
      throw new Error('Invalid token format');
    }
  }

  // Get user permissions based on role
  getUserPermissions(role: string): string[] {
    const permissions: { [key: string]: string[] } = {
      admin: [
        'documents:upload',
        'documents:view',
        'documents:status',
        'documents:results',
        'workflow:execute',
        'system:health',
        'admin:manage',
      ],
      provider: [
        'documents:upload',
        'documents:view',
        'documents:status',
        'documents:results',
        'workflow:execute',
        'system:health',
      ],
      reviewer: [
        'documents:view',
        'documents:status',
        'documents:results',
        'system:health',
      ],
      user: [
        'system:health',
      ],
    };

    return permissions[role] || [];
  }

  // Check if user has specific permission
  hasPermission(userRole: string, permission: string): boolean {
    const userPermissions = this.getUserPermissions(userRole);
    return userPermissions.includes(permission) || userPermissions.includes('admin:manage');
  }
}

export const authService = new AuthService();
export default authService;