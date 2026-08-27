"""角色日常配置加载器。

统一放在 `config/` 下管理 character_daily 相关配置：
- `config/yaml/character_daily.yaml`：角色日程模板
- `config/yaml/app.yaml` 的 `character_daily` 节：运行参数
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List

import yaml

from core.utils.common import get_project_root

logger = logging.getLogger(__name__)


@dataclass
class ActivityTemplate:
    """活动模板（来自 YAML 的单条活动定义）"""

    activity: str
    duration_min: int
    duration_max: int
    weight: float = 1.0


@dataclass
class TimeBlock:
    """一个时段的模板"""

    period: str
    start: str
    end: str
    fixed: List[ActivityTemplate] = field(default_factory=list)
    pool: List[ActivityTemplate] = field(default_factory=list)


@dataclass
class RoleScheduleTemplate:
    """单个角色的日程模板"""

    role_id: str
    wake_time: str
    sleep_time: str
    sleep_profile: "SleepProfileConfig" = None
    time_blocks: List[TimeBlock] = field(default_factory=list)
    rest_day_extras: Dict[str, List[ActivityTemplate]] = field(default_factory=dict)


@dataclass
class SleepProfileConfig:
    """角色睡眠性格配置"""

    chronotype: str = "neutral"
    weekday_wake_time: str = ""
    weekend_wake_time: str = ""
    weekday_sleep_time: str = ""
    weekend_sleep_time: str = ""
    sleep_inertia_tendency: float = 0.5
    night_owl_tendency: float = 0.35
    late_snack_tendency: float = 0.2
    nap_tendency: float = 0.3
    oversleep_tendency: float = 0.15
    nightmare_tendency: float = 0.15
    wake_by_message_sensitivity: float = 0.5
    resume_sleep_tendency: float = 0.7
    schedule_adjust_tendency: float = 0.25
    diary_backfill_tendency: float = 0.08
    silence_window_seconds: int = 180

    def normalized(self, value: float) -> float:
        """将概率值规整到 0~1。"""
        return max(0.0, min(1.0, float(value)))


@dataclass
class PeerChatConfig:
    """peer chat 配置"""

    min_gap_seconds: float = 5400.0
    daily_soft_limit: int = 4
    daily_hard_limit: int = 6
    base_probability: float = 0.04
    eligible_hours_start: int = 9
    eligible_hours_end: int = 22
    urgent_interrupt_probability: float = 0.15
    retry_after_fail_seconds: float = 300.0


@dataclass
class LLMPlanConfig:
    """LLM 生成每日计划的配置"""

    enabled: bool = False
    model: str = "cloud:deepseek:qqbot1:deepseek-v4-pro"
    fallback_to_template: bool = True


@dataclass
class ReplyPolicyConfig:
    """被动回复时（用户发消息）的睡眠/忙碌处理配置"""

    enabled: bool = True
    dnd_delay_min: float = 30.0
    dnd_delay_max: float = 120.0
    busy_delay_min: float = 5.0
    busy_delay_max: float = 20.0
    soft_delay_quick_min_seconds: float = 8.0
    soft_delay_quick_max_seconds: float = 18.0
    soft_delay_normal_min_seconds: float = 18.0
    soft_delay_normal_max_seconds: float = 35.0
    soft_delay_slow_min_seconds: float = 28.0
    soft_delay_slow_max_seconds: float = 55.0
    soft_delay_recovery_min_seconds: float = 20.0
    soft_delay_recovery_max_seconds: float = 40.0
    force_reply_threshold: int = 6
    force_reply_cooldown_seconds: float = 600.0
    reply_window_seconds: float = 120.0
    manual_interrupt_window_seconds: float = 300.0
    proactive_reply_window_seconds: float = 300.0
    plan_transition_notice_seconds: float = 300.0
    # 同 role 跨人设唤醒宽限窗口：角色被唤醒（force_wake / /wake）后，
    # 在该窗口内切换到同 role 的另一个人设，直接放行回复，不重新走 DND 静默累积。
    # 解决"人设A吵醒Ling，切到人设B却说还在睡觉"的问题。
    # 默认 1200s（20 分钟），覆盖 night_awake 的 silence 衰减窗口（默认 3 分钟）
    # 与 wake-based 衰减阈值（默认 15 分钟）。
    role_wake_grace_seconds: float = 1200.0
    # 活动切换告别：角色从"可聊天"切到"忙碌/睡觉"时，若用户最近在聊天，主动发告别消息
    activity_transition_farewell_enabled: bool = True
    activity_transition_user_active_seconds: float = 300.0  # 判断"用户在聊天"的窗口（最近 N 秒内发过消息）
    activity_transition_farewell_cooldown_seconds: float = 60.0  # 同一活动切换的去重冷却（避免 tick 间隔内重复发）
    # 做事结束主动处理累积消息：角色从"忙碌"切回"可聊天"时，
    # 主动把做事期间静默累积的用户消息走 active_care 主动管线发回去，
    # 而不是等用户再发新消息才会被注入处理（修原"做完事没回"体验缺失）。
    activity_done_pending_process_enabled: bool = True
    # 做事结束触发处理的最小累积条数：少于 N 条不主动触发（避免单条小事也强触发）
    activity_done_pending_min_count: int = 1
    # 同 role + 同活动切换的去重冷却，避免 tick 间隔内重复触发
    activity_done_pending_cooldown_seconds: float = 60.0


@dataclass
class CharacterDailyConfig:
    """角色日常引擎运行参数"""

    enabled: bool = True
    check_interval_seconds: int = 120
    check_interval_jitter: float = 0.2
    sleep_runtime_enabled: bool = True
    sleep_runtime_poll_seconds: int = 30
    sleep_runtime_decision_model: str = "cloud:deepseek:qqbot1:deepseek-v4-flash"
    peer_chat: PeerChatConfig = field(default_factory=PeerChatConfig)
    llm_plan: LLMPlanConfig = field(default_factory=LLMPlanConfig)
    reply_policy: ReplyPolicyConfig = field(default_factory=ReplyPolicyConfig)


def _parse_activity_template(data: dict) -> ActivityTemplate:
    """解析单条活动模板"""

    dur = data.get("duration", [20, 40])
    return ActivityTemplate(
        activity=data["activity"],
        duration_min=int(dur[0]) if len(dur) > 0 else 20,
        duration_max=int(dur[1]) if len(dur) > 1 else 40,
        weight=float(data.get("weight", 1.0)),
    )


def _parse_time_block(data: dict) -> TimeBlock:
    """解析一个时段模板"""

    fixed = [_parse_activity_template(a) for a in (data.get("fixed") or [])]
    pool = [_parse_activity_template(a) for a in (data.get("pool") or [])]
    return TimeBlock(
        period=data.get("period", ""),
        start=data.get("start", "00:00"),
        end=data.get("end", "23:59"),
        fixed=fixed,
        pool=pool,
    )


def _parse_sleep_profile(
    data: dict,
    wake_time: str,
    sleep_time: str,
) -> SleepProfileConfig:
    """解析角色睡眠性格配置。"""

    data = data or {}
    return SleepProfileConfig(
        chronotype=str(data.get("chronotype", "neutral")),
        weekday_wake_time=str(data.get("weekday_wake_time") or wake_time),
        weekend_wake_time=str(data.get("weekend_wake_time") or wake_time),
        weekday_sleep_time=str(data.get("weekday_sleep_time") or sleep_time),
        weekend_sleep_time=str(data.get("weekend_sleep_time") or sleep_time),
        sleep_inertia_tendency=float(data.get("sleep_inertia_tendency", 0.5)),
        night_owl_tendency=float(data.get("night_owl_tendency", 0.35)),
        late_snack_tendency=float(data.get("late_snack_tendency", 0.2)),
        nap_tendency=float(data.get("nap_tendency", 0.3)),
        oversleep_tendency=float(data.get("oversleep_tendency", 0.15)),
        nightmare_tendency=float(data.get("nightmare_tendency", 0.15)),
        wake_by_message_sensitivity=float(data.get("wake_by_message_sensitivity", 0.5)),
        resume_sleep_tendency=float(data.get("resume_sleep_tendency", 0.7)),
        schedule_adjust_tendency=float(data.get("schedule_adjust_tendency", 0.25)),
        diary_backfill_tendency=float(data.get("diary_backfill_tendency", 0.08)),
        silence_window_seconds=int(data.get("silence_window_seconds", 180)),
    )


def _parse_role_template(role_id: str, role_data: dict) -> RoleScheduleTemplate:
    """从 YAML 单个角色 dict 解析为 RoleScheduleTemplate。"""
    wake_time = role_data.get("wake_time", "07:00")
    sleep_time = role_data.get("sleep_time", "23:00")
    blocks = [_parse_time_block(b) for b in (role_data.get("time_blocks") or [])]
    rest_day_extras = {
        str(period): [_parse_activity_template(item) for item in (items or [])]
        for period, items in (role_data.get("rest_day_extras") or {}).items()
        if isinstance(items, list)
    }
    return RoleScheduleTemplate(
        role_id=role_id,
        wake_time=wake_time,
        sleep_time=sleep_time,
        sleep_profile=_parse_sleep_profile(
            role_data.get("sleep_profile") or {},
            wake_time=str(wake_time),
            sleep_time=str(sleep_time),
        ),
        time_blocks=blocks,
        rest_day_extras=rest_day_extras,
    )


def _load_yaml_templates(yaml_path) -> Dict[str, RoleScheduleTemplate]:
    """从单个 YAML 文件加载角色日程模板。"""
    if not yaml_path.exists():
        return {}

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("CharacterDaily: 加载日程模板失败 (%s): %s", yaml_path, exc)
        return {}

    templates: Dict[str, RoleScheduleTemplate] = {}
    for role_id, role_data in raw.items():
        if not isinstance(role_data, dict):
            continue
        templates[role_id] = _parse_role_template(role_id, role_data)
    return templates


def load_schedule_templates() -> Dict[str, RoleScheduleTemplate]:
    """加载所有角色的日程模板。

    主模板来自 `config/yaml/character_daily.yaml`（已提交）。
    敏感角色模板来自 `config/yaml/character_daily_sensitive.yaml`（已 gitignore），
    用于 rushuang / mianmian 等私密人设的作息接入，与主文件解耦。
    后加载的模板会覆盖同 role_id 的主模板（敏感角色不会与主模板冲突，这里只是保留语义）。
    """
    root = get_project_root()
    main_path = root / "config" / "yaml" / "character_daily.yaml"
    sensitive_path = root / "config" / "yaml" / "character_daily_sensitive.yaml"

    if not main_path.exists():
        logger.warning("CharacterDaily: 主日程模板文件不存在: %s", main_path)
        templates: Dict[str, RoleScheduleTemplate] = {}
    else:
        templates = _load_yaml_templates(main_path)

    # 合并敏感角色模板（独立文件，便于 gitignore 与隐私隔离）
    sensitive_templates = _load_yaml_templates(sensitive_path)
    if sensitive_templates:
        templates.update(sensitive_templates)
        logger.info(
            "CharacterDaily: 已合并敏感角色模板，角色=%s",
            list(sensitive_templates.keys()),
        )

    logger.info("CharacterDaily: 加载日程模板完成，角色=%s", list(templates.keys()))
    return templates


def load_character_daily_config(app_config: dict = None) -> CharacterDailyConfig:
    """从 app.yaml 的 character_daily 节加载引擎配置。"""

    if app_config is None:
        cfg_dict = {}
    else:
        cfg_dict = app_config

    cd = cfg_dict.get("character_daily", {}) if cfg_dict else {}

    if not cd:
        try:
            from config.yaml_loader import load_resolved_yaml_config_from_disk

            yaml_path = get_project_root() / "config" / "yaml" / "app.yaml"
            if yaml_path.exists():
                full, _, _ = load_resolved_yaml_config_from_disk(yaml_path)
                cd = full.get("character_daily", {})
        except Exception:
            pass

    pc_data = cd.get("peer_chat", {}) if isinstance(cd, dict) else {}
    llm_plan_default_model = "cloud:deepseek:qqbot1:deepseek-v4-pro"
    sleep_decision_default_model = "cloud:deepseek:qqbot1:deepseek-v4-flash"
    try:
        from config.model_config import (
            get_character_daily_plan_model,
            get_character_daily_sleep_decision_model,
        )

        llm_plan_default_model = get_character_daily_plan_model(llm_plan_default_model)
        sleep_decision_default_model = get_character_daily_sleep_decision_model(
            sleep_decision_default_model
        )
    except Exception:
        pass

    peer_chat_cfg = PeerChatConfig(
        min_gap_seconds=float(pc_data.get("min_gap_seconds", 5400)),
        daily_soft_limit=int(pc_data.get("daily_soft_limit", 4)),
        daily_hard_limit=int(pc_data.get("daily_hard_limit", 6)),
        base_probability=float(pc_data.get("base_probability", 0.04)),
        eligible_hours_start=int(pc_data.get("eligible_hours", [9, 22])[0]),
        eligible_hours_end=int(pc_data.get("eligible_hours", [9, 22])[-1]),
        urgent_interrupt_probability=float(
            pc_data.get("urgent_interrupt_probability", 0.15)
        ),
        retry_after_fail_seconds=float(
            pc_data.get("retry_after_fail_seconds", 300.0)
        ),
    )

    llm_data = cd.get("llm_plan", {}) if isinstance(cd, dict) else {}
    llm_cfg = LLMPlanConfig(
        enabled=bool(llm_data.get("enabled", False)),
        model=str(llm_plan_default_model),
        fallback_to_template=bool(llm_data.get("fallback_to_template", True)),
    )

    rp_data = cd.get("reply_policy", {}) if isinstance(cd, dict) else {}
    dnd = rp_data.get("do_not_disturb", {}) if isinstance(rp_data, dict) else {}
    busy = rp_data.get("busy", {}) if isinstance(rp_data, dict) else {}
    reply_cfg = ReplyPolicyConfig(
        enabled=bool(rp_data.get("enabled", True)),
        dnd_delay_min=float(dnd.get("delay_min_seconds", 30)),
        dnd_delay_max=float(dnd.get("delay_max_seconds", 120)),
        busy_delay_min=float(busy.get("delay_min_seconds", 5)),
        busy_delay_max=float(busy.get("delay_max_seconds", 20)),
        soft_delay_quick_min_seconds=float(
            rp_data.get("soft_delay_quick_min_seconds", 8.0)
        ),
        soft_delay_quick_max_seconds=float(
            rp_data.get("soft_delay_quick_max_seconds", 18.0)
        ),
        soft_delay_normal_min_seconds=float(
            rp_data.get("soft_delay_normal_min_seconds", 18.0)
        ),
        soft_delay_normal_max_seconds=float(
            rp_data.get("soft_delay_normal_max_seconds", 35.0)
        ),
        soft_delay_slow_min_seconds=float(
            rp_data.get("soft_delay_slow_min_seconds", 28.0)
        ),
        soft_delay_slow_max_seconds=float(
            rp_data.get("soft_delay_slow_max_seconds", 55.0)
        ),
        soft_delay_recovery_min_seconds=float(
            rp_data.get("soft_delay_recovery_min_seconds", 20.0)
        ),
        soft_delay_recovery_max_seconds=float(
            rp_data.get("soft_delay_recovery_max_seconds", 40.0)
        ),
        force_reply_threshold=int(rp_data.get("force_reply_threshold", 6)),
        force_reply_cooldown_seconds=float(
            rp_data.get("force_reply_cooldown_seconds", 600.0)
        ),
        reply_window_seconds=float(rp_data.get("reply_window_seconds", 120.0)),
        manual_interrupt_window_seconds=float(
            rp_data.get("manual_interrupt_window_seconds", 300.0)
        ),
        proactive_reply_window_seconds=float(
            rp_data.get("proactive_reply_window_seconds", 300.0)
        ),
        plan_transition_notice_seconds=float(
            rp_data.get("plan_transition_notice_seconds", 300.0)
        ),
        role_wake_grace_seconds=float(
            rp_data.get("role_wake_grace_seconds", 1200.0)
        ),
        activity_transition_farewell_enabled=bool(
            rp_data.get("activity_transition_farewell_enabled", True)
        ),
        activity_transition_user_active_seconds=float(
            rp_data.get("activity_transition_user_active_seconds", 300.0)
        ),
        activity_transition_farewell_cooldown_seconds=float(
            rp_data.get("activity_transition_farewell_cooldown_seconds", 60.0)
        ),
        activity_done_pending_process_enabled=bool(
            rp_data.get("activity_done_pending_process_enabled", True)
        ),
        activity_done_pending_min_count=int(
            rp_data.get("activity_done_pending_min_count", 1)
        ),
        activity_done_pending_cooldown_seconds=float(
            rp_data.get("activity_done_pending_cooldown_seconds", 60.0)
        ),
    )

    return CharacterDailyConfig(
        enabled=bool(cd.get("enabled", True)),
        check_interval_seconds=int(cd.get("check_interval_seconds", 120)),
        check_interval_jitter=float(cd.get("check_interval_jitter", 0.2)),
        sleep_runtime_enabled=bool(cd.get("sleep_runtime", {}).get("enabled", True)),
        sleep_runtime_poll_seconds=int(
            cd.get("sleep_runtime", {}).get("poll_seconds", 30)
        ),
        sleep_runtime_decision_model=str(
            sleep_decision_default_model
        ),
        peer_chat=peer_chat_cfg,
        llm_plan=llm_cfg,
        reply_policy=reply_cfg,
    )


__all__ = [
    "ActivityTemplate",
    "TimeBlock",
    "RoleScheduleTemplate",
    "SleepProfileConfig",
    "PeerChatConfig",
    "LLMPlanConfig",
    "ReplyPolicyConfig",
    "CharacterDailyConfig",
    "load_schedule_templates",
    "load_character_daily_config",
]
