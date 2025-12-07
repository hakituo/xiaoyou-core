import React from 'react';
import { createRoot } from 'react-dom/client';
import Aveline from './Aveline';
import './index.css';

// 创建根节点并渲染应用
const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element not found in the DOM');
}

const root = createRoot(container);
root.render(
  <React.StrictMode>
    <Aveline />
  </React.StrictMode>
);

// 注册Service Worker（PWA & Push）
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
