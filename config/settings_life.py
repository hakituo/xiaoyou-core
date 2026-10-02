"""
生活模拟、情绪、双角色、学习相关配置
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config._base import BaseSettings, Field, SettingsConfigDict


class DualRoleSettings(BaseSettings):
    event_decay_half_life_hours: float = Field(
        default=24.0, description="双角色事件权重半衰期（小时）"
    )
    weight_meal: float = Field(default=1.1, description="饮食互动事件权重")
    weight_care: float = Field(default=1.4, description="关怀互动事件权重")
    weight_switch: float = Field(default=0.5, description="前台切换事件权重")
    weight_mention: float = Field(default=0.4, description="关系提及事件权重")
    summary_hot_threshold: float = Field(default=4.5, description="关系升温阈值")
    summary_warm_threshold: float = Field(default=2.0, description="关系稳定阈值")
    dedup_window_seconds: float = Field(default=30.0, description="事件去重窗口(秒)")
    bert_intent_threshold_meal: float = Field(
        default=0.62, description="BERT meal/drink 判定阈值"
    )
    bert_intent_threshold_switch: float = Field(
        default=0.72, description="BERT switch 判定阈值"
    )
    bert_intent_threshold_care: float = Field(
        default=0.72, description="BERT care 判定阈值"
    )
    peer_private_chat_enabled: bool = Field(
        default=True, description="是否允许双QQ角色之间私聊（关闭后对方发来的私聊消息会被忽略）"
    )
    peer_chat_enabled: bool = Field(
        default=True, description="是否启用双QQ角色主动互聊（由Active Care调度）"
    )
    peer_chat_daily_limit: int = Field(
        default=6, description="每日双角色主动互聊全局上限（所有角色合计）"
    )
    peer_chat_min_gap_seconds: float = Field(
        default=5400.0, description="双角色主动互聊全局最小间隔(秒)，默认1.5小时"
    )
    peer_chat_decision_model_hint: str = Field(
        default="", description="双角色互聊决策模型（空则复用active_care决策模型）"
    )
    peer_chat_content_model_hint: str = Field(
        default="", description="双角色互聊内容生成模型（空则复用active_care内容模型）"
    )
    peer_chat_max_rounds: int = Field(
        default=8, description="双角色互聊剧本最大轮次（LLM生成剧本时的参考轮数范围上限）"
    )
    peer_chat_check_interval_seconds: float = Field(
        default=1800.0, description="PeerChatScheduler 调度循环检查间隔(秒)，默认30分钟"
    )
    peer_chat_backoff_base_seconds: float = Field(
        default=1800.0, description="连续失败后的指数退避基数(秒)"
    )
    peer_chat_backoff_max_seconds: float = Field(
        default=14400.0, description="指数退避上限(秒)，默认4小时"
    )
    peer_chat_backoff_threshold: int = Field(
        default=3, description="连续失败多少次后启用指数退避"
    )
    peer_chat_user_activity_grace_seconds: float = Field(
        default=45.0, description="用户发消息后，互聊暂停的宽限期(秒)"
    )
    peer_chat_user_idle_window_seconds: float = Field(
        default=900.0, description="用户最后消息后允许多少秒内触发互聊(秒)"
    )
    peer_chat_require_live_connections: bool = Field(
        default=True,
        description=(
            "互聊是否要求参与双方都有真实客户端连接"
            "（关闭后恢复旧行为：常驻角色即使离线也会互聊）"
        ),
    )
    peer_chat_decision_timeout_seconds: float = Field(
        default=20.0, description="peer chat 决策 LLM 调用超时(秒)"
    )
    peer_chat_script_timeout_seconds: float = Field(
        default=45.0, description="peer chat 剧本生成 LLM 调用超时(秒)，单次调用含重试"
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_DUAL_ROLE_", extra="allow")


class StudySettings(BaseSettings):
    study_root: str = Field(default="D:\\AI\\Study", description="学习文件夹路径（绝对路径）")
    enabled: bool = Field(default=False, description="是否启用词库功能（禁用时不加载词库数据）")
    tutor_enabled: bool = Field(default=True, description="是否启用教学决策引擎（TutorEngine）")
    daily_briefing_enabled: bool = Field(default=True, description="是否生成每日学习简报")
    weakness_tracking: bool = Field(default=True, description="是否启用薄弱点追踪与间隔复习")
    review_intervals_days: str = Field(default="1,3,7,14", description="间隔复习天数，逗号分隔")
    daily_study_goal_minutes: int = Field(default=120, description="每日学习目标（分钟）")
    active_care_briefing: bool = Field(default=True, description="是否通过 Active Care 推送学习简报")
    # 背单词提醒时刻（24 小时制，逗号分隔）：到点若今天还没背完就推一次。
    # 多个时刻 = 一天多次催背（12 点没背 16 点继续催），不是只提醒一次。
    vocab_reminder_hours: str = Field(
        default="12,16,20,22", description="背单词提醒时刻（24 小时制，逗号分隔）"
    )
    # 剩余待背词数低于该值不打扰（避免"就剩 1 个词"也弹通知）
    vocab_reminder_min_due: int = Field(default=1, description="触发背单词提醒的最小待背词数")
    # 每日单词推送时刻（24 小时制，逗号分隔）：到点把今天的 20 个词推给用户，一天一次。
    # 默认早上 8 点，刻意与 vocab_reminder_hours（12/16/20/22 催背）错开：
    # 同一小时里既推"今日单词"又催"还没背"，对用户是重复轰炸。
    daily_vocab_push_hours: str = Field(
        default="8", description="每日单词推送时刻（24 小时制，逗号分隔）"
    )

    def get_review_intervals(self) -> list:
        """解析间隔复习天数列表"""
        try:
            return [int(x.strip()) for x in self.review_intervals_days.split(",") if x.strip()]
        except Exception:
            return [1, 3, 7, 14]

    def get_vocab_reminder_hours(self) -> list:
        """解析背单词提醒时刻，非法输入回退到默认四个时刻。"""
        try:
            hours = [
                int(x.strip())
                for x in str(self.vocab_reminder_hours).split(",")
                if x.strip()
            ]
            hours = [h for h in hours if 0 <= h <= 23]
            return sorted(set(hours)) or [12, 16, 20, 22]
        except Exception:
            return [12, 16, 20, 22]

    def get_daily_vocab_push_hours(self) -> list:
        """解析每日单词推送时刻，非法输入回退到默认早上 8 点。

        一天只推一次（按 daily_vocab_status.json 的日期去重），配置多个时刻时
        以最早的为准：服务到点后才启动时，当天补推一次。
        """
        try:
            hours = [
                int(x.strip())
                for x in str(self.daily_vocab_push_hours).split(",")
                if x.strip()
            ]
            hours = [h for h in hours if 0 <= h <= 23]
            return sorted(set(hours)) or [8]
        except Exception:
            return [8]

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_STUDY_", extra="allow")


class StudyModeSettings(BaseSettings):
    """学习模式（enter_study_mode 工具）的会话生命周期配置。

    学习模式由 LLM 通过原生工具进入，历史上因为只在内存存状态、没有过期机制，
    模型一旦忘了退出就会永久锁定会话（表现为一直追问同一个学科）。
    这些阈值让学习会话必须持续有学习信号才能续命，任一条件命中即自动退出。

    子键在 app.yaml 中位于 ``life_simulation.study_mode.*``，与其它
    active_care 配置分区开来，避免同名键互相干扰。
    """

    study_mode_session_ttl_seconds: float = Field(
        default=10800.0, description="单次学习会话最长存活时长(秒)，默认 3 小时"
    )
    study_mode_max_turns: int = Field(
        default=60, description="单次学习会话最多持续多少轮，超出自动退出"
    )
    study_mode_idle_turns: int = Field(
        default=6, description="连续多少轮没有学习信号就自动退出（话题漂移检测）"
    )
    study_mode_idle_seconds: float = Field(
        default=1800.0, description="距上一次学习信号满多少秒自动退出，默认 30 分钟"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_STUDY_MODE_", extra="allow"
    )


class LifeSimulationSettings(BaseSettings):
    """生活模拟配置"""

    enable_spontaneous_reaction: bool = Field(
        default=False, description="是否启用自发反应"
    )
    idle_threshold: int = Field(default=1800, description="闲置阈值(秒)")
    active_check_interval: int = Field(
        default=60, description="Active Care 活跃时段检查间隔(秒)"
    )
    quiet_check_interval: int = Field(
        default=60, description="Active Care 安静时段检查间隔(秒)"
    )

    # 主动关怀配置
    active_care_enabled: bool = Field(default=True, description="是否全局启用主动关怀")
    # 允许发送主动关怀消息的角色白名单；留空/未配置时回退代码默认值
    # (sleep_manager._ACTIVE_CARE_ENABLED_ROLES_DEFAULT)。
    # 注意：必须是声明字段才能被 apply_yaml_config 回写，否则 app.yaml 配置不生效。
    active_care_enabled_roles: Optional[List[str]] = Field(
        default=None,
        description="允许发送主动关怀消息的角色白名单（角色 ID 列表），留空回退代码默认值",
    )
    # 是否把主动关怀消息补投到手机 App / Web 等 WebSocket 客户端。
    # App 客户端的 user_id（如 mobile_user）与 QQ 传输 uid（private_xxx）不属于
    # 同一命名空间，按主人 uid 广播时 App 根本收不到，需要单独补投一次。
    # 关闭后主动消息只走 QQ，回到 2026-09 之前的行为。
    active_care_app_delivery_enabled: bool = Field(
        default=True,
        description="是否把主动关怀消息补投到手机 App / Web 等 WebSocket 客户端",
    )
    active_care_epsilon: float = Field(
        default=0.2, description="主动关怀决策探索率 (Bandit Epsilon)"
    )
    active_care_daily_limit: int = Field(default=20, description="每日主动消息上限")
    active_care_min_gap_seconds: int = Field(
        default=900, description="主动消息最小间隔(秒)"
    )
    active_care_default_next_check_seconds: int = Field(
        default=300, description="默认下一次检查等待(秒)"
    )
    # P2-10: 补齐幽灵配置项，decision.py:54 读取但未在配置系统中定义
    active_care_silence_breaker_seconds: int = Field(
        default=2700, description="长时间沉默打破阈值(秒)，超过则强制触发主动消息"
    )
    active_care_model_hint: str = Field(
        default="cloud:siliconflow:Pro/Qwen/Qwen3.5-397B-A17B",
        description="Active Care 专用模型路由提示",
    )
    active_care_startup_check: bool = Field(
        default=False, description="是否在启动时执行主动关怀检查"
    )
    active_care_startup_delay_seconds: int = Field(
        default=180, description="启动后延迟多久执行第一次主动关怀检查(秒)，默认3分钟"
    )
    active_care_require_active_client: bool = Field(
        default=True, description="是否要求存在活跃客户端后才执行主动关怀触发"
    )
    active_care_enable_auto_goodnight_reduced_mode: bool = Field(
        default=True, description="是否在检测到晚安意图时自动进入低打扰模式"
    )

    # 2026-09-15 补齐幽灵配置项：下面这些字段多年来只在代码里被
    # get_active_care_config / _get_config_value 读取，却从未在 Settings 中声明。
    # 未声明字段不会被 apply_yaml_config 回写，于是 app.yaml 配了也恒取代码 default，
    # 表现为"配置项完全无效"。这里按代码中现有的 default 值原样声明，
    # 行为不变，但配置重新可调。
    active_care_enable_focus_reduced_mode: bool = Field(
        default=False,
        description="是否允许进入专注(focus)低打扰模式；关闭时会清理已存在的 focus 低打扰状态",
    )
    active_care_quiet_hours: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "静默时段配置：enabled / allow_goodnight_probe / "
            "goodnight_probe_gap_seconds / goodnight_low_disturb_gap_seconds"
        ),
    )
    active_care_user_quiet_seconds: int = Field(
        default=300, description="最近用户交互保护窗口(秒)：距上次交互小于该值时不主动发消息"
    )
    active_care_focus_user_quiet_seconds: int = Field(
        default=1800, description="专注模式下要求用户静默多久才允许低打扰发送(秒)"
    )
    active_care_focus_low_disturb_gap_seconds: int = Field(
        default=7200, description="专注模式下两次低打扰发送的最小间隔(秒)"
    )
    active_care_mdp_epsilon: float = Field(
        default=0.2, description="主动关怀 MDP 决策探索率"
    )
    active_care_mdp_learning_rate: float = Field(
        default=0.15, description="主动关怀 MDP 学习率"
    )
    active_care_decision_temperature: float = Field(
        default=0.45, description="主动关怀决策 LLM 温度"
    )
    active_care_generation_temperature: float = Field(
        default=0.65, description="主动关怀消息生成 LLM 温度"
    )
    active_care_generation_max_tokens: int = Field(
        default=400, description="主动关怀消息生成最大 token 数"
    )
    primary_role_id: str = Field(
        default="",
        description="生命模拟主角色 ID；留空时回退到已知角色列表第一个",
    )

    # 时间预期和紧急程度调度配置
    active_care_time_expectation_enabled: bool = Field(
        default=True, description="是否启用基于时间预期的智能跟进"
    )
    active_care_urgency_detection_enabled: bool = Field(
        default=True, description="是否启用紧急程度检测"
    )
    active_care_min_follow_up_seconds: int = Field(
        default=30, description="跟进消息的最小延迟秒数"
    )
    active_care_max_follow_up_seconds: int = Field(
        default=3600, description="跟进消息的最大延迟秒数"
    )
    active_care_urgent_follow_up_seconds: int = Field(
        default=60, description="紧急消息的跟进延迟秒数"
    )
    active_care_delayed_task_max_count: int = Field(
        default=50, description="延迟任务队列最大数量"
    )
    active_care_reminder_inject_to_chat: bool = Field(
        default=True, description="计划提醒是否注入到当前聊天上下文（而非发送独立消息）"
    )
    active_care_reminder_inject_window_seconds: int = Field(
        default=600, description="用户聊天注入窗口（秒），在此时间内的交互视为'正在聊天'"
    )

    # 用户进程活动检测配置
    active_care_activity_detection_enabled: bool = Field(
        default=True, description="是否启用进程活动检测（通过查看任务进程判断用户在做什么）"
    )
    active_care_activity_busy_threshold: float = Field(
        default=0.60, description="忙碌判定阈值(0.0~1.0)，超过此值视为忙碌应跳过发送"
    )
    active_care_activity_cache_ttl_seconds: float = Field(
        default=30.0, description="活动检测缓存有效期(秒)，避免频繁扫描进程"
    )
    active_care_busy_user_next_check_seconds: int = Field(
        default=600, description="用户忙碌时下次检查间隔(秒)"
    )

    # 2026-09-04 频控改造：多层频控（Cadence Guard）配置。
    # 决策默认值见 cadence/cadence_guard.py，config 缺失时兜底；实际运行优先读本配置。
    active_care_global_proactive_cooldown_seconds: int = Field(
        default=2400, description="全局主动冷却(秒)：任意两条主动消息之间最小间隔，默认 40 分钟"
    )
    active_care_question_cooldown_seconds: int = Field(
        default=4500, description="提问冷却(秒)：问过一次后短时间内不再问，默认 75 分钟"
    )
    active_care_same_topic_cooldown_seconds: int = Field(
        default=10800, description="同组题材冷却(秒)：换措辞追同一件事的最小间隔，默认 3 小时"
    )
    active_care_max_unanswered_proactive: int = Field(
        default=1, description="未回复抑制：用户未回时最多悬着的普通主动消息数"
    )
    active_care_max_curious_question_per_day: int = Field(
        default=3, description="每日好奇提问软上限，达到后优先 defer"
    )
    active_care_unanswered_suppress_window_seconds: int = Field(
        default=21600, description="未回复抑制窗口(秒)：超时后解除抑制允许重新接触，默认 6 小时"
    )

    # --- 2026-09-21 起床退出低打扰相关 ---
    # 注意：这些字段必须在此显式声明。app.yaml 里写了但类里没声明的键不会
    # 进入 config 对象（pydantic 的 extra="allow" 只在构造时传入才生效），
    # 结果就是"改了 yaml 完全没用、永远走代码默认值"。
    active_care_bert_wakeup_exit_threshold: float = Field(
        default=0.70,
        description=(
            "BERT 判定 WAKEUP_NOW 的置信度阈值；达到即作为清醒信号退出晚安低打扰。"
            "调高更保守，调低更容易被识别为已醒"
        ),
    )
    active_care_daytime_exit_activity_seconds: int = Field(
        default=1800,
        description=(
            "白天兜底退出：白天里用户在晚安后持续活跃满该时长(秒)即强制退出晚安模式，"
            "不再依赖单句起床意图检测。设 0 关闭该兜底"
        ),
    )
    role_awake_while_user_chatting_grace_seconds: float = Field(
        default=600.0,
        description=(
            "用户最近一次发言后多久内，角色按作息入睡也不进入 sleeping 覆盖（保持清醒陪聊）。"
            "调大=陪你聊更久才回睡，设 0=关闭（角色照常按作息睡）"
        ),
    )
    study_mode: StudyModeSettings = Field(default_factory=lambda: StudyModeSettings())

    mood_delay_threshold: float = Field(
        default=40.0, description="心情低于该阈值时注入回复延迟"
    )
    mood_delay_scale: float = Field(default=0.1, description="心情延迟系数(秒/分数)")
    mood_delay_max_seconds: float = Field(default=4.0, description="心情延迟上限(秒)")

    ignore_threshold: float = Field(
        default=15.0, description="心情低于该阈值时可能拒绝响应"
    )
    ignore_probability: float = Field(default=0.3, description="低心情拒绝响应概率")

    enable_ignore_injection: bool = Field(
        default=False, description="是否启用低心情/高害羞的沉默注入"
    )

    system_error_base_probability: float = Field(
        default=0.02, description="基础system error概率"
    )
    system_error_mood_threshold: float = Field(
        default=25.0, description="心情低于该阈值时增加system error概率"
    )
    system_error_low_mood_max_probability: float = Field(
        default=0.12, description="低心情额外system error概率上限"
    )
    system_error_shy_threshold: float = Field(
        default=70.0, description="害羞分数高于该阈值时增加system error概率"
    )
    system_error_high_shy_max_probability: float = Field(
        default=0.10, description="高害羞额外system error概率上限"
    )
    system_error_sick_probability: float = Field(
        default=0.08, description="生病状态额外system error概率"
    )
    system_error_probability_cap: float = Field(
        default=0.35, description="system error概率上限"
    )

    enable_system_error_injection: bool = Field(
        default=False, description="是否启用system error熔断注入"
    )

    shyness_decay_per_minute: float = Field(
        default=6.0, description="害羞分数每分钟自然衰减"
    )
    shyness_bump_on_intimacy: float = Field(
        default=18.0, description="触发亲密语境时害羞增加"
    )

    health_poll_interval_seconds: float = Field(
        default=10.0, description="服务健康状态轮询间隔(秒)"
    )
    immune_damage_increase_per_unhealthy: float = Field(
        default=12.0, description="每个异常子系统造成的免疫损伤"
    )
    immune_damage_decay_per_tick: float = Field(
        default=3.0, description="健康时免疫损伤恢复"
    )
    sickness_threshold: float = Field(
        default=60.0, description="免疫损伤超过阈值进入生病状态"
    )
    sickness_mood_penalty_per_minute: float = Field(
        default=1.0, description="生病时每分钟心情惩罚"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_LIFE_SIMULATION_", extra="allow"
    )


class EmotionSettings(BaseSettings):
    """情绪模块配置"""

    enabled: bool = Field(default=False, description="情绪模块总开关")
    detector_mode: str = Field(default="smart", description="检测模式: smart(关键词+BERT) / legacy(LLM标签)")
    affect_prompt_enabled: bool = Field(default=True, description="是否在对话prompt中注入情绪信息")
    hardware_control_enabled: bool = Field(default=True, description="是否控制呼吸灯等硬件")
    data_dir: str = Field(default="data/emotions", description="情绪历史存储目录")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_EMOTION_", extra="allow"
    )
