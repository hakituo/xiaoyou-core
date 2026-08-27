"""
角色日常系统（Character Daily Life）

独立管理两个角色的日常活动计划和 peer chat 触发。
"""
from typing import Any


def __getattr__(name: str) -> Any:
    """按需加载 engine，避免包初始化时触发循环依赖。"""
    if name in {
        "CharacterDailyEngine",
        "get_character_daily_engine",
        "init_character_daily_engine",
    }:
        from core.services.character_daily.engine import (
            CharacterDailyEngine,
            get_character_daily_engine,
            init_character_daily_engine,
        )

        mapping = {
            "CharacterDailyEngine": CharacterDailyEngine,
            "get_character_daily_engine": get_character_daily_engine,
            "init_character_daily_engine": init_character_daily_engine,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CharacterDailyEngine",
    "get_character_daily_engine",
    "init_character_daily_engine",
]
