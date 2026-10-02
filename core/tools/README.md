# 角色工具架构

工具实现注册一次，角色通过配置获得独立的工具集合。常驻列表、文本路由、搜索范围和执行权限分开处理，但共同服从角色策略。

```text
本轮persona → 稳定scope → tool_profiles.json
                         ├─ resident：每轮发送
                         ├─ on_demand：关键词命中或search_tools发现后发送
                         └─ disabled：禁止，优先于前两者
                               ↓
既有人设tool_access与运行时可用性过滤
                               ↓
原生工具schema / 本地文本协议 → execution.py → 业务工具
```

## 配置入口

编辑 `config/tool_profiles.json`，文件版本变化会在下一轮读取时生效，无需为新角色修改聊天流程。

- `defaults`：未单独配置的角色继承的基线。
- `roles`：键使用角色注册表的稳定 `meta.scope`，不使用显示名。
- `resident`：工具名列表；角色配置替换默认常驻列表。
- `on_demand`：工具名、`domain:领域` 或 `*`；角色配置可替换默认可用范围。常驻工具也属于允许集合。
- `disabled`：工具名或领域选择器，始终优先；默认、角色和模式的禁用集合累加。
- `modes`：模式常驻工具追加到角色集合；可覆盖按需范围及追加禁用项。
- `routes`：关键词只召回候选，不授予权限，不能绕过角色配置。

例如给某角色设置 `resident: ["search_tools", "calculator"]`、`on_demand: ["domain:information"]`、`disabled: ["get_weather"]`，它常驻搜索和计算，只能按需发现信息查询领域，且不能使用天气工具。新角色未写专属配置时继承默认设置。原有 `tool_access` 的类别、名称和模式限制继续生效。

## 当前常驻判断

| 角色/模式 | 常驻工具 | 理由 |
|---|---|---|
| 所有角色 | `manage_todo` | 当前重要的事顺手记下来、做完就划掉，比其它能力更常用 |
| 叶 | `search_tools`、`update_character_state` | 现场变化可能由角色主动产生，不依赖用户文本 |
| Aveline、Ling | `search_tools`、`message_peer` | 保留既有同伴互动能力，由角色自主决定使用 |
| 其他已配置角色/默认 | `search_tools` | 其他能力均可按需发现 |
| 学习模式 | 追加学习画像、进入/退出学习模式 | 学习会话的专用能力 |

待办是追加在角色常驻列表之上的公共能力，因此每个角色的 `resident` 都要列一遍（`roles.<scope>.resident` 是替换而非追加默认值）。

它只占一个工具：查看、记一条、划掉、删除合并进 `manage_todo` 的 `action` 参数，避免每轮多付三四份 schema（拆成四个工具时闲聊 schema 从 1457 字符涨到 3231 字符，合并后只涨到 1785 字符）。待办按角色隔离，存 `companion_data/<scope>_data/todo_list.json`，Aveline记的只有Aveline看得到。每轮 prompt 还会注入当前角色那份摘要，模型才知道有事没做完、做完了要去划掉。

时间查询与聊天时间戳重复、语音合成与已有语音输出协议职责不同、计算只在部分请求需要，因此三者均保留按需。记忆、人物档案、用户记录、天气、文件、计划、设备与主动关怀控制也按需。全部工具领域清单见 `TOOL_CATALOG.md`。

叶未接入原双角色的仿生体、投喂、商城与同伴系统，因此在其配置中禁用这些能力及跨角色文件管理；用户日常记录、学习、记忆等工具仍可按需使用。

## 代码职责

| 文件 | 职责 |
|---|---|
| `registry.py` / `base.py` | 实现注册与工具接口 |
| `tool_metadata.py` | 工具领域、别名和风险；不承担角色授权 |
| `config/tool_profiles.py` | 配置校验、按文件版本缓存 |
| `tool_policy.py` | 角色/模式常驻和按需范围、文本路由 |
| `tool_visibility.py` | 策略与原有人设权限、工具适用性取交集 |
| `tool_search_tool.py` | 只搜索编排层传入的允许集合 |
| `execution.py` | 流式、非流式、重试共用的授权检查和独立调用上下文 |
| `character_state_tool.py` | 当前角色现场状态参数校验与存储调用 |

请求的人设快照从工具准备一直传到执行。注册表中的实现不保存本次调用上下文：执行时浅复制工具实例并绑定独立上下文，拒绝未授权或停用的工具。既有业务服务仍按自身生命周期运行；本改动隔离工具配置和调用上下文，不重建全部业务服务。

## 叶现场状态

`config/ye_runtime_state_extraction.json` 的 `scene_write_mode=tool` 接管位置、活动、衣着、在场人物、身体状态和持有物。模型只传变化字段；省略保留，显式 `null` 清空。衣着及持有物传变化后的完整内容，避免放下一件物品时误清其他物品。

当前请求自动确定角色，参数不开放角色或路径选择。保存复用状态服务锁和现有 JSON I/O，标注 `source=llm_tool`，在运行元数据保留最近一次更新依据；重复值不重复写入，损坏文件拒绝覆盖。历史保存后的规则/UIE不再改这六个字段；规则、待办、期限及互动模式继续原处理。`scene_write_mode=automatic` 可恢复旧模式，原模型、实现和状态不删除。

该工具当前仅接入叶的状态存储及主对话工具循环；Active Care继续读取同一状态，本次未给主动消息生成新增工具循环。模型是否准确判断已发生、是否漏调用以及最终回复是否一致，需要后续真实对话验证，确定性测试不代替模型效果评估。

验证入口：`tests/scripts/prompt/verify_role_tool_profiles.py`、`tests/scripts/prompt/verify_tool_discovery_metadata.py`、`tests/scripts/prompt/verify_prompt_tool_schema_budget.py`、`tests/scripts/personas/verify_character_state_tool.py`、`tests/scripts/personas/verify_ye_runtime_state_writeback.py`。
