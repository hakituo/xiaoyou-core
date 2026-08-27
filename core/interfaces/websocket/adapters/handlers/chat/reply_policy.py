#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
被动回复策略（Reply Policy）

角色在睡觉/午睡/学习/做饭时，统一静默累积消息，不再发占位消息；
连续消息强制唤醒/打断；回复窗口期趁热打铁延续对话；DND 强制唤醒后不享受窗口期。

对外暴露 ``apply_reply_policy`` 协程：输入当前消息上下文，输出（可能被改写/注入的
content 与 service_dynamic_context），以及是否应当直接返回（静默累积）。
"""

import asyncio
import time
from typing import List, Tuple

from core.utils.logger import get_logger

logger = get_logger(__name__)


async def apply_reply_policy(
    adapter,
    *,
    conversation_id: str,
    content: str,
    persona_filename: str,
    service_dynamic_context: str = "",
    websocket=None,
    is_disconnected=None,
) -> Tuple[str, str, bool]:
    """应用被动回复策略。

    Returns:
        (content, service_dynamic_context, should_return)
    """
    from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
        append_pending_message,
        build_after_activity_done_hint,
        cancel_sleep_recovery,
        clear_pending_messages,
        get_last_reply_state,
        get_pending_activity,
        get_pending_messages,
        has_sleep_recovery_tracking,
        record_successful_reply,
        remove_pending_message,
        schedule_sleep_recovery,
    )
    try:
        from core.services.character_daily.engine import get_character_daily_engine
        from core.services.character_daily.reply_policy import (
            ReplyDecision,
            evaluate_reply_state,
        )
        from core.services.character_daily.reply_policy_support import (
            resolve_reply_scope,
        )

        cd_engine = get_character_daily_engine()
        if not cd_engine:
            return content, service_dynamic_context, False

        rp_config = cd_engine.get_reply_policy_config()
        reply_role_id = resolve_reply_scope("aveline", persona_filename)
        ws_key = adapter._get_ws_key(websocket) if websocket is not None else None

        # cleanup_expired_dnd_pending 不在这里调用：
        # force_reply_cooldown_seconds 默认仅 600s，用户睡眠 8+ 小时后醒来发消息，
        # 昨晚累积的 pending 会被误清，醒来后无法注入上下文——静默消息石沉大海。
        # cleanup 改到 try 块末尾（pending 注入处理之后）执行。
        pending_messages = get_pending_messages(conversation_id)
        consecutive_dnd_count = len(pending_messages)

        last_reply_ts, last_reply_activity = get_last_reply_state(conversation_id)
        sleep_recovery_active = has_sleep_recovery_tracking(conversation_id)
        if sleep_recovery_active:
            from core.services.life_simulation import get_life_simulation_service

            life_sim = get_life_simulation_service()
            if life_sim:
                summary = life_sim.notify_sleep_chat_activity(
                    reply_role_id,
                    str(content),
                )
                if ws_key is not None:
                    schedule_sleep_recovery(
                        cid=conversation_id,
                        ws_key=ws_key,
                        role_id=reply_role_id,
                        silence_window_seconds=int(
                            summary.get("silence_window_seconds", 180)
                        ),
                    )
            # sleep_recovery 分支原本直接构造 ReplyDecision 跳过 evaluate_reply_state，
            # 导致 /打断 创建的中断窗口 persona_hint 不会注入到 LLM 上下文。
            # 这里补充查询中断窗口，如果存在则构建 persona_hint 注入。
            sleep_recovery_hint = ""
            try:
                from core.services.character_daily.activity_model import (
                    ACTIVITY_VERBS_ONGOING,
                    ActivityType,
                )
                from core.services.character_daily.reply_policy_support import (
                    build_manual_interrupt_window_hint,
                    get_manual_interrupt_window_state,
                )

                manual_interrupt_window = get_manual_interrupt_window_state(
                    reply_role_id,
                    conversation_id,
                )
                if manual_interrupt_window:
                    remaining_seconds = max(
                        0.0,
                        float(manual_interrupt_window.get("expire_ts") or 0.0)
                        - time.time(),
                    )
                    interrupted_activity_str = str(
                        manual_interrupt_window.get("activity") or ""
                    ).strip()
                    interrupted_activity = ActivityType.from_str(
                        interrupted_activity_str
                    )
                    skip_activity = bool(manual_interrupt_window.get("skip_activity"))
                    if skip_activity:
                        interrupted_activity_verb = ACTIVITY_VERBS_ONGOING.get(
                            interrupted_activity, "做事"
                        )
                        sleep_recovery_hint = (
                            f"用户决定跳过你今天的「{interrupted_activity_verb}」任务，"
                            "专心陪用户聊天。继续自然地聊天就好。"
                            "你今天已经不打算做这个任务了。"
                        )
                    else:
                        sleep_recovery_hint = build_manual_interrupt_window_hint(
                            interrupted_activity, remaining_seconds
                        )
                    logger.info(
                        f"[ReplyPolicy] cid={conversation_id} sleep_recovery 期间"
                        f"命中手动中断窗口(interrupted={interrupted_activity.value}, "
                        f"remaining={remaining_seconds:.1f}s, skip={skip_activity})，"
                        "注入 persona_hint"
                    )
            except Exception as e:
                logger.debug(
                    f"[ReplyPolicy] sleep_recovery 期间查询中断窗口失败: {e}"
                )

            reply_decision = ReplyDecision(
                should_reply=True,
                activity="idle",
                reason="sleep_recovery_active",
                persona_hint=sleep_recovery_hint,
            )
        else:
            reply_decision = await evaluate_reply_state(
                reply_role_id,
                rp_config,
                consecutive_dnd_count=consecutive_dnd_count,
                accumulated_messages=pending_messages,
                last_reply_ts=last_reply_ts,
                last_reply_activity=last_reply_activity,
                persona_filename=persona_filename,
                conversation_id=conversation_id,
            )

        # 如果用户在回归消息等待期内回复，延长窗口并给 LLM 注入决策提示
        try:
            from core.services.character_daily.reply_policy_support import (
                extend_window_on_return_reply,
            )

            await extend_window_on_return_reply(conversation_id, str(content))
        except Exception as e:
            logger.debug(f"[ReplyPolicy] 处理回归消息回复失败: {e}")

        if reply_decision.delay_seconds > 0:
            logger.info(
                f"[ReplyPolicy] cid={conversation_id} 延迟 {reply_decision.delay_seconds:.1f}s "
                f"(activity={reply_decision.activity}, reason={reply_decision.reason})"
            )
            try:
                await asyncio.sleep(reply_decision.delay_seconds)
            except asyncio.CancelledError:
                if reply_decision.should_reply:
                    append_pending_message(
                        conversation_id,
                        str(content),
                        reply_decision.activity,
                        reply_role_id,
                    )
                    logger.info(
                        f"[ReplyPolicy] cid={conversation_id} 延迟期间被取消，"
                        f"已转存到 pending_messages 等待重连补发"
                        f"（activity={reply_decision.activity}）"
                    )
                raise

            if websocket is not None and is_disconnected is not None and is_disconnected(websocket):
                if reply_decision.should_reply:
                    append_pending_message(
                        conversation_id,
                        str(content),
                        reply_decision.activity,
                        reply_role_id,
                    )
                    logger.info(
                        f"[ReplyPolicy] cid={conversation_id} 延迟结束后发现连接已断开，"
                        f"已转存到 pending_messages 等待重连补发"
                        f"（activity={reply_decision.activity}）"
                    )
                return content, service_dynamic_context, True

        if not reply_decision.should_reply:
            append_pending_message(
                conversation_id,
                str(content),
                reply_decision.activity,
                reply_role_id,
            )
            logger.info(
                f"[ReplyPolicy] cid={conversation_id} 静默累积"
                f"（activity={reply_decision.activity}, reason={reply_decision.reason}）"
            )
            return content, service_dynamic_context, True

        record_successful_reply(conversation_id, reply_decision.activity)

        # 当前这条已决定回复的用户消息，若此前曾被静默累积进 pending，
        # 需要从待活动结束后统一处理的队列里移除，避免二次注入主程序造成重复回复。
        remove_pending_message(conversation_id, str(content))

        _accumulated_to_inject: List[str] = []

        if reply_decision.accumulated_messages:
            logger.info(
                f"[ReplyPolicy] cid={conversation_id} 强制唤醒/打断，附带 "
                f"{len(reply_decision.accumulated_messages)} 条累积消息"
            )
            _accumulated_to_inject = list(reply_decision.accumulated_messages)
            clear_pending_messages(conversation_id)
            from core.services.character_daily.activity_model import (
                ActivityType,
                DO_NOT_DISTURB_ACTIVITIES,
            )
            from core.services.life_simulation import get_life_simulation_service

            activity_type = ActivityType.from_str(reply_decision.activity)
            if activity_type in DO_NOT_DISTURB_ACTIVITIES:
                life_sim = get_life_simulation_service()
                if life_sim:
                    summary = life_sim.notify_sleep_interruption(
                        reply_role_id,
                        str(content),
                        conversation_id,
                    )
                    if ws_key is not None:
                        schedule_sleep_recovery(
                            cid=conversation_id,
                            ws_key=ws_key,
                            role_id=reply_role_id,
                            silence_window_seconds=int(
                                summary.get("silence_window_seconds", 180)
                            ),
                        )
            elif has_sleep_recovery_tracking(conversation_id):
                await cancel_sleep_recovery(conversation_id)
        else:
            pending = get_pending_messages(conversation_id)
            if pending:
                _accumulated_to_inject = list(pending)
                pending_activity_str = get_pending_activity(conversation_id)
                after_hint = build_after_activity_done_hint(
                    pending_activity_str, pending
                )
                if after_hint:
                    logger.info(
                        f"[ReplyPolicy] cid={conversation_id} 活动结束后处理 "
                        f"{len(pending)} 条累积消息（activity={pending_activity_str}）"
                    )
                    if service_dynamic_context:
                        service_dynamic_context = (
                            after_hint + "\n\n" + service_dynamic_context
                        )
                    else:
                        service_dynamic_context = after_hint
                clear_pending_messages(conversation_id)

        if _accumulated_to_inject:
            messages_block = "\n".join(
                f"{i}. {msg}" for i, msg in enumerate(_accumulated_to_inject, 1)
            )
            content = (
                f"【你之前没回的消息，请逐条回应】\n{messages_block}\n\n"
                f"【用户最新消息】\n{content}"
            )
            logger.info(
                f"[ReplyPolicy] cid={conversation_id} 已将 "
                f"{len(_accumulated_to_inject)} 条累积消息拼接到用户消息中"
            )

        if reply_decision.persona_hint:
            if service_dynamic_context:
                service_dynamic_context = (
                    reply_decision.persona_hint + "\n\n" + service_dynamic_context
                )
            else:
                service_dynamic_context = reply_decision.persona_hint

        # pending 注入处理完成后，清理过期的拒回累积计数。
        # 放在末尾保证睡眠期间累积的消息先被注入处理，再清过期计数。
        # DND 状态（强制唤醒后仍未真正醒来）跳过，避免误清同会话后续累积。
        try:
            from core.services.character_daily.activity_model import (
                DO_NOT_DISTURB_ACTIVITIES,
            )

            _end_activity = cd_engine.get_current_activity(reply_role_id)
            if _end_activity not in DO_NOT_DISTURB_ACTIVITIES:
                cleanup_expired_dnd_pending(rp_config.force_reply_cooldown_seconds)
        except Exception as _cleanup_err:
            logger.debug("[ReplyPolicy] 末尾 pending 清理失败: %s", _cleanup_err)

        return content, service_dynamic_context, False

    except Exception as rp_e:
        logger.warning(f"[ReplyPolicy] 评估失败，走正常流程: {rp_e}")
        return content, service_dynamic_context, False


def cleanup_expired_dnd_pending(force_reply_cooldown_seconds: float):
    """清理过期的 DND 累积消息计数（仅在非 DND 状态末尾调用）。"""
    try:
        from core.services.character_daily.reply_policy_support import (
            cleanup_expired_dnd_pending as _impl,
        )

        _impl(force_reply_cooldown_seconds)
    except Exception as e:
        logger.debug("[ReplyPolicy] cleanup_expired_dnd_pending 失败: %s", e)
