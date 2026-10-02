# Configuration package for xiaoyou-core
# 统一配置入口：get_settings() 返回 AppSettings 实例
from .integrated_config import get_settings, AppSettings, Config
from .character_daily_config import (
    CharacterDailyConfig,
    ReplyPolicyConfig,
    RoleScheduleTemplate,
    SleepProfileConfig,
    load_character_daily_config,
    load_schedule_templates,
)

__all__ = [
    "get_settings",
    "AppSettings",
    "Config",
    "CharacterDailyConfig",
    "ReplyPolicyConfig",
    "RoleScheduleTemplate",
    "SleepProfileConfig",
    "load_character_daily_config",
    "load_schedule_templates",
]
