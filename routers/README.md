# Routers Layer (路由层)

> 最后更新：2026-06-18，反映 2026-06-15 路由重构（从扁平 `*_router.py` + `api_v1/` 重构为 `v1/` + `admin/` 分域结构）

## 概述

路由层是 Xiaoyou-Core 系统的 API 入口层，负责 HTTP REST API 和 WebSocket 的路由定义、请求处理、响应封装等功能。该层基于 FastAPI 框架构建，采用**分域模块化设计**：

- **业务域**（`v1/`）：面向终端用户的业务端点，统一挂在 `/api/v1/*` 下
- **运维域**（`admin/`）：开发态/运维端点，统一挂在 `/api/v1/admin/*` 下，业务端不应引用
- **顶层独立路由**：因路径前缀特殊（如 OpenAI 兼容 `/v1/*`）或文件组织习惯，独立挂在 `routers/` 顶层

## 目录结构

```
routers/
├── __init__.py                # 顶层聚合：唯一 /api/v1 前缀声明点
├── v1/                        # 业务域路由（统一前缀 /api/v1/）
│   ├── __init__.py            # v1 业务域聚合入口
│   ├── chat.py                # 聊天对话
│   ├── sessions.py            # 会话管理
│   ├── health.py              # 健康检查（聚合多维度快照）
│   ├── user.py                # 用户状态
│   ├── personas.py            # 人设管理
│   ├── models.py              # 模型管理
│   ├── plugins.py             # 插件/敏感模式
│   ├── peer_chat.py           # 双角色对话
│   ├── food.py                # 食物系统
│   ├── vision.py              # 视觉/图像
│   ├── life.py                # 生命状态/情绪
│   ├── system.py              # 系统状态/主动关怀/联网搜索/通用 LLM 直调
│   ├── memories.py            # 加权记忆
│   ├── context.py             # 上下文同步/每日记录/意图识别
│   ├── media.py               # STT/TTS/upload
│   ├── vocab.py               # 词汇与学习工具集
│   ├── tutor.py               # 教学域
│   ├── diary.py               # 日记/摘要/快照/定时消息/仿生延迟画像
│   ├── tasks.py               # 每日任务面板
│   └── workspace.py           # Study 工作区联动
├── admin/                     # 运维域路由（统一前缀 /api/v1/admin/）
│   ├── __init__.py            # admin 域聚合入口
│   ├── auto_heal.py           # 自愈系统
│   ├── data_ops.py            # 数据运维
│   └── remote_ops.py          # 远程操作
├── openai_compat.py           # OpenAI 兼容路由（顶层独立，/v1/chat/completions）
├── websocket.py               # WebSocket 路由（/api/v1/ws，由 v1 聚合引入）
├── demo.py                    # 演示路由
├── README.md                  # 本文档
└── 评估报告.md                 # 评估报告
```

## 路由聚合方式（`routers/__init__.py`）

顶层 `api_v1_router` 是**唯一的 `/api/v1` 前缀声明点**：

```python
from fastapi import APIRouter

from .v1 import router as v1_router
from .admin import router as admin_router
from .openai_compat import router as openai_compat_router

# 唯一 /api/v1 前缀声明点
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(v1_router)      # 业务域 → /api/v1/*
api_v1_router.include_router(admin_router)   # 运维域 → /api/v1/admin/*
```

### 挂载规则

| 路由 | 前缀 | 挂载方式 |
|---|---|---|
| `api_v1_router` | `/api/v1` | `main.py` 中 `app.include_router(api_v1_router)` |
| `v1_router`（业务域） | 继承 `/api/v1` | 由 `api_v1_router` 内部 `include_router` |
| `admin_router`（运维域） | 继承 `/api/v1/admin` | 由 `api_v1_router` 内部 `include_router` |
| `openai_compat_router` | `/v1` | **独立挂在顶层**，`main.py` 需单独 `app.include_router` |
| `websocket_router` | `/api/v1/ws` | 文件位于顶层，但由 `v1_router` 内部 `include_router` 引入 |

