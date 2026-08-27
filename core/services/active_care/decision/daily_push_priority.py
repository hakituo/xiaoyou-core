"""每日推送优先级分析模块

从 PriorityAnalyzer 拆分而来，包含：
- build_daily_push_priority_candidates：构建每日推送优先级候选列表
- build_daily_push_priority_fallback：构建后备方案
- analyze_daily_push_priority：分析每日推送优先级（含 LLM 调用）
- persist_daily_push_priority_analysis：持久化分析结果
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from core.utils.timestamp_utils import safe_timestamp
from core.llm import get_llm_module
from core.utils.data_paths import get_role_daily_dir

logger = get_module_logger("ACTIVE_CARE_PRIORITY", "active_care_schedule.log")


def build_daily_push_priority_candidates(
    *,
    workspace_snapshot: Dict[str, Any],
    priority_focus: Dict[str, Any],
    urgent_needs: List[str],
) -> List[Dict[str, Any]]:
    """构建每日推送优先级候选列表"""
    snapshot = workspace_snapshot if isinstance(workspace_snapshot, dict) else {}
    focus = priority_focus if isinstance(priority_focus, dict) else {}
    daily_tasks = snapshot.get("daily_tasks") or {}
    task_focus = daily_tasks.get("focus") or {}

    candidates: List[Dict[str, Any]] = []
    seen_ids = set()

    def _push(item: Dict[str, Any]) -> None:
        cid = str((item or {}).get("id") or "").strip()
        if not cid or cid in seen_ids:
            return
        seen_ids.add(cid)
        candidates.append(item)

    task_probe = focus.get("task_probe") or {}
    if task_probe:
        title = str(task_probe.get("task_title") or "任务进展").strip() or "任务进展"
        reason = str(task_probe.get("reason") or "task_follow_up").strip() or "task_follow_up"
        _push(
            {
                "id": f"task:{str(task_probe.get('task_id') or title).strip()}",
                "title": f"跟进任务：{title}",
                "reason": reason,
                "suggested_intent": "curious_question",
                "base_score": 92 if reason == "overdue" else (86 if reason == "due_soon" else 80),
            }
        )

    for t in (task_focus.get("timed_overdue") or [])[:2]:
        title = str((t or {}).get("title") or "任务").strip() or "任务"
        tid = str((t or {}).get("id") or title).strip()
        _push(
            {
                "id": f"task:{tid}",
                "title": f"跟进任务：{title}",
                "reason": "overdue",
                "suggested_intent": "curious_question",
                "base_score": 95,
            }
        )

    for t in (task_focus.get("timed_due_soon") or [])[:2]:
        title = str((t or {}).get("title") or "任务").strip() or "任务"
        tid = str((t or {}).get("id") or title).strip()
        _push(
            {
                "id": f"task:{tid}",
                "title": f"临近任务：{title}",
                "reason": "due_soon",
                "suggested_intent": "curious_question",
                "base_score": 88,
            }
        )

    # ── 学习系统推送候选（来自 TutorEngine）──
    try:
        from core.services.study.tutor_engine import get_tutor_engine
        _te = get_tutor_engine()
        _briefing = _te.generate_daily_briefing()

        # 间隔复习到期提醒
        _reviews = _briefing.get("review_reminders") or []
        if _reviews:
            _n = len(_reviews)
            _score = min(90, 78 + _n * 2)
            _topics_text = "、".join(
                f"{r.get('subject', '')}·{r.get('topic', '')}"
                for r in _reviews[:3]
            )
            _push(
                {
                    "id": "study:review_due",
                    "title": f"学习复习提醒：{_n}个知识点到期",
                    "reason": "review_due",
                    "suggested_intent": "planned_topic",
                    "base_score": _score,
                    "_study_detail": _topics_text,
                }
            )

        # streak 守护（昨天没学 + streak > 0 → 提醒今天别断）
        _streak = _briefing.get("streak_info") or {}
        _yday = _briefing.get("yesterday_review") or {}
        _cs = _streak.get("current_streak", 0)
        if _cs >= 2 and not _yday.get("studied", False):
            _push(
                {
                    "id": "study:streak_nudge",
                    "title": f"streak守护：已连续{_cs}天，今天别断",
                    "reason": "streak_at_risk",
                    "suggested_intent": "planned_topic",
                    "base_score": 76,
                }
            )
    except Exception:
        pass

    # ── 今日学习生活计划推送候选（来自 JournalService.DailyPlan）──
    # 让计划项能影响 Active Care 的主动推送决策：
    # - 高优先级（high）的计划项得到更高 base_score
    # - 接近计划时间的项加分（30 分钟内）
    # - 已完成/跳过的项不参与候选
    # 注意：本函数是同步函数，直接同步读 plan.json 避免 asyncio 事件循环问题
    try:
        import json as _json
        from core.utils.data_paths import get_user_data_dir as _get_user_data_dir
        from core.utils.time_utils import get_current_time as _get_current_time
        from core.services.journal.models import DailyPlan as _DailyPlan

        _now = _get_current_time()
        _plan_path = (
            _get_user_data_dir() / "daily"
            / _now.strftime("%Y") / _now.strftime("%m") / _now.strftime("%d")
            / "plan.json"
        )
        if _plan_path.exists():
            _plan_data = _json.loads(_plan_path.read_text(encoding="utf-8"))
            _plan = _DailyPlan.model_validate(_plan_data)
            _now_ts = _now.timestamp()
            for _pi in _plan.items:
                # 跳过已完成/跳过的项
                if _pi.status in {"completed", "skipped"}:
                    continue
                # 按优先级映射 base_score
                _priority_score = {"high": 85, "normal": 75, "low": 65}.get(_pi.priority, 75)
                # 接近计划时间的项加分（30 分钟内 +10，1 小时内 +5）
                _time_bonus = 0
                if _pi.time:
                    try:
                        _h, _m = _pi.time.split(":")
                        _plan_ts = _now.replace(
                            hour=int(_h), minute=int(_m), second=0, microsecond=0
                        ).timestamp()
                        _diff = abs(_now_ts - _plan_ts)
                        if _diff <= 1800:
                            _time_bonus = 10
                        elif _diff <= 3600:
                            _time_bonus = 5
                    except Exception:
                        pass
                _final_score = min(95, _priority_score + _time_bonus)
                _subject_suffix = f"（{_pi.subject}）" if _pi.subject else ""
                _time_prefix = f"[{_pi.time}] " if _pi.time else ""
                _push(
                    {
                        "id": f"plan:{_pi.id}",
                        "title": f"计划项：{_time_prefix}{_pi.title}{_subject_suffix}",
                        "reason": "plan_item",
                        "suggested_intent": "planned_topic",
                        "base_score": _final_score,
                    }
                )
    except Exception:
        pass

    for item in (focus.get("portrait_priority") or [])[:3]:
        p = str(item or "").strip()
        if not p:
            continue
        cn_map = {
            "wakeup": "起床",
            "sleep": "睡眠",
            "meal": "饮食",
            "activity": "活动",
            "study": "学习",
            "mood": "心情",
            "health": "健康",
        }
        _push(
            {
                "id": f"portrait:{p}",
                "title": f"补齐画像：{cn_map.get(p, p)}",
                "reason": "portrait_missing",
                "suggested_intent": "user_health_reminder",
                "base_score": 70,
            }
        )

    for need in (urgent_needs or [])[:2]:
        need_text = str(need or "").strip()
        if not need_text:
            continue
        intent = "bio_complaint" if need_text in {"tired", "sick", "low_battery"} else "share_thought"
        _push(
            {
                "id": f"urgent:{need_text}",
                "title": f"突发状态：{need_text}",
                "reason": "urgent",
                "suggested_intent": intent,
                "base_score": 84,
            }
        )

    if not candidates:
        _push(
            {
                "id": "general:companion",
                "title": "轻量陪伴",
                "reason": "fallback",
                "suggested_intent": "share_thought",
                "base_score": 60,
            }
        )

    # 双角色互聊话题：今天和室友聊了有趣的事，可以分享给主人
    recent_peer_chat_topics = focus.get("recent_peer_chat_topics") or []
    if recent_peer_chat_topics:
        first_topic = str(recent_peer_chat_topics[0]).strip()
        _push(
            {
                "id": "peer_chat:share",
                "title": f"和室友聊了：{first_topic[:30]}",
                "reason": "peer_chat_share",
                "suggested_intent": "share_peer_chat",
                "base_score": 75,
            }
        )

    return candidates[:6]


def build_daily_push_priority_fallback(
    *,
    candidates: List[Dict[str, Any]],
    now: float,
    latest_user_signal_ts: float,
) -> Dict[str, Any]:
    """构建每日推送优先级的后备方案"""
    sorted_items = sorted(
        candidates,
        key=lambda x: float((x or {}).get("base_score") or 0.0),
        reverse=True,
    )
    ranked = []
    for idx, item in enumerate(sorted_items[:5], start=1):
        ranked.append(
            {
                "priority": idx,
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "reason": str(item.get("reason") or "fallback"),
                "suggested_intent": str(item.get("suggested_intent") or "share_thought"),
                "score": int(max(0, min(100, float(item.get("base_score") or 0.0)))),
            }
        )
    summary = "基于任务紧迫度、画像缺口和突发状态的启发式排序"
    return {
        "analysis_ts": float(now),
        "latest_user_signal_ts": float(latest_user_signal_ts),
        "summary": summary,
        "ranked": ranked,
        "raw_text": "",
        "source": "fallback",
    }


async def analyze_daily_push_priority(
    *,
    now: float,
    now_dt,
    latest_user_signal_ts: float,
    workspace_snapshot: Dict[str, Any],
    priority_focus: Dict[str, Any],
    urgent_needs: List[str],
    state_data: Dict[str, Any],
    recent_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """分析每日推送优先级

    Args:
        now: 当前时间戳
        now_dt: 当前datetime对象
        latest_user_signal_ts: 最新用户信号时间戳
        workspace_snapshot: 工作区快照
        priority_focus: 优先级焦点
        urgent_needs: 紧急需求列表
        state_data: 状态数据
        recent_history: 最近历史记录

    Returns:
        {
            "enabled": bool,
            "skip_reason": str,
            "analysis": dict,
        }
    """
    from core.services.active_care.decision.decision_output_parser import _extract_json_block

    analysis_interval_seconds = 3600
    if latest_user_signal_ts <= 0 or (now - latest_user_signal_ts) > analysis_interval_seconds:
        return {
            "enabled": False,
            "skip_reason": "no_recent_user_reply_within_1h",
            "analysis": {},
        }

    # 使用统一 safe_timestamp 工具函数
    last_analysis_ts = safe_timestamp(state_data.get("daily_push_priority_analysis_ts"))

    same_day = (
        str(state_data.get("daily_push_priority_date") or "")
        == now_dt.strftime("%Y-%m-%d")
    )
    cached_ranked = state_data.get("daily_push_priority_ranked") or []
    cache_valid = (
        same_day
        and last_analysis_ts > 0
        and (now - last_analysis_ts) < analysis_interval_seconds
        and isinstance(cached_ranked, list)
        and cached_ranked
    )
    if cache_valid:
        cached_reduced_mode = state_data.get("daily_push_priority_reduced_mode")
        current_reduced_mode = bool(state_data.get("reduced_mode_active"))
        if cached_reduced_mode is not None and cached_reduced_mode != current_reduced_mode:
            cache_valid = False
    if cache_valid:
        return {
            "enabled": True,
            "skip_reason": "within_hour_use_cache",
            "analysis": {
                "analysis_ts": last_analysis_ts,
                "latest_user_signal_ts": latest_user_signal_ts,
                "summary": str(state_data.get("daily_push_priority_summary") or ""),
                "ranked": cached_ranked,
                "raw_text": str(state_data.get("daily_push_priority_raw_text") or ""),
                "source": "cache",
            },
        }

    candidates = build_daily_push_priority_candidates(
        workspace_snapshot=workspace_snapshot,
        priority_focus=priority_focus,
        urgent_needs=urgent_needs,
    )
    fallback = build_daily_push_priority_fallback(
        candidates=candidates,
        now=now,
        latest_user_signal_ts=latest_user_signal_ts,
    )

    llm = get_llm_module()
    # 从 model_config.json 读取优先级分析专用模型
    priority_model_path = None
    try:
        from config.model_config import get_priority_analysis_model
        priority_model_path = get_priority_analysis_model()
    except Exception:
        pass

    # 构建最近聊天摘要供 LLM 参考
    recent_chat_summary = []
    if recent_history:
        for m in recent_history[-8:]:
            role = str(m.get("role") or "unknown").strip()
            content = str(m.get("content") or "").strip()[:120]
            if content:
                recent_chat_summary.append(f"{role}: {content}")

    prompt_payload = {
        "now": now_dt.isoformat(),
        "latest_user_signal_age_seconds": int(max(0.0, now - latest_user_signal_ts)),
        "priority_focus": priority_focus,
        "urgent_needs": urgent_needs,
        "portrait_completeness": (workspace_snapshot.get("portrait_completeness") or {}),
        "daily_tasks_focus": ((workspace_snapshot.get("daily_tasks") or {}).get("focus") or {}),
        "candidates": candidates,
        "recent_chat": recent_chat_summary,
        "covered_topics": priority_focus.get("covered_topics") or [],
    }
    from core.agents.chat_agent_components.persona_system.prompt.components import PRIORITY_ANALYSIS_SYSTEM_PROMPT
    system_prompt = PRIORITY_ANALYSIS_SYSTEM_PROMPT
    user_prompt = (
        "请根据以下上下文生成今日推送优先级：\n"
        + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        + "\n输出格式："
        + json.dumps(
            {
                "summary": "一句话说明排序依据",
                "priorities": [
                    {
                        "priority": 1,
                        "id": "候选ID",
                        "title": "优先事项标题",
                        "reason": "为什么现在该优先",
                        "suggested_intent": "curious_question",
                        "score": 90,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    raw_text = ""
    parsed: Dict[str, Any] = {}
    # 双QQ模式下 _PER_PERSONA_TIMEOUT=60s，单次 LLM 超时必须远小于 60s
    # 否则会耗尽整个 persona 的决策预算导致超时跳过（参考 proactive_checker.py:330）
    # 单次 15s + 失败立即回退 fallback，最坏 15s，为后续 select_action/decide 留足预算
    max_retries = 1
    for attempt in range(max_retries):
        try:
            raw_text = await asyncio.wait_for(
                llm.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.25,
                    max_new_tokens=420,
                    model_path=priority_model_path or None,
                ),
                timeout=15.0,
            )
            if isinstance(raw_text, dict):
                # 优先检查 response 字段（LLM 模块可能返回 status=None 但有 response）
                response_text = raw_text.get("response")
                if response_text:
                    raw_text = str(response_text)
                elif raw_text.get("status") == "success":
                    raw_text = str(raw_text.get("response") or "")
                else:
                    logger.warning(f"Active Care: priority LLM 返回非 success 状态: status={raw_text.get('status')}, error={raw_text.get('error')}")
                    raw_text = ""
            text = _extract_json_block(str(raw_text or ""))
            parsed = json.loads(text) if text else {}
            if parsed:
                break  # 成功，退出重试循环
            logger.warning(f"Active Care: priority LLM 返回空结果 (attempt {attempt + 1}/{max_retries}), raw_text={str(raw_text)[:200]}")
        except asyncio.TimeoutError:
            logger.warning(f"Active Care: priority LLM 超时 (attempt {attempt + 1}/{max_retries}, 15s)")
            if attempt < max_retries - 1:
                continue  # 重试
        except Exception as e:
            logger.warning(f"Active Care: priority LLM 异常 (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                continue  # 重试
    else:
        # 所有重试都失败
        logger.warning(f"Active Care: daily push priority LLM analysis failed after all retries, fallback used. raw_text={str(raw_text)[:200]}")
        return {"enabled": True, "skip_reason": "llm_fallback", "analysis": fallback}

    candidate_map = {str(item.get("id") or ""): item for item in candidates}
    priorities = parsed.get("priorities") if isinstance(parsed, dict) else None
    ranked: List[Dict[str, Any]] = []
    if isinstance(priorities, list):
        for item in priorities:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            base = candidate_map.get(cid)
            if not base:
                continue
            suggested_intent = str(item.get("suggested_intent") or base.get("suggested_intent") or "share_thought").strip()
            if suggested_intent not in {
                "curious_question",
                "share_thought",
                "emotional_support",
                "user_health_reminder",
                "bio_complaint",
                "share_peer_chat",
            }:
                suggested_intent = str(base.get("suggested_intent") or "share_thought")
            try:
                score = int(float(item.get("score") or base.get("base_score") or 0))
            except Exception:
                score = int(float(base.get("base_score") or 0))
            ranked.append(
                {
                    "priority": len(ranked) + 1,
                    "id": cid,
                    "title": str(item.get("title") or base.get("title") or "").strip(),
                    "reason": str(item.get("reason") or base.get("reason") or "").strip(),
                    "suggested_intent": suggested_intent,
                    "score": max(0, min(100, score)),
                }
            )

    if not ranked:
        return {"enabled": True, "skip_reason": "empty_rank_fallback", "analysis": fallback}

    analysis = {
        "analysis_ts": float(now),
        "latest_user_signal_ts": float(latest_user_signal_ts),
        "summary": str(parsed.get("summary") or "").strip() or fallback.get("summary"),
        "ranked": ranked[:5],
        "raw_text": str(raw_text or ""),
        "source": "llm",
    }
    return {
        "enabled": True,
        "skip_reason": "",
        "analysis": analysis,
    }


async def persist_daily_push_priority_analysis(
    *,
    now_dt,
    analysis: Dict[str, Any],
    workspace_snapshot: Dict[str, Any],
    priority_focus: Dict[str, Any],
    runtime_scope: str,
) -> None:
    """持久化每日推送优先级分析结果"""
    if not isinstance(analysis, dict) or not analysis.get("ranked"):
        return

    role_daily_dir = get_role_daily_dir(runtime_scope)
    events_dir = (
        role_daily_dir
        / now_dt.strftime("%Y")
        / now_dt.strftime("%m")
        / now_dt.strftime("%d")
        / "events"
    )
    raw_file = events_dir / "active_care_daily_push_priority_raw.jsonl"
    ranked_file = events_dir / "active_care_daily_push_priority_ranked.json"

    raw_payload = {
        "timestamp": float(analysis.get("analysis_ts") or now_dt.timestamp()),
        "time": now_dt.strftime("%H:%M:%S"),
        "summary": str(analysis.get("summary") or ""),
        "source": str(analysis.get("source") or "unknown"),
        "latest_user_signal_ts": float(analysis.get("latest_user_signal_ts") or 0.0),
        "priority_focus": priority_focus,
        "workspace_digest": {
            "daily_tasks_focus": ((workspace_snapshot.get("daily_tasks") or {}).get("focus") or {}),
            "portrait_completeness": (workspace_snapshot.get("portrait_completeness") or {}),
        },
        "ranked": analysis.get("ranked") or [],
        "raw_text": str(analysis.get("raw_text") or ""),
    }
    ranked_payload = {
        "date": now_dt.strftime("%Y-%m-%d"),
        "updated_at": now_dt.isoformat(),
        "summary": str(analysis.get("summary") or ""),
        "ranked": analysis.get("ranked") or [],
    }

    def _write_files() -> None:
        events_dir.mkdir(parents=True, exist_ok=True)
        with open(raw_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(raw_payload, ensure_ascii=False) + "\n")
        with open(ranked_file, "w", encoding="utf-8") as f:
            json.dump(ranked_payload, f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write_files)
