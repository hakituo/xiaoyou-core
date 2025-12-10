import React from 'react';
import { createRoot } from 'react-dom/client';
import Aveline from './Aveline';
import { MobileApp } from './MobileApp';
import './index.css';

// Check for mobile device
const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth < 768;

// 创建根节点并渲染应用
const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element not found in the DOM');
}

const root = createRoot(container);
root.render(
  <React.StrictMode>
    {isMobile ? <MobileApp /> : <Aveline />}
  </React.StrictMode>
);

// 注册Service Worker（PWA & Push）
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
