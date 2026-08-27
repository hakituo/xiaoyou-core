# Aveline Web - 前端应用

## 概述

Aveline Web 是 Xiaoyou Core 的前端应用，基于 React 18 + TypeScript + Vite 构建。支持 Web 端、移动端和 Electron 桌面端三种运行模式，提供桌面宠物、聊天交互、状态监控、记忆管理等功能。

## 技术栈

- **框架**: React 18 + TypeScript
- **构建工具**: Vite 5
- **状态管理**: Zustand 5
- **样式**: TailwindCSS 3
- **动画**: Framer Motion
- **3D渲染**: Three.js + React Three Fiber
- **移动端**: Capacitor 8
- **桌面端**: Electron 33

## 目录结构

```
aveline-web/
├── public/                    # 静态资源
│   ├── icons/                 # 图标资源
│   ├── manifest.json          # PWA配置
│   └── sw.js                  # Service Worker
├── src/
│   ├── api/                   # API服务层
│   │   ├── apiService.ts      # API请求封装
│   │   ├── config.ts          # 配置管理
│   │   └── errorHandler.ts    # 错误处理
│   ├── components/            # React组件
│   │   ├── mobile/            # 移动端专用组件
│   │   │   ├── MobileChatTab.tsx
│   │   │   ├── MobileMainContent.tsx
│   │   │   ├── MobileSettingsOverlay.tsx
│   │   │   ├── MobileSidebar.tsx
│   │   │   └── MobileStatusPanel.tsx
│   │   ├── pet/               # 桌面宠物组件
│   │   │   ├── PetAvatar.tsx
│   │   │   ├── PetBubble.tsx
│   │   │   ├── PetContextMenu.tsx
│   │   │   ├── PetControls.tsx
│   │   │   ├── PetInput.tsx
│   │   │   ├── useFileDrop.ts
│   │   │   ├── usePetDrag.ts
│   │   │   ├── usePetMovement.ts
│   │   │   └── usePetVoice.ts
│   │   ├── ui/                # 通用UI组件
│   │   │   ├── Calendar.tsx
│   │   │   ├── ConfirmDialog.tsx
│   │   │   └── CustomSelect.tsx
│   │   ├── AvelineCore.tsx    # 核心布局组件
│   │   ├── BreathingSystem.tsx # 呼吸系统
│   │   ├── ChatPanel.tsx      # 聊天面板
│   │   ├── DailyDataPanel.tsx # 日数据面板
│   │   ├── DailyDataWidget.tsx # 日数据小部件
│   │   ├── DesktopPet.tsx     # 桌面宠物
│   │   ├── DeviceWidget.tsx   # 设备小部件
│   │   ├── EmotionWidget.tsx  # 情绪小部件
│   │   ├── ErrorBoundary.tsx  # 错误边界
│   │   ├── ImageModelSelector.tsx # 图像模型选择器
│   │   ├── InfoCard.tsx       # 信息卡片
│   │   ├── InputArea.tsx      # 输入区域
│   │   ├── LoginModal.tsx     # 登录模态框
│   │   ├── MemoryPanel.tsx    # 记忆面板
│   │   ├── MessageBubble.tsx  # 消息气泡
│   │   ├── PersonaPanel.tsx   # 人设面板
│   │   ├── PetStatsPanel.tsx  # 宠物状态面板
│   │   ├── PluginsPanel.tsx   # 插件面板
│   │   ├── SciFiCore.tsx      # 科幻风格核心
│   │   ├── SessionList.tsx    # 会话列表
│   │   ├── SettingsModal.tsx  # 设置模态框
│   │   ├── SettingsView.tsx   # 设置视图
│   │   ├── ShopModal.tsx      # 商店模态框
│   │   ├── ShopPanel.tsx      # 商店面板
│   │   ├── SidebarButton.tsx  # 侧边栏按钮
│   │   ├── StatusPanel.tsx    # 状态面板
│   │   ├── StudyFileManager.tsx # 学习文件管理器
│   │   ├── StudyPanel.tsx     # 学习面板
│   │   └── TypingIndicator.tsx # 打字指示器
│   ├── hooks/                 # 自定义Hooks
│   │   ├── useContextSync.ts      # 上下文同步
│   │   ├── useImageModels.ts      # 图像模型管理
│   │   ├── useLongPress.ts        # 长按检测
│   │   ├── useMobileBackgroundMode.ts # 移动端后台模式
│   │   ├── useMobileDeepLink.ts   # 移动端深度链接
│   │   ├── useMobileFileUpload.ts # 移动端文件上传
│   │   ├── useMobileHaptics.ts    # 移动端触觉反馈
│   │   ├── useMobileInitialData.ts # 移动端初始数据
│   │   ├── useMobileKeyboardResize.ts # 移动端键盘适配
│   │   ├── useMobileMessageActions.ts # 移动端消息操作
│   │   ├── useMobileNativeBack.ts # 移动端返回键
│   │   ├── useMobileNativeSync.ts # 移动端原生同步
│   │   ├── useMobileSessionActions.ts # 移动端会话操作
│   │   ├── useMobileSessionHistory.ts # 移动端会话历史
│   │   ├── useMobileSidebarSwipe.ts # 移动端侧边栏滑动
│   │   ├── useMobileStudyMode.ts  # 移动端学习模式
│   │   ├── useMobileTTS.ts        # 移动端TTS
│   │   ├── useMobileViewport.ts   # 移动端视口
│   │   ├── useMobileWebSocketHandler.ts # 移动端WebSocket处理
│   │   ├── useModels.ts           # 模型管理
│   │   ├── useNativeCapabilities.ts # 原生能力
│   │   ├── useStatus.ts           # 状态管理
│   │   └── useWebSocket.ts        # WebSocket连接
│   ├── store/                 # 状态管理
│   │   └── useStore.ts        # Zustand全局状态
│   ├── systems/               # 系统模块
│   │   └── BreathingSystem/   # 呼吸系统动画
│   │       ├── components.tsx
│   │       ├── index.ts
│   │       ├── rules.ts
│   │       ├── types.ts
│   │       └── useBreathingSystem.ts
│   ├── types/                 # TypeScript类型定义
│   │   └── index.ts
│   ├── utils/                 # 工具函数
│   │   ├── common.ts          # 通用工具
│   │   ├── constants.ts       # 常量定义
│   │   ├── emotion.ts         # 情绪处理
│   │   ├── logger.ts          # 日志工具
│   │   ├── nativeService.ts   # 原生服务
│   │   └── text.ts            # 文本处理
│   ├── Aveline.tsx            # Web端主组件
│   ├── MobileApp.tsx          # 移动端主组件
│   ├── index.css              # 全局样式
│   ├── main-mobile.tsx        # 移动端入口
│   └── main.tsx               # Web端入口
├── index.html                 # Web端入口HTML
├── mobile.html                # 移动端入口HTML
├── vite.config.ts             # Vite配置
├── tailwind.config.js         # TailwindCSS配置
├── tsconfig.json              # TypeScript配置
├── Dockerfile                 # Docker构建文件
├── nginx.conf                 # Nginx配置
└── package.json               # 依赖配置
```

