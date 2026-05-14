'use client';

import React, { Component, ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallbackModule?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorId: string;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorId: '' };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
      errorId: `EB-${Date.now().toString(36).toUpperCase()}`,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // In production, this would send to a logging service
    console.error(
      `[EconomicBridge Error Boundary] Module: ${this.props.fallbackModule || 'Unknown'}`,
      '\nError:', error.message,
      '\nStack:', errorInfo.componentStack,
      '\nTimestamp:', new Date().toISOString(),
    );
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorId: '' });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="panel anim a1" role="alert" aria-live="assertive">
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '320px',
            textAlign: 'center',
            gap: '16px',
            padding: '40px 24px',
          }}>
            <div style={{
              width: '56px',
              height: '56px',
              borderRadius: '50%',
              background: '#fde8e1',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '24px',
            }}>
              ⚠
            </div>
            <div style={{
              fontFamily: "'Playfair Display', serif",
              fontSize: '18px',
              fontWeight: 700,
              color: 'var(--ink)',
            }}>
              Module Temporarily Unavailable
            </div>
            <div style={{
              fontSize: '11px',
              color: 'var(--muted)',
              maxWidth: '420px',
              lineHeight: '1.7',
            }}>
              {this.props.fallbackModule
                ? `The ${this.props.fallbackModule} module encountered an unexpected error. Your data is safe — this is an isolated display issue.`
                : 'A display component encountered an unexpected error. Your data is safe — this is an isolated issue.'}
            </div>
            <div style={{
              fontSize: '9px',
              letterSpacing: '2px',
              color: 'var(--dim)',
              textTransform: 'uppercase' as const,
            }}>
              Error Reference: {this.state.errorId}
            </div>
            <button
              onClick={this.handleRetry}
              style={{
                marginTop: '8px',
                padding: '8px 24px',
                fontFamily: "'DM Mono', monospace",
                fontSize: '10px',
                letterSpacing: '2px',
                textTransform: 'uppercase',
                background: 'var(--ink)',
                color: '#fff',
                border: 'none',
                borderRadius: '3px',
                cursor: 'pointer',
              }}
            >
              Retry Module
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
