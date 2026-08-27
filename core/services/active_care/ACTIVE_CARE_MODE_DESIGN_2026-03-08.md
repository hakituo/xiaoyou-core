# Active Care 状态模式设计（想你模式 + 学习工作陪伴模式）

## 1. 背景与问题

当前 Active Care 主要围绕“晚安静默”和“普通主动关怀”工作，缺少“用户显式声明一个长期状态后，持续按该状态说话/触发”的能力。  
这导致两个体验问题：

1. 用户说“我要睡觉/学习/做事了”后，系统没有形成明确状态机，后续行为不稳定。  
2. 主动话题自由度较高，容易出现“猜测用户状态”的幻觉表达（如“看你状态不太对”）。

本设计目标是引入可持续、可退出、可约束的状态模式，先把行为边界定清楚，再讨论人工指定频率。

---

## 2. 目标

### 2.1 功能目标

新增统一模式层，支持至少三类状态：

- `goodnight_mode`（晚安静默）
- `miss_you_mode`（想你模式，偶尔表达“想你了”）
- `focus_mode`（学习/工作陪伴模式，偶尔轻量陪伴）

### 2.2 交互目标

- 用户一句话可进入模式（类似“晚安逻辑”）。
- 模式默认“持续有效”，直到用户显式结束（例如“我学习完了”）。
- 可选支持“预计时长”作为参考，但**不会自动退出**，退出以用户口令为准。

### 2.3 安全目标

- 模式期主动内容受强约束，不允许无依据推断用户行为。
- 睡眠模式优先免打扰；想你/陪伴模式允许低频触发，但语义必须可控。

---

## 3. 模式定义

### 3.1 goodnight_mode（已存在，需纳入统一模式层）

- 进入意图：`晚安/睡觉/睡了` 等。  
- 退出意图：`早安/起床/醒了` 等。  
- 行为：默认严格静默；仅在配置允许时执行低频探测。

### 3.2 miss_you_mode（新增）

- 场景：用户希望“偶尔被惦记”，例如“你可以偶尔想我吗”。  
- 进入意图：`想我/惦记我/偶尔找我` 等。  
- 退出意图：`先别想我了/停一下这个模式` 等。  
- 行为约束：
  - 只允许轻量情感句式（如“想你了”“你忙完再回我也行”）。
  - 不允许任务催办与状态猜测。
  - 不与睡眠模式冲突；若同时存在，睡眠模式优先。

### 3.3 focus_mode（新增，学习/工作）

- 场景：用户进入学习/工作阶段，希望被低频陪伴。  
- 进入意图：`我要学习了/我要工作了/开始专注` 等。  
- 退出意图：`学习完了/工作结束了/收工了` 等。  
- 时长输入（可选）：`学习2小时`、`工作90分钟`。  
- 行为约束：
  - 可发送简短鼓励/补水提醒/休息提醒。
  - 不做情绪诊断，不编造“看到你状态”。
  - 若用户未退出且预计时长已过，只提示“我还在陪你，需要我继续吗”，不自动结束模式。

---

## 4. 状态存储方案（基于 ActiveCareStorage.proactive_state）

建议新增字段（按 `default_user` 存储）：

- `relationship_mode`: `"none" | "goodnight" | "miss_you" | "focus"`
- `relationship_mode_started_ts`: `float`
- `relationship_mode_source`: `"user_intent"`
- `relationship_mode_note`: `str`（原始用户语句摘要）
- `focus_expected_end_ts`: `float`（可选）
- `focus_task_label`: `str`（学习/工作）
- `relationship_mode_last_probe_ts`: `float`
- `relationship_mode_last_message_ts`: `float`

说明：

- 不新增独立数据库，先复用 `proactive_state`，保持落地成本最低。
- 后续若模式变复杂，再迁移到 `Aveline_daily_data/status/relationship_mode.json`。

---

## 5. 入口与路由（拟实施）

### 5.1 入口文件

- `core/services/active_care/service.py`（用户消息意图入口）
- `core/services/active_care/proactive_checker.py`（调度与拦截）
- `core/services/active_care/decision.py`（提示词与内容边界）

### 5.2 用户语句到模式状态

在 `service.py` 的用户消息处理中，新增模式识别分支：

1. 先识别退出口令（防止“结束学习并晚安”冲突时状态残留）。  
2. 再识别进入口令。  
3. 写入 `proactive_state`。  
4. 强制刷新 `checker._next_llm_decision_ts` 到合理窗口（例如 2-5 分钟后）。

---

## 6. 决策与防幻觉约束（拟实施）

### 6.1 模式优先级

`goodnight_mode` > `focus_mode` > `miss_you_mode` > 默认策略

### 6.2 提示词约束

在 `decision.py` 根据模式注入硬约束：

- goodnight：仅允许“轻声收尾/不打扰”语义。
- focus：仅允许“陪伴+节律提醒”，禁止“你看起来很累/状态不好”。
- miss_you：仅允许“情感表达+不要求立即回复”。

### 6.3 输出检查（后处理）

在 `executor` 发送前增加简单规则过滤（建议）：

- 若命中禁用短语（如“看你状态不太对”），自动替换为中性句式。
- 长度上限控制（如 30~45 字）减少跑偏空间。

---

## 7. 与“多久叫我一次”的关系

本设计先只处理“状态”与“语义边界”，不锁定具体频率策略。  
频率相关参数后续单独设计，但当前模式层预留两个接口位：

- `relationship_mode_probe_interval_seconds`
- `relationship_mode_message_cooldown_seconds`

这样可在不改状态机的前提下单独调频。

---

## 8. 分阶段实施建议

### Phase A（最小可用）

1. 增加 `miss_you_mode` / `focus_mode` 的进入退出口令与状态存储。  
2. 在 `proactive_checker` 中按模式进行硬拦截或放行。  
3. 在 `decision` 注入模式提示词硬约束。

### Phase B（稳态增强）

1. 增加发送前禁用短语过滤。  
2. 增加模式行为诊断脚本（类似 `verify_active_care_portrait_quiet_hours.py`）。  
3. 增加模式事件日志（`daily/.../events/relationship_mode_events.jsonl`）。

---

## 9. 验收标准（文档版）

1. 用户说“我要学习了”后，Active Care 进入 `focus_mode`，直到“我学习完了”才退出。  
2. 用户说“晚安”后，不再出现“看你状态不太对”类消息。  
3. 用户开启“想你模式”后，可收到低频“我想你了”风格消息，且不含行为臆测。  
4. 任意模式下都可被显式退出口令立即终止。

