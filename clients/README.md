# Clients Layer (客户端系统)

## 概述

客户端系统是Xiaoyou-Core系统的客户端层，包含Web前端、Android客户端、桌面应用、机器人适配器等多种客户端。该层采用前后端分离架构，通过统一的HTTP REST API和WebSocket与后端通信。

## 目录结构

```
clients/
├── bots/                    # 机器人适配器
│   ├── handlers/            # 业务逻辑处理模块
│   │   ├── base.py          # 基础Handler类
│   │   ├── command_router.py # 声明式命令路由
│   │   ├── config.py        # 配置管理
│   │   ├── dashboard.py     # 状态面板
│   │   ├── food.py          # 食物系统
│   │   ├── intent.py        # 意图识别
│   │   ├── lifecycle.py     # 生命周期管理
│   │   ├── media.py         # 多媒体处理
│   │   ├── meme.py          # 表情包系统
│   │   ├── openclaw.py      # OpenClaw集成
│   │   ├── resources.py     # 资源管理
│   │   ├── system.py        # 系统命令
│   │   └── telegram.py      # Telegram处理
│   ├── utils/               # 工具函数
│   ├── tests/               # 测试文件
│   ├── qq_adapter_main.py   # QQ适配器主入口
│   ├── telegram_adapter.py  # Telegram适配器
│   └── config.json          # 配置文件
├── frontend/                # 前端项目
│   ├── aveline-web/         # Web前端 (React + Vite)
│   ├── aveline-android/     # Android原生应用
│   ├── aveline-electron/    # Electron桌面应用
│   └── packages/            # 共享包
└── 评估报告.md
```

## 核心组件

### 1. Bots (机器人适配器)

**目录**: `clients/bots/`
**技术栈**: Python 3.12 + aiohttp + NapCat QQ协议 + Telegram Bot API

机器人适配器提供QQ和Telegram机器人功能，采用模块化Handler架构。

#### QQ Adapter

**主文件**: `qq_adapter_main.py`

**核心特性**:
- **模块化Handler架构**: 业务逻辑完全解耦，主循环与业务分离
- **声明式命令路由**: `CommandRouter` 支持命令别名、权限校验和处理器绑定
- **Fast Path意图识别**: 常用指令走本地正则匹配，毫秒级响应
- **拟人化交互**: 错误与异常返回友好反馈，而非技术日志
- **全媒体支持**:
  - 语音: 支持接收语音消息（STT转录）和发送语音回复（TTS，支持参考音频克隆）
  - 视觉: 支持接收图片并调用视觉模型理解
  - 表情: 支持QQ表情/Emoji和自动斗图
- **生活模拟系统**: 内置食物、背包、购买与进食系统
- **资源管理**: 支持动态切换LLM模型、TTS音色和人设
- **仿生延迟**: 支持从后端获取仿生延迟配置，模拟真实思考时间
- **Master会话监控**: 内置守护进程确保Master会话始终在线

**消息处理流水线**:
```
1. Preprocess (预处理)
   ├── 表情提取
   ├── 引用消息展开
   ├── 图片理解 (Vision)
   └── 语音转写 (STT)
2. Command (命令路由)
   └── CommandRouter.dispatch() -> Handler
3. Chat (对话处理)
   └── WebSocket -> Xiaoyou Core
```

**常用命令**:
| 命令 | 说明 | 示例 |
|------|------|------|
| `/help` | 查看帮助菜单 | `/help` |
| `/状态` | 查看系统运行状态 | `/状态`, `/status` |
| `/模型` | 查看可用LLM模型 | `/模型` |
| `/切模型` | 切换对话模型 (Master) | `/切模型 deepseek-v3` |
| `/人设` | 查看可用人设 | `/人设` |
| `/切人设` | 切换当前人设 | `/切人设 傲娇` |
| `/参考音频` | 查看可用TTS音色 | `/参考音频` |
| `/食物` | 查看食物菜单 | `/食物` |
| `/库存` | 查看背包 | `/库存` |
| `/oc` | 调用OpenClaw执行任务 | `/oc 帮我总结今天改动` |
| `/表情` | 发送表情包 | `/表情 开心` |
| `/历史` | 查看会话历史 | `/历史 20` |
| `/清除短期记忆` | 重置对话上下文 | `/clear` |

