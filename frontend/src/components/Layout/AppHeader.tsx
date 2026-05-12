import React from 'react';
import { Layout, Button, Dropdown, Avatar, Space, Typography } from 'antd';
import { UserOutlined, LogoutOutlined, SettingOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import { useLocation } from 'react-router-dom';

const { Header } = Layout;
const { Text } = Typography;

const AppHeader: React.FC = () => {
  const { user, logout } = useAuth();
  const location = useLocation();

  const getPageTitle = (pathname: string): string => {
    switch (pathname) {
      case '/dashboard':
        return 'Dashboard';
      case '/upload':
        return '';
      case '/status':
        return 'Document Status';
      default:
        if (pathname.startsWith('/results/')) {
          return 'Assessment Results';
        }
        return '';
    }
  };

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: 'Profile',
      onClick: () => {
        // Handle profile click
        console.log('Profile clicked');
      },
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: 'Settings',
      onClick: () => {
        // Handle settings click
        console.log('Settings clicked');
      },
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: 'Logout',
      onClick: logout,
    },
  ];

  return (
    <Header className="app-header">
      <div className="header-title">
        {/* nosemgrep: jsx-not-internationalized */}
        <span className="header-logo">Prior Authorization Assistant</span>
      </div>
      
      <div className="header-actions">
        <Space size="middle">
          {/* User Menu */}
          <Dropdown
            menu={{ items: userMenuItems }}
            placement="bottomRight"
            trigger={['click']}
          >
            <div className="user-info" style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} />
              <div style={{ marginLeft: 8 }}>
                <div style={{ fontWeight: 500 }}>{user?.name}</div>
              </div>
            </div>
          </Dropdown>
        </Space>
      </div>
    </Header>
  );
};

export default AppHeader;