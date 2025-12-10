import React from 'react';
import { logComponentError } from '../utils/logger';

export class ErrorBoundary extends React.Component<{ children: React.ReactNode, componentName?: string }, { hasError: boolean }>{
  constructor(props: { children: React.ReactNode, componentName?: string }){
    super(props);
    this.state = { hasError: false };
  }
  componentDidCatch(error: any, errorInfo: any){
    logComponentError(this.props.componentName || 'Component', error, errorInfo);
    this.setState({ hasError: true });
  }
  render(){
    if (this.state.hasError){
      return <div className="p-8 text-red-400 text-sm">组件发生错误 (Error in {this.props.componentName || 'Component'})</div>;
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