## 核心功能

### 1. 多端支持

#### Web端 (Aveline.tsx)

- 完整的桌面端体验
- 桌面宠物模式
- 多面板布局（聊天、记忆、学习、商店等）
- 呼吸系统动画
- 情绪可视化

#### 移动端 (MobileApp.tsx)

- 优化的移动端体验
- 侧边栏导航
- 触觉反馈
- 原生能力集成
- 后台模式支持

#### 桌面端 (Electron)

- 系统托盘集成
- 原生窗口控制
- 自动更新

### 2. WebSocket通信

```typescript
// 连接管理
const { isConnected, sendMessage } = useWebSocket({
  onMessage: (data) => {
    // 处理消息
  },
  onAuthError: () => {
    // 鉴权失败处理
  }
});

// 自动重连（指数退避 + 抖动）
const delay = Math.min(30000, base * Math.pow(1.5, attempt) + jitter);
```

### 3. 状态管理

使用 Zustand 进行轻量级状态管理：

```typescript
const useAvelineStore = create<AvelineState>((set) => ({
  // 消息
  messages: [],
  addMessage: (message) => set((state) => ({ 
    messages: [...state.messages, message] 
  })),
  
  // 情绪
  emotion: 'neutral',
  emotionMix: {},
  
  // 系统状态
  lifeStatus: {},
  stats: { fps: 0, memory: 0, cpu: 0, gpu: 0, temperature: 0 },
  
  // 设置
  autoTtsEnabled: false,
  replyDisplayMode: 'text_and_tts',
  ttsSpeed: 1.0,
  ttsPitch: 1.0,
}));
```

### 4. 呼吸系统

基于系统状态和情绪的动态背景动画：

```typescript
const breathingState = useBreathingSystem({ 
  stats,      // 系统统计
  emotion,    // 当前情绪
  emotionMix, // 情绪混合
  lifeStatus, // 生命状态
  isThinking  // 是否思考中
});

// 返回值
const { colors, speed, pattern } = breathingState;
```

### 5. 桌面宠物

可拖拽的桌面宠物组件：

```typescript
<DesktopPet
  emotion={emotion}
  isTyping={isTyping}
  onSendMessage={handleSend}
  onClose={() => setShowPet(false)}
/>
```

特性：
- 自由拖拽
- 自动移动
- 语音输入
- 文件拖放
- 右键菜单

### 6. 消息处理

支持多种消息类型：

```typescript
interface Message {
  id: string;
  text: string;
  isUser: boolean;
  timestamp: number;
  messageType?: 'text' | 'audio' | 'image' | 'file' | 'study' | 'system';
  audioBase64?: string;
  imageUrl?: string;
  imageBase64?: string;
  file?: File;
  studyData?: any;
  emotion?: EmotionType;
  isStreaming?: boolean;
}
```