> **注意**：`openai_compat_router` 因需保留 OpenAI 标准 `/v1/chat/completions` 路径，不能进 `/api/v1` 前缀，故独立挂在顶层，`main.py` 必须单独执行 `app.include_router(openai_compat_router)`。

### `main.py` 接入示例

```python
from fastapi import FastAPI
from routers import api_v1_router, openai_compat_router

app = FastAPI(title="Xiaoyou Core API", version="1.0.0")

# 业务 + 运维端点（含 /api/v1/admin/* 与 /api/v1/ws）
app.include_router(api_v1_router)
# OpenAI 兼容端点（/v1/chat/completions，独立前缀）
app.include_router(openai_compat_router)
```

## `routers/v1/` 业务路由（统一前缀 /api/v1/）

| 文件 | 主要端点 |
|---|---|
| `chat.py` | `/chat/persona`, `/chat/greeting`, `/chat/message`, `/chat/regenerate` |
| `sessions.py` | 会话 CRUD + 批量删除 |
| `health.py` | `/health`（聚合 services/lifecycle/resources/gpu_gate/tasks） |
| `user.py` | `/user/status` |
| `personas.py` | 人设列表/切换 |
| `models.py` | 模型列表/切换 |
| `plugins.py` | 敏感模式开关 |
| `peer_chat.py` | 双角色对话历史/状态/触发 |
| `food.py` | 食物菜单/库存/购买/进食 |
| `vision.py` | 图像生成/描述/屏幕分析 |
| `life.py` | 生命状态/情绪检测 |
| `system.py` | 系统状态/主动关怀/联网搜索/通用 LLM 直调 |
| `memories.py` | 加权记忆列表/删除/清空/统计/标签 |
| `context.py` | 上下文同步/每日记录/意图识别 |
| `media.py` | STT/TTS/upload |
| `vocab.py` | 词汇与学习工具集 |
| `tutor.py` | 教学域 |
| `diary.py` | 日记/摘要/快照/定时消息/仿生延迟画像 |
| `tasks.py` | 每日任务面板/生成/CRUD |
| `workspace.py` | Study 工作区联动 |

### 健康检查端点（`health.py`）

**路径**: `/api/v1/health`

返回系统整体健康状态，并聚合多维度快照，字段尽量保持稳定：

- `status`: `healthy/degraded/...`（来自 `HealthChecker.get_health_summary()`）
- `services`: 每个服务的健康状态（来自 `HealthChecker.check_all_services()`）
- `lifecycle`: 服务初始化状态（来自 `ServiceLifecycle.get_status()`）
- `resources`: 系统资源快照（来自 `core/services/monitoring/resource_monitor.py::to_contract_dict()`）
- `resource_manager`: 模型/显存调度侧快照（来自 `core/resource_manager.py::get_resource_stats()`，包含 `snapshot`）
- `gpu_gate`: 全局 GPU 门控/背压状态（来自 `core/utils/resource_lock.py::GlobalResourceLock.get_status()`）
- `tasks`: 当前活跃任务列表（来自 `GlobalTaskScheduler.get_active_tasks()`）

## `routers/admin/` 运维路由（统一前缀 /api/v1/admin/）

> **警告**：运维域端点仅供开发/运维使用，业务端**永远不应**引用此目录下的端点。

| 文件 | 主要端点 |
|---|---|
| `auto_heal.py` | 自愈系统：stats/patches/apply/rollback/reject/check/source 操作 |
| `data_ops.py` | 数据运维：summary/daily/weekly/planner/memory denoise |
| `remote_ops.py` | 远程操作：file action/approve/reject |

## 顶层独立路由

### `routers/openai_compat.py`

**路径前缀**: `/v1`

OpenAI API 兼容接口，保留 OpenAI SDK 标准路径：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/models` | GET | OpenAI 兼容模型列表 |
| `/v1/embeddings` | POST | OpenAI 兼容向量嵌入 |
| `/v1/chat/completions` | POST | OpenAI 兼容对话补全 |

**使用示例**:

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-api-key"
)

response = client.chat.completions.create(
    model="qwen-7b",
    messages=[{"role": "user", "content": "你好"}]
)
```

