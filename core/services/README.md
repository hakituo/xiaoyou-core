# Service Layer (服务层)

## 概览

`core/services` 是后端业务编排层，负责把对话、主动关怀、日记、画像、调度、监控等能力串成完整链路。

## 目录用途与联动关系

| 模块 | 主要作用 | 关键上游 | 关键下游 |
|---|---|---|---|
| `aveline/` | 对话主编排、工具调用、记忆整合 | chat 路由、WebSocket | LLM/记忆模块、`workspace`、`active_care` |
| `active_care/` | 主动关怀决策与执行 | `life_simulation`、`emotion`、`workspace snapshot`、设备上下文 | WebSocket 推送、`workspace` 日记/提醒 |
| `planning/` | 用户计划与角色日程共用的确定性评分/容量排程引擎 | `journal`、`character_daily` | 纯内存排程结果（不读业务数据、不持久化） |
| `workspace/` | 用户可操控记录入口（状态/提醒/日记聚合）；自动每日任务只镜像 Journal 主计划 | 工具层、路由层、`active_care` | `journal`、`daily`、`status_manager`、本地 JSON |
| `journal/` | 日记、日报总结和用户学习主计划持久化 | `study`、`planning`、`workspace`、`active_care executor` | `companion_data/user_data/daily/*`、Study Daily `plan.md` |
| `daily/` | 每日生活画像记录与读取 | 工具层、`workspace` 快照 | `Aveline_daily_data/daily_records/*` |
| `scheduler/` | Python 侧调度封装与 C++ 调度桥接 | `aveline`、`journal`、多模块任务提交 | `CPPSchedulerEngine`、GPU/CPU任务执行 |
| `life_simulation/` | 生理状态模拟（饥饿/精力/节律），已重构为门面+协调器架构 | `active_care`、系统事件 | 决策上下文、状态播报 |
| `user_physiology/` | 用户生理指标接收与缓存 | WebSocket/HTTP 上报 | `active_care` 决策上下文 |
| `immune/` | 服务健康检查与自愈重启 | 生命周期管理器、监控数据 | 服务重启、系统保护 |
| `monitoring/` | 资源与系统监控采样 | 系统/硬件指标 | `immune`、状态面板 |
| `intent/` | 意图识别服务化入口 | 路由/Agent | 工具选择、命令执行 |
| `metacognition/` | 元认知记忆与策略条目管理 | 对话链路 | 决策增强、长期偏好 |
| `study/` | 学习服务（从 `study_service.py` 扩展为完整目录，含会话/画像/弱项追踪） | 用户学习请求 | 学习工具、画像、`journal` 总结输入、前端统计 |
| `command/` | 命令处理封装 | 对话命令入口 | 记忆/模型/系统动作 |
| `communication/` | 对外消息内容拼装 | 业务服务 | 多端消息格式输出 |
| `reaction/` | 反应与行为节律管理 | `life_simulation`/`active_care` | 主动行为触发 |
| `vtube/` | VTube Studio 同步桥接 | 情绪状态/角色状态 | VTS 动作与表情 |
| `auto_heal/` | 运行时日志驱动的自动 bug 检测与修复（7 层安全机制） | `log_sanitizer` 错误回调 | `WorkspaceService` 源码读写、`AvelineService` LLM 分析 |
| `data_ops/` | BERT 语义分析流水线 + 日报/周报 + 记忆去噪 + 任务规划 | 记忆系统、BERT 模型 | 报告文件、压缩后记忆 |
| `self_improvement/` | 结构化学习、纠正追踪、核心记忆管理（MEMORY.md） | 用户纠正/错误 | `project_rules.md`、`MEMORY.md` |
| `discovery/` | UDP 服务发现信标（局域网广播，端口 28899） | 无 | 安卓客户端 |
| `maintenance/` | 维护服务（记忆同步到状态） | 记忆系统 | `user_status.json` |
| `remote_ops/` | 远程操作服务（文件操作 + 审批流） | admin 路由 | `workspace` |

## 当前关键联动链路

### 1) 对话主链路
`routers/api_v1/chat` → `aveline/service.py` → `scheduler/*`（LLM任务）→ 记忆写入 → WebSocket/HTTP 返回

### 2) 主动关怀链路
`active_care/proactive_checker.py` → 读取 `workspace snapshot` + `life_simulation` + `user_physiology` + `emotion` → `active_care/decision.py` → `active_care/executor.py` 推送消息 → `workspace/journal` 记录

### 3) 记录落盘链路
`workspace/service.py` → `journal/storage.py`（日记）+ `daily/manager.py`（画像）+ `status_manager.py`（状态）+ `reminders.json`（提醒）→ `Aveline_daily_data/*`

