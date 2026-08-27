"""回归消息对外核心接口。"""

from __future__ import annotations
from core.utils.logger import get_logger


import asyncio
import time
from typing import Any, Literal

from core.services.character_daily.activity_return.instruction import (
    _resolve_activity_verb,
    build_return_decision_hint,
    build_return_instruction,
    resolve_persona_filename,
)
from core.services.character_daily.activity_return.scheduler import (
    schedule_activity_return,
)
from core.services.character_daily.activity_return.state import (
    DEFAULT_GRACE_SECONDS,
    PendingReturn,
    _lock,
    _pending_returns,
    get_pending_return,
    resolve_pending_return,
)
from core.services.character_daily.reply_policy_support import (
    RECENT_ACTIVITY_GRACE_SECONDS,
    is_user_recently_active,
)

logger = get_logger(__name__)

# 用户在等待期内回复时延长的窗口时间
_RETURN_REPLY_GRACE_EXTEND_SECONDS = 120.0

# work 回归消息发送前的 LLM 决策超时（秒）
_RETURN_DECISION_TIMEOUT_SECONDS = 8.0


async def send_activity_return_message(
    *,
    conversation_id: str,
    role_id: str,
    activity: str,
    return_type: Literal["work", "sleep"],
    source: str = "",
    sys_prompt_type: str = "activity_return_proactive",
    user_input_mock: str = "[ACTIVITY_RETURN]",
    thought: str = "",
) -> dict[str, Any]:
    """发送活动回归消息。

    Args:
        conversation_id: 目标会话 ID
        role_id: 角色 ID
        activity: 要回归的活动
        return_type: work 或 sleep
        source: 触发来源，用于日志
        sys_prompt_type: active_care prompt 类型
        user_input_mock: 模拟用户输入占位
        thought: 给 executor 的 thought

    Returns:
        {"delivered": bool, "content": str, "decision": str, ...}
    """
    conversation_id = str(conversation_id or "").strip()
    role_id = str(role_id or "").strip().lower()
    activity = str(activity or "").strip()

    result: dict[str, Any] = {
        "delivered": False,
        "content": "",
        "decision": "unknown",
        "conversation_id": conversation_id,
        "role_id": role_id,
        "return_type": return_type,
    }

    if not role_id:
        logger.warning("send_activity_return_message: role_id 为空，跳过")
        return result

    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if not ac or not getattr(ac, "executor", None):
            logger.warning(
                "Active Care 未就绪，跳过 %s 的回归消息 (conversation=%s)",
                role_id, conversation_id,
            )
            return result

        persona_filename = resolve_persona_filename(role_id)
        if not persona_filename:
            # 未知角色无 persona 映射，跳过发送，避免误挂到 aveline 名义。
            logger.warning(
                "角色 %s 无 persona 映射，跳过回归消息发送（避免误挂到其他角色）",
                role_id,
            )
            return result

        # work 场景：发送前先让 LLM 判断用户是否还在挽留，若应顺延则延长窗口、本次不发送。
        # 这是修复"到点就发回去做事"的最后一环：决定权从"到了预定时间"交还给对话氛围。
        if return_type == "work":
            should_defer = await _decide_work_return_should_defer(
                ac, conversation_id, role_id, activity
            )
            if should_defer:
                try:
                    from core.services.character_daily.interrupt_window import (
                        extend_manual_interrupt_window,
                    )
                    extended = extend_manual_interrupt_window(
                        conversation_id=conversation_id,
                        extend_seconds=_RETURN_REPLY_GRACE_EXTEND_SECONDS,
                        max_extend_count=100,  # 被挽留顺延不受普通延长次数限制
                    )
                    if extended:
                        logger.info(
                            "角色 %s 回归消息因用户挽留顺延发送 (cid=%s, activity=%s)",
                            role_id, conversation_id, activity,
                        )
                        # 顺延后重新调度：到新窗口快结束时再触发一次决策，
                        # 若用户仍挽留则继续顺延，否则到点正常发送。
                        remaining_seconds = max(
                            0.0,
                            float(extended.get("expire_ts") or 0.0) - time.time(),
                        )
                        await schedule_activity_return(
                            conversation_id=conversation_id,
                            role_id=role_id,
                            activity=activity,
                            return_type="work",
                            window_seconds=remaining_seconds,
                            source="work_return_defer_reschedule",
                        )
                        return {
                            **result,
                            "delivered": False,
                            "reason": "user_retention_deferred",
                        }
                    logger.warning(
                        "角色 %s 回归消息判定顺延但延长窗口失败，按正常发送处理 (cid=%s)",
                        role_id, conversation_id,
                    )
                except Exception as e:
                    logger.warning(
                        "角色 %s 顺延回归消息时延长窗口异常，按正常发送处理 (cid=%s): %s",
                        role_id, conversation_id, e,
                    )
        specific_instruction = build_return_instruction(role_id, activity, return_type)

        delivered = await ac.executor.trigger_message(
            sys_prompt_type=sys_prompt_type,
            user_input_mock=user_input_mock,
            thought=thought or f"activity_return_{return_type}_{role_id}",
            specific_instruction=specific_instruction,
            persona_filename=persona_filename,
            client_type="qq",
            # 自发做事（做事归来消息）：不需要用户回复，
            # 不记录题材、不进 MDP/bandit 学习闭环
            self_activity=True,
        )

        result["delivered"] = bool(delivered)
        if delivered:
            now = time.time()
            # 标记窗口已发送结束通知（避免重复发送）
            if conversation_id and return_type == "work":
                try:
                    from core.services.character_daily.interrupt_window import (
                        mark_interrupt_window_ending_notified,
                    )
                    mark_interrupt_window_ending_notified(conversation_id)
                except Exception:
                    pass
            # 标记 pending return（空 conversation_id 时不追踪，如半夜睡回去场景）
            if conversation_id:
                with _lock:
                    _pending_returns[conversation_id] = PendingReturn(
                        conversation_id=conversation_id,
                        role_id=role_id,
                        activity=activity,
                        return_type=return_type,
                        source=str(source or "").strip(),
                        message_sent_ts=now,
                        grace_expire_ts=now + DEFAULT_GRACE_SECONDS,
                        resolved=False,
                        decision="pending",
                    )
            logger.info(
                "角色 %s 已发送%s回归消息（conversation=%s, activity=%s, source=%s），"
                "等待期 %.0fs",
                role_id,
                "睡回去" if return_type == "sleep" else "回去做事",
                conversation_id,
                activity,
                source,
                DEFAULT_GRACE_SECONDS,
            )
        else:
            logger.warning(
                "角色 %s 的%s回归消息未发送（conversation=%s）",
                role_id,
                "睡回去" if return_type == "sleep" else "回去做事",
                conversation_id,
            )

    except Exception as e:
        logger.error(
            "发送%s回归消息异常 (conversation=%s): %s",
            "睡回去" if return_type == "sleep" else "回去做事",
            conversation_id,
            e,
            exc_info=True,
        )

    return result


