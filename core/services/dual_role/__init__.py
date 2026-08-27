# dual_role 模块 - 双角色社交事件与角色定义
from .social_events import SocialEventEngine, get_social_event_engine
from .constants import (
    normalize_persona_name,
    persona_names_equal,
    AVELINE_CANONICAL_NAME,
    LING_CANONICAL_NAME,
)

__all__ = [
    "SocialEventEngine",
    "get_social_event_engine",
    "normalize_persona_name",
    "persona_names_equal",
    "AVELINE_CANONICAL_NAME",
    "LING_CANONICAL_NAME",
]
