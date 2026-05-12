import React, { useState, useCallback } from 'react';
import { Typography, Space } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { useDropzone } from 'react-dropzone';

const { Text, Paragraph } = Typography;

interface DocumentUploadProps {
  onFileUpload: (file: File) => void;
  disabled?: boolean;
}

const DocumentUpload: React.FC<DocumentUploadProps> = ({ onFileUpload, disabled = false }) => {
  const [dragActive, setDragActive] = useState(false);

  // Supported file types
  const supportedTypes = [
    'application/pdf',
    'application/json',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/tiff',
  ];

  const maxFileSize = 25 * 1024 * 1024; // 25MB (increased for PDFs)

  const validateFile = (file: File): string | null => {
    if (!supportedTypes.includes(file.type)) {
      return 'Unsupported file type. Please upload PDF, JSON (FHIR), Word document, or image files.';
    }

    // Different size limits for different file types
    const sizeLimit = file.type === 'application/json' ? 10 * 1024 * 1024 : maxFileSize;
    if (file.size > sizeLimit) {
      const limitMB = sizeLimit / (1024 * 1024);
      return `File size exceeds ${limitMB}MB limit. Please choose a smaller file.`;
    }

    return null;
  };

  const onDrop = useCallback((acceptedFiles: File[]) => {
    setDragActive(false);
    
    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0];
      const error = validateFile(file);
      
      if (error) {
        // Handle error - you might want to show a notification here
        console.error(error);
        return;
      }

      // Automatically start upload instead of showing confirmation
      onFileUpload(file);
    }
  }, [onFileUpload]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/json': ['.json'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'image/tiff': ['.tiff', '.tif'],
    },
    multiple: false,
    disabled,
    onDragEnter: () => setDragActive(true),
    onDragLeave: () => setDragActive(false),
  });



  return (
    <div>
      <div
        {...getRootProps()} // nosemgrep: react-props-spreading — standard react-dropzone API pattern
        className={`upload-area ${isDragActive || dragActive ? 'dragover' : ''}`}
        style={{
          opacity: disabled ? 0.6 : 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        <input {...getInputProps()} /> {/* nosemgrep: react-props-spreading — standard react-dropzone API pattern */}
        <Space direction="vertical" size="middle" style={{ textAlign: 'center' }}>
          <InboxOutlined style={{ fontSize: 48, color: '#1890ff' }} />
          <div>
            <Paragraph style={{ fontSize: 16, margin: 0 }}>
              {isDragActive || dragActive
                ? 'Drop your document here'
                : 'Drag & drop your document here, or click to browse'}
            </Paragraph>
            {/* nosemgrep: jsx-not-internationalized */}
            <Text type="secondary">
              Supports PDF (max 25MB), JSON/FHIR (max 10MB), Word documents, and images
            </Text>
          </div>
        </Space>
      </div>
    </div>
  );
};

export default DocumentUpload;