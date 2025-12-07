# xiaoyou-core 系统架构全面重构计划

## 当前架构审查与基线
- 后端入口：`main.py` 负责应用初始化、路由挂载、异常处理与静态前端挂载（d:\AI\xiaoyou-core\main.py:52–80, 128–166, 169–197）。
- 配置系统：统一强类型配置（Pydantic v2），通过 `get_settings()` 提供单例（d:\AI\xiaoyou-core\config\integrated_config.py:150–191）。YAML 配置管理用于运行时加载与覆盖（d:\AI\xiaoyou-core\core\config_manager.py）。
- 路由聚合：`routers/api_router.py` 提供消息/语音/健康等 HTTP 接口（d:\AI\xiaoyou-core\routers\api_router.py:109–170）。WebSocket 入口在 `websocket_router.py` 与 `fastapi_websocket_adapter.py`。
- 模型层：`core/model_adapter.py` 统一适配文本/图像/远程推理（d:\AI\xiaoyou-core\core\model_adapter.py:89–158）。文本生成管线在 `core/text_infer.py`（d:\AI\xiaoyou-core\core\text_infer.py:191–200）。
- 独立推理子服务：`services/infer_service/infer_service.py` 作为 REST 推理服务（d:\AI\xiaoyou-core\services\infer_service\infer_service.py:64–73, 198–200）。
- 前端：`frontend/Aveline_UI` 为 React+Vite 应用，后端静态挂载 `dist`。（d:\AI\xiaoyou-core\main.py:128–141）
- 工具与测试：`tools/tts_test.py` 用于 TTS 环境自检（d:\AI\xiaoyou-core\tools\tts_test.py:20–23）。`tests/` 覆盖配置、API 与 WS。

## 重构总目标
- 模块化边界明确、接口稳定且可测试；错误处理与观测性完善；在保持全部业务功能的同时提升可维护性与性能。
- 统一模型管理与适配层，支持版本控制与热更新；前端架构组件化与状态管理规范化；依赖分组与环境标记清晰。

## 目标架构概览
- 分层模型：
  - 核心平台层：配置、日志、事件总线、调度与缓存（`config/`, `core/utils/`, `core/event_bus.py`, `core/scheduler/`）。
  - 领域服务层：会话/记忆、语音、图像、代理（`core/memory`, `core/voice`, `core/image`, `core/agents`）。
  - 通信接口层：HTTP/WS 路由与协议（`routers/`, `core/fastapi_websocket_adapter.py`, `core/websocket_manager.py`）。
  - 模型适配层：文本/视觉/图像生成/远程推理（`core/text_model_adapter.py`, `core/vision_model_adapter.py`, `core/sd_adapter.py`, `core/llm/infer_service_client.py`）。
  - 基础设施层：模型注册、生命周期、资源监控（`core/model_manager.py`, `core/lifecycle_manager.py`, `services/resource_monitor.py`）。
- 目录结构（目标）：
  - `app/` 应用入口与装配（替代分散启动逻辑，保持 `main.py` 兼容入口）。
  - `core/` 保留但按模块边界重组；`core/model/` 仅保留抽象与必要实现。
  - `services/` 独立子服务（推理、监控、回退），统一服务模板与健康探针。
  - `frontend/` Monorepo 化：`apps/aveline-ui` 与潜在 `apps/admin-ui`；共享 `packages/api-client`。
  - `configs/` 强类型配置+YAML 映射；`requirements/` 分组管理。

## 阶段1：系统架构分析
- 审阅与标注核心文件职责、交互与依赖，产出现状架构图（Mermaid + PNG）。
- 依赖拓扑与模块耦合度分析；识别可保留的核心功能点与需要抽象的通用能力。
- 输出：《现有架构评审》与《模块依赖图》，包含代码参考定位。

## 阶段2：架构重构实施
- 模块化设计：为每个功能建立独立封装与明确接口（HTTP/WS、Adapter、Service、Repository）。
- 清晰接口定义：
  - 错误返回统一 Envelope：`{status,error_code,detail,request_id}`（与 `api_router` 兼容）。
  - WebSocket 消息协议稳定化：心跳、速率限制、上下文标识与错误事件。
