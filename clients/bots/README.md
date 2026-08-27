# Xiaoyou Core QQ Bot Adapter (NapCatQQ Integration)

此目录包含基于 NapCatQQ (OneBot 11) 的 QQ 机器人接入程序。这是 Xiaoyou Core 的官方 QQ 客户端实现。

> **状态更新 (2026-03)**: 该模块已完成**深度重构与解耦**，采用模块化 Handler 架构，性能与稳定性大幅提升。

## 核心特性

- **高性能架构**: 采用 Handler 模式彻底解耦，主循环与业务逻辑分离
- **Fast Path 意图识别**: 常用指令（如状态查看、记忆清除）走本地正则匹配，毫秒级响应，无需等待 LLM
- **拟人化交互**: 错误与异常不再返回冰冷的技术日志，而是由 Aveline 语气生成的友好反馈
- **全媒体支持**:
  - **语音**: 支持接收语音消息（自动 STT 转录）和发送语音回复（TTS，支持参考音频克隆）
  - **视觉**: 支持接收图片并调用视觉模型进行理解与描述
  - **表情**: 支持接收和发送 QQ 表情/Emoji，自动斗图功能
- **生活模拟系统**: 内置食物、背包、购买与进食系统，影响 AI 状态
- **资源管理**: 支持动态切换 LLM 模型、TTS 音色和人设
- **仿生延迟**: 支持从后端获取仿生延迟配置，模拟真实思考时间
- **Master 会话监控**: 内置守护进程确保 Master 会话始终在线

## 目录结构

```text
clients/bots/
├── qq/                         # NapCat QQ 适配器
│   ├── __init__.py
│   ├── adapter.py              # 入口脚本
│   ├── main.py                 # [核心] QQAdapter 主类
│   ├── settings.py             # 全局配置与常量
│   ├── config.py               # 运行时配置 QQAdapterConfig
│   ├── transport.py            # NapCat 传输层
│   ├── aggregator.py           # 消息聚合器
│   ├── face.py                 # QQ 表情注入器
│   ├── emotion.py              # 情绪管理器
│   ├── intent.py               # 语义意图识别器
│   ├── peer_chat.py            # 双角色互聊管理器
│   ├── utils.py                # 通用工具函数
│   └── session/                # 会话子系统
│       ├── __init__.py
│       ├── session.py          # XiaoyouSession Facade
│       ├── heartbeat.py        # 心跳处理
│       ├── state.py            # 会话状态管理
│       ├── message.py          # 消息断句与发送
│       ├── connection.py       # WS 连接管理
│       └── receiver.py         # 消息接收分发
├── qq_official/                # QQ 官方适配器
│   ├── __init__.py
│   ├── adapter.py
│   ├── config.py
│   └── transport.py
├── telegram/                   # Telegram 适配器
│   ├── __init__.py
│   ├── adapter.py
│   └── settings.py
├── handlers/                   # 业务逻辑处理模块
│   ├── __init__.py
│   ├── base.py                 # 基础 Handler 类
│   ├── command_router.py       # 声明式命令路由与权限分发
│   ├── config.py               # 配置与偏好管理
│   ├── dashboard.py            # 系统状态与监控面板
│   ├── food.py                 # 食物与背包系统
│   ├── intent.py               # 意图识别 (Fast Path + LLM)
│   ├── lifecycle.py            # 生命周期与清理任务
│   ├── media.py                # 多媒体处理 (Reply/STT/Vision)
│   ├── meme.py                 # 表情包系统
│   ├── openclaw.py             # OpenClaw 任务执行集成
│   ├── resources.py            # 模型/语音/人设管理
│   ├── system.py               # 帮助与文档系统
│   └── telegram.py             # Telegram 消息处理
├── utils/                      # 工具函数
│   ├── __init__.py
│   └── status_renderer.py      # 状态面板图片渲染
├── config/                     # JSON 配置文件
│   ├── commands.json           # 命令配置
│   ├── config.json             # QQ 连接配置
│   ├── config_official.json    # QQ 官方配置
│   └── multi_qq_config.json    # 多QQ配置
├── scripts/                    # 启动与辅助脚本
│   ├── start_adapter.ps1
│   ├── start_telegram.ps1
│   ├── run_napcat.ps1
│   └── setup_napcat.ps1
├── tests/                      # 测试文件
├── multi_qq_adapter.py         # 多QQ启动器
├── debug_latency.py            # 延迟调试工具
└── __init__.py                 # 公共 API re-export
```

