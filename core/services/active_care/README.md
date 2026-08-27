# Active Care Service (主动关怀服务)

## 概述

主动关怀服务是Xiaoyou-Core系统的智能交互核心，负责在用户无主动操作时，根据时间、用户状态、情绪等因素主动发起关怀交互。该服务采用模块化设计，支持多模式决策、硬件联动、词汇学习等功能。

## 目录结构

```
active_care/
├── core/                          # 核心编排与服务入口（15个文件）
│   ├── service.py                 # 服务主类
│   ├── proactive_checker.py       # 主动关怀检查器（初始化/门控/节流已拆分到 checker/，保留转发方法）
│   ├── proactive_loop.py          # 主动关怀循环
│   ├── watchdog.py                # 看门狗
│   ├── startup_handler.py         # 启动处理
│   ├── executor.py                # 执行器（QQ连接/LLM生成/硬件意图已拆分，保留转发方法）
│   ├── context.py                 # 上下文管理（会话解析/作息配置已拆分，保留转发方法）
│   ├── conversation_resolver.py   # 会话 ID 解析与候选排序（缓存，persona token 匹配）
│   ├── response_generator.py      # LLM 响应生成与 fallback
│   ├── qq_connection_resolver.py  # QQ/NapCat/官方机器人/WebSocket 连接解析
│   ├── hardware_intent.py         # 硬件震动/灯效意图策略
│   ├── sleep_policy.py            # 睡眠策略
│   ├── sleep_session_manager.py   # 睡眠会话状态机管理器（SleepSessionManager，10 个方法）
│   ├── user_response_handler.py   # 用户响应处理
│   └── persona_resolver.py        # 人设解析
├── decision/                      # 决策引擎与执行（13个文件）
│   ├── decision.py                # 决策引擎（输出解析/指令构建已拆分，保留转发方法）
│   ├── decision_executor.py       # 决策执行器（动作构建/上下文采集已拆分，保留转发方法；MDP 优先 + bandit 兜底）
│   ├── decision_context.py        # 决策上下文
│   ├── decision_tools.py          # 决策工具
│   ├── decision_output_parser.py  # 决策输出解析（JSON 修复，regex fallback，peer chat 解析）
│   ├── decision_instruction_builder.py # 决策指令构建（日常探测指令，特定动作指令）
│   ├── action_builder.py          # 动作构建器（build_available_actions，apply_action_overrides，should_force_send）
│   ├── context_gatherer.py        # 上下文采集器（workspace 快照，历史记录，用户信号，紧急需求）
│   ├── daily_push_priority.py     # 每日推送优先级（候选构建，LLM 分析，持久化）
│   ├── portrait_keyword_map.py    # 画像关键词映射（统一 decision.py 和 priority_analyzer.py 的重复映射）
│   ├── priority_analyzer.py       # 优先级分析（每日推送/画像关键词已拆分，保留转发方法）
│   ├── mdp.py                     # 题材感知 MDP（状态 S=(tod,last_topic,last_reply)，Q 表，ε-greedy 选择，增量更新）
│   └── topic_classifier.py        # 题材分类（intent 主类 + detect_topic_category 子类型，如 share_thought:food）
├── detection/                     # 检测与识别（4个文件）
│   ├── activity_detector.py       # 活动检测（活动映射已拆分到 activity_maps.py，保留转发方法）
│   ├── activity_maps.py           # 活动映射表（进程名/窗口标题分类）
│   ├── intent_detector.py         # 意图检测（BERT 语义先行 + 关键词兜底）
│   └── gate_scorer.py             # 软评分门控系统（7 层）
├── postprocess/                   # 后处理管线（5个文件）
│   ├── postprocessor.py           # 后处理管线（睡眠净化/去重/泄露检测已拆分，保留转发方法）
│   ├── sleep_sanitizer.py         # 睡眠净化器（SleepSanitizer）
│   ├── deduplicator.py            # 去重器（Deduplicator）
│   ├── leak_detector.py           # 泄露检测器（LeakDetector）
│   └── event_target_guard.py      # 数字健康、词汇完成态等硬事件的目标与事实守卫
├── peer_chat/                     # 同伴对话（5个文件）
│   ├── peer_chat_scheduler.py     # 同伴对话调度
│   ├── peer_script_generator.py   # 剧本生成（分发/钩子已拆分，保留转发方法）
│   ├── peer_script_dispatch.py    # 剧本分发（逐条 WebSocket 广播）
│   ├── peer_script_hooks.py       # 剧本后处理钩子（日记/会话记录/巡逻触发）
│   └── peer_chat_metrics.py       # 同伴对话指标
├── prompt/                        # 提示词构建（3个文件）
│   ├── prompt_builder.py          # Prompt 组装（上下文构建/话题多样性已拆分，保留转发方法）
│   ├── prompt_context_builders.py # Prompt 上下文构建（设备/生物/健康/食物/学习上下文）
│   └── topic_diversity.py         # 话题多样性控制
├── scheduling/                    # 调度与时间管理（5个文件）
│   ├── scheduler_logic.py         # 心跳间隔计算
│   ├── schedule_adapter.py        # 作息学习适配器
│   ├── schedule_config_loader.py  # 作息调度配置加载
│   ├── delayed_scheduler.py       # 延迟调度
│   └── delayed_task_handler.py    # 延迟任务处理
├── storage/                       # 存储与持久化（3个文件）
│   ├── storage.py                 # 存储层（JSON + 延迟写入缓冲）
│   ├── state_persistence.py       # 状态持久化（事件记录、发送历史）
│   └── user_profile_service.py    # 用户画像
├── checker/                       # 检查器子模块（3个文件）
│   ├── checker_init_state.py      # 检查器初始化与状态恢复（CheckerInitState）
│   ├── checker_client_gate.py     # 检查器客户端门控（CheckerClientGate，活跃检测、私密模式）
│   └── checker_throttle.py        # 检查器节流与时间调度（CheckerThrottle，抖动、退避）
├── shared/                        # 共享常量与工具（2个文件）
│   ├── constants.py               # 常量（SkipReasons, 退避算法, 睡眠状态描述）
│   └── vocabulary.py              # 词汇学习
├── state/                         # 统一状态管理模块（5个文件）
│   ├── base.py                    # 状态管理基类
│   ├── sleep_state.py             # 睡眠状态
│   ├── focus_state.py             # 专注/学习状态
│   ├── mode_state.py              # 模式状态
│   └── manager.py                 # 统一状态管理器
├── README.md                      # 本文档
├── REFACTOR_PLAN.md               # 重构计划文档
└── ACTIVE_CARE_MODE_DESIGN_2026-03-08.md # 模式设计文档
```

