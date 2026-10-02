# 角色与人设资料

`configs/` 统一存放 v1 单文件人设和 v2 分层人设；Agent 的 Prompt 目录负责模板与组装代码。

新角色可直接在现有配置的 `meta.context_profile` 内嵌核心、语气、稳定关系、时效阶段资料和带 ID 的长期资料数组，
无需复制角色专用 Python 模块或强制拆成多文件。富资料角色也可引用文件/递归目录。
通用接入契约见 `../agents/chat_agent_components/persona_system/prompt/README.md`。

分层资料职责固定为：
- `core`：长期稳定身份与底层人格；
- `voice`：聊天表达、注意力、节奏和即时反应；
- `relationship`：长期稳定关系基线；
- `temporal_profile`：当前学年、阶段身份等会过期的慢变化事实，按日期窗口动态注入；
- `knowledge`：按话题检索的长期背景与历史事实；
- `companion_data/<scope>_data/runtime/`：今天在哪里、正在做什么等现场状态。

月度角色变化仅保存在角色数据目录 `monthly/YYYY/MM/summary.json` 的 `persona_evolution` 字段中，由 `read_monthly_summary` 工具读取；不再维护独立的 `configs/evolution/` 副本。`configs/extra/` 的月度画像蒸馏及可选注入保持原有行为。

## 叶 Persona 2.0

- `configs/ye/core_ye.json`：核心身份，声明稳定的 `meta.scope=ye` 与历史别名。
- `configs/ye/voice_ye.json`：表达风格。
- `configs/ye/knowledge/`、`configs/ye/overlays/`：按需读取的角色资料和条件覆盖层。
- `companion_data/ye_data/runtime/current_state.json`：运行状态，由 `config/ye_runtime_state_extraction.json` 配置读写路径。
- `companion_data/ye_data/memories/persona_v2/`：分层人设使用的语义及事件记忆，与已有记忆存储区分。

## Ling Prompt V2 草稿

- `configs/ling/core_ling.json`：精简后的稳定核心，并声明 `temporal_profile.json`。
- `configs/ling/voice_ling.json`：语气、节奏、注意力、第一反应、幽默、情绪、关系表达、关心、边界与主动分享。
- `configs/ling/relationship_ling.json`：与Master的稳定关系历史和长期关系基线。
- `configs/ling/temporal_profile.json`：当前高三阶段等带有效期事实；到期后自动停止注入。
- `configs/ling/knowledge/`：长期背景与历史资料，不再承担当前年级等阶段状态。

`PersonaManager` 只把 `<scope>/core_<scope>.json` 暴露为分层人设入口，不把语气、知识、覆盖层列成可切换的人设。叶继续使用 `core_ye.json` 作为客户端标识，历史 `qq/Ye_QQ_Master.json` 通过声明的别名兼容；不会改变现有会话与数据 scope。

人设原始资料和运行数据已由 `.gitignore` 排除。新增角色目录时，应根据资料内容设置对应忽略规则。

验证：`tests/scripts/personas/verify_qq_v2_persona_switch.py`、`verify_ye_layered_prompt.py`、`verify_ye_runtime_state_writeback.py`、`verify_temporal_profile.py`。