## 架构设计

### 消息处理流水线

```
┌─────────────────────────────────────────────────────────────┐
│                     NapCatQQ (OneBot11)                      │
│                    传输层 (WebSocket)                        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    QQAdapter (主路由层)                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Stage 1: Preprocess (预处理)                            ││
│  │   ├── 表情提取 (FaceInjector.extract)                   ││
│  │   ├── 引用消息展开 (process_reply_in_message)           ││
│  │   ├── 图片理解 (Vision, process_images_in_message)      ││
│  │   └── 语音转写 (STT, process_audio_in_message)          ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Stage 2: Command (命令路由)                             ││
│  │   └── CommandRouter.dispatch() -> Handler               ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Stage 3: Intent (意图路由) [可选]                       ││
│  │   ├── Fast Path: 本地正则匹配                           ││
│  │   └── Slow Path: LLM 意图分类                           ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Stage 4: Chat (对话处理)                                ││
│  │   └── XiaoyouSession -> WebSocket -> Xiaoyou Core       ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Xiaoyou Core (后端)                       │
│              能力层 (LLM/TTS/Vision/Memory)                  │
└─────────────────────────────────────────────────────────────┘
```

### Handler 架构

所有业务逻辑都封装在独立的 Handler 类中，继承自 `BaseHandler`：

```python
class BaseHandler:
    def __init__(self, adapter):
        self.adapter = adapter
        self.logger = adapter.logger
    
    async def api_request(self, method, path, json_body=None, params=None):
        """委托给适配器的 API 请求方法"""
        return await self.adapter._api_request(method, path, json_body, params)
    
    async def send_text(self, session_id, content):
        """委托给适配器的发送方法"""
        await self.adapter.send_to_napcat(session_id, content)
```

### 命令路由系统

`CommandRouter` 使用声明式路由配置：

```python
@dataclass(frozen=True)
class CommandRoute:
    aliases: set[str]           # 命令别名集合
    master_only: bool           # 是否仅 Master 可用
    handler: Callable[..., Awaitable[bool]]  # 处理函数

# 路由注册示例
CommandRoute({"状态", "status"}, False, self._status),
CommandRoute({"切模型", "switchmodel"}, True, self._switch_model),
```

## 会话管理

### XiaoyouSession 类

每个用户/群组拥有独立的会话实例，负责：

- **WebSocket 连接管理**: 与后端建立持久连接
- **消息队列**: 异步消息发送队列
- **流式处理**: 支持流式输出与断句发送
- **仿生延迟**: 模拟真实打字延迟
- **主动关怀**: 接收并处理主动关怀消息

```python
class XiaoyouSession:
    def __init__(self, session_id, adapter):
        self.session_id = session_id
        self.ws = None
        self.running = False
        self.queue = asyncio.Queue()
        self._bionic_profile = {}  # 仿生延迟配置
        self._recent_proactive_messages = {}  # 消息去重
```

### 仿生延迟系统

支持从后端获取仿生延迟配置，实现更自然的回复节奏：

```python
# 延迟计算公式
final_delay = base_delay * random.uniform(min_factor, max_factor)

# 惊喜延迟（随机长时间停顿）
if random.random() < surprise_probability:
    final_delay = max(final_delay, random.uniform(surprise_min, surprise_max))
```

## 常用指令