## 核心组件

### 1. ActiveCareService (服务主类)

**文件**: `core/service.py`

主动关怀服务主类，协调各组件工作：

```python
class ActiveCareService:
    def __init__(self):
        # 初始化组件
        self.storage = ActiveCareStorage()
        self.context = ActiveCareContext(self.storage)
        self.scheduler_logic = ActiveCareSchedulerLogic()
        self.decision = ActiveCareDecision(self.storage)
        self.executor = ActiveCareExecutor(self.context, self.storage)
        self.vocab = ActiveCareVocabulary(self.storage)
        self.mode_state = ActiveCareModeState()

        # 初始化检查器
        self.checker = ProactiveChecker(
            storage=self.storage,
            context=self.context,
            scheduler_logic=self.scheduler_logic,
            decision=self.decision,
            executor=self.executor
        )
```

**主要功能**:
- 服务生命周期管理
- 组件协调
- 健康检查注册
- 事件订阅

### 2. ProactiveChecker (主动关怀检查器)

**文件**: `core/proactive_checker.py`

主动关怀检查器，负责定时检查是否需要发起关怀。已将初始化/状态恢复、客户端门控、节流调度拆分到 `checker/` 子目录，本类通过属性委托和转发方法保持向后兼容：

```python
class ProactiveChecker:
    async def check_proactive_care(self) -> Optional[Dict[str, Any]]:
        """检查是否需要主动关怀"""

    async def should_trigger(self, context: Dict) -> bool:
        """判断是否触发"""
```

