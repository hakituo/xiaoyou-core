"""兼容层：转发 character_daily 配置到 `config/character_daily_config.py`。

真正的配置定义与加载逻辑统一放在 `config/` 目录。
这里保留旧 import 路径，并把显式 workday/rest_day 作息同步到 SleepProfile，
确保 DailyPlan 与 SleepManager 对同一天的起床/入睡时间使用同一事实源。
"""

from config.character_daily_config import (
    ActivityTemplate,
    CharacterDailyConfig,
    LLMPlanConfig,
    PeerChatConfig,
    ReplyPolicyConfig,
    RoleScheduleTemplate,
    SleepProfileConfig,
    TimeBlock,
    load_character_daily_config,
    load_schedule_templates as _load_schedule_templates,
)


def load_schedule_templates():
    """加载角色模板，并把 day-type 作息同步进睡眠配置。"""
    templates = _load_schedule_templates()
    try:
        from core.services.character_daily.day_type_schedule import (
            load_day_type_schedules,
        )

        day_types = load_day_type_schedules()
        for role_id, schedules in day_types.items():
            template = templates.get(role_id)
            if template is None:
                continue
            workday = schedules.workday
            rest_day = schedules.rest_day
            if workday is not None:
                # top-level 时间作为普通工作日兼容值。
                template.wake_time = workday.wake_time
                template.sleep_time = workday.sleep_time
            profile = template.sleep_profile
            if profile is None:
                profile = SleepProfileConfig(
                    weekday_wake_time=template.wake_time,
                    weekend_wake_time=template.wake_time,
                    weekday_sleep_time=template.sleep_time,
                    weekend_sleep_time=template.sleep_time,
                )
                template.sleep_profile = profile
            if workday is not None:
                profile.weekday_wake_time = workday.wake_time
                profile.weekday_sleep_time = workday.sleep_time
            if rest_day is not None:
                profile.weekend_wake_time = rest_day.wake_time
                profile.weekend_sleep_time = rest_day.sleep_time
    except Exception:
        # day-type 是增强覆盖；解析失败时保持原模板，兼容旧部署。
        pass
    return templates


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
