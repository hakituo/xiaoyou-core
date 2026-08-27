"""
上下文采集模块
负责拉取和清洗主动关怀决策所需的各类上下文数据，包括工作区快照、历史记录、
用户信号与意图、生命/情绪状态、紧急需求、设备上下文等。
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_module_logger
from core.utils.timestamp_utils import safe_timestamp
from config.debug_config import is_debug_enabled
from core.services.life_simulation.service import get_life_simulation_service
from core.emotion import get_emotion_manager

logger = get_module_logger("ACTIVE_CARE_DECISION", "active_care_schedule.log")


async def get_workspace_snapshot(now_dt) -> Dict[str, Any]:
    """获取工作区快照"""
    workspace_snapshot = {}
    try:
        from core.services.workspace.service import get_workspace_service

        ws = get_workspace_service()
        workspace_snapshot = await asyncio.wait_for(
            ws.get_daily_workspace_snapshot(
                date=now_dt.strftime("%Y-%m-%d"), diary_limit=8
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Active Care: get_daily_workspace_snapshot timed out (>6s), using empty snapshot."
        )
    except Exception as e:
        logger.warning(f"Active Care: Failed to get workspace snapshot: {e}")
    return workspace_snapshot


async def get_recent_history(
    workspace_snapshot: Dict[str, Any], cached_history: list = None, context=None
) -> List[Dict[str, Any]]:
    """
    获取最近的历史记录

    Args:
        workspace_snapshot: 工作区快照，用于回退
        cached_history: 已缓存的历史记录，若为 None 则从 context 拉取
        context: 上下文服务实例，用于拉取历史记录
    """
    history_msgs = cached_history
    if history_msgs is None:
        try:
            history_msgs = await asyncio.wait_for(
                context.get_latest_history(limit=8), timeout=3.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Active Care: get_latest_history(limit=8) timed out (>3s), fallback to diary snapshot."
            )
        except Exception:
            history_msgs = []

    recent_history = []
    for m in (history_msgs or []):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ["user", "assistant"]:
            continue
        c = str(m.get("content", ""))
        if len(c) > 120:
            c = c[:120] + "..."
        recent_history.append({"role": role, "content": c})

    if not recent_history:
        snapshot_diary = ((workspace_snapshot.get("diary") or {}).get("recent_entries") or [])
        for item in snapshot_diary[-8:]:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if len(content) > 120:
                content = content[:120] + "..."
            recent_history.append({"role": "assistant", "content": content})

    return recent_history


async def get_user_signal_and_intent(
    cached_history: list = None,
    primary_cid: str = None,
    persona_filename: str = "",
    context=None,
    intent_detector=None,
) -> Tuple[str, float, bool, bool, bool, str]:
    """
    获取用户信号与意图

    Args:
        cached_history: 已缓存的历史记录
        primary_cid: 主会话 ID
        persona_filename: 人设文件名
        context: 上下文服务实例
        intent_detector: 意图检测器实例
    """
    inferred_goodnight = False
    inferred_goodmorning = False
    inferred_sleep_hint = False
    inferred_user_msg = {}

    if primary_cid is None:
        try:
            primary_cid = await context.resolve_primary_conversation_id()
        except Exception:
            primary_cid = "default"

    if cached_history is not None:
        inferred_user_msg = intent_detector.extract_latest_user_signal(
            cached_history
        )
    else:
        try:
            primary_history = await context.get_latest_history_for_conversation(
                primary_cid, limit=20
            )
            inferred_user_msg = intent_detector.extract_latest_user_signal(
                primary_history
            )
        except Exception:
            history_for_signal = await context.get_latest_history(limit=20, persona_filename=persona_filename)
            inferred_user_msg = intent_detector.extract_latest_user_signal(
                history_for_signal
            )

    inferred_text = str(inferred_user_msg.get("content") or "").strip()
    inferred_ts = safe_timestamp(inferred_user_msg.get("timestamp"))

    # 用 _recent_user_message_cache 补全尚未落盘的最新用户消息
    # 解决：用户消息要等 LLM 生成完回复后才保存到历史，导致 Active Care 看不到最新消息
    try:
        cached = context.get_recent_user_message(primary_cid)
        cached_content = str(cached.get("content") or "").strip()
        cached_ts = safe_timestamp(cached.get("timestamp"))
        if cached_content and cached_ts > 0:
            from core.services.active_care.shared.constants import normalize_content
            normalized_cached = normalize_content(cached_content)
            normalized_inferred = normalize_content(inferred_text)
            if normalized_cached != normalized_inferred and cached_ts > inferred_ts:
                inferred_text = cached_content
                inferred_ts = cached_ts
                if is_debug_enabled("active_care_decision"):
                    logger.info(
                        "Active Care: get_user_signal_and_intent 使用缓存消息 (缓存ts=%.0f, 历史ts=%.0f)",
                        cached_ts, safe_timestamp(inferred_user_msg.get("timestamp"))
                    )
    except Exception as cache_e:
        if is_debug_enabled("active_care_decision"):
            logger.info(f"Active Care: get_user_signal_and_intent 检查缓存失败: {cache_e}")

    if inferred_text:
        inferred_goodnight = intent_detector.contains_goodnight_intent(inferred_text)
        inferred_goodmorning = intent_detector.contains_goodmorning_intent(inferred_text)
        inferred_sleep_hint = intent_detector.contains_sleep_hint(inferred_text)

    return inferred_text, inferred_ts, inferred_goodnight, inferred_goodmorning, inferred_sleep_hint, primary_cid


def _parse_sleep_duration_from_daily_record() -> Optional[float]:
    """从 daily_record 的 sleep_cycle.duration 解析睡眠小时数。

    支持格式: "10h2m", "8h", "45m" 等。解析失败返回 None。
    """
    try:
        import re as _re
        from core.services.daily.manager import get_daily_manager
        daily_mgr = get_daily_manager()
        record = daily_mgr.get_record()
        duration_str = (record.get("sleep_cycle") or {}).get("duration") or ""
        h_match = _re.search(r"(\d+)h", duration_str)
        m_match = _re.search(r"(\d+)m", duration_str)
        if h_match:
            hours = float(h_match.group(1))
            if m_match:
                hours += float(m_match.group(1)) / 60.0
            return hours
        if m_match:
            return float(m_match.group(1)) / 60.0
    except Exception:
        pass
    return None


def get_life_and_emotion_state() -> Tuple[Dict, Dict, Dict, Dict]:
    """
    获取生命状态和情绪状态

    Returns:
        (life_stats, immune_stats, user_bio_state, emo_payload)
    """
    sim_service = get_life_simulation_service()
    state = sim_service.get_state()
    life_stats = state.get("life", {})
    immune_stats = state.get("immune", {})

    user_bio_state = None
    try:
        from core.services.user_physiology.service import (
            get_user_physiology_service,
        )
        user_bio_state = get_user_physiology_service().get_latest("default_user")
    except Exception:
        user_bio_state = None

    # 优先从 daily_record 获取睡眠小时数，覆盖 user_physiology 中可能过时的数据
    daily_sleep_h = _parse_sleep_duration_from_daily_record()
    if daily_sleep_h is not None:
        if user_bio_state is not None and isinstance(user_bio_state, dict):
            metrics = user_bio_state.get("metrics")
            if isinstance(metrics, dict):
                metrics["sleep_hours_last_night"] = daily_sleep_h
                metrics["sleep_source"] = "daily_record"
            else:
                user_bio_state["metrics"] = {
                    "sleep_hours_last_night": daily_sleep_h,
                    "sleep_source": "daily_record",
                }
            user_bio_state["source"] = "daily_record+physiology"
        else:
            # user_physiology 无数据，从 daily_record 构造基本 user_bio_state
            import time as _time
            user_bio_state = {
                "user_id": "default_user",
                "updated_at": _time.time(),
                "measured_at": _time.time(),
                "source": "daily_record",
                "metrics": {
                    "sleep_hours_last_night": daily_sleep_h,
                    "sleep_source": "daily_record",
                },
                "flags": {"urgent_needs": []},
            }

    emotion_mgr = get_emotion_manager()
    emo_payload = emotion_mgr.get_effective_payload("default_user")

    return life_stats, immune_stats, user_bio_state, emo_payload


def _parse_device_context_ts(device_context: Dict, now: float) -> float:
    """解析设备上下文时间戳，消除 build_urgent_needs 和 sanitize_device_context 中的重复逻辑"""
    ctx_ts_raw = device_context.get("timestamp")
    try:
        if ctx_ts_raw:
            return float(ctx_ts_raw)
    except (ValueError, TypeError):
        pass
    return 0.0


def build_urgent_needs(
    life_stats: Dict,
    immune_stats: Dict,
    device_context: Dict,
    now: float
) -> List[str]:
    """构建紧急需求列表"""
    aveline_hunger = float(life_stats.get("hunger", 100))
    aveline_energy = float(life_stats.get("energy", 100))
    aveline_is_sick = bool(immune_stats.get("is_sick", False))

    urgent_needs = []
    if aveline_hunger < 20:
        urgent_needs.append("hungry")
    if aveline_energy < 15:
        urgent_needs.append("tired")
    if aveline_is_sick:
        urgent_needs.append("sick")

    battery_level = device_context.get("battery_level")
    is_charging = device_context.get("is_charging")

    ctx_ts_val = _parse_device_context_ts(device_context, now)
    is_context_fresh = (now - ctx_ts_val) < 3600

    if (
        is_context_fresh
        and battery_level is not None
        and battery_level < 0.20
        and not is_charging
    ):
        urgent_needs.append("low_battery")

    return urgent_needs


def sanitize_device_context(
    device_context: Dict,
    now: float
) -> Dict:
    """清理设备上下文，移除过期数据"""
    ctx_ts_val = _parse_device_context_ts(device_context, now)
    is_context_fresh = (now - ctx_ts_val) < 3600

    safe_device_context = device_context
    if not is_context_fresh and device_context:
        safe_device_context = device_context.copy()
        safe_device_context.pop("battery_level", None)
        safe_device_context.pop("is_charging", None)
        safe_device_context.pop("is_sleeping", None)
        safe_device_context["note"] = "Data is stale (older than 1h)"

    return safe_device_context