**检查维度**:
- 用户静默时间
- 时间段（早晨、中午、傍晚、深夜）
- 用户状态（忙碌、空闲）
- 情绪状态
- 设备上下文

**委托子模块**（`checker/` 目录）:

| 子模块 | 文件 | 职责 |
|--------|------|------|
| CheckerInitState | `checker/checker_init_state.py` | 初始化与状态恢复（决策时间戳管理、per-persona 独立决策时间） |
| CheckerClientGate | `checker/checker_client_gate.py` | 客户端门控（活跃客户端检测、用户进程活动检测、私密/敏感模式检测、客户端类型探测） |
| CheckerThrottle | `checker/checker_throttle.py` | 检查节流与时间调度（间隔抖动计算、非响应退避乘数） |

### 3. ActiveCareDecision (决策引擎)

**文件**: `decision/decision.py`（输出解析已拆分到 `decision/decision_output_parser.py`，指令构建已拆分到 `decision/decision_instruction_builder.py`，保留转发方法）

决策引擎，负责选择关怀动作：

```python
class ActiveCareDecision:
    async def select_action_bandit(
        self, ctx: Dict[str, Any], actions: List[str]
    ) -> str:
        """使用Contextual Bandit选择动作"""

    async def update_policy_reward(self, action: str, reward: float):
        """更新动作奖励值"""
```

**决策算法**:
- **题材感知 MDP（马尔可夫决策过程）**：状态 `S = (tod_slot, last_topic_sub, last_reply)`，Q 表 `active_care_mdp.json`，增量 Q-learning（学习率 0.15 随样本衰减）。题材分类复用 `prompt/topic_diversity.detect_topic_category`（intent 主类 + 题材子类型，如 `share_thought:food`）
- Contextual Bandit（上下文强盗）：保留作 MDP 冷启动/异常兜底
- 增量平均奖励计算
- 探索/利用平衡
- **自发做事排除**：角色日程切换告别消息（`activity_transition` / `activity_return`）传 `self_activity=True`，不记录题材、不进 MDP/bandit 学习闭环

**动作类型**:
| 动作 | 说明 |
|------|------|
| greeting | 问候 |
| reminder | 提醒 |
| weather | 天气提醒 |
| health | 健康关怀 |
| emotion | 情绪关怀 |
| study | 学习提醒 |
| random | 随机闲聊 |

**委托子模块**（`decision/` 目录）:

| 子模块 | 文件 | 职责 |
|--------|------|------|
| 决策输出解析 | `decision/decision_output_parser.py` | `_parse_decision_output`，JSON 修复，regex fallback，peer chat 输出解析 |
| 决策指令构建 | `decision/decision_instruction_builder.py` | `_build_daily_routine_probe_instruction`，`_build_specific_instruction` |

### 4. ActiveCareExecutor (执行器)

**文件**: `core/executor.py`（QQ 连接解析已拆分到 `core/qq_connection_resolver.py`，LLM 生成已拆分到 `core/response_generator.py`，硬件意图已拆分到 `core/hardware_intent.py`，保留转发方法）

执行器，负责执行关怀动作；QQ 连接来源解析已下沉到
`core/qq_connection_resolver.py`，LLM 生成与 fallback 已下沉到
`core/response_generator.py`，硬件震动/灯效策略已下沉到
`core/hardware_intent.py`。执行器只消费标准化后的
`user_id/persona_filename/client_id/role_id/adapter_type` 连接结构和生成后的消息内容：

```python
class ActiveCareExecutor:
    async def execute_care(
        self, action: str, context: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """执行关怀动作"""

    def determine_hardware_intent(
        self, sys_prompt_type: str, device_context: Dict[str, Any]
    ) -> HardwareIntent:
        """决定硬件控制参数"""
```