| 指令 | 说明 | 示例 |
| :--- | :--- | :--- |
| `/help` | 查看帮助菜单 | `/help` |
| `/状态` | 查看系统运行状态与资源面板 | `/状态`, `/status` |
| `/状态 资源` | 查看资源详情 | `/状态 资源` |
| `/状态 服务` | 查看服务状态 | `/状态 服务` |
| `/状态 生物` | 查看生物状态 | `/状态 生物` |
| `/模型` | 查看可用 LLM 模型列表 | `/模型` |
| `/切模型` | 切换对话模型 (Master) | `/切模型 deepseek-v3` |
| `/人设` | 查看可用人设 | `/人设` |
| `/切人设` | 切换当前性格/人设 | `/切人设 傲娇` |
| `/参考音频` | 查看可用 TTS 音色 | `/参考音频` |
| `/设置参考音频` | 设置当前 TTS 音色 | `/设置参考音频 voice1` |
| `/食物` | 查看食物菜单 | `/食物` |
| `/库存` | 查看背包 | `/库存` |
| `/买` | 购买食物 | `/买 奶茶` |
| `/吃` | 进食 | `/吃 奶茶` |
| `/oc` | 调用 OpenClaw 执行任务并回报 | `/oc 帮我总结今天仓库改动` |
| `/oc 状态` | 查看 OpenClaw 连通状态 | `/oc 状态` |
| `/oc 模型` | 查看/设置 OpenClaw 模型 | `/oc 模型 anthropic/claude-opus-4-1` |
| `/表情` | 发送表情包 | `/表情 开心` |
| `/历史` | 查看会话历史 | `/历史 20` |
| `/会话列表` | 查看所有会话 | `/会话列表` |
| `/清除短期记忆` | 重置当前对话上下文 | `/clear` |
| `/回复模式` | 切换回复模式 | `/回复模式 all` |
| `/只语音` | 切换仅语音回复 | `/只语音 on` |
| `/仿生延迟` | 切换仿生延迟 | `/仿生延迟 on` |

## 配置

### config.json 配置文件

```json
{
  "napcat_ws_url": "ws://localhost:3001",
  "xiaoyou_ws_url": "ws://localhost:8000/api/v1/ws",
  "xiaoyou_http_base_url": "http://localhost:8000",
  "napcat_access_token": "",
  "xiaoyou_access_token": "",
  "openclaw_enabled": false,
  "openclaw_http_base_url": "http://127.0.0.1:18789",
  "openclaw_api_key": "",
  "openclaw_model": "",
  "openclaw_timeout_seconds": 120,
  "session_idle_seconds": 1800,
  "temp_images_ttl_seconds": 86400,
  "temp_images_max_files": 300,
  "reply_mode": "at_only",
  "master_qq_id": ""
}
```

### 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `napcat_ws_url` | NapCat WebSocket 地址 | `ws://localhost:3001` |
| `xiaoyou_ws_url` | Xiaoyou Core WebSocket 地址 | `ws://localhost:8000/api/v1/ws` |
| `xiaoyou_http_base_url` | Xiaoyou Core HTTP 地址 | `http://localhost:8000` |
| `reply_mode` | 回复模式 (`at_only`/`all`) | `at_only` |
| `master_qq_id` | Master QQ 号（仅回复此人消息） | - |
| `session_idle_seconds` | 会话空闲超时（秒） | `1800` |

### Telegram 主程序托管

Telegram 与 QQ 的启动方式不同：Telegram 不需要另开 Adapter 终端，
`main.py` 会在 FastAPI lifespan 内直接托管它。