### `routers/websocket.py`

**路径**: `WS /api/v1/ws`

WebSocket 连接端点（文件位于顶层，由 `v1_router` 内部 `include_router` 引入，最终挂在 `/api/v1/ws`），支持：

- 实时消息推送
- 流式对话
- 心跳检测
- 主动关怀通知

**连接示例**:

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/ws?token=xxx&user_id=xxx');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp }));
    } else {
        // 处理消息
    }
};
```

### `routers/demo.py`

演示用路由，不参与核心业务流程。

## 架构设计

### 请求处理流程

```
┌─────────────────────────────────────────────────────────────┐
│                    HTTP Request                              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Router                            │
│  - 路由匹配（/api/v1/* 或 /v1/* 或 /api/v1/admin/*）         │
│  - 参数验证                                                  │
│  - 中间件处理                                                │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Route Handler                             │
│  - 业务逻辑调用                                              │
│  - 错误处理                                                  │
│  - 响应封装                                                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Service Layer                             │
│  - 业务服务（chat / memory / image / ...）                   │
│  - C++ 调度器（CPPSchedulerEngine，GPU 访问唯一入口）        │
└─────────────────────────────────────────────────────────────┘
```

### 响应格式

**成功响应**:

```json
{
    "status": "success",
    "data": { ... },
    "timestamp": "2026-06-18T10:00:00Z"
}
```

**错误响应**（错误统一返回 `{success: False, error: "..."}`，首字超时要给中文兜底）:

```json
{
    "success": false,
    "error": "错误描述"
}
```

### 错误码定义

| 错误码 | 说明 |
|---|---|
| INTERNAL_ERROR | 内部错误 |
| INVALID_REQUEST | 无效请求 |
| NOT_FOUND | 资源未找到 |
| UNAUTHORIZED | 未授权 |
| RATE_LIMITED | 请求频率限制 |

## 使用示例

### 发送聊天消息

```bash
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好",
    "conversation_id": "conv_123",
    "user_id": "user_456"
  }'
```

### OpenAI 兼容对话补全

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "model": "qwen-7b",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

### 健康检查

```bash
curl http://localhost:8000/api/v1/health
```

## 配置

### CORS 配置

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 配置单一源

所有配置统一由 `config/integrated_config.py` 管理，路由层不应自建配置文件。

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [核心层文档](../core/README.md)
- [服务层文档](../core/services/README.md)
- [评估报告](./评估报告.md)

## 已删除说明

以下旧文件已于 **2026-06-17** 全部删除，端点已由新路由完整覆盖：

- `routers/api_v1/` 子目录（旧版业务路由聚合，含 `chat.py` / `daily_data.py` / `food.py` / `image.py` / `media.py` / `memory.py` / `misc.py` / `study_notifications.py` / `system.py` / `vision.py` 等）
- `routers/api_router.py`（旧版 API 路由聚合入口）
- `routers/session_router.py` → 已由 `v1/sessions.py` 覆盖
- `routers/memory_router.py` → 已由 `v1/memories.py` 覆盖
- `routers/study_router.py` → 已由 `v1/vocab.py` + `v1/tutor.py` + `v1/workspace.py` 覆盖
- `routers/workspace_router.py` → 已由 `v1/workspace.py` 覆盖
- `routers/peer_chat_router.py` → 已由 `v1/peer_chat.py` 覆盖
- `routers/health_router.py` → 已由 `v1/health.py` 覆盖
- `routers/model_router.py` → 已由 `v1/models.py` 覆盖
- `routers/persona_router.py` → 已由 `v1/personas.py` 覆盖
- `routers/plugin_router.py` → 已由 `v1/plugins.py` 覆盖
- `routers/user_router.py` → 已由 `v1/user.py` 覆盖
- `routers/data_ops_router.py` → 已由 `admin/data_ops.py` 覆盖
- `routers/openai_compat_router.py` → 已由 `openai_compat.py` 覆盖
- `routers/websocket_router.py` → 已由 `websocket.py` 覆盖