async def handle_user_reply_during_return(
    conversation_id: str,
    user_message: str,
) -> dict[str, Any]:
    """用户在回归消息等待期内回复时调用。

    会自动延长中断窗口，让用户和 AI 有机会根据回复内容决定继续聊还是回去。
    适用于 work 场景；sleep 场景由 sleep_manager 的 silence window 处理。

    Args:
        conversation_id: 会话 ID
        user_message: 用户消息原文

    Returns:
        {"handled": bool, "extended": bool, "hint": str}
    """
    cid = str(conversation_id or "").strip()
    result = {
        "handled": False,
        "extended": False,
        "hint": "",
    }
    if not cid:
        return result

    pending_state = get_pending_return(cid)
    if not pending_state:
        return result

    result["handled"] = True
    activity = str(pending_state.get("activity") or "").strip()
    return_type = pending_state.get("return_type") or "work"
    result["hint"] = build_return_decision_hint(activity, return_type)

    # work 场景：延长窗口并重新安排回归消息
    if return_type == "work":
        try:
            from core.services.character_daily.interrupt_window import (
                extend_manual_interrupt_window,
            )

            extended = extend_manual_interrupt_window(
                conversation_id=cid,
                extend_seconds=_RETURN_REPLY_GRACE_EXTEND_SECONDS,
                max_extend_count=100,  # 等待期内回复不受普通延长次数限制
            )
            if extended:
                # 重新调度回归消息
                role_id = str(pending_state.get("role_id") or "").strip()
                remaining_seconds = max(
                    0.0,
                    float(extended.get("expire_ts") or 0.0) - time.time(),
                )
                await schedule_activity_return(
                    conversation_id=cid,
                    role_id=role_id,
                    activity=activity,
                    return_type="work",
                    window_seconds=remaining_seconds,
                    source="return_user_reply_extend",
                )
                result["extended"] = True
                logger.info(
                    "会话 %s 用户在回归消息等待期内回复，延长窗口 %.0fs 并重新调度回归消息",
                    cid, _RETURN_REPLY_GRACE_EXTEND_SECONDS,
                )
            else:
                logger.debug("会话 %s 延长窗口失败，可能窗口已过期", cid)
        except Exception as e:
            logger.warning("会话 %s 处理回归消息回复时延长窗口失败: %s", cid, e)

    # sleep 场景：由 sleep_manager 的 silence window 自然处理，这里只注入 hint
    resolve_pending_return(cid, "stay")
    return result


