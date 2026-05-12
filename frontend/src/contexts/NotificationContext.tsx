import React, { createContext, useContext, ReactNode } from 'react';
import { notification } from 'antd';
import { CheckCircleOutlined, ExclamationCircleOutlined, InfoCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';

type NotificationType = 'success' | 'error' | 'info' | 'warning';

interface NotificationContextType {
  showNotification: (type: NotificationType, message: string, description?: string) => void;
  showSuccess: (message: string, description?: string) => void;
  showError: (message: string, description?: string) => void;
  showInfo: (message: string, description?: string) => void;
  showWarning: (message: string, description?: string) => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

interface NotificationProviderProps {
  children: ReactNode;
}

export const NotificationProvider: React.FC<NotificationProviderProps> = ({ children }) => {
  const [api, contextHolder] = notification.useNotification();

  const getIcon = (type: NotificationType) => {
    switch (type) {
      case 'success':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'error':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      case 'warning':
        return <ExclamationCircleOutlined style={{ color: '#fa8c16' }} />;
      case 'info':
      default:
        return <InfoCircleOutlined style={{ color: '#1890ff' }} />;
    }
  };

  const showNotification = (type: NotificationType, message: string, description?: string) => {
    // nosemgrep: unsafe-dynamic-method — type is constrained to NotificationType union ('success'|'error'|'info'|'warning')
    api[type]({
      message,
      description,
      icon: getIcon(type),
      placement: 'topRight',
      duration: type === 'error' ? 6 : 4,
    });
  };

  const showSuccess = (message: string, description?: string) => {
    showNotification('success', message, description);
  };

  const showError = (message: string, description?: string) => {
    showNotification('error', message, description);
  };

  const showInfo = (message: string, description?: string) => {
    showNotification('info', message, description);
  };

  const showWarning = (message: string, description?: string) => {
    showNotification('warning', message, description);
  };

  const value: NotificationContextType = {
    showNotification,
    showSuccess,
    showError,
    showInfo,
    showWarning,
  };

  return (
    <NotificationContext.Provider value={value}>
      {contextHolder}
      {children}
    </NotificationContext.Provider>
  );
};

export const useNotification = (): NotificationContextType => {
  const context = useContext(NotificationContext);
  if (context === undefined) {
    throw new Error('useNotification must be used within a NotificationProvider');
  }
  return context;
};