import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from 'antd';
import AppHeader from './components/Layout/AppHeader';

import Upload from './pages/Upload';
import Results from './pages/Results';
import Login from './pages/Login';
import { useAuth } from './contexts/AuthContext';
import './App.css';

const { Content } = Layout;

const App: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner" />
        {/* nosemgrep: jsx-not-internationalized */}
        <p>Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <Layout className="app-layout">
      <AppHeader />
      <Content className="main-content">
        <Routes>
          <Route path="/" element={<Navigate to="/upload" replace />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/results/:documentId" element={<Results />} />
          <Route path="*" element={<Navigate to="/upload" replace />} />
        </Routes>
      </Content>
    </Layout>
  );
};

export default App;