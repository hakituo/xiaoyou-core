# Active Care Service (主动关怀服务)

## 概述

主动关怀服务是Xiaoyou-Core系统的智能交互核心，负责在用户无主动操作时，根据时间、用户状态、情绪等因素主动发起关怀交互。该服务采用模块化设计，支持多模式决策、硬件联动、词汇学习等功能。

## 目录结构

```
active_care/
├── core/                          # 核心编排与服务入口（18个文件）
│   ├── service.py                 # 服务主类
│   ├── proactive_checker.py       # 主动关怀检查器（初始化/门控/节流已拆分到 checker/，保留转发方法）
│   ├── proactive_loop.py          # 主动关怀循环
│   ├── watchdog.py                # 看门狗
│   ├── startup_handler.py         # 启动处理
│   ├── executor.py                # 执行器门面（触发链路已拆分为准备/生成/收尾，保留转发方法）
│   ├── trigger_preparer.py        # 触发前置准备（会话路由→早安注入→上下文→Prompt）
│   ├── generation_pipeline.py     # 生成 + 后处理管线
│   ├── post_send_handler.py       # 发送后收尾（清pending/通知服务/日记/清推迟提醒）
│   ├── context.py                 # 上下文管理（会话解析/作息配置已拆分，保留转发方法）
│   ├── conversation_resolver.py   # 会话 ID 解析与候选排序（缓存，persona token 匹配）
│   ├── response_generator.py      # LLM 响应生成与 fallback
│   ├── qq_connection_resolver.py  # QQ/NapCat/官方机器人/WebSocket 连接解析
│   ├── hardware_intent.py         # 硬件震动/灯效意图策略
│   ├── sleep_policy.py            # 睡眠策略
│   ├── sleep_session_manager.py   # 睡眠会话状态机管理器（SleepSessionManager，10 个方法）
│   ├── user_response_handler.py   # 用户响应处理
│   └── persona_resolver.py        # 人设解析
├── decision/                      # 决策引擎与执行（14个文件）
│   ├── decision.py                # 决策引擎（输出解析/指令构建已拆分，保留转发方法）
│   ├── decision_executor.py       # 决策执行器（动作构建/上下文采集已拆分，保留转发方法；MDP 优先 + bandit 兜底）
│   ├── decision_context.py        # 决策上下文
│   ├── decision_tools.py          # 决策工具（含 send_active_care / defer_active_care 终止型出口）
│   ├── action_protocol.py         # send/defer 双出口归一化（ActiveCareDecisionAction，工具调用与 JSON 共用）
│   ├── decision_output_parser.py  # 决策输出解析（action/text/defer_reason 协议，JSON 修复，regex fallback，peer chat 解析）
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
├── postprocess/                   # 后处理管线（6个文件）
│   ├── postprocessor.py           # 后处理管线（睡眠净化/去重/泄露检测已拆分，保留转发方法）
│   ├── pipeline.py                # 管线步骤（新增 PokeStyleGuardStep 发送硬 Gate）
│   ├── sleep_sanitizer.py         # 睡眠净化器（SleepSanitizer）
│   ├── deduplicator.py            # 去重器（Deduplicator）
│   ├── leak_detector.py           # 泄露检测器（LeakDetector）
│   ├── send_validator.py          # 发送硬 Gate（内部标记/决策过程泄漏/超长/铺垫结构拦截 + 压缩 DROP）
│   └── event_target_guard.py      # 数字健康、词汇完成态等硬事件的目标与事实守卫
├── cadence/                       # 频控守卫（2026-09-04，3个文件）
│   ├── cadence_guard.py           # 多层频控：全局/提问/同题材冷却 + 未回复抑制 + 每日好奇提问软上限
│   └── topic_groups.py            # 题材分组（food→meal，防"吃饭没→外卖点了→饭到了"换措辞绕过冷却）
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
├── shared/                        # 共享常量与工具（11个文件）
│   ├── state_keys.py              # 状态键 StateKeys 与低打扰清理字典构建
│   ├── keywords.py                # 晚安/早安/睡眠暗示/专注/题材等关键词与匹配模式
│   ├── mode_reasons.py            # 低打扰原因取值域、SkipReasons、SysPromptType
│   ├── tuning.py                  # 通用数值阈值（间隔/生成/提醒/退避/抖动）
│   ├── sleep_thresholds.py        # 睡眠与晚安相关窗口阈值
│   ├── scheduling_utils.py        # 调度纯函数（非响应退避）
│   ├── text_utils.py              # 文本归一化、时长解析/格式化、人设 token
│   ├── prompt_helpers.py          # Prompt 片段构建器（睡眠状态描述、静默指令）
│   ├── daily_record_sync.py       # 睡眠区间回写 Daily Record
│   ├── constants.py               # 兼容门面（仅 re-export，2026-09-03 起不再新增内容）
│   └── vocabulary.py              # 词汇学习
├── state/                         # 统一状态管理模块（5个文件）
│   ├── base.py                    # 状态管理基类
│   ├── sleep_state.py             # 睡眠状态
│   ├── focus_state.py             # 专注/学习状态
│   ├── mode_state.py              # 模式状态
│   └── manager.py                 # 统一状态管理器
├── README.md                      # 本文档
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
| CheckerClientGate | `checker/checker_client_gate.py` | 客户端门控（活跃客户端、用户进程活动、主人设运行时交互模式、敏感模式、客户端类型探测） |
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

**文件**: `core/executor.py`（QQ 连接解析已拆分到 `core/qq_connection_resolver.py`，LLM 生成已拆分到 `core/response_generator.py`，硬件意图已拆分到 `core/hardware_intent.py`，触发链路已拆分为 `trigger_preparer.py` / `generation_pipeline.py` / `post_send_handler.py`，保留转发方法）

执行器，负责执行关怀动作；QQ 连接来源解析已下沉到
`core/qq_connection_resolver.py`，LLM 生成与 fallback 已下沉到
`core/response_generator.py`，硬件震动/灯效策略已下沉到
`core/hardware_intent.py`。执行器只消费标准化后的
`user_id/persona_filename/client_id/role_id/adapter_type` 连接结构和生成后的消息内容。

`trigger_message_with_result` 只保留调度编排，七段职责分别落在不同模块：

| 阶段 | 落点 |
|------|------|
| 重叠保护 | `core/overlap_guard.py` |
| 会话路由 → 早安注入 → 历史/上下文 → Prompt | `core/trigger_preparer.py` |
| 生成 + 后处理 | `core/generation_pipeline.py` |
| 发送前事实纠偏 | `postprocess/send_content_corrector.py` |
| 分发 + 状态持久化 | `core/message_dispatcher.py` |
| 发送后收尾 | `core/post_send_handler.py` |
| 失败回退 | `core/overlap_guard.py`（`rollback_on_failure`） |

验证脚本：`tests/scripts/active_care/verify_executor_trigger_pipeline_decoupled.py`。

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

### 2026-09-04 四层改造：决策 / 生成 / 频控 / 发送

一句话概括：**把 Active Care 从"定时让 LLM 写一条消息"改成"定时让 LLM 判断有没有必要说一句话"**。
解决三个问题：不该发时硬发、发得太频繁、每条写得太满。

**决策层（要不要发）**：send/defer 双出口。
- 值得联系 → `send_active_care(text)`；不值得 → `defer_active_care(reason, retry_after_minutes)`。
- `reason` 只进日志，永远不进用户消息链路；支持工具调用的模型走 function calling，
  不支持的模型走 JSON `action` 字段，统一归一化到 `decision/action_protocol.py`。
- 决策 prompt 新增约束："大多数检查轮次不发送是正常结果"、"禁止把'先不发了/等他回复'
  等决策过程写成消息"。LLM 空响应兜底改为默认 defer（不再 conversation_incomplete 强制补发）。

**生成层（写多短）**：短 poke 约束。
- 主动消息默认一句话、6~20 汉字，禁止"话说/对了/刚好/刚看到"等无意义转场和
  "我在做X→想到你→再问Y"铺垫三段式，附正反例（prompt 见 `active_care_prompts.py` 的
  `PROACTIVE_SHORT_POKE_RULES`）。允许直接问，不鼓励用假生活铺垫弱化"查岗感"。

**频控层（多久一次）**：`cadence/` 多层频控，决策前预检（省 LLM 调用）+ 决策后带话题复检。
- 全局冷却 40min、提问冷却 75min、同题材冷却 3h（topic_group 把吃饭/外卖归入 meal，
  防换措辞绕过冷却）、未回复抑制（最多悬 1 条普通提问，用户回消息自动解除）、
  每日好奇提问软上限 3 条。
- 硬事件类 intent（真实提醒/通知/数字健康/早安晚安等）全部豁免——"特殊新事件允许突破"。

**发送层（硬 Gate）**：`postprocess/send_validator.py` + 管线 `PokeStyleGuardStep`。
- 拦截内部控制标记（`[GOODNIGHT_GUARD]` 等）/决策过程表述/prompt 泄漏 → 直接 DROP；
  超长或铺垫结构 → 先压缩一次，仍不合规 → DROP。

状态追踪：发送时持久化 `last_proactive_at/type/topic/topic_group/replied`，
用户回复时置 `last_proactive_replied=True`（`user_response_handler`）。
验证入口：`tests/unit/test_active_care_poke_gate.py`。

### Prompt V2 与主人设联动

Active Care 不再单独拼一份旧人设，而是通过
`PersonaPromptLayers` / `get_persona_prompt_layers()` 与主对话共享人物投影：

1. system 保留主人设静态层、主动关怀固定约束、风格约束和 voice guide，形成稳定缓存前缀。
2. dynamic prompt 依次放入人物动态层、场景事实、最近历史和本轮触发任务；语气样例与日期事件也属于每轮动态内容。
3. 叶使用 Persona 2.0 的 overlay/runtime/knowledge/memory 动态层；其他角色继续回退原有人设模板。
4. “是否发送”决策只读取角色名与稳定 scope 的轻量身份投影，完整人设只用于生成消息。
5. 主人设运行时交互模式同时参与主动消息门控，防止角色当前上下文被无关主动话题打断。

任务型少样本由角色自己的 Prompt 配置持有：Aveline/Ling使用各自 `core_*.json`
的 `active_care` 段，Ye使用 Persona 2.0 的 `ye/voice_ye.json`。组装器按稳定
scope 和当前任务类型只选择本轮示例；示例只提供关系动作、语气和节奏，不提供当前
事实，也不会回退到其他角色。`good_morning_proactive` 不再把旧主动消息原文作为
最近历史或去重锚点，避免低质量问候在后续日期形成自我强化。数字健康硬事件
（`usage_limit_exceeded`）不做发送前文案纠偏：模型输出原样发送。原先的
「拼应用名前缀 / 防声称强退」兜底会产出「哔哩哔哩：B站快两小时了」这类系统通知式
文案，与角色口吻冲突，已连同其别名配置 `config/digital_wellbeing_app_aliases.json`
一并删除；禁声称强退的约束改由 prompt 承担。

验证入口：`tests/scripts/active_care/verify_active_care_prompt_v2.py`、
`tests/scripts/active_care/verify_role_specific_wakeup_examples.py`；后者可加 `--live`
执行不发送、不写聊天历史的生产模型生成对比。

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

#### 9.1 core/ — 核心编排与服务入口（18个文件）

| 文件 | 职责 |
|------|------|
| `service.py` | 服务主类 |
| `proactive_checker.py` | 主动关怀检查器（初始化/门控/节流已拆分到 `checker/`，保留转发方法） |
| `proactive_loop.py` | 主动关怀循环 |
| `watchdog.py` | 看门狗 |
| `startup_handler.py` | 启动处理 |
| `executor.py` | 执行器门面（QQ连接/LLM生成/硬件意图/触发三段均已拆分，保留转发方法） |
| `trigger_preparer.py` | 触发前置准备（会话路由 → 早安注入 → 历史/上下文 → Prompt，返回 `PreparedTrigger`） |
| `generation_pipeline.py` | 生成 + 后处理管线（预生成文案复用 / 隔离 LLM 路径 → postprocessor） |
| `post_send_handler.py` | 发送后收尾（清早安 pending、通知服务、写日记、清推迟提醒） |
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

#### 9.10 shared/ — 共享常量与工具（11个文件）

原 `constants.py` 于 2026-09-03 按职责拆分为 9 个原子模块，只保留兼容 re-export 门面：

| 文件 | 职责 |
|------|------|
| `state_keys.py` | `StateKeys` 状态键 + `build_reduced_mode_clear_updates()` / `build_goodnight_clear_updates()` |
| `keywords.py` | 晚安/早安/睡眠暗示/清醒/专注/题材关键词与匹配模式（纯数据） |
| `mode_reasons.py` | 低打扰原因取值域（`SLEEP/FOCUS/QUIET_MODE_REASONS`、`SLEEP_HINT_REASON`）、`SkipReasons`、`SysPromptType` |
| `tuning.py` | 通用数值阈值（检查间隔/生成参数/提醒重试/退避/抖动/情绪乘数） |
| `sleep_thresholds.py` | 睡眠与晚安窗口阈值（自动醒来、晚安信号间隔、作息自适应） |
| `scheduling_utils.py` | 调度纯函数 `calculate_non_response_backoff()`（Equal Jitter） |
| `text_utils.py` | `normalize_content`、时长解析/格式化、人设 token 解析 |
| `prompt_helpers.py` | Prompt 片段构建（睡眠状态描述、静默指令、动作指令变体） |
| `daily_record_sync.py` | `sync_sleep_to_daily_record()`（shared 下唯一带 IO 的模块） |
| `constants.py` | 兼容门面：集中 re-export 上述模块，`__all__` 覆盖 75 个历史导出名 |
| `vocabulary.py` | 词汇学习 |

> 新代码请直接引用原子模块，不要再从 `constants.py` 门面取常量；
> 验证脚本：`tests/scripts/active_care/verify_shared_constants_decoupled.py`。

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
