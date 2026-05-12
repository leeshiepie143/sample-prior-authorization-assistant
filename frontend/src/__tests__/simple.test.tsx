import React from 'react';
import { render, screen } from '@testing-library/react';

// Simple component for testing
const TestComponent = () => {
  return <div data-testid="test-component">Hello World</div>;
};

describe('Simple Test', () => {
  test('renders test component', () => {
    render(<TestComponent />);
    expect(screen.getByTestId('test-component')).toBeInTheDocument();
    expect(screen.getByText('Hello World')).toBeInTheDocument();
  });
});