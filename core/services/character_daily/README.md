# Character Daily (角色日常系统)

## 概述

角色日常系统为 `character_daily.yaml` 及敏感模板文件中全部已配置角色提供独立生活节奏管理。引擎直接遍历已加载模板键，不维护计划角色白名单；新增角色只需增加完整 YAML 模板，重启后即使当天已有状态也会自动补齐该角色计划。Peer chat 是独立的角色配对能力，仍按其 persona/账号映射决定可互聊角色，不限制其他角色生成和推进日程。

该系统与 Active Care 集成：Active Care 决策时会参考角色当前活动，角色忙碌时抑制主动消息发送，角色空闲时增加发送概率。

## 目录结构

```
character_daily/
├── __init__.py              # 模块入口 + 全局单例
├── engine.py                # CharacterDailyEngine 主引擎（独立 async loop）
├── daily_plan.py            # DailyPlanGenerator：YAML 候选适配 + 共享确定性排程
├── llm_plan_generator.py    # 历史兼容模块；CharacterDailyEngine 不再导入或实例化
├── activity_model.py        # ActivityType 枚举、ActivitySlot、DailyPlan 数据类
├── plan_view.py             # 计划格式化与工具返回文本
├── config.py                # 加载 character_daily.yaml + app.yaml 配置
├── peer_chat_gate.py        # Peer chat 触发门控（多因素概率判定 + 紧急打断）
├── reply_policy.py          # 被动回复策略：DND/BUSY 静默累积 + 回复窗口期 + 递增概率强制唤醒/打断
├── reply_policy_support.py  # ReplyPolicy 辅助函数（手动打断窗口读取、回归决策提示、窗口延长）
├── reply_hints.py           # 回复提示模板与 builder（被吵醒/被打断/起床后/忙完后）
├── interrupt_window.py      # /打断 后的临时聊天窗口管理（激活/延长/跳过/过期）
├── activity_return/         # 统一回归消息模块
│   ├── __init__.py          # 对外导出统一入口
│   ├── instruction.py       # 回归文案与决策提示构建
│   ├── state.py             # pending_return 状态管理
│   ├── scheduler.py         # 异步调度回归消息
│   └── core.py              # 发送消息、处理用户回复
└── state.py                 # 状态持久化（daily_state.json 读写）
```

**配置文件**: `config/yaml/character_daily.yaml` — 角色日程模板

## 核心组件

### 1. ActivityType（活动类型）

**文件**: `activity_model.py`

定义 20 种活动类型，分为日常活动和社交活动：

| 类型 | 说明 | 是否忙碌 |
|------|------|----------|
| SLEEPING | 睡觉 | 忙碌 |
| WAKING_UP | 起床/洗漱 | - |
| BREAKFAST | 吃早饭 | - |
| LUNCH | 吃午饭 | - |
| DINNER | 吃晚饭 | - |
| COOKING | 做饭 | 忙碌 |
| STUDYING | 学习/做题 | 忙碌 |
| READING | 看书/看番 | **空闲** |
| HOUSEWORK | 做家务 | **空闲** |
| NAPPING | 午休 | 忙碌 |
| WALKING | 散步 | **空闲** |
| PHONE_SCROLLING | 刷手机 | **空闲** |
| GARDENING | 浇花 | **空闲** |
| EXERCISING | 运动/拉伸 | 忙碌 |
| GAMING | 玩游戏 | **空闲** |
| SELF_CARE | 洗澡/护肤/整理 | - |
| CREATIVE_HOBBY | 手工/写字/画画 | **空闲** |
| SHOPPING | 出门购物/买小东西 | **空闲** |
| IDLE | 发呆/休息 | **空闲** |
| PEER_CHAT | 和对方聊天 | - |

`CHAT_ELIGIBLE_ACTIVITIES` 定义了哪些活动期间适合发起 peer chat：IDLE、PHONE_SCROLLING、READING、HOUSEWORK、GARDENING、WALKING、GAMING、CREATIVE_HOBBY、SHOPPING。

### 2. DailyPlanGenerator（每日计划生成）

**文件**: `daily_plan.py`

每天凌晨为每个角色生成一份当天的活动计划。

