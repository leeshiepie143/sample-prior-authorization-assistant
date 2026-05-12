import React from 'react';
import { Layout, Menu } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  UploadOutlined,
} from '@ant-design/icons';


const { Sider } = Layout;

const AppSidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();


  const menuItems = [
    {
      key: '/upload',
      icon: <UploadOutlined />,
      label: 'Upload Document',
      onClick: () => navigate('/upload'),
    },
  ];

  const selectedKeys = [location.pathname];

  return (
    <Sider className="app-sidebar" width={200} theme="dark">
      <div className="sidebar-logo">
        {/* nosemgrep: jsx-not-internationalized */}
        <h2>Prior Auth</h2>
      </div>
      
      <Menu
        mode="inline"
        selectedKeys={selectedKeys}
        theme="dark"
        items={menuItems}
        style={{ borderRight: 0, flex: 1 }}
      />
    </Sider>
  );
};

export default AppSidebar;