**执行流程**:
1. 检查提醒
2. 构建提示词
3. 调用LLM生成响应
4. 确定硬件控制参数
5. 发送消息

### 4.1 QQConnectionResolver (QQ 连接解析器)

**文件**: `core/qq_connection_resolver.py`

统一解析 Active Care 可投递的 QQ 连接，按以下顺序兜底：

1. NapCat `QQAdapter` 活跃实例注册表
2. QQ 官方机器人 `QQOfficialAdapter` 活跃实例注册表
3. `clients/bots/multi_qq_config.json` 多 QQ 跨进程配置
4. WebSocket 连接扫描（单 QQ 兼容）

该模块让 `executor.py` 不再直接耦合不同客户端适配器的发现细节。QQ
目标解析必须同时保留两类 ID：`shared__persona__{role}` 用于历史与人格上下文，
`private_{master_qq_id}` 用于 WebSocket 广播和离线队列。双 QQ 实时广播与离线
重放再按 `client_id=qq_{role_id}_{session_id}` 选择目标角色，不能由其他角色连接
代收后忽略。

### 4.2 ActiveCareResponseGenerator (响应生成器)

**文件**: `core/response_generator.py`

集中处理 Active Care 主动消息生成：

1. 解析 Active Care 内容模型路径
2. 读取生成温度与 max tokens 配置
3. 调用 LLM 并处理 45 秒主模型超时
4. 对 fallback 模型执行重试
5. 剥离 `<arg_key>` / reasoning 输出并拦截提示词泄漏

该模块让 `executor.py` 不再直接管理模型调用、reasoning 泄漏与 fallback 细节。

### 4.3 ActiveCareHardwareIntentResolver (硬件意图策略)

**文件**: `core/hardware_intent.py`

集中维护主动关怀类型到震动、灯效、优先级的映射。执行器保留
`determine_hardware_intent()` 兼容入口，但实际策略由该模块负责。

### 5. ActiveCareContext (上下文管理)

**文件**: `core/context.py`（会话解析已拆分到 `core/conversation_resolver.py`，作息配置已拆分到 `scheduling/schedule_config_loader.py`，保留转发方法）

上下文管理，负责聚合决策所需的上下文信息：

```python
class ActiveCareContext:
    async def build_context(self) -> Dict[str, Any]:
        """构建决策上下文"""
```

**上下文信息**:
| 字段 | 说明 |
|------|------|
| elapsed_seconds | 用户静默时间 |
| time_period | 时间段 |
| emotion | 当前情绪 |
| life_status | 生命状态 |
| device_context | 设备上下文 |
| recent_activities | 最近活动 |
| user_preferences | 用户偏好 |

### 6. ActiveCareSchedulerLogic (调度逻辑)

**文件**: `scheduling/scheduler_logic.py`

调度逻辑，负责计算下次关怀时间：

```python
class ActiveCareSchedulerLogic:
    def calculate_next_decision(
        self, context: Dict[str, Any]
    ) -> int:
        """计算下次决策间隔（秒）"""
```

**调度策略**:
- 基础间隔：根据时间段调整
- 静默因子：用户静默时间越长，间隔越短
- 情绪因子：情绪低落时增加关怀频率
- 随机抖动：避免固定模式

### 7. ActiveCareVocabulary (词汇学习)

**文件**: `shared/vocabulary.py`

词汇学习，负责学习用户常用词汇：

```python
class ActiveCareVocabulary:
    async def learn_from_message(self, message: str):
        """从消息中学习词汇"""

    async def get_vocabulary_stats(self) -> Dict[str, Any]:
        """获取词汇统计"""
```

**学习内容**:
- 用户常用词汇
- 表达习惯
- 情感词汇

### 8. ActiveCareModeState (模式状态)

**文件**: `state/mode_state.py`

模式状态管理，支持多种关怀模式：

```python
class ActiveCareModeState:
    def get_current_mode(self) -> str:
        """获取当前模式"""

    def set_mode(self, mode: str):
        """设置模式"""
```

