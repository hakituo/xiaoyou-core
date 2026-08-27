# Frontend (前端系统)

## 概述

前端系统是Xiaoyou-Core系统的客户端界面层，包含Web前端、Android原生应用、Electron桌面应用等多种平台实现。采用React + TypeScript技术栈，支持桌面宠物、移动端、Web端等多种交互形态。

## 目录结构

```
frontend/
├── app/                       # Next.js应用入口
│   ├── globals.css            # 全局样式
│   ├── layout.tsx             # 布局组件
│   └── page.tsx               # 页面组件
├── aveline-web/               # Web前端 (React + Vite)
│   ├── public/                # 静态资源
│   │   ├── icons/             # 图标资源
│   │   ├── manifest.json      # PWA配置
│   │   └── sw.js              # Service Worker
│   ├── src/
│   │   ├── api/               # API服务层
│   │   │   ├── apiService.ts  # API请求封装
│   │   │   ├── config.ts      # 配置管理
│   │   │   └── errorHandler.ts # 错误处理
│   │   ├── components/        # React组件
│   │   │   ├── mobile/        # 移动端专用组件
│   │   │   ├── pet/           # 桌面宠物组件
│   │   │   ├── ui/            # 通用UI组件
│   │   │   ├── AvelineCore.tsx    # 核心组件
│   │   │   ├── BreathingSystem.tsx # 呼吸系统
│   │   │   ├── ChatPanel.tsx      # 聊天面板
│   │   │   ├── DesktopPet.tsx     # 桌面宠物
│   │   │   ├── MemoryPanel.tsx    # 记忆面板
│   │   │   ├── SessionList.tsx    # 会话列表
│   │   │   ├── SettingsModal.tsx  # 设置模态框
│   │   │   ├── StatusPanel.tsx    # 状态面板
│   │   │   └── StudyPanel.tsx     # 学习面板
│   │   ├── hooks/             # 自定义Hooks
│   │   │   ├── useWebSocket.ts    # WebSocket连接管理
│   │   │   ├── useModels.ts       # 模型管理
│   │   │   ├── useStatus.ts       # 状态管理
│   │   │   └── useMobile*.ts      # 移动端专用Hooks
│   │   ├── store/             # 状态管理
│   │   │   └── useStore.ts        # Zustand全局状态
│   │   ├── systems/           # 系统模块
│   │   │   └── BreathingSystem/   # 呼吸系统动画
│   │   ├── types/             # TypeScript类型定义
│   │   ├── utils/             # 工具函数
│   │   ├── Aveline.tsx        # Web端主组件
│   │   └── MobileApp.tsx      # 移动端主组件
│   ├── index.html             # Web端入口
│   ├── mobile.html            # 移动端入口
│   ├── vite.config.ts         # Vite配置
│   ├── tailwind.config.js     # TailwindCSS配置
│   └── package.json           # 依赖配置
├── aveline-android/           # Android原生应用
│   ├── android/
│   │   └── app/src/main/
│   │       ├── assets/        # 前端打包资源
│   │       ├── java/          # Kotlin/Java代码
│   │       │   └── com/aveline/ai/
│   │       │       ├── AvelineApplication.kt
│   │       │       ├── AvelineForegroundService.java
│   │       │       └── NativeSettingsActivity.kt
│   │       └── res/           # Android资源
│   ├── capacitor.config.ts    # Capacitor配置
│   └── build.gradle.kts       # Gradle配置
├── aveline-electron/          # Electron桌面应用
│   ├── electron/
│   │   └── main.js            # Electron主进程
│   └── README.md
└── packages/                  # 共享包
    └── api-client/            # API客户端
```

## 核心组件

### aveline-web (Web前端)

**技术栈**: React 18 + TypeScript + Vite + Zustand + TailwindCSS

#### 主要功能模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 桌面宠物 | `DesktopPet.tsx` | 可拖拽的桌面宠物组件 |
| 聊天面板 | `ChatPanel.tsx` | 消息展示与交互 |
| 状态面板 | `StatusPanel.tsx` | 系统状态监控 |
| 记忆面板 | `MemoryPanel.tsx` | 记忆管理与查看 |
| 会话列表 | `SessionList.tsx` | 多会话管理 |
| 学习面板 | `StudyPanel.tsx` | 学习功能集成 |
| 设置面板 | `SettingsModal.tsx` | 用户设置管理 |
| 呼吸系统 | `BreathingSystem.tsx` | 动画呼吸效果 |

#### 移动端专用组件

