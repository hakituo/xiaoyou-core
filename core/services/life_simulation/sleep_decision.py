"""角色睡眠决策逻辑。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from core.utils.json_utils import extract_json_object
from core.utils.time_utils import ts_to_str

from .sleep_models import SleepDecision, SleepRuntimeState


def ts_to_text(value: float) -> str:
    """将时间戳格式化为可读文本。"""
    if not value:
        return "无"
    try:
        return ts_to_str(float(value), "%m-%d %H:%M")
    except Exception:
        return "无"


def format_recent_events(state: SleepRuntimeState) -> str:
    """格式化最近睡眠事件。"""
    if not state.recent_events:
        return "- 无特殊夜间事件"
    lines = []
    for item in state.recent_events[-6:]:
        lines.append(f"- {ts_to_text(item.ts)} {item.event_type}: {item.detail}")
    return "\n".join(lines)


def normalize_decision(raw: str) -> Optional[Dict[str, Any]]:
    """归一化 LLM 输出。"""
    data = extract_json_object(raw) if raw else None
    if not isinstance(data, dict):
        return None
    decision = str(data.get("decision") or "").strip().lower()
    if decision not in {item.value for item in SleepDecision}:
        return None
    stay_up_activity = str(data.get("stay_up_activity") or "idle").strip().lower()
    if stay_up_activity not in {"idle", "reading", "phone_scrolling", "late_snack", "housework"}:
        stay_up_activity = "idle"
    sleep_after_minutes = int(data.get("sleep_after_minutes") or 0)
    if decision == SleepDecision.SLEEP_LATER.value:
        sleep_after_minutes = max(5, min(180, sleep_after_minutes or 15))
    else:
        sleep_after_minutes = 0
    return {
        "decision": decision,
        "reason": str(data.get("reason") or "").strip(),
        "stay_up_activity": stay_up_activity,
        "sleep_after_minutes": sleep_after_minutes,
    }


async def call_llm_sleep_decision(
    *,
    scheduler: Any,
    model_path: str,
    role_id: str,
    role_name: str,
    state: SleepRuntimeState,
    profile: Any,
    now: datetime,
    wake_dt: datetime,
) -> Optional[Dict[str, Any]]:
    """调用 LLM 进行睡眠恢复决策。"""
    from core.agents.chat_agent_components.persona_system.prompt.components.character_sleep_prompts import (
        CHARACTER_SLEEP_DECISION_SYSTEM_PROMPT,
        CHARACTER_SLEEP_DECISION_USER_PROMPT_TEMPLATE,
    )

    prompt = CHARACTER_SLEEP_DECISION_USER_PROMPT_TEMPLATE.format(
        role_name=role_name,
        date_label=state.date,
        current_time=now.strftime("%Y-%m-%d %H:%M"),
        is_rest_day="是" if now.weekday() >= 5 else "否",
        planned_sleep_time=state.planned_sleep_time,
        planned_wake_time=state.planned_wake_time,
        minutes_until_wakeup=max(0, int((wake_dt - now).total_seconds() / 60)),
        phase=state.phase.value,
        is_sleeping="是" if state.is_sleeping else "否",
        night_wake_count=state.night_wake_count,
        last_wake_time=ts_to_text(state.last_wake_ts),
        last_chat_time=ts_to_text(state.last_chat_ts),
        slept_hours=f"{state.current_sleep_duration_hours:.2f}",
        last_sleep_hours=f"{state.last_sleep_duration_hours:.2f}",
        sleep_debt=f"{state.sleep_debt_hours:.2f}",
        sleep_quality=f"{state.sleep_quality_score:.1f}",
        sleep_inertia=f"{state.sleep_inertia_score:.1f}",
        nightmare_level=state.nightmare_level,
        impact_level=state.impact_level,
        overslept="是" if state.overslept else "否",
        chronotype=profile.chronotype,
        sleep_inertia_tendency=f"{profile.sleep_inertia_tendency:.2f}",
        night_owl_tendency=f"{profile.night_owl_tendency:.2f}",
        late_snack_tendency=f"{profile.late_snack_tendency:.2f}",
        nap_tendency=f"{profile.nap_tendency:.2f}",
        oversleep_tendency=f"{profile.oversleep_tendency:.2f}",
        nightmare_tendency=f"{profile.nightmare_tendency:.2f}",
        wake_by_message_sensitivity=f"{profile.wake_by_message_sensitivity:.2f}",
        resume_sleep_tendency=f"{profile.resume_sleep_tendency:.2f}",
        silence_seconds=int(profile.silence_window_seconds),
        recent_events=format_recent_events(state),
    )
    raw = ""
    async for chunk in scheduler.submit_llm_task(
        [
            {"role": "system", "content": CHARACTER_SLEEP_DECISION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=260,
        temperature=0.4,
        model_path=str(model_path or "cloud:deepseek:qqbot1:deepseek-v4-flash"),
    ):
        if isinstance(chunk, str):
            raw += chunk
        elif isinstance(chunk, dict) and chunk.get("content"):
            raw += str(chunk.get("content") or "")
    return normalize_decision(raw)


def build_fallback_decision(
    *,
    state: SleepRuntimeState,
    profile: Any,
    now: datetime,
    wake_dt: datetime,
) -> Dict[str, Any]:
    """构建启发式兜底决策。"""
    minutes_until_wakeup = max(0, int((wake_dt - now).total_seconds() / 60))
    sleepy_score = (
        profile.resume_sleep_tendency * 0.45
        + min(1.0, state.sleep_debt_hours / 2.5) * 0.3
        + (0.2 if minutes_until_wakeup > 90 else 0.0)
        + (0.1 if state.nightmare_level in {"mild", "medium"} else 0.0)
    )
    awake_score = (
        profile.night_owl_tendency * 0.35
        + profile.wake_by_message_sensitivity * 0.25
        + (0.25 if minutes_until_wakeup < 45 else 0.0)
        + (0.15 if now.weekday() >= 5 else 0.0)
    )
    if sleepy_score >= awake_score:
        return {
            "decision": SleepDecision.RETURN_TO_SLEEP.value,
            "reason": "静默后困意重新占上风",
            "stay_up_activity": "idle",
            "sleep_after_minutes": 0,
        }
    if minutes_until_wakeup < 50 or profile.night_owl_tendency > 0.5:
        return {
            "decision": SleepDecision.STAY_AWAKE.value,
            "reason": "已经比较清醒，决定先不睡",
            "stay_up_activity": "phone_scrolling",
            "sleep_after_minutes": 0,
        }
    return {
        "decision": SleepDecision.SLEEP_LATER.value,
        "reason": "暂时还醒着，打算一会儿再睡",
        "stay_up_activity": "reading",
        "sleep_after_minutes": 15,
    }