**支持模式**:
| 模式 | 说明 |
|------|------|
| normal | 正常模式 |
| focus | 专注模式（减少打扰） |
| sleep | 睡眠模式（静音） |
| busy | 忙碌模式（仅紧急提醒） |

### 9. 子目录拆分说明

原 55 个平铺文件已整理为 10 个子目录 + `state/`（已存在），每个源文件保留转发方法保持向后兼容。

#### 9.1 core/ — 核心编排与服务入口（15个文件）

| 文件 | 职责 |
|------|------|
| `service.py` | 服务主类 |
| `proactive_checker.py` | 主动关怀检查器（初始化/门控/节流已拆分到 `checker/`，保留转发方法） |
| `proactive_loop.py` | 主动关怀循环 |
| `watchdog.py` | 看门狗 |
| `startup_handler.py` | 启动处理 |
| `executor.py` | 执行器（QQ连接/LLM生成/硬件意图已拆分，保留转发方法） |
| `context.py` | 上下文管理（会话解析/作息配置已拆分，保留转发方法） |
| `conversation_resolver.py` | 会话 ID 解析与候选排序 |
| `response_generator.py` | LLM 响应生成与 fallback |
| `qq_connection_resolver.py` | QQ/NapCat/官方机器人/WebSocket 连接解析 |
| `hardware_intent.py` | 硬件震动/灯效意图策略 |
| `sleep_policy.py` | 睡眠策略 |
| `sleep_session_manager.py` | 睡眠会话状态机管理器 |
| `user_response_handler.py` | 用户响应处理 |
| `persona_resolver.py` | 人设解析 |

#### 9.2 decision/ — 决策引擎与执行（11个文件）

| 文件 | 职责 |
|------|------|
| `decision.py` | 决策引擎（输出解析/指令构建已拆分，保留转发方法） |
| `decision_executor.py` | 决策执行器（动作构建/上下文采集已拆分，保留转发方法） |
| `decision_context.py` | 决策上下文 |
| `decision_tools.py` | 决策工具 |
| `decision_output_parser.py` | 决策输出解析（JSON 修复，regex fallback，peer chat 解析） |
| `decision_instruction_builder.py` | 决策指令构建 |
| `action_builder.py` | 动作构建器 |
| `context_gatherer.py` | 上下文采集器 |
| `daily_push_priority.py` | 每日推送优先级 |
| `portrait_keyword_map.py` | 画像关键词映射（统一了 decision.py 和 priority_analyzer.py 的重复映射） |
| `priority_analyzer.py` | 优先级分析（每日推送/画像关键词已拆分，保留转发方法） |

#### 9.3 detection/ — 检测与识别（4个文件）

| 文件 | 职责 |
|------|------|
| `activity_detector.py` | 活动检测（活动映射已拆分到 `activity_maps.py`，保留转发方法） |
| `activity_maps.py` | 活动映射表（进程名/窗口标题分类） |
| `intent_detector.py` | 意图检测（BERT 语义先行 + 关键词兜底） |
| `gate_scorer.py` | 软评分门控系统（7 层） |

#### 9.4 postprocess/ — 后处理管线（4个文件）

| 文件 | 职责 |
|------|------|
| `postprocessor.py` | 后处理管线（睡眠净化/去重/泄露检测已拆分，保留转发方法） |
| `sleep_sanitizer.py` | 睡眠净化器（SleepSanitizer） |
| `deduplicator.py` | 去重器（Deduplicator） |
| `leak_detector.py` | 泄露检测器（LeakDetector） |

#### 9.5 peer_chat/ — 同伴对话（5个文件）

| 文件 | 职责 |
|------|------|
| `peer_chat_scheduler.py` | 同伴对话调度 |
| `peer_script_generator.py` | 剧本生成（分发/钩子已拆分，保留转发方法） |
| `peer_script_dispatch.py` | 剧本分发（逐条 WebSocket 广播） |
| `peer_script_hooks.py` | 剧本后处理钩子（日记/会话记录/巡逻触发） |
| `peer_chat_metrics.py` | 同伴对话指标 |

