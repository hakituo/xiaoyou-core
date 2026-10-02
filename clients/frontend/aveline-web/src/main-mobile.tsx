import React from 'react';
import { createRoot } from 'react-dom/client';
import { MobileApp } from './MobileApp';
import './index.css';

// Create root and render app
const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element not found in the DOM');
}

const root = createRoot(container);
root.render(
  <React.StrictMode>
    <MobileApp />
  </React.StrictMode>
);

// Register Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
