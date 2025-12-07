import React from 'react';
import { MessageSquare, LayoutGrid, Activity, Terminal } from 'lucide-react';

export const SIDEBAR_ITEMS = [
  { id: 'Chat', icon: React.createElement(MessageSquare, { size: 20 }), label: 'Chat', title: '聊天 (Chat)' },
  { id: 'Plugins', icon: React.createElement(LayoutGrid, { size: 20 }), label: 'Plugins', title: '插件管理 (Plugins)' },
  { id: 'Memory', icon: React.createElement(Activity, { size: 20 }), label: 'Memory', title: '记忆管理 (Memory)' },
  { id: 'Console', icon: React.createElement(Terminal, { size: 20 }), label: 'Console', title: '控制管理 (Console)' },
];
