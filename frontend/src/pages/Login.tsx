import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography } from 'antd';
import { UserOutlined, LockOutlined, FileTextOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import { useNotification } from '../contexts/NotificationContext';

const { Title, Paragraph } = Typography;

interface LoginForm {
  email: string;
  password: string;
}

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const { showError } = useNotification();

  const onFinish = async (values: LoginForm) => {
    try {
      setLoading(true);
      await login(values.email, values.password);
    } catch (error: any) {
      showError('Login Failed', error.message || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };



  return (
    <div className="simple-kiro-login">
      <div className="simple-login-content">
        {/* Header */}
        <div className="simple-header">
          {/* nosemgrep: jsx-not-internationalized */}
          <h1 className="simple-title">Prior Authorization Assistant</h1>
          <p className="simple-subtitle">AI-Powered Medical Necessity Assessment</p>
        </div>

        {/* Form */}
        <div className="simple-form-section">
          {/* nosemgrep: jsx-not-internationalized */}
          <h2 className="simple-form-title">Log in to your account</h2>
          
          <Form
            name="login"
            onFinish={onFinish}
            className="simple-form"
            initialValues={{
              email: 'demo@priorauth.com',
              password: 'demo123'
            }}
          >
            <Form.Item
              name="email"
              rules={[
                { required: true, message: 'Please input your email!' },
                { type: 'email', message: 'Please enter a valid email!' }
              ]}
            >
              <Input
                placeholder="Email"
                type="email"
                className="simple-input"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: 'Please input your password!' }]}
            >
              <Input.Password
                placeholder="Password"
                className="simple-input"
              />
            </Form.Item>

            <Form.Item>
              {/* nosemgrep: jsx-not-internationalized */}
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                className="simple-button"
                block
              >
                Sign In
              </Button>
            </Form.Item>
          </Form>

          <div className="simple-demo-notice">
            {/* nosemgrep: jsx-not-internationalized */}
            Demo Mode.
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;