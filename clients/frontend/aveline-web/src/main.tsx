import React from 'react';
import { createRoot } from 'react-dom/client';
import Aveline from './Aveline';
import { MobileApp } from './MobileApp';
import './index.css';

// Check for mobile device
// Exclude Pet Mode from mobile detection (Pet Mode window is small but should render Aveline/DesktopPet)
const isPetMode = window.location.hash.includes('pet-mode');
const isMobile = !isPetMode && (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth < 768);

// 创建根节点并渲染应用
const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element not found in the DOM');
}

const root = createRoot(container);
root.render(
  // 临时禁用 StrictMode 以修复 WebSocket 连接问题
  // React.StrictMode 在开发模式下会故意执行两次 mount/unmount
  // 这导致 WebSocket 连接立即被关闭
  // <React.StrictMode>
    isMobile ? <MobileApp /> : <Aveline />
  // </React.StrictMode>
);

// 注册Service Worker（PWA & Push）
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