## 移动端专用Hooks

| Hook | 说明 |
|------|------|
| `useMobileWebSocketHandler` | WebSocket消息处理 |
| `useMobileNativeSync` | 原生能力同步 |
| `useMobileHaptics` | 触觉反馈 |
| `useMobileKeyboardResize` | 键盘弹出适配 |
| `useMobileViewport` | 视口管理 |
| `useMobileBackgroundMode` | 后台模式 |
| `useMobileDeepLink` | 深度链接处理 |
| `useMobileFileUpload` | 文件上传 |
| `useMobileMessageActions` | 消息操作（复制、删除等） |
| `useMobileSessionActions` | 会话操作 |
| `useMobileSessionHistory` | 会话历史管理 |
| `useMobileStudyMode` | 学习模式 |
| `useMobileTTS` | TTS语音播放 |
| `useMobileSidebarSwipe` | 侧边栏滑动手势 |
| `useMobileNativeBack` | 原生返回键处理 |
| `useMobileInitialData` | 初始数据加载 |

## API服务

### 请求封装

```typescript
// 基础请求
const response = await api.get('/api/v1/sessions');
const response = await api.post('/api/v1/chat', { message: 'Hello' });

// 带超时的请求
const response = await api.get('/api/v1/models', { timeoutMs: 5000 });

// 静默请求（不记录日志）
const response = await api.get('/api/v1/health', { silent: true });
```

### 错误处理

```typescript
// 统一错误处理
try {
  const response = await api.get('/api/v1/endpoint');
} catch (error) {
  if (error instanceof ApiError) {
    switch (error.type) {
      case ErrorType.NETWORK:
        // 网络错误
        break;
      case ErrorType.AUTH:
        // 认证错误
        break;
      case ErrorType.TIMEOUT:
        // 超时错误
        break;
    }
  }
}
```

## 构建与运行

### 开发环境

```bash
# 安装依赖
npm install

# 启动Web开发服务器
npm run dev

# 启动Electron开发模式
npm run electron:dev
```

### 生产构建

```bash
# Web端构建
npm run build

# 预览构建结果
npm run preview

# Electron构建
npm run electron:build
```

### Docker部署

```bash
# 构建镜像
docker build -t aveline-web .

# 运行容器
docker run -d -p 80:80 aveline-web
```

### 移动端构建

```bash
# 同步到Android
npx cap sync android

# 打开Android Studio
npx cap open android
```

## 配置

### 环境变量

创建 `.env` 文件：

```env
VITE_API_URL=http://localhost:8000
```

### localStorage键值

| 键 | 说明 |
|----|------|
| `AVELINE_API_URL` | 自定义API地址 |
| `XIAOYOU_ACCESS_TOKEN` | 访问令牌 |
| `XIAOYOU_USER_ID` | 用户ID |
| `XIAOYOU_USER_NAME` | 用户名称 |
| `aveline_chat_history_v2` | 聊天历史 |
| `aveline_settings_v1` | 用户设置 |

## 依赖说明

### 核心依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| react | ^18.2.0 | UI框架 |
| zustand | ^5.0.9 | 状态管理 |
| framer-motion | ^10.12.7 | 动画库 |
| three | ^0.182.0 | 3D渲染 |
| @react-three/fiber | ^8.15.0 | React Three.js |
| @react-three/drei | ^9.88.0 | Three.js辅助工具 |

### 移动端依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| @capacitor/core | ^8.0.1 | Capacitor核心 |
| @capacitor/android | ^8.0.1 | Android平台 |
| @capacitor/haptics | ^8.0.0 | 触觉反馈 |
| @capacitor/keyboard | ^8.0.0 | 键盘管理 |
| @capacitor/local-notifications | ^8.0.0 | 本地通知 |

### 桌面端依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| electron | ^33.0.0 | Electron框架 |
| electron-updater | ^6.6.2 | 自动更新 |

## 常见问题

**Q: WebSocket连接失败？**
A: 检查以下几点：
1. 后端服务是否正常运行
2. API地址配置是否正确
3. 如果使用FRP，确认端口映射（18000 → 18999）
4. Token是否有效

**Q: 移动端通知不工作？**
A: 检查以下几点：
1. 浏览器通知权限是否授予
2. NativeService是否正确初始化
3. 系统通知设置是否开启

**Q: 桌面宠物拖拽不流畅？**
A: 检查以下几点：
1. CSS transform是否正确应用
2. 是否有性能瓶颈
3. requestAnimationFrame是否正确使用

**Q: 如何添加新的移动端Hook？**
A: 参考 `useMobile*.ts` 系列文件的模式：
1. 创建新的Hook文件
2. 使用Capacitor调用原生能力
3. 在MobileApp.tsx中引入使用

## 相关文档

- [系统架构文档](../../../PROJECT_TECHNICAL_REFERENCE.md)
- [前端系统文档](../README.md)
- [客户端层文档](../../README.md)
- [路由系统文档](../../../routers/README.md)