#### Telegram Adapter

**主文件**: `clients/bots/telegram/adapter.py`

**核心特性**:
- 基于 `python-telegram-bot` 库
- 支持文本、图片、语音消息处理
- 会话管理与状态持久化
- Markdown消息自动清理
- 由主程序 lifespan 直接托管，不需要像 QQ Adapter 一样另开终端
- `config/yaml/app.yaml` 的 `telegram.enabled` 是唯一启停开关；敏感值放在 `.env`

### 2. Frontend (前端)

#### aveline-web (Web前端)

**目录**: `clients/frontend/aveline-web/`
**技术栈**: React 18 + TypeScript + Vite + Zustand + TailwindCSS

**核心特性**:
- **模块化组件设计**:
  - `components/pet/` - 桌面宠物组件
  - `components/mobile/` - 移动端专用组件
  - `components/ui/` - 通用UI组件
  - `systems/BreathingSystem/` - 呼吸系统动画
- **状态管理**: Zustand轻量级全局状态，自动持久化到localStorage
- **WebSocket实时通信**:
  - 自动重连（指数退避 + 抖动，最大30秒）
  - 心跳检测保持连接
  - 页面可见性变化时重连
  - FRP穿透端口适配（18000 → 18999）
  - 原生通知支持（主动关怀消息）
- **完善的API服务层**:
  - 统一错误处理
  - 请求取消管理
  - 智能重试机制
  - 超时控制（默认120秒）
- **移动端优化**:
  - 独立的移动端入口 (`mobile.html`, `MobileApp.tsx`)
  - 专用Hooks (`useMobile*`系列)
  - 原生能力集成 (`NativeService`)

**关键Hooks**:
| Hook | 说明 |
|------|------|
| `useWebSocket` | WebSocket连接管理 |
| `useModels` | 模型列表管理 |
| `useStatus` | 系统状态管理 |
| `useMobileWebSocketHandler` | 移动端WebSocket处理 |
| `useMobileNativeSync` | 移动端原生同步 |
| `useMobileHaptics` | 移动端触觉反馈 |

#### aveline-android (Android原生应用)

**目录**: `clients/frontend/aveline-android/`
**技术栈**: Kotlin + Android SDK + Gradle

**核心特性**:
- 原生Android应用，内置WebView加载前端
- 前台服务维护WebSocket连接
- 本地通知推送
- 原生能力集成

#### aveline-electron (桌面应用)

**目录**: `clients/frontend/aveline-electron/`
**技术栈**: Electron + Node.js

**核心特性**:
- 桌面端应用封装
- 系统托盘支持
- 原生窗口控制

## 架构设计

### 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| 单例模式 | Zustand Store, QQAdapter | 确保全局唯一实例 |
| 观察者模式 | WebSocket Hook, EventBus | 事件监听和响应 |
| 适配器模式 | QQ Adapter, Telegram Adapter | 协议适配 |
| 工厂模式 | API Service, Handler | 对象创建 |
| 策略模式 | CommandRouter | 命令分发策略 |
| 模板方法模式 | BaseHandler | Handler基类 |

### 消息流架构

```
┌─────────────────┐
│   QQ/Telegram   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Adapter Main  │────▶│  CommandRouter  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         │                       ▼
         │              ┌─────────────────┐
         │              │    Handlers     │
         │              │ (Dashboard,     │
         │              │  Resources,     │
         │              │  Food, Media...)│
         │              └─────────────────┘
         │
         ▼
┌─────────────────┐
│  Xiaoyou Core   │
│   (Backend)     │
└─────────────────┘
```

