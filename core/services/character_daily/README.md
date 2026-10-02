# Character Daily (角色日常系统)

## 概述

Character Daily 负责角色的“今天怎么过”：生成每日活动计划、推进当前活动、维护 peer chat 的活动门控，并向主对话和 Active Care 暴露角色当前生活状态。

系统分为两个层次：

1. **DailyPlan**：决定“什么时候大体在做什么”。
2. **ActivityInstance**：为某个已确定的活动时段补充稳定的具体事实，例如目的、同行方式、地点、交通方式和其他细节。

角色是否属于“持续自主生活角色”不再由 Active Care 私有配置决定，而由通用 Character Runtime 能力统一声明。当前自主角色为：

- `aveline`
- `ling`
- `ye`

配置真源为 `config/yaml/character_runtime.yaml`，读取入口为 `core/character/runtime_roles.py`。Character Daily、SleepManager、Activity Return、Nightly 等需要判断自主角色的模块都应复用该入口，不自行维护角色白名单。

Peer chat 是独立能力，仍按自己的 persona/账号映射决定可互聊角色；“能自主生活”不等于“必须参加 peer chat”。

## 目录结构

```text
character_daily/
├── __init__.py              # 模块入口 + 全局单例
├── engine.py                # CharacterDailyEngine 主引擎（独立 async loop）
├── daily_plan.py            # DailyPlanGenerator：共享确定性排程
├── day_type_schedule.py     # workday/rest-day 完整日型配置解析
├── activity_instance.py     # ActivityInstance 解析、持久化与读取
├── nightly.py               # 次日 ActivityInstance 预生成入口
├── llm_plan_generator.py    # 历史兼容模块；主引擎不再依赖
├── activity_model.py        # ActivityType、ActivitySlot、DailyPlan
├── plan_view.py             # 计划格式化与工具返回文本
├── config.py                # Character Daily 配置加载与 SleepProfile 兼容
├── peer_chat_gate.py        # Peer chat 触发门控
├── reply_policy.py          # 被动回复策略
├── reply_policy_support.py  # ReplyPolicy 辅助函数
├── reply_hints.py           # 回复提示模板与 builder
├── interrupt_window.py      # /打断 临时聊天窗口
├── activity_return/         # 统一回归消息模块
│   ├── __init__.py
│   ├── instruction.py
│   ├── state.py
│   ├── scheduler.py
│   └── core.py
└── state.py                 # DailyPlan 状态持久化
```

主要配置：

- `config/yaml/character_daily.yaml`：传统日程模板与兼容配置。
- `config/yaml/character_day_types.yaml`：角色完整 `workday` / `rest_day` 日型骨架。
- `config/yaml/character_activity_instances.yaml`：ActivityInstance 各字段的角色/活动候选池。
- `config/yaml/character_runtime.yaml`：通用自主角色能力声明。

运行状态：

- `companion_data/character_daily/daily_state.json`：每日计划与当前活动状态。
- `companion_data/character_daily/activity_instances.json`：已经确定的 ActivityInstance 事实。

## 核心组件

### 1. ActivityType（活动类型）

**文件**: `activity_model.py`

活动类型用于 DailyPlan、回复策略、peer chat 和 Active Care 的粗粒度活动判断。当前包括 sleeping、waking_up、breakfast、lunch、dinner、cooking、studying、reading、housework、napping、walking、phone_scrolling、gardening、exercising、gaming、self_care、creative_hobby、shopping、idle、peer_chat 等。

`CHAT_ELIGIBLE_ACTIVITIES` 定义哪些粗粒度活动适合聊天；`BUSY_ACTIVITIES` / `DO_NOT_DISTURB_ACTIVITIES` 负责忙碌和不可打扰语义。

### 2. DailyPlanGenerator（每日计划）

**文件**: `daily_plan.py`

DailyPlan 只负责“时间 + 大类活动”，不应该承担同行人物、具体地点、出行方式等容易漂移的具体事实。

#### workday / rest-day

对已经在 `character_day_types.yaml` 中声明日型的角色，工作日与休息日是**两套完整计划骨架**，而不是在同一套计划上简单调权重。

每个日型可独立定义：

```yaml
workday:
  wake_time: "07:00"
  sleep_time: "23:00"
  time_blocks: [...]

rest_day:
  wake_time: "09:00"
  sleep_time: "00:30"
  time_blocks: [...]
```

当前 `aveline`、`ling`、`ye` 都使用完整日型配置。例如 Ling 的工作日可体现学校/住宿生活，休息日则允许更晚起床以及游戏、购物、散步等不同节奏；Ye 的工作日体现医学研究/实验安排，休息日更灵活。

生成流程：

1. 根据日期判定 `workday` 或 `rest_day`。
2. `day_type_schedule.py` 解析对应角色的完整日型。
3. fixed 候选优先进入时间段，pool 候选继续使用共享确定性排程评分。
4. 对已有完整日型的角色，不再叠加旧的“周末降低 studying 权重”或 `rest_day_extras`，避免两套休息日逻辑同时生效。
5. 没有显式日型配置的旧角色仍走原有兼容逻辑。
6. 最后补 sleeping slot；跨午夜睡眠会正确落在下一自然日，不会错误覆盖整天计划。

同一角色同一天的候选排序和时间槽保持稳定；日期变化后稳定哈希会产生新的日程抖动。

```python
generator = DailyPlanGenerator(templates)
plan = generator.generate("aveline", "2026-09-11")
```

`config.py` 会把完整日型中的工作日/休息日起床、睡觉时间同步覆盖到对应 `SleepProfile` 兼容字段，使 SleepManager 与 DailyPlan 使用一致的作息基线。

### 3. ActivityInstance（活动实例）

**文件**: `activity_instance.py`

ActivityInstance 解决的是“今天这一个 slot 到底具体怎么发生”。一个实例包含：

- `instance_id`
- `role_id`
- `date`
- `slot_key`
- `activity`
- `planned_start` / `planned_end`
- `purpose`
- `companion_mode`
- `companion_profile_ids`
- `location`
- `transport`
- `detail`
- `resolution_source`
- `resolved_at`

候选池来自 `config/yaml/character_activity_instances.yaml`。解析器使用 `role/date/slot/activity/field` 构造稳定 SHA-256 选择，因此同一天同一活动时段不会因为重新读取或重新启动而随机换地点、换同行方式。

设计原则：

- **只为自主角色生成**：资格统一走 `is_autonomous_role()`。
- **先确定、后消费**：生成出来的事实写入持久化层，聊天和主动行为读取同一份事实。
- **first-write wins**：相同 role/date/slot 已有实例时不覆盖，避免一次重跑改写当天已经说过的生活事实。
- **不捏造命名关系**：配置只使用 `alone`、`friend`、`classmate`、`classmates`、`labmates`、`online_friends` 等通用同行模式；具体命名关系必须来自可信角色资料。
- **原子写入**：临时文件完成后替换正式 JSON。
- **历史裁剪**：实例存储默认保留最近 14 天。

### 4. Nightly 次日预生成

**文件**: `nightly.py`

`prepare_activity_instances_for_date()` 负责在夜间任务中先生成下一天的 DailyPlan，再把各 slot 的 ActivityInstance 解析并落盘。

`memory/nightly/global_tasks.py` 会为次日调用这一流程。单个角色失败不会中止全局 Nightly。

这样普通聊天或主动消息都不需要在使用事实时临时抽签决定地点/同行等细节；消费方只读取已经存在的实例。

### 5. CharacterDailyEngine（主引擎）

**文件**: `engine.py`

主引擎独立 async 循环，周期性：

1. 为模板中的角色补齐今日计划。
2. 更新每个角色当前粗粒度 ActivityType。
3. 检查 Character Daily 管辖的 peer chat 门控。