- 错误处理机制：全局异常处理与局部 try/except 统一记录与脱敏（参考 d:\AI\xiaoyou-core\main.py:84–93）。
- 性能优化：
  - 请求级性能中间件与指标上报（参考 d:\AI\xiaoyou-core\core\async_monitor.py 及 d:\AI\xiaoyou-core\main.py:96–98）。
  - 模型内存/缓存策略统一；GPU/CPU 路径降级策略一致化。
- 冗余清理：依据 `CLEANUP_REPORT.md` 与静态分析报告，删除未用模块与脚本，保留兼容适配层。
- 产出：重写后的核心架构文件、接口规范文档与变更日志。

## 阶段3：模型集成
- 保留 `models/` 全量文件；新增 `models/manifest.json`（名称、路径、参数、能力、校验哈希）。
- 适配层：为每个模型创建 Adapter，实现统一接口：`load/unload/info/generate(capabilities)/metrics`。
- 统一模型加载与管理：`ModelManager` 负责注册/缓存/生命周期/资源监控与事件（参考 d:\AI\xiaoyou-core\core\model_manager.py）。
- 版本控制与热更新：
  - 目录监听与安全重载（参考 d:\AI\xiaoyou-core\main.py:187–191 的 watcher 调用）。
  - 变更检测：基于目录哈希（参考 d:\AI\xiaoyou-core\core\model_adapter.py:63–87）。
- 与独立推理服务对接：统一客户端协议与错误语义（参考 d:\AI\xiaoyou-core\services\infer_service\infer_service.py）。

## 阶段4：前端重构
- 组件化开发与状态管理（建议使用 Zustand/Redux Toolkit），统一 API Client（TypeScript，OpenAPI 生成或手写 `packages/api-client`）。
- 响应式布局与性能优化：按需路由拆分、懒加载、SSR/SSG（Next 应用保留，Vite 应用按需优化）。
- 类型与契约：将后端 `schemas`（d:\AI\xiaoyou-core\core\api\schemas.py）导出为前端类型；错误 Envelope 一致。
- 静态资源挂载与兼容：保持 `main.py` 静态挂载策略，兼容 `dist` 与多应用目录。

## 阶段5：依赖管理
- 新版 `requirements.txt` 与分组：
  - 核心：`fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx`, `websockets`。
  - 模型（可选）：`transformers`, `torch`, `accelerate`, `safetensors`, `sentencepiece`。
  - 语音（可选）：`soundfile`, `numpy`, `scipy`, `edge-tts` 或本地 TTS 相关。
  - 开发/测试：`pytest`, `pytest-asyncio`, `ruff` 或 `flake8`, `mypy`, `black`。
- 环境标记与分发：提供 `requirements/core.txt`, `requirements/models.txt`, `requirements/dev.txt` 并在根 `requirements.txt` 加聚合安装提示；区分 CPU/GPU（例如 `torch==<cpu>` 与 `torch==<cuda>` 的说明与安装指南）。
- 兼容性说明：Windows 环境与常见 CUDA 版本对应矩阵，提供安装脚本与排障指南。

## 阶段6：交付与质量保证
- 架构设计文档：包含分层说明、接口契约、模型适配方案与运维指南（更新 `ARCHITECTURE.md`）。
- 测试用例：
  - 单元：配置、错误处理、适配器接口、模型管理。
  - 集成：HTTP/WS、推理服务联通性、静态挂载回退。
- 性能基准：文本生成耗时/吞吐、内存占用与 OOM 降级验证；TTS 环境自检维持（参考 d:\AI\xiaoyou-core\tools\tts_test.py）。
- 迁移指南：从旧接口到新契约的映射、配置迁移（旧 YAML → 新设置）、脚本替换建议。
- 版本控制记录：按模块提交，变更可追溯（说明 PR/Commit 粒度与标签规范）。

## 兼容与风险控制
- 保持旧入口 `main.py` 与路由路径兼容；为旧接口提供适配器与废弃期说明。
- 提供回滚策略（保留 `backup/` 快照），可在功能风险时快速切换至旧版本。

## 验收标准
- 所有测试通过，接口契约一致；性能基线达标或提升；文档与迁移指南完整；依赖安装在 Windows/CPU/GPU 环境可复现。

## 后续执行要点（确认后实施）
- 输出现状架构图与详细评审文档。
- 按模块提交重构：平台层→通信层→模型层→前端→测试与基准。
- 提交新的依赖分组与安装说明；完成模型清单与热更新机制。
