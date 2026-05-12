export * from './card';
export * from './badge';
export * from './button';
export * from './dialog';

// Additional UI components as placeholders
import React from 'react';
import { Tabs as AntTabs, Progress, Select, Input, Alert } from 'antd';

export const Tabs = AntTabs;
export const TabsRoot = AntTabs;
export const TabsList = AntTabs;
export const TabsTrigger: React.FC<{ children: React.ReactNode }> = ({ children }) => React.createElement('div', {}, children);
export const TabsContent: React.FC<{ children: React.ReactNode }> = ({ children }) => React.createElement('div', {}, children);

export const ProgressBar = Progress;
export const SelectRoot = Select;
export const SelectTrigger = Select;
export const SelectContent = Select;
export const SelectItem = Select.Option;
export const SelectValue: React.FC<{ children: React.ReactNode }> = ({ children }) => React.createElement('div', {}, children);

export const InputRoot = Input;
export const Textarea = Input.TextArea;

export const AlertRoot = Alert;
export const AlertDescription: React.FC<{ children: React.ReactNode }> = ({ children }) => React.createElement('div', {}, children);
export const AlertTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => React.createElement('h4', {}, children);