`DailyPlanGenerator.role_ids` 与 `CharacterDailyEngine.managed_role_ids` 仍来自已加载的日程模板键；“模板是否存在”和“是否拥有通用自主角色能力”是两个不同概念。ActivityInstance、SleepManager 主动生命周期等需要自主能力的路径必须额外通过 Character Runtime 判断。

对外接口：

- `get_current_activity(role_id)`
- `get_activity_context_text(role_id)`
- `get_peer_chat_summary()`

空档期活动解析：

- 命中当前 slot 时使用该 slot 活动。
- 睡觉结束后的短空档只短暂保留 `waking_up`。
- 其他无 slot 的空档回落到 `idle`，避免长时间卡在上一活动。
- `current_activity` 切换时会落盘。

### 6. 主对话 Prompt 接入

**文件**: `core/agents/chat_agent_components/persona_system/prompt/components/character_daily_context.py`

主对话会：

1. 按 persona 的稳定 scope 找到当前角色。
2. 读取已经运行的 DailyPlan 和当前 slot。
3. 从 `ActivityInstanceStore` 读取该 slot 已落盘的具体事实。
4. 将“当前大类活动 + 已确定实例事实”作为角色自己的状态注入动态 Prompt。

关键约束：

```python
ActivityInstanceStore().get_for_slot(
    plan,
    slot,
    resolve_if_missing=False,
)
```

即普通聊天路径**只读**。如果 Nightly/日常流程还没有生成实例，聊天退化为只知道基础 DailyPlan，不允许因为用户问了一句就现场生成并写回生活事实。

Prompt 也明确要求模型不要为了证明自己读到了日程而每条报备，更不能补造不存在的细节。

### 7. DailyStateStore / ActivityInstanceStore（持久化）

DailyPlan 状态：

```text
companion_data/character_daily/daily_state.json
```

ActivityInstance 事实：

```text
companion_data/character_daily/activity_instances.json
```

两者职责不同：DailyStateStore 保存计划和当前活动推进；ActivityInstanceStore 保存某个具体时段已经确定的稳定生活事实。

## 与 Active Care 的联动

这里必须区分**旧有的粗粒度活动联动**与**新的 ActivityInstance 细节联动**。

### 1. 粗粒度 CharacterDaily 活动（原本就有）

Active Care 原本就会读取角色当前 ActivityType，并把 `activity` / `activity_text` / `is_idle` 放进主动关怀上下文。这个能力不是 ActivityInstance 改造新增的。

现在该消费者不再硬编码 `aveline/ling`：`CheckerStateDetector._get_character_daily_context(persona_filename)` 从 Character Runtime 获取自主角色，并在有当前 persona 时只保留对应 scope，因此 `ye` 也能使用同一条通用路径。

### 2. ActivityInstance 已接入 Active Care 内容上下文

`core/services/active_care/prompt/prompt_context_builders.py::build_role_activity_context_text()` 复用主聊天的 `build_character_daily_context()`，所以 Active Care 与普通聊天读取的是**同一份当前活动事实投影**：

```text
当前 persona
  → scope
  → Character Runtime 资格
  → 当前 DailyPlan / 当前 slot
  → ActivityInstanceStore.get_for_slot(..., resolve_if_missing=False)
```

这意味着 `purpose`、`companion_mode`、`location`、`transport`、`detail` 已可用于主动消息，而不是只知道抽象的 `shopping/studying`。

接入分两层：

- **决策层**：`CheckerStateDetector` 把 `activity_facts` 放入 `character_daily`；`ContentPlanner._build_dynamic_constraints()` 可据此判断当前生活里有没有一个有依据、值得分享的新内容，没有就 defer。
- **生成层**：`core/services/active_care/core/context_builder.py` 把同一份事实投影作为 `role_activity_text` 交给 Active Care Prompt；`activity_return_proactive` 也允许保留该活动锚点。

关键边界：