async def _decide_work_return_should_defer(
    ac: Any,
    conversation_id: str,
    role_id: str,
    activity: str,
) -> bool:
    """发送"回去做事"回归消息前，让 LLM 判断是否应顺延（用户还在挽留）。

    核心修复：旧逻辑到点就强制发"回去做事"，LLM 只负责生成文案，从不决定
    "现在该不该回去"。这里在真正发送前做一次轻量 LLM 决策：
    - 依用户最近对话氛围判断是否应顺延（用户在挽留/还在热聊/还有话要说）
    - 判定应顺延 → 返回 True，调用方延长窗口、不发送
    - 判定应回去或无法判断 → 返回 False，正常发送

    任何异常/超时都回退为 False（正常发送），宁可发也不卡死流程。

    Args:
        ac: Active Care service（用于取 history 和 executor）
        conversation_id: 目标会话 ID
        role_id: 角色 ID
        activity: 要回归的活动类型字符串

    Returns:
        True 应顺延（不发送）；False 应回去（正常发送）
    """
    cid = str(conversation_id or "").strip()
    if not cid:
        return False

    # 统一逻辑：若用户最近还在活跃聊天（最近 N 秒内有消息），直接顺延，
    # 不急着回到原活动。与"被叫醒后聊完才睡回"共用"交互结束→回原状态"判定：
    # 用精确的"最近用户消息时间戳"作为"还在聊"的信号，避免 LLM 误判后"还在聊就回去"。
    if is_user_recently_active(cid, lookback_seconds=RECENT_ACTIVITY_GRACE_SECONDS):
        logger.info(
            "角色 %s 回归消息因用户仍在活跃聊天顺延 (cid=%s, activity=%s)",
            role_id, cid, activity,
        )
        return True

    activity_verb = _resolve_activity_verb(activity)

    # 1. 取最近对话历史（用户最近几条消息）
    history_lines: list[str] = []
    try:
        context = getattr(ac.executor, "context", None)
        if context is not None and hasattr(context, "get_latest_history_for_conversation"):
            history = await context.get_latest_history_for_conversation(
                cid, limit=8
            )
            for m in history or []:
                role = str(m.get("role") or "")
                content = str(m.get("content") or "")[:120]
                if role in ("user", "assistant") and content:
                    history_lines.append(f"{role}: {content}")
    except Exception as e:
        logger.warning("获取回归决策历史失败 (cid=%s): %s", cid, e)

    if not history_lines:
        # 没有历史上下文，无法判断，正常发送
        return False

    history_text = "\n".join(history_lines[-8:])

    # 2. 构造决策 prompt
    decision_prompt = (
        "你是判断 AI 伴侣是否应该回去继续做事的决策器。\n"
        f"角色 {role_id} 刚才被打断陪用户聊天，现在该项目回去继续{activity_verb}了，"
        "但发送前需要先判断用户的当前氛围。\n\n"
        "最近的对话如下（user=用户，assistant=角色）：\n"
        f"{history_text}\n\n"
        "请判断：用户最后这几条消息是否表现出不希望你走、还想继续聊的迹象？\n"
        "例如：\n"
        "- 用户在挽留/撒娇/说还有事要说/说今天不开心/分享重要事 → 应顺延（defer=true）\n"
        "- 用户只是简单回应（嗯/哈哈/好/拜拜）或已道别 → 正常回去（defer=false）\n"
        "- 用户很久没回复（最后一条是角色的消息）→ 正常回去（defer=false）\n\n"
        "只输出 JSON，格式：{\"defer\": true/false, \"reason\": \"简短原因\"}\n"
    )

    try:
        from core.llm import get_llm_module  # noqa: PLC0415
        from config.model_config import resolve_active_care_model_path  # noqa: PLC0415

        llm = get_llm_module()
        model_path = resolve_active_care_model_path(
            model_type="decision",
            settings=ac.settings if hasattr(ac, "settings") else None,
            llm_module=llm,
        )
        raw = await asyncio.wait_for(
            llm.chat(
                [{"role": "system", "content": decision_prompt}],
                max_new_tokens=100,
                temperature=0.1,
                model_path=model_path,
            ),
            timeout=_RETURN_DECISION_TIMEOUT_SECONDS,
        )
        if isinstance(raw, dict):
            if raw.get("status") == "success":
                raw = str(raw.get("response") or "")
            else:
                raw = str(raw.get("response") or raw.get("text") or "")
        else:
            raw = str(raw or "")

        # 用正则兜底解析 defer 布尔值
        text = (raw or "").strip()
        import re  # noqa: PLC0415
        m = re.search(r'"defer"\s*:\s*(true|false)', text, re.IGNORECASE)
        if m:
            defer = m.group(1).strip().lower() == "true"
            logger.info(
                "角色 %s 回归消息决策: defer=%s (cid=%s, activity=%s)",
                role_id, defer, cid, activity,
            )
            return defer
        logger.warning("回归决策未解析到 defer 字段，回退为正常发送 (raw=%s)", text[:200])
        return False
    except asyncio.TimeoutError:
        logger.warning("回归决策 LLM 超时，回退为正常发送 (cid=%s)", cid)
        return False
    except Exception as e:
        logger.warning("回归决策异常，回退为正常发送 (cid=%s): %s", cid, e)
        return False