- 唯一启停开关：`config/yaml/app.yaml` 的 `telegram.enabled`
- 非敏感配置：语音/视觉开关、后端地址、HTTP 超时和会话超时同样位于 `telegram` 段
- 本机敏感配置：`.env` 中的 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_MASTER_USER_ID`、`TELEGRAM_PROXY_URL`
- 就绪依据：日志出现“Telegram 轮询已启动，正在监听消息”；“托管任务已提交”不代表 Telegram API 已连通
- 退出与恢复：主程序退出时会清理轮询和会话；异常退出后监督任务会退避重启

`clients/bots/scripts/start_telegram.ps1` 只用于独立调试。主程序已经托管 Telegram
时不要再运行该脚本，否则 Telegram `getUpdates` 会发生轮询冲突。

### QQ Adapter 运行环境

QQ 仍是独立 Adapter 进程，但启动脚本与根目录 `start.bat` 保持相同的
Python 环境选择：优先使用 `venv_cpu`，仅在该环境不存在时回退到
`venv_core`。启动日志会打印 Adapter 实际使用的 Python 路径。

### OpenClaw 任务模式

当你希望机器人不止"聊天"，而是"执行任务后汇报"，可以开启 OpenClaw：

1. 在 `config.json` 设置 `openclaw_enabled=true`，并填写 `openclaw_model`
2. 使用 `/oc <任务>` 发送执行请求
3. 使用 `/oc 状态` 检查网关连通与鉴权配置

## 快速开始

### 1. 环境准备

确保已安装：
*   **Node.js** (v18 或更高版本)
*   **Python 3.8+**
*   **pnpm**: NapCatQQ 使用 pnpm workspace。如果系统中没有，`setup_napcat.ps1` 会尝试自动安装。
*   **QQNT**: 系统中需要安装官方 QQ (NT 版本)。

### 2. 安装 Python 依赖

```powershell
pip install -r requirements.txt
```

### 3. 设置 NapCatQQ

运行以下脚本以安装依赖并构建 NapCatQQ：

```powershell
.\setup_napcat.ps1
```

### 4. 启动 NapCatQQ (登录)

运行以下脚本启动 NapCatQQ。如果是第一次运行，你需要扫描二维码登录 QQ。

```powershell
.\run_napcat.ps1
```

登录成功后，NapCatQQ 应该会监听 WebSocket (默认 ws://localhost:3001)。

### 5. 启动适配器

在新的终端窗口中，运行适配器以连接 Xiaoyou Core：

```powershell
.\start_adapter.ps1
```

或者直接运行 Python 脚本：

```powershell
python -m clients.bots.qq.adapter
```

## 故障排除

### 连接失败

*   确保 Xiaoyou Core (Server) 已启动并在运行
*   检查 `config.json` 中的连接地址是否正确
*   检查后端健康检查日志

### NapCat 无法启动

*   检查 `external\NapCatQQ-main` 下的构建状态
*   NapCat 需要编译后才能运行
*   确保已安装正确版本的 Node.js

### 消息不回复

*   检查终端日志
*   确认消息来自 Master（非 Master 消息会被过滤）
*   检查 `reply_mode` 配置
*   如果日志显示 `Fast Path Intent: NONE` 且 `LLM Intent` 也为空，可能是模型未响应或意图未识别

### 图片/语音无法发送

*   检查 `ffmpeg` 和 `ffprobe` 是否在系统路径中
*   确认后端 TTS/STT 服务正常运行

### 会话断开重连

*   检查网络连接稳定性
*   查看后端 WebSocket 连接状态
*   Master 会话监控会自动重启断开的会话

## 扩展开发

### 添加新命令

1. 在 `handlers/` 下创建或使用现有 Handler
2. 在 `CommandRouter._build_routes()` 中注册命令路由：

```python
CommandRoute(
    {"新命令", "newcmd"},  # 命令别名集合
    False,                  # 是否仅 Master 可用
    self._new_command       # 处理函数
),
```

3. 实现处理函数：

```python
async def _new_command(self, **ctx) -> bool:
    session_id = ctx["session_id"]
    await self.send_text(session_id, "新命令已执行")
    return True
```

### 添加新 Handler

1. 创建新文件 `handlers/new_handler.py`
2. 继承 `BaseHandler`：

```python
from clients.bots.handlers.base import BaseHandler

class NewHandler(BaseHandler):
    async def do_something(self, session_id: str, arg: str):
        # 调用后端 API
        status, data = await self.api_request("GET", "/api/v1/endpoint")
        # 发送响应
        await self.send_text(session_id, f"结果: {data}")
```

3. 在 `qq/main.py` 中注册：

```python
from clients.bots.handlers.new_handler import NewHandler

class QQAdapter:
    def __init__(self):
        # ... 其他初始化 ...
        self.new_handler = NewHandler(self)
```

## 相关文档

- [系统架构文档](../../PROJECT_TECHNICAL_REFERENCE.md)
- [客户端层文档](../README.md)
- [路由系统文档](../../routers/README.md)
- [核心服务文档](../../core/services/README.md)