| 组件 | 文件 | 说明 |
|------|------|------|
| 移动端聊天 | `MobileChatTab.tsx` | 移动端聊天界面 |
| 移动端侧边栏 | `MobileSidebar.tsx` | 移动端导航侧边栏 |
| 移动端状态面板 | `MobileStatusPanel.tsx` | 移动端状态展示 |
| 移动端设置 | `MobileSettingsOverlay.tsx` | 移动端设置覆盖层 |

#### 桌面宠物组件

| 组件 | 文件 | 说明 |
|------|------|------|
| 宠物头像 | `PetAvatar.tsx` | 宠物形象展示 |
| 宠物气泡 | `PetBubble.tsx` | 对话气泡组件 |
| 宠物控制 | `PetControls.tsx` | 控制按钮组 |
| 宠物输入 | `PetInput.tsx` | 输入框组件 |
| 拖拽功能 | `usePetDrag.ts` | 拖拽交互Hook |
| 移动功能 | `usePetMovement.ts` | 自动移动Hook |
| 语音功能 | `usePetVoice.ts` | 语音输入Hook |

### 状态管理

采用Zustand进行轻量级全局状态管理：

```typescript
interface AvelineState {
  // 消息
  messages: Message[];
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[]) => void;
  
  // 状态
  lifeStatus: any;
  setLifeStatus: (status: any) => void;
  
  // 人设
  persona: any;
  setPersona: (persona: any) => void;
  
  // 情绪
  emotion: EmotionType;
  setEmotion: (emotion: EmotionType) => void;
  emotionMix: Record<string, number>;
  setEmotionMix: (mix: Record<string, number>) => void;
  
  // 系统统计
  stats: Stats;
  updateStats: (stats: Partial<Stats>) => void;
  
  // UI状态
  isTyping: boolean;
  setIsTyping: (isTyping: boolean) => void;
  studyMode: boolean;
  setStudyMode: (enabled: boolean) => void;
  
  // 设置
  breathingRate: number;
  autoTtsEnabled: boolean;
  replyDisplayMode: 'text_and_tts' | 'tts_only';
  ttsSpeed: number;
  ttsPitch: number;
  referenceAudio: string | null;
}
```

### WebSocket通信

#### 连接管理

```typescript
export function useWebSocket(options: UseWebSocketOptions = {}) {
  // 自动重连（指数退避 + 抖动）
  const scheduleReconnect = useCallback(() => {
    const base = Math.max(500, currentReconnectIntervalRef.current || 3000);
    const attempt = reconnectAttemptRef.current;
    const cappedAttempt = Math.min(8, attempt);
    const backoff = base * Math.pow(1.5, cappedAttempt);
    const jitter = backoff * (0.15 * Math.random());
    const delay = Math.min(30000, Math.floor(backoff + jitter));
    // ...
  }, []);

  // FRP穿透端口适配
  if (wsBaseUrl.includes(':18000')) {
    wsBaseUrl = wsBaseUrl.replace(':18000', ':18999');
  }
}
```

#### 消息处理

- **心跳检测**: 自动响应服务器ping消息
- **主动关怀通知**: 支持原生通知推送
- **断线重连**: 页面可见性变化时自动重连
- **鉴权处理**: Token无效时触发回调

### API服务层

#### 核心功能

- **统一请求封装**: 超时控制、错误处理
- **智能重试**: 可配置的重试策略
- **请求取消**: 支持AbortController
- **日志记录**: 请求/响应日志

```typescript
// API请求示例
const request = async (endpoint: string, options: CustomRequestInit = {}) => {
  const url = `${getBaseUrl()}${endpoint}`;
  const headers = { ...getHeaders(), ...options.headers };
  
  // FormData自动处理
  if (options.body instanceof FormData) {
    delete headers['Content-Type'];
  }
  
  // 超时控制
  const response = await timeoutPromise(timeoutMs, fetch(url, requestConfig));
  
  // 错误处理
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw createErrorFromResponse(response, errorData);
  }
  
  return response.json();
};
```

### 自定义Hooks

#### 核心Hooks

| Hook | 说明 |
|------|------|
| `useWebSocket` | WebSocket连接管理 |
| `useModels` | 模型列表管理 |
| `useStatus` | 系统状态管理 |
| `useContextSync` | 上下文同步 |
| `useImageModels` | 图像模型管理 |
| `useNativeCapabilities` | 原生能力集成 |

#### 移动端专用Hooks

