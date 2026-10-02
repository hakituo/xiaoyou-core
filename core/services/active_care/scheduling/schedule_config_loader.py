"""
调度配置加载模块

从 ActiveCareContext 中拆出的调度配置加载逻辑，包括：
- 推送调度（push_schedule）和静默时段（quiet_hours）的默认值构建
- 旧版调度文件清理
- 配置加载与缓存
"""

import os
import time
from typing import Any, Dict, Tuple

from core.utils.data_paths import (
    get_user_data_dir,
    get_user_schedule_dir,
)
from core.utils.logger import get_logger
from core.utils.config_accessor import get_config

logger = get_logger("ACTIVE_CARE_CONTEXT")


# ---------------------------------------------------------------------------
# 模块级缓存
# ---------------------------------------------------------------------------
_schedule_cache: Dict[str, Any] = {"push_schedule": {}, "quiet_hours": {}}
_schedule_cache_loaded_at: float = 0.0
_schedule_cache_ttl_seconds: float = 60.0
_schedule_legacy_cleanup_done: bool = False


# ---------------------------------------------------------------------------
# 路径与默认值构建
# ---------------------------------------------------------------------------

def get_daily_data_paths() -> Tuple[str, str, str]:
    """获取调度相关数据路径（base_dir, push_schedule_path, quiet_hours_path）"""
    base = str(get_user_data_dir())
    schedule_dir = str(get_user_schedule_dir())
    push_schedule = os.path.join(schedule_dir, "push_schedule.json")
    quiet_hours = os.path.join(schedule_dir, "quiet_hours.json")
    return base, push_schedule, quiet_hours


def build_default_push_schedule(settings: Any = None) -> Dict[str, Any]:
    """构建默认推送调度配置"""
    # P1-4: 默认值与 settings_life.py 的 pydantic Field 对齐（daily_limit=20, min_gap=900）
    daily_limit = int(
        get_config("life_simulation.active_care_daily_limit", default=20, settings=settings)
    )
    min_gap_seconds = int(
        get_config("life_simulation.active_care_min_gap_seconds", default=900, settings=settings)
    )
    default_next_check = int(
        get_config("life_simulation.active_care_default_next_check_seconds", default=300, settings=settings)
    )
    timezone = get_config(
        "system.timezone", default="Asia/Shanghai", settings=settings
    )
    return {
        "schema_version": 1,
        "timezone": timezone,
        "rules": {
            "daily_limit": daily_limit,
            "min_gap_seconds": min_gap_seconds,
            "default_next_check_seconds": default_next_check,
        },
        "windows": [],
    }


def build_default_quiet_hours() -> Dict[str, Any]:
    """构建默认静默时段配置"""
    return {
        "enabled": True,
        "goodnight_probe_gap_seconds": 2 * 3600,
        "allow_goodnight_probe": False,
    }


# ---------------------------------------------------------------------------
# 旧版文件清理
# ---------------------------------------------------------------------------

def cleanup_legacy_schedule_files() -> None:
    """清理旧版调度文件（仅执行一次）"""
    global _schedule_legacy_cleanup_done
    if _schedule_legacy_cleanup_done:
        return
    _schedule_legacy_cleanup_done = True
    try:
        schedule_dir = get_user_schedule_dir()
        for file_name in ("push_schedule.json", "quiet_hours.json"):
            target = schedule_dir / file_name
            if target.exists() and target.is_file():
                try:
                    target.unlink()
                except Exception:
                    pass
    except Exception:
        return


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

async def load_schedule_configs(settings: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    加载调度配置（从配置文件合并默认值）

    Args:
        settings: 配置设置对象，如未提供则使用默认值
    """
    cleanup_legacy_schedule_files()
    push_schedule = build_default_push_schedule(settings=settings)
    quiet_hours = build_default_quiet_hours()
    try:
        cfg_push = get_config(
            "life_simulation.active_care_schedule", default={}, settings=settings
        )
        if isinstance(cfg_push, dict) and cfg_push:
            push_schedule.update(cfg_push)
    except Exception:
        pass
    try:
        cfg_quiet = get_config(
            "life_simulation.active_care_quiet_hours", default={}, settings=settings
        )
        if isinstance(cfg_quiet, dict) and cfg_quiet:
            quiet_hours.update(cfg_quiet)
    except Exception:
        pass
    return push_schedule, quiet_hours


async def get_schedule_configs(settings: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    获取调度配置（带模块级缓存）

    Args:
        settings: 配置设置对象
    """
    global _schedule_cache, _schedule_cache_loaded_at

    now = time.time()
    if (
        _schedule_cache_loaded_at
        and (now - _schedule_cache_loaded_at)
        < _schedule_cache_ttl_seconds
    ):
        ps = _schedule_cache.get("push_schedule")
        qh = _schedule_cache.get("quiet_hours")
        if isinstance(ps, dict) and isinstance(qh, dict):
            return ps, qh

    push_schedule, quiet_hours = await load_schedule_configs(settings=settings)

    _schedule_cache = {
        "push_schedule": push_schedule if isinstance(push_schedule, dict) else {},
        "quiet_hours": quiet_hours if isinstance(quiet_hours, dict) else {},
    }
    _schedule_cache_loaded_at = now
    return _schedule_cache["push_schedule"], _schedule_cache["quiet_hours"]
