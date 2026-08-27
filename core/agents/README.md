# core/agents 目录说明

`core/agents` 目录主要存放“智能体（Agent）”相关的代码，是 Xiaoyou Core 中最贴近“人格与行为”的一层。这里的 Agent 负责：
- 接收来自接口层 / 服务层的抽象请求（如一次对话、一次学习任务）
- 组织上下文、记忆、模式（学习 / 日常聊天 / 英语等）
- 调用 LLM / 语音 / 图像等模块生成多模态响应

当前目录下最核心的实现是 `ChatAgent` 及其组件化拆分。

## ChatAgent 总览

- 主入口文件：`chat_agent.py`
- 组件目录：`chat_agent_components/`

`chat_agent.py` 对外暴露统一的聊天接口，例如：
- 普通单轮 / 多轮对话
- 流式回复（边生成边推送）
- 学习模式对话

内部则尽量保持薄壳（thin wrapper），把实际逻辑委托给 `chat_agent_components` 下的各个子模块。

## chat_agent_components 组件划分

为避免单文件过大、职责混乱，ChatAgent 已被拆分为多个小而专一的组件，每个组件对应一个 Python 文件：

- `context.py`：负责构建当前对话需要的上下文，包括历史消息裁剪与摘要
- `triggers.py`：负责“彩蛋”与触发器逻辑，例如关键词触发特殊回复、惊喜语音等
- `streaming.py`：流式输出的**编排层**（thin orchestration），按预处理→上下文构建→模型解析→多轮流式生成→后处理→空回复重试等阶段串联 `streaming_pipeline` 子包，将 LLM Token 实时推送给前端或调用方
- `streaming_pipeline/`：从 `streaming.py` 拆分出的流式管线子包，按职责分为 `preparation.py`（预处理）、`dynamic_context.py`（动态上下文与消息构建）、`model_resolution.py`（模型解析与原生工具准备）、`tag_stream_parser.py`（流式标签解析状态机 `StreamTagSession`）、`postprocess.py`（后处理清洗链）、`empty_retry.py`（空回复兜底重试）
- `persona.py`：负责判断当前对话模式（如普通聊天 / 英语练习 / 情感支持等），并生成对应的 System Prompt / 人设信息
- `study.py`：负责学习模式相关逻辑，包括学科分类、学习上下文构建等
- `handler.py`：负责非流式消息处理的主流程，协调调用其他组件，产出最终回复
- `history.py`：负责会话标题生成、历史消息持久化与清理

### Prompt 与工具 schema 预算

- `BaseTool.category` 只作为人设权限边界；`core/tools/tool_metadata.py` 另行维护发现领域、标签、风险等级、加载策略和短摘要，避免一个分类字段承担互相冲突的职责。
- `context_persona.py::select_message_tools()` 根据本轮消息稳定选择常用候选工具；常驻的小型 `search_tools` schema 在关键词路由未命中时，只检索当前人设有权限的能力。
- `search_tools` 返回 3–5 个候选后，流式与非流式调用链只在下一模型轮次追加候选 schema，不会回退到全量工具注入。
- 流式与非流式路径共用同一份 `active_tools`，避免文本 prompt 声称可用的工具与原生 function schema 不一致。
- 云模型只通过原生 function schema 接收工具定义；`assembler.py` 不再重复注入精简工具列表。本地模型仍保留文本工具说明作为兼容路径。
- `model_resolution.py` 会记录本轮 `tool_count` 与 `schema_chars`，用于持续检查工具上下文是否重新膨胀。
- 回归脚本：`tests/scripts/prompt/verify_prompt_tool_schema_budget.py` 和 `tests/scripts/prompt/verify_tool_discovery_metadata.py`。

一个典型的调用流程大致如下：
1. 外部服务（如 `AvelineService`）调用 `ChatAgent` 的对话接口
2. `chat_agent.py` 内部根据是否流式、是否学习模式等条件，调用对应组件
3. `context.py` 从记忆系统中取出历史消息，构建 Prompt
4. `persona.py` 根据当前模式生成合适的人设与系统提示词
5. LLM 模块生成回复，`streaming.py` 负责边生成边推送（如启用流式）
6. `history.py` 记录本轮消息，如有需要生成会话标题等
7. `triggers.py` 在必要时追加彩蛋 / 特殊行为

## 开发建议

- 修改 ChatAgent 行为时，优先找到对应组件文件，不要在 `chat_agent.py` 中继续堆积逻辑
- 如果发现某块逻辑越来越庞大（例如学习模式增加了多种子模式），优先考虑在 `chat_agent_components` 下继续拆分或新增文件
- 保持组件的职责单一：一个文件解决一个核心问题，避免“上帝对象”
- 对外暴露的接口（方法签名、返回结构）尽量保持稳定，必要变更时需要同步检查：
  - `AvelineService` 等上层服务
  - WebSocket / HTTP API 的请求与响应模型

## 与其他模块的关系

Agent 层本身不直接关心底层模型实现细节，而是通过模块层与核心引擎交互：

- 通过 LLM 模块获取文本回复
- 通过记忆模块读取 / 写入用户记忆、对话历史
- 通过语音模块生成 TTS 或处理 ASR
- 通过事件总线发布重要事件（如学习成绩、情绪波动等）

因此在修改 Agent 行为时，如果涉及到底层模块（如切换模型、修改缓存策略），请同时检查：
- `core/modules/` 下对应模块
- `core/core_engine/` 下的配置与生命周期管理逻辑