### 4) 稳定性保护链路
`monitoring/*` + 运行时错误回调 → `immune/service.py` → 生命周期重启与降级保护

### 5) 自愈链路
`log_sanitizer` 错误回调 → `auto_heal/anomaly_detector.py`（异常检测）→ `auto_heal/root_cause_analyzer.py`（LLM 根因分析）→ `auto_heal/patch_generator.py`（补丁生成）→ `auto_heal/patch_sandbox.py`（沙箱验证）→ `auto_heal/patch_manager.py`（三重备份 + 人工审批）→ `WorkspaceService` 源码写入

### 6) 数据运维链路
记忆系统 + BERT 模型 → `data_ops/analysis_pipeline.py`（三级异步 Worker：`summary_worker` / `human_digest_worker` / `task_planner_worker`）→ `data_ops/memory_compactor.py`（记忆去噪压缩）→ 报告文件输出 + 任务规划

### 7) 自我改进链路
用户纠正 / 错误日志 → `self_improvement/correction_tracker.py`（6 种纠正信号检测）→ `self_improvement/learning_promoter.py`（晋升机制）→ `self_improvement/drift_guard.py`（漂移防护）→ `self_improvement/core_memory.py`（MEMORY.md 写入）+ `project_rules.md` 同步

### 8) 学习文件夹联动链路
`workspace/service.py` → `core/tools/study_data_tool.py`（Study 安全读写）+ `study/service.py`（学习会话/统计）→ `d:/AI/Study` + `daily_records.study.sessions`

### 9) 共享确定性计划链路

`StudyService/WeaknessTracker/昨日 plan.json + character_daily.yaml` → 各业务候选适配器 → `planning/engine.py`（稳定哈希抖动 + 加权评分 + 固定项优先 + 冲突/容量约束）→ Journal 用户主计划 / CharacterDaily 角色计划。CharacterDaily 直接以全部已加载模板键为角色真源，不维护计划角色白名单。中午、傍晚的用户计划压缩复用同一引擎，不调用 LLM。Workspace `daily_tasks` 只是主计划的 MDP 快照，不再独立从学习摘要生成第二套计划，也不为自动镜像项创建硬提醒。

## Life Simulation 重构说明（2026-07-11）

原 `LifeSimulationService`（532 行）承担了 12+ 个职责，已重构为门面+协调器分层架构：

- **`service.py`**（295 行）：轻量级门面，保留全部外部 API（28 个方法 + 16 个属性），委托到 `LifeOrchestrator`
- **`orchestrator.py`**（415 行）：总协调器，管理子模块初始化、主监控循环、每分钟 tick、状态构建
- **`coordinators/`**：6 个专职协调器，各管一域
  - `HardwareCoordinator` → 硬件状态采集与阈值检测
  - `ActorCoordinator` → 角色状态与关系管理
  - `FoodCoordinator` → 食物库存、消化与自动进食
  - `SleepCoordinator` → 睡眠状态查询与中断通知
  - `ReactionCoordinator` → 仪式触发与自发反应
  - `WebSocketCoordinator` → 状态广播

架构层次：`LifeSimulationService`（门面）→ `LifeOrchestrator`（总协调）→ 6 × `Coordinator`（专职）→ 子模块

外部调用者零修改，`get_life_simulation_service()` 单例和所有方法签名保持不变。

## Workspace 解耦说明

- `workspace/service.py` 保留对外 Facade 职责，负责状态、提醒、日记等统一入口。
- 快照聚合逻辑已独立到 `workspace/snapshot.py`，由 `WorkspaceSnapshotBuilder` 负责记录聚合、画像摘要与完整度计算。
- 这样做后，`workspace/service.py` 复杂度下降，后续扩展快照字段不会继续膨胀服务主文件。
- Study 读写路径与工具层统一复用 `study_data_tool` 的安全路径策略，避免出现双套规则。
- `study/action` 使用白名单动作控制，阻止非授权文件操作。
- Study 写入动作会自动同步学习记录到 daily 画像，确保学习行为可回溯。
- Workspace 核心保存动作会同步写入 Weighted Memory，保障后续记忆检索可见。
- 用户计划真源是 `journal` 的 `plan.json` / Study Daily `plan.md`；Workspace 自动任务是单向镜像快照。只有用户手动新增或修改的定时项保留硬提醒创建行为。

## 相关文档

- [系统架构文档](../../PROJECT_TECHNICAL_REFERENCE.md)
- [评估报告](./评估报告.md)
- [核心引擎层文档](../core_engine/README.md)
- [模块层文档](../modules/README.md)

---

最后更新：2026-08-25