## 通信机制

### HTTP REST API

前端和适配器通过HTTP调用后端API：

```typescript
// API服务封装示例
const request = async (endpoint: string, options = {}) => {
  const url = `${getBaseUrl()}${endpoint}`;
  const headers = { ...getHeaders(), ...options.headers };
  const response = await timeoutPromise(timeoutMs, fetch(url, { ...options, headers }));
  return await response.json();
};
```

### WebSocket实时通信

```typescript
// WebSocket连接管理
const connect = useCallback(() => {
  const baseUrl = getBaseUrl().replace(/\/$/, '');
  let wsBaseUrl = baseUrl.replace(/^http/, 'ws').replace(/^https/, 'wss');
  
  // FRP适配
  if (wsBaseUrl.includes(':18000')) {
    wsBaseUrl = wsBaseUrl.replace(':18000', ':18999');
  }
  
  const wsUrl = `${wsBaseUrl}/api/v1/ws?token=${token}&user_id=${userId}`;
  const ws = new WebSocket(wsUrl);
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'ping') {
      ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp }));
      return;
    }
    onMessage(data);
  };
}, []);
```

## 配置管理

### Telegram 配置 (`config/yaml/app.yaml`)

Telegram 由主程序直接托管。将 `telegram.enabled` 设为 `true` 后随 `main.py`
启动；Bot Token、Master 用户 ID 和代理分别通过 `.env` 的
`TELEGRAM_BOT_TOKEN`、`TELEGRAM_MASTER_USER_ID`、`TELEGRAM_PROXY_URL` 提供。
`clients/bots/scripts/start_telegram.ps1` 仅供独立调试，不能与主程序轮询同时运行。

### QQ Adapter配置 (`config.json`)

```json
{
  "napcat_ws_url": "ws://localhost:3001",
  "xiaoyou_ws_url": "ws://localhost:8000/api/v1/ws",
  "xiaoyou_http_base_url": "http://localhost:8000",
  "napcat_access_token": "",
  "xiaoyou_access_token": "",
  "openclaw_enabled": false,
  "openclaw_http_base_url": "http://127.0.0.1:18789",
  "session_idle_seconds": 1800,
  "reply_mode": "at_only"
}
```

## 扩展指南

### 添加新的QQ命令

1. 在 `handlers/` 下创建或使用现有Handler
2. 在 `CommandRouter._build_routes()` 中注册命令路由：

```python
CommandRoute(
    {"新命令", "newcmd"},  # 命令别名
    False,                  # 是否仅Master可用
    self._new_command       # 处理函数
),
```

### 添加新的前端组件

1. 在 `aveline-web/src/components/` 下创建组件
2. 如需全局状态，在 `store/useStore.ts` 中添加
3. 如需WebSocket通信，使用 `useWebSocket` Hook

## 常见问题

**Q: QQ机器人不回复消息？**
A: 检查以下几点：
1. NapCat是否正常运行并登录
2. `config.json`中的连接地址是否正确
3. 消息是否来自Master（非Master消息会被过滤）
4. 查看终端日志确认错误原因

**Q: WebSocket连接失败？**
A: 检查以下几点：
1. 后端服务是否正常运行
2. 端口是否被占用
3. 如果使用FRP，确认端口映射正确（18000 → 18999）
4. Token是否有效

**Q: 如何启用语音回复？**
A: 使用 `/只语音 on` 命令开启仅语音回复模式

**Q: 如何切换回复模式？**
A: 使用 `/回复模式 all` 回复所有消息，或 `/回复模式 at_only` 仅回复艾特消息

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [评估报告](./评估报告.md)
- [QQ机器人详细文档](./bots/README.md)
- [Web前端文档](./frontend/aveline-web/README.md)
- [路由系统文档](../routers/README.md)
- [核心服务文档](../core/services/README.md)
