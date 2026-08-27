"""角色睡眠恢复保护的辅助判断。"""

from __future__ import annotations

from typing import Any, Dict


def _impact_recovery_window_seconds(impact_level: str, sleep_inertia_score: float) -> int:
    """根据影响等级给出恢复保护的最长窗口。"""
    impact = str(impact_level or "none").strip().lower()
    if impact == "severe":
        return 3 * 3600
    if impact == "medium":
        return 2 * 3600
    if sleep_inertia_score >= 28:
        return 90 * 60
    return 60 * 60


def should_attempt_sleep_recovery_refresh(summary: Dict[str, Any], now_ts: float) -> bool:
    """判断当前是否值得先主动刷新一次睡眠恢复状态。"""
    phase = str(summary.get("phase") or "").strip().lower()
    if phase not in {"night_awake", "sleep_later"}:
        return False

    silence_window_seconds = max(180, int(summary.get("silence_window_seconds") or 180))
    last_chat_ts = float(summary.get("last_chat_ts") or 0.0)
    last_wake_ts = float(summary.get("last_wake_ts") or 0.0)
    elapsed_since_chat = (
        max(0.0, float(now_ts) - last_chat_ts) if last_chat_ts > 0 else float("inf")
    )
    elapsed_since_wake = (
        max(0.0, float(now_ts) - last_wake_ts) if last_wake_ts > 0 else 0.0
    )
    return (
        elapsed_since_chat >= silence_window_seconds
        or elapsed_since_wake >= max(15 * 60, silence_window_seconds * 2)
    )


def build_sleep_recovery_guard(summary: Dict[str, Any], now_ts: float) -> Dict[str, Any]:
    """构建 Active Care 是否继续拦截的保护信息。"""
    phase = str(summary.get("phase") or "").strip().lower()
    if not phase:
        return {}

    sleep_debt_hours = float(summary.get("sleep_debt_hours") or 0.0)
    sleep_inertia_score = float(summary.get("sleep_inertia_score") or 0.0)
    impact_level = str(summary.get("impact_level") or "none").strip().lower()
    silence_window_seconds = max(180, int(summary.get("silence_window_seconds") or 180))
    last_wake_ts = float(summary.get("last_wake_ts") or 0.0)
    last_chat_ts = float(summary.get("last_chat_ts") or 0.0)

    elapsed_since_wake = (
        max(0.0, float(now_ts) - last_wake_ts) if last_wake_ts > 0 else 0.0
    )
    elapsed_since_chat = (
        max(0.0, float(now_ts) - last_chat_ts) if last_chat_ts > 0 else float("inf")
    )
    max_guard_seconds = _impact_recovery_window_seconds(
        impact_level=impact_level,
        sleep_inertia_score=sleep_inertia_score,
    )

    guarded = False
    if phase in {"night_awake", "sleep_later"}:
        guarded = elapsed_since_wake < max_guard_seconds or elapsed_since_chat < silence_window_seconds
    elif phase == "stay_up_late":
        guarded = (
            elapsed_since_wake < max_guard_seconds
            and (
                sleep_debt_hours >= 0.5
                or sleep_inertia_score >= 18
                or impact_level in {"mild", "medium", "severe", "high"}
            )
        )

    if not guarded:
        return {}

    return {
        "phase": phase,
        "sleep_debt_hours": sleep_debt_hours,
        "sleep_inertia_score": sleep_inertia_score,
        "impact_level": impact_level,
        "wait_seconds": silence_window_seconds,
        "elapsed_since_wake_seconds": int(elapsed_since_wake),
        "elapsed_since_chat_seconds": int(
            0 if elapsed_since_chat == float("inf") else elapsed_since_chat
        ),
    }
