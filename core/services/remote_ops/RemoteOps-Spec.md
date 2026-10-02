# 远程能力服务（RemoteOps Service）架构大纲

## 1. 核心定位
本服务 (`core/services/remote_ops`) 旨在为小友核心提供 **安全、受控、可审计** 的远程操作能力，使其能够作为“远程助手”执行本机任务，并在效率与安全之间做分级平衡。

它不仅是简单的命令转发，而是构建在 workspace 安全边界之上的“代理层”。

## 2. 核心原则
1.  **分级安全 (Tiered Safety)**: 学习文档类操作在 Study 沙箱内默认直写；未来系统命令等高风险操作再走审批。
2.  **最小权限 (Least Privilege)**: 文件操作仅限于 `workspace/study` 目录，严禁访问系统敏感目录（如 Windows/System32）。
3.  **可追溯 (Auditability)**: 关键操作需有日志记录（Request ID、操作者、时间、结果）。
4.  **显式开启 (Explicit Opt-in)**: 功能默认关闭，需在配置文件显式 `enabled=true` 才生效。

## 3. 架构分层

### 3.1 接入层 (Entry Layer)
-   **QQ Bot (`clients/bots`)**:
    -   `handlers/system.py`: 解析 `/截图`、`/文件`、`/批准` 等自然语言指令。
    -   `handlers/command_router.py`: 路由分发，负责第一层 Master 权限校验。
-   **HTTP API (`routers/workspace_router.py`)**:
    -   `POST /api/v1/workspace/remote/file/action`: 文件操作入口。
    -   `POST /api/v1/workspace/remote/approve`: 审批确认入口（当前主要为后续高风险能力预留）。

### 3.2 业务逻辑层 (Service Layer)
-   **RemoteOpsService (`core/services/remote_ops/service.py`)**:
    -   **功能**: 统一调度入口，桥接 Workspace Study 沙箱。
    -   **逻辑**:
        -   读/列出/写入/追加/建目录/存在判断均在 Study 沙箱内直接执行。
-   **ApprovalService (`core/services/remote_ops/approval.py`)**:
    -   **功能**: 管理审批单生命周期。
    -   **存储**: 内存存储 (Dict)，支持 TTL 过期（默认 5 分钟）。
    -   **状态**: Pending -> Approved / Rejected / Expired。

### 3.3 数据/执行层 (Execution Layer)
-   **WorkspaceService (`core/services/workspace`)**:
    -   提供受限的文件读写能力（`Study` 目录沙箱）。
-   **System Executor (待实现)**:
    -   负责安全的 Shell 命令执行（如 `subprocess` 封装），需配合白名单。

## 4. 功能模块与代码映射

| 功能模块 | 对应文件/目录 | 说明 |
| :--- | :--- | :--- |
| **服务入口** | `core/services/remote_ops/__init__.py` | 导出 `get_remote_ops_service` |
| **核心逻辑** | `core/services/remote_ops/service.py` | 风险判断、拦截逻辑、Workspace 桥接 |
| **审批系统** | `core/services/remote_ops/approval.py` | Token 生成、校验、回调执行 |
| **API 路由** | `routers/workspace_router.py` | `/remote/file/action`, `/remote/approve` |
| **QQ 处理器** | `clients/bots/handlers/system.py` | `handle_remote_file`, `handle_approval` |
| **QQ 命令** | `clients/bots/handlers/command_router.py` | 注册 `/文件`, `/批准`, `/拒绝`, `/截图` |
| **配置项** | `clients/bots/qq/settings.py` | `REMOTE_FILE_OPS_ENABLED` 等开关 |

## 5. 已实现功能清单
-   [x] **远程截图**: `/截图` (QQ -> Handler -> PIL ImageGrab -> 回传)
-   [x] **受控文件浏览**: `/文件 列表`, `/文件 读` (只读，无风险，直接执行)
-   [x] **受控文件写入**: `/文件 写`, `/文件 追加`, `/文件 建目录`（Study 沙箱内默认直写）
-   [x] **审批预留通道**: `/批准`, `/拒绝` 已保留，供后续高风险远程命令接入
-   [x] **权限控制**: 仅 Master 账号可用，且需配置开启 `remote_file_ops_enabled`

## 6. 后续演进路线 (Roadmap)
1.  **命令执行 (Command Executor)**:
    -   新增 `/执行 <cmd>` 能力。
    -   实现 `SafeCommandExecutor`，支持命令白名单（如 `python scripts/*.py`, `npm run build`）。
    -   接入审批流：所有命令执行默认均需审批。
2.  **审计日志 (Audit Log)**:
    -   记录所有 `RemoteOps` 的操作流水到 `logs/remote_ops.log` 或数据库。
3.  **文件上传/下载**:
    -   支持通过 QQ 发送文件直接保存到 Workspace。
    -   支持 `/下载 <path>` 将服务器文件发给 QQ。
