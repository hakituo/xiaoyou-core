"""兼容层：转发 character_daily 配置到 `config/character_daily_config.py`。

真正的配置定义与加载逻辑统一放在 `config/` 目录。
这里仅保留旧 import 路径，避免一次性修改大量业务引用。
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
    load_schedule_templates,
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