#### 9.6 prompt/ — 提示词构建（3个文件）

| 文件 | 职责 |
|------|------|
| `prompt_builder.py` | Prompt 组装（上下文构建/话题多样性已拆分，保留转发方法） |
| `prompt_context_builders.py` | Prompt 上下文构建（设备/生物/健康/食物/学习上下文） |
| `topic_diversity.py` | 话题多样性控制 |

#### 9.7 scheduling/ — 调度与时间管理（5个文件）

| 文件 | 职责 |
|------|------|
| `scheduler_logic.py` | 心跳间隔计算 |
| `schedule_adapter.py` | 作息学习适配器 |
| `schedule_config_loader.py` | 作息调度配置加载 |
| `delayed_scheduler.py` | 延迟调度 |
| `delayed_task_handler.py` | 延迟任务处理 |

#### 9.8 storage/ — 存储与持久化（3个文件）

| 文件 | 职责 |
|------|------|
| `storage.py` | 存储层（JSON + 延迟写入缓冲）；用户级 `user_sleep_state.json` 同时保存共享低打扰状态与带来源的 Samsung Health 睡眠区间，读取 persona 状态时统一覆盖旧副本 |
| `state_persistence.py` | 状态持久化（事件记录、发送历史） |
| `user_profile_service.py` | 用户画像 |

#### 9.9 checker/ — 检查器子模块（3个文件）

| 文件 | 职责 |
|------|------|
| `checker_init_state.py` | 检查器初始化与状态恢复（CheckerInitState） |
| `checker_client_gate.py` | 检查器客户端门控（CheckerClientGate，活跃检测、私密模式） |
| `checker_throttle.py` | 检查器节流与时间调度（CheckerThrottle，抖动、退避） |

#### 9.10 shared/ — 共享常量与工具（2个文件）

| 文件 | 职责 |
|------|------|
| `constants.py` | 常量（SkipReasons, 退避算法, 睡眠状态描述） |
| `vocabulary.py` | 词汇学习 |

#### 9.11 state/ — 统一状态管理模块（5个文件，已存在）

| 文件 | 职责 |
|------|------|
| `base.py` | 状态管理基类 |
| `sleep_state.py` | 用户级低打扰与睡眠状态；聊天只进入/退出低打扰，正式睡眠区间由 Samsung Health 写入并标注 main_sleep/nap |
| `focus_state.py` | 专注/学习状态 |
| `mode_state.py` | 模式状态 |
| `manager.py` | 统一状态管理器 |

## 架构设计

### 睡眠事实与室友共享事件边界

- “晚安”“我起来了”等聊天信号只切换用户级低打扰，不写 Daily Record，也不改写正式睡眠开始/结束时间。
- 即时消息入口必须按 `reason/label` 分流：学习类 `focus/focus` 进入专注低打扰，只有 `goodnight/sleep` 可以进入晚安低打扰并供 nightly 判断。`WAKEUP_NOW` 不能仅凭零样本 BERT 相似度退出晚安，必须命中明确的当前起床陈述。
- Samsung Health 上报的时间戳是睡眠事实真源；主睡眠更新当天正式起床，短时白天睡眠记为 `nap`，不得覆盖主睡眠。
- 睡醒、吃饭等生活近况进入 `SocialEventEngine` 共享事件池，保存 `source`、`learned_by` 与 `certainty`。Peer Chat 可以自然选用，也可以不聊；跨角色引用时必须体现“Aveline 转告”或“Ling转告”等来源。

### 词汇任务事实边界

- Active Care 的词汇数量必须来自词汇管理器的当日实时状态，昨日日记、旧聊天和 Peer Chat 只能提供话题背景，不能覆盖当日数量与完成态。
- `StudyService` 在词汇会话结束时写入的“完成词汇复习”记录是显式完成证据。会话结束后 FSRS 动态队列再次出现少量到期词时，仍不得把已完成任务改判为未完成或继续催促。
- `share_peer_chat` 与普通主动关怀使用同一学习上下文；所有发送路径在分发前还会经过 `event_target_guard.py`，清除旧数量并拦截完成后的追问或催促。

### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Active Care Service                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 ProactiveChecker                     │   │
│  │  定时检查 → 构建上下文 → 判断是否触发                 │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            │                                │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 ActiveCareDecision                   │   │
│  │  Contextual Bandit → 选择动作 → 更新奖励             │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            │                                │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 ActiveCareExecutor                   │   │
│  │  构建提示词 → LLM生成 → 硬件控制 → 发送消息          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 上下文聚合

```
┌─────────────────────────────────────────────────────────────┐
│                    ActiveCareContext                         │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Time Info  │  │ User State  │  │ Emotion     │         │
│  │  - 时间段   │  │ - 静默时间  │  │ - 当前情绪  │         │
│  │  - 节假日   │  │ - 活动状态  │  │ - 情绪历史  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ Life Status │  │ Device Ctx  │  │ Preferences │         │
│  │  - 能量     │  │ - 设备类型  │  │ - 关怀频率  │         │
│  │  - 饥饿     │  │ - 前台/后台 │  │ - 关怀类型  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

## 使用示例

### 启动服务

```python
from core.services.active_care.core.service import get_active_care_service

# 获取服务实例
service = get_active_care_service()

# 启动服务
await service.start()

# 停止服务
await service.stop()
```

### 手动触发关怀

```python
# 手动触发关怀检查
result = await service.checker.check_proactive_care()
if result:
    action = result.get("action")
    context = result.get("context")
    success, message = await service.executor.execute_care(action, context)
```

### 更新奖励

```python
# 用户积极响应后更新奖励
await service.decision.update_policy_reward(
    action="greeting",
    reward=1.0  # 0.0-1.0
)
```

### 设置模式

```python
# 设置专注模式
service.mode_state.set_mode("focus")

# 设置睡眠模式
service.mode_state.set_mode("sleep")
```

## 配置

### 服务配置

```python
# config/integrated_config.py
class ActiveCareSettings:
    # 基础间隔（秒）
    base_interval: int = 1800  # 30分钟

    # 静默阈值（秒）
    silence_threshold: int = 2700  # 45分钟

    # 最大间隔（秒）
    max_interval: int = 7200  # 2小时

    # 最小间隔（秒）
    min_interval: int = 600  # 10分钟
```

### 时间段配置

```python
# 时间段定义
TIME_PERIODS = {
    "morning": (6, 12),    # 早晨
    "afternoon": (12, 18), # 下午
    "evening": (18, 22),   # 傍晚
    "night": (22, 6),      # 深夜
}
```

### 动作配置

```python
# 动作权重
ACTION_WEIGHTS = {
    "greeting": 1.0,
    "reminder": 1.2,
    "weather": 0.8,
    "health": 1.0,
    "emotion": 1.1,
    "study": 0.9,
    "random": 0.7,
}
```

## 硬件联动

### 震动控制

```python
class VibrationType(Enum):
    NONE = "none"
    GENTLE = "gentle"      # 轻柔震动
    PULSE = "pulse"        # 脉冲震动
    WAVE = "wave"          # 波浪震动
    HEARTBEAT = "heartbeat" # 心跳震动
```

### 呼吸灯控制

```python
class LightMode(Enum):
    OFF = "off"
    BREATHING = "breathing"  # 呼吸灯
    PULSE = "pulse"          # 脉冲
    RAINBOW = "rainbow"      # 彩虹
    SOLID = "solid"          # 常亮
```

## 性能特性

### 响应时间

- **决策延迟**: < 100ms
- **上下文聚合**: < 50ms
- **消息生成**: 取决于LLM

### 资源占用

- **内存**: < 10MB
- **CPU**: 低（定时检查）
- **网络**: 仅LLM调用

## 相关文档

- [系统架构文档](../../../PROJECT_TECHNICAL_REFERENCE.md)
- [服务层文档](../README.md)
- [核心层文档](../../README.md)
- [模式设计文档](./ACTIVE_CARE_MODE_DESIGN_2026-03-08.md)