| Hook | 说明 |
|------|------|
| `useMobileWebSocketHandler` | 移动端WebSocket处理 |
| `useMobileNativeSync` | 移动端原生同步 |
| `useMobileHaptics` | 移动端触觉反馈 |
| `useMobileKeyboardResize` | 移动端键盘适配 |
| `useMobileViewport` | 移动端视口管理 |
| `useMobileBackgroundMode` | 移动端后台模式 |
| `useMobileDeepLink` | 移动端深度链接 |
| `useMobileFileUpload` | 移动端文件上传 |
| `useMobileMessageActions` | 移动端消息操作 |
| `useMobileSessionActions` | 移动端会话操作 |
| `useMobileStudyMode` | 移动端学习模式 |
| `useMobileTTS` | 移动端TTS |

### aveline-android (Android原生应用)

**技术栈**: Kotlin + Android SDK + Capacitor

#### 核心组件

| 组件 | 说明 |
|------|------|
| `AvelineApplication.kt` | 应用入口 |
| `AvelineForegroundService.java` | 前台服务（保持WebSocket连接） |
| `AvelineNotificationService.java` | 通知服务 |
| `NativeSettingsActivity.kt` | 原生设置界面 |
| `HealthManager.kt` | 健康状态管理 |

#### 特性

- 前台服务维护WebSocket连接
- 本地通知推送
- 原生能力集成（相机、文件、振动等）
- 多语言支持（中文/英文）

### aveline-electron (Electron桌面应用)

**技术栈**: Electron + Node.js

#### 特性

- 桌面端应用封装
- 系统托盘支持
- 原生窗口控制
- 自动更新

## 架构设计

### 组件层次结构

```
App
├── ErrorBoundary
│   └── Aveline / MobileApp
│       ├── Sidebar
│       │   ├── SessionList
│       │   ├── StatusPanel
│       │   └── SettingsButton
│       ├── MainContent
│       │   ├── ChatPanel
│       │   │   ├── MessageList
│       │   │   │   └── MessageBubble
│       │   │   └── InputArea
│       │   ├── MemoryPanel
│       │   ├── StudyPanel
│       │   └── ShopPanel
│       └── Modals
│           ├── SettingsModal
│           ├── LoginModal
│           └── ConfirmDialog
└── DesktopPet (可选)
    ├── PetAvatar
    ├── PetBubble
    ├── PetControls
    └── PetInput
```

### 数据流架构

```
┌─────────────────────────────────────────────────────────────┐
│                       Frontend (React)                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Components │  │    Hooks    │  │    Store    │         │
│  │  (UI渲染)   │◀─│  (业务逻辑) │◀─│  (状态管理) │         │
│  └─────────────┘  └──────┬──────┘  └─────────────┘         │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    API Service                       │   │
│  │  (HTTP请求封装、错误处理、重试机制)                  │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend (Xiaoyou Core)                    │
│  HTTP REST API + WebSocket                                  │
└─────────────────────────────────────────────────────────────┘
```

## 构建与部署

### 开发环境

```bash
# 安装依赖
cd aveline-web
npm install

# 启动开发服务器
npm run dev

# 启动移动端开发
npm run dev:mobile
```

### 生产构建

```bash
# Web端构建
npm run build

# 移动端构建
npm run build:mobile
```

### Docker部署

```bash
# 构建镜像
docker build -t aveline-web .

# 运行容器
docker run -p 80:80 aveline-web
```

### Android构建

```bash
# 同步前端资源
npx cap sync android

# 打开Android Studio
npx cap open android

# 或直接构建APK
cd aveline-android
./gradlew assembleRelease
```

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_URL` | 后端API地址 | `http://localhost:8000` |
| `VITE_WS_URL` | WebSocket地址 | 自动从API地址推导 |

### localStorage键值

| 键 | 说明 |
|----|------|
| `AVELINE_API_URL` | 自定义API地址 |
| `XIAOYOU_ACCESS_TOKEN` | 访问令牌 |
| `XIAOYOU_USER_ID` | 用户ID |
| `XIAOYOU_USER_NAME` | 用户名称 |
| `aveline_chat_history_v2` | 聊天历史 |
| `aveline_settings_v1` | 用户设置 |

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
2. 是否有性能瓶颈（过多渲染）
3. requestAnimationFrame是否正确使用

**Q: 如何添加新的移动端Hook？**
A: 参考 `useMobile*.ts` 系列文件的模式：
1. 创建新的Hook文件
2. 使用Capacitor调用原生能力
3. 在MobileApp.tsx中引入使用

## 相关文档

- [系统架构文档](../../PROJECT_TECHNICAL_REFERENCE.md)
- [客户端层文档](../README.md)
- [QQ机器人文档](../bots/README.md)
- [路由系统文档](../../routers/README.md)
