"""生命模拟服务的状态推导辅助函数。"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Tuple

from config.debug_config import is_debug_enabled
from core.utils.data_paths import get_active_care_dir


def read_active_care_sleep_state() -> bool:
    """检查 Active Care 是否处于睡眠会话状态。"""
    try:
        # 睡眠是用户级事实，优先读取 Active Care 的全局真源；旧文件仅作迁移兼容。
        state_file = get_active_care_dir("user") / "user_sleep_state.json"
        if not state_file.exists():
            state_file = get_active_care_dir(None) / "proactive_state.json"
        if not state_file.exists():
            return False
        with open(state_file, "r", encoding="utf-8") as file:
            state = json.load(file)
        goodnight_ts = float(state.get("last_goodnight_ts") or 0.0)
        goodmorning_ts = float(state.get("last_goodmorning_ts") or 0.0)
        if goodnight_ts > 0 and goodmorning_ts < goodnight_ts:
            return True
        reduced_active = bool(state.get("reduced_mode_active"))
        reduced_reason = str(state.get("reduced_mode_reason") or "none")
        return reduced_active and reduced_reason in (
            "goodnight",
            "sleep_hint",
        )
    except Exception:
        return False


def derive_activity_and_mood(
    *,
    hour: int,
    status: Dict[str, Any],
    life_stats: Dict[str, Any],
    activity_time_ranges: Iterable[Tuple[int, int, str]],
    active_care_sleeping: bool,
    sleeping_override: str,
    high_cpu_temp_working: int,
    overheat_cpu_temp: int,
    low_battery: int,
    low_energy: int,
    low_hunger: int,
    low_thirst: int,
    high_mood_score: int,
    good_physical_score: int,
) -> Tuple[str, str]:
    """根据时间、硬件与生命状态推导活动和情绪。"""
    activity = "idle"
    for start, end, act in activity_time_ranges:
        if start <= hour < end:
            activity = act
            break

    if activity == "working" and status.get("cpu_temp", 0) > high_cpu_temp_working:
        activity = "working_hard"

    if sleeping_override:
        activity = sleeping_override
    elif activity != "sleeping" and active_care_sleeping:
        activity = "sleeping"

    cpu_temp = status.get("cpu_temp", 0)
    battery = status.get("battery", 100)
    energy = float(life_stats.get("energy", 100) or 100)
    hunger = float(life_stats.get("hunger", 100) or 100)
    thirst = float(life_stats.get("thirst", 100) or 100)
    mood_score = float(life_stats.get("mood_score", 80) or 80)
    physical_score = (energy + hunger + thirst) / 3

    if cpu_temp > overheat_cpu_temp:
        mood = "overheated"
    elif battery < low_battery:
        mood = "exhausted"
    elif energy < low_energy:
        mood = "tired"
    elif hunger < low_hunger:
        mood = "hungry"
    elif thirst < low_thirst:
        mood = "thirsty"
    elif activity == "working_hard":
        mood = "focused"
    elif activity in {"relaxing", "sleep_recovery", "overslept_recovery"}:
        mood = "calm"
    elif mood_score > high_mood_score and physical_score > good_physical_score:
        mood = "excited"
    else:
        mood = "happy"
    return activity, mood


def build_bio_stats(engine: Any) -> Dict[str, Any]:
    """读取 C++ BioSystem 的基础统计。"""
    bio_stats: Dict[str, Any] = {}
    if not engine or not getattr(engine, "enabled", False) or not getattr(engine, "bio_system", None):
        return bio_stats
    try:
        nt = engine.bio_system.getNeurotransmitters()
        sleep_debt = _get_sleep_debt(engine)
        bio_stats = {
            "dopamine": getattr(nt, "dopamine", 0),
            "serotonin": getattr(nt, "serotonin", 0),
            "norepinephrine": getattr(nt, "norepinephrine", 0),
            "oxytocin": getattr(nt, "oxytocin", 0),
            "cortisol": getattr(nt, "cortisol", 0),
            "sleep_debt": sleep_debt,
        }
    except Exception as exc:
        if is_debug_enabled("life_simulation"):
            from core.utils.logger import get_logger

            get_logger("LIFE_SIMULATION").info(f"获取生物统计数据失败: {exc}")
    return bio_stats


def _get_sleep_debt(engine: Any) -> float:
    """兼容不同 BioSystem 接口获取睡眠债。"""
    try:
        bio = engine.bio_system
        for attr in ("getSleepDebt", "get_sleep_debt"):
            getter = getattr(bio, attr, None)
            if callable(getter):
                return float(getter())
        for attr in ("sleep_debt", "sleepDebt"):
            value = getattr(bio, attr, None)
            if value is not None:
                return float(value)
    except Exception as exc:
        if is_debug_enabled("life_simulation"):
            from core.utils.logger import get_logger

            get_logger("LIFE_SIMULATION").info(f"获取睡眠债务失败: {exc}")
    return 0.0


def get_vision_summary(hour: int) -> str:
    """获取视觉摘要。"""
    if 6 <= hour < 18:
        return "光线充足，传感器正常"
    return "环境昏暗，启用夜视模式"
