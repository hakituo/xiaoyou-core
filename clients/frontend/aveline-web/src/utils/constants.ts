import React from 'react';
import { MessageSquare, LayoutGrid, Activity, Terminal, Database, ScanFace, BookOpen, Utensils, Calendar, Users } from 'lucide-react';

export const SIDEBAR_ITEMS = [
  { id: 'Chat', icon: React.createElement(MessageSquare, { size: 20 }), label: 'Chat', title: '聊天 (Chat)' },
  { id: 'Circle', icon: React.createElement(Users, { size: 20 }), label: 'Circle', title: '圈子 (Circle)' },
  { id: 'Status', icon: React.createElement(Activity, { size: 20 }), label: 'Status', title: '状态监控 (Status)' },
  { id: 'Persona', icon: React.createElement(ScanFace, { size: 20 }), label: 'Persona', title: '人设管理 (Persona)' },
  { id: 'Memory', icon: React.createElement(Database, { size: 20 }), label: 'Memory', title: '记忆管理 (Memory)' },
  { id: 'DailyData', icon: React.createElement(Calendar, { size: 20 }), label: 'Daily', title: '日常数据 (Daily Data)' },
  { id: 'Study', icon: React.createElement(BookOpen, { size: 20 }), label: 'Study', title: '学习模块 (Study)' },
  { id: 'Shop', icon: React.createElement(Utensils, { size: 20 }), label: 'Food', title: '食物 (Food)' },
  { id: 'Plugins', icon: React.createElement(LayoutGrid, { size: 20 }), label: 'Plugins', title: '插件管理 (Plugins)' },
];