- **只读**：Active Care 不调用 resolver 生成新实例，不改写 `activity_instances.json`。
- **按 persona 隔离**：当前角色只读取自己的 scope，不回退成别的角色的生活状态。
- **缺失即降级**：当前 slot 没有实例时，只使用粗粒度 DailyPlan/activity，不现场补造地点、同行者等。
- **事实不是强制报备理由**：ActivityInstance 只是候选生活素材；没有新的、值得分享的内容仍应 defer。
- **禁止固定三段式**：不使用“我在做 X → 突然想到你 → 你在干嘛”的机械开场，也不逐项念目的、地点、同行、交通。
- **不把计划写成完成事实**：正在学习不等于已经写完，出门购物不等于已经买到了某物或付了多少钱。

因此现在可以自然出现“角色根据自己正在发生的具体生活发一条消息”，同时保证当天已经说过的地点/同行/目的不会在不同聊天路径里漂移。

## SleepManager / Activity Return 联动

SleepManager 的角色资格判断已改为通用 `is_autonomous_role()`，不再维护 Active Care 私有角色白名单。

作息状态机遵循“**真实已经醒来 > 计划起床时间**”：如果当前睡眠窗口中已经记录了实际 wake，不能因为休息日计划起床时间更晚又把 `WAKING_UP/FULLY_AWAKE` 推回 `SLEEPING`。

Activity Return 同样复用通用自主角色能力判断；Active Care executor 仍只是实际消息投递后端之一，不是角色自主能力的所有者。

## Peer Chat Gate

Peer chat 仍支持：

- 双方空闲时的正常聊天。
- 一方空闲、一方忙碌时的异步聊天。
- 用户活跃、全局最小间隔、每日软/硬上限、时间范围、活动类型和概率等门控。

Peer chat 的配对和角色范围由其自身配置决定，不能从 `character_runtime.yaml` 推导“所有自主角色都应该互聊”。

## 配置示例

### character_runtime.yaml

```yaml
autonomous_roles:
  - aveline
  - ling
  - ye
```

### character_day_types.yaml

```yaml
ling:
  workday:
    wake_time: "07:00"
    sleep_time: "23:30"
    time_blocks: [...]
  rest_day:
    wake_time: "09:00"
    sleep_time: "00:30"
    time_blocks: [...]
```

### character_activity_instances.yaml

```yaml
ling:
  shopping:
    purpose:
      - value: "补日用品"
        weight: 3
    companion_mode:
      - value: "classmates"
        weight: 2
    location:
      - value: "附近商场"
        weight: 2
    transport:
      - value: "walk"
        weight: 1
```

这里的示例只展示结构；正式角色事实应以仓库实际配置为准。

## 当前数据流

```text
character_runtime.yaml
        │
        └── is_autonomous_role()
             ├── ActivityInstance
             ├── SleepManager
             ├── Activity Return
             └── Active Care persona scope 资格

character_day_types.yaml + character_daily.yaml
        │
        ▼
DailyPlanGenerator
        │
        ├── CharacterDailyEngine ──> current activity
        │                              └──> Active Care 粗粒度活动上下文
        │
        └── Nightly
             │
             ▼
      ActivityInstanceResolver
             │
             ▼
activity_instances.json
             │
             ├──> 主对话动态 Prompt（只读）
             │
             └──> build_role_activity_context_text()
                        │
                        ├──> Active Care 决策动态约束
                        └──> Active Care 内容生成 Prompt
```

## 验证说明

ActivityInstance/Character Runtime 原始代码改造在 PR #8 合并前经过 Core CI；期间发现并修复了休息日起床时间覆盖实际 wake 状态的回归，最终 Secret Guard、Ruff、pytest 全绿后合并。

后续 `f934d156` 将 ActivityInstance 只读事实投影接入 Active Care 决策/内容生成路径，并加入对应的角色活动上下文验证脚本。本文档只描述当前代码边界，不把运行时活动事实写成人设长期事实。