**生成算法**:
1. 从 `character_daily.yaml` 加载角色日程模板，fixed 转为固定候选，pool 每种活动展开多个候选实例。
2. 使用 `core/services/planning/engine.py` 统一评分：`模板权重 + 优先级 - 昨日同活动次数×重复惩罚 - 时长惩罚 + stable_hash(date, role, candidate)`。
3. fixed 候选优先进入时段；pool 候选按分数贪心放入各自时间窗，并检查冲突与时段容量。
4. 周末/休息日降低 studying 权重；角色专属额外候选从 YAML `rest_day_extras.<period>` 读取，算法文件不包含角色特例表。
5. 最后插入跨天 sleeping slot；现有 `ActivitySlot`、聊天资格、执行状态与持久化格式不变。

同一角色同一天的候选排序、时长和时间槽稳定；日期变化会改变稳定哈希抖动。`generate(role_id, date_str, previous_plan=None)` 的第三个参数可选，旧调用仍兼容。`DailyPlanGenerator.role_ids` 与 `CharacterDailyEngine.managed_role_ids` 都直接返回模板键。`CharacterDailyEngine` 无条件使用该生成器，即使旧配置误设 `llm_plan.enabled=true` 也不会调用角色日程 LLM。

```python
generator = DailyPlanGenerator(templates)
plan = generator.generate("aveline", "2026-06-25")
# → DailyPlan(role_id="aveline", date="2026-06-25", slots=[...])
```

### 3. CharacterDailyEngine（主引擎）

**文件**: `engine.py`

独立的 async 主循环，每 2 分钟（±20% jitter）检查一次：

```python
async def _tick(self):
    # 1. 按全部模板键补齐今日计划；当天新增角色也能补齐
    await self._ensure_daily_plans(today_str)

    # 2. 更新每个角色的当前活动
    for role_id in self.managed_role_ids:
        self._update_current_activity(plan, now)

    # 3. 检查是否触发 peer chat
    await self._maybe_trigger_peer_chat(now)
```

`KNOWN_ROLES` 仅为旧验证脚本和外部导入保留，不再参与计划生成、状态同步或活动切换遍历。

**生命周期**:
- `start()` — 启动主循环（幂等）
- `stop()` — 停止主循环，保存最终状态
- `set_peer_chat_scheduler(scheduler)` — 注入 PeerChatScheduler 实例

**对外接口**:
- `get_current_activity(role_id)` — 获取角色当前活动
- `get_activity_context_text(role_id)` — 获取自然语言描述（如 "Ling现在在发呆"）
- `get_peer_chat_summary()` — 获取今日 peer chat 摘要

**空档期活动解析**:
- 命中当前 `slot` 时直接使用该活动
- 睡觉结束后的短空档仅保留几分钟 `waking_up`
- 其他无 `slot` 的时间空档统一回落到 `idle`，避免角色长时间卡在上一项 `dinner/cooking/studying` 等活动上，压制 `peer chat`
- 当 `current_activity` 发生切换时会自动落盘，避免 `daily_state.json` 长时间残留早上的 `waking_up`

**工具层接入**:
- `core/tools/character_daily_plan_tool.py` 提供 `get_character_daily_plan`
- 主程序 LLM 可直接查看自己、同伴或两人的当日角色日常计划

### 4. Peer Chat Gate（触发门控）

**文件**: `peer_chat_gate.py`

支持两种触发模式：
- **正常聊天**：双方都空闲 → 多轮对话
- **异步聊天**：一方空闲 + 另一方忙碌 → 忙碌方可能不回/简短回/边做边聊

6 层门控条件，全部满足才触发 peer chat：

| 层级 | 条件 | 默认值 |
|------|------|--------|
| 1 | 用户活跃检测 | 用户正在聊天时跳过 |
| 2 | 全局最小间隔 | 5400s（1.5小时） |
| 3 | 今日总次数 | 软上限 4（概率降低），硬上限 6（阻止） |
| 4 | 时间范围 | 9:00-22:00 |
| 5 | 至少一方空闲，对方不在 DND 状态 | CHAT_ELIGIBLE + DO_NOT_DISTURB |
| 6 | 概率判定 | 基础 0.04，多因素修正 |

**活动分类**：
- `CHAT_ELIGIBLE_ACTIVITIES`：空闲（idle/phone/reading/housework/gardening/walking）
- `BUSY_ACTIVITIES`：忙碌（studying/cooking/napping/sleeping）
- `DO_NOT_DISTURB_ACTIVITIES`：不可打扰（sleeping/napping/waking_up）

**异步聊天概率修正**：
- 对方忙碌时，触发概率 ×0.4（降低打断频率）
- 发起者必须是空闲方
- 情境上下文会告诉 LLM 对方在忙，生成短轮次剧本

**计数方式**：`max(plan_a.count, plan_l.count)`（只给发起者 +1，不再双计数）

**概率修正因子**:
- 活动类型：idle=2.0x, phone_scrolling=1.5x, reading=0.5x
- 异步模式：×0.4（打断忙碌方）
- 今日已聊次数：超过软上限 → 0.3x，接近软上限 → 0.6x
- 午饭时段（12-13点）：0.3x
- 距上次聊天时间：超过 2 小时 → 1.5x，超过 4 小时 → 2.0x

### 5. DailyStateStore（状态持久化）

**文件**: `state.py`

JSON 文件持久化，支持原子写入和节流：

```
companion_data/character_daily/daily_state.json
```

**特性**:
- 原子替换（写 tmp 文件再 rename）
- 节流保存（最小间隔 10s，`immediate=True` 可跳过）
- 启动时自动恢复上次状态

## 与 Active Care 的集成

Character Daily 通过两条路径与 Active Care 联动：

### 1. 决策上下文注入

`CheckerStateDetector._get_character_daily_context()` 在每次 Active Care 决策时注入角色活动状态：

```json
{
  "aveline": {"activity": "reading", "activity_text": "Ling现在在看书", "is_idle": true},
  "ling": {"activity": "idle", "activity_text": "七濑澪现在在发呆", "is_idle": true},
  "peer_chat_summary": "今天还没聊过。"
}
```

### 2. 动态约束注入

`ActiveCareDecision.decide_proactive_content()` 根据角色活动生成 LLM 动态约束：

```
【角色日常】Ling现在在看书，七濑澪现在在发呆。有角色空闲，适合发消息。今天还没聊过。
```

或：

```
【角色日常】Ling现在在学习，七濑澪现在在做饭。两人都在忙，除非有紧急事项，否则 should_send=false。
```

### 3. PeerChatScheduler 适配

当 CharacterDailyEngine 运行时，PeerChatScheduler 自动让出调度权：

```python
# peer_chat_scheduler.py
async def _run_loop(self):
    while self._running:
        # 每次迭代都检查 CharacterDailyEngine 是否已接管
        if self._is_character_daily_active():
            self._running = False
            break
        # ... 正常逻辑
```

当 CharacterDailyEngine 未启用时，PeerChatScheduler 独立运行（降级模式），
使用全局计数（`peer_chat_global_count_{date}`），所有角色合计不超过 `daily_limit`。

## 配置

### app.yaml

```yaml
character_daily:
  enabled: true                        # 是否启用
  check_interval_seconds: 120          # 主循环检查间隔（秒）
  check_interval_jitter: 0.2           # 随机抖动比例（±20%）
  peer_chat:
    min_gap_seconds: 5400              # 全局最小间隔 1.5 小时
    daily_soft_limit: 4                # 软上限（概率降低）
    daily_hard_limit: 6                # 硬上限（绝对阻止）
    base_probability: 0.04             # 基础触发概率
    eligible_hours: [9, 22]            # 允许聊天的小时范围
```

### character_daily.yaml

角色日程模板，定义每个角色的作息和活动偏好：

```yaml
aveline:
  wake_time: "07:00"
  sleep_time: "23:00"
  time_blocks:
    - period: "morning_routine"
      start: "07:00"
      end: "08:30"
      fixed:
        - { activity: "waking_up", duration: [15, 30] }
      pool:
        - { activity: "cooking",   duration: [20, 35], weight: 3 }
        - { activity: "breakfast", duration: [15, 25], weight: 5 }
```

## 预期效果

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 角色生活 | 无，只有生理状态 | 完整的每日活动计划 |
| Peer chat 频率 | 固定 30min 定时器 | 全局 90min + 概率自然波动 |
| 间隔控制 | per-role 30min（减半） | 全局 90min + 活动门控 + 用户活跃检测 |
| 规律性 | 完全规律 | 活动间隙 + 概率 + jitter |
| 活动感知 | 无 | 知道角色在干嘛，只在空闲时聊 |
| Active Care 联动 | 无 | 角色忙碌时抑制主动消息 |
