"""
主动关怀检查器 - 动作流程

负责决策流程的最终动作执行，包括：
- 构建优先级上下文、选择动作、执行最终决策
- 根据决策结果执行发送或跳过

依赖通过构造函数注入 checker 实例，方法内通过 checker.xxx 访问原 self 属性，
参考 SleepSessionManager 的依赖注入模式。
"""
import asyncio
import time
from typing import Dict

from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled
from core.services.active_care.shared.constants import (
    MIN_QUIET_EVEN_INCOMPLETE_SECONDS,
    MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP,
)
from core.services.active_care.decision.decision_context import DecisionFlowContext

logger = get_module_logger("ACTIVE_CARE_CHECKER", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")

# 提醒类 intent 集合（这些 intent 需要走跨 persona 分工协调）
_REMINDER_INTENTS = frozenset({"planned_topic", "user_health_reminder"})


def _resolve_persona_from_filename(persona_filename: str) -> str:
    """从 persona_filename 解析 persona 标识（aveline / ling）"""
    fn = str(persona_filename or "").strip().lower()
    if "ling" in fn:
        return "ling"
    return "aveline"


def _get_reminder_id_for_intent(priority_analysis: Dict, intent: str) -> tuple:
    """从 priority_analysis 的 ranked 列表中找到匹配 intent 的候选 id 和 title

    Returns:
        (reminder_id, title) 元组，未找到返回 ("", "")
    """
    if not isinstance(priority_analysis, dict):
        return ("", "")
    ranked = priority_analysis.get("ranked") or []
    if not isinstance(ranked, list):
        return ("", "")
    for item in ranked:
        if not isinstance(item, dict):
            continue
        if str(item.get("suggested_intent") or "") == intent:
            rid = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if rid:
                return (rid, title)
    return ("", "")


class CheckerActionFlow:
    """主动关怀检查器 - 动作流程

    封装决策流程的最终动作执行逻辑，由 ProactiveChecker 委托调用。
    方法签名与原 ProactiveChecker 中对应方法保持一致（去掉 _ 前缀变公开方法）。
    """

    def __init__(self, checker):
        """
        Args:
            checker: ProactiveChecker 实例，用于访问 executor/decision/_decision_executor 等依赖
        """
        self._checker = checker

    async def build_priority_and_select_action(self, ctx: DecisionFlowContext, persona_filename: str = ""):
        """构建优先级上下文、选择动作、执行最终决策

        Args:
            persona_filename: 人设文件名，双QQ模式下按 persona 独立触发
        """
        checker = self._checker
        now = ctx.now
        now_dt = ctx.now_dt

        ctx.non_response_count = checker.executor.get_non_response_count(
            checker.executor._resolve_persona_key_from_filename(persona_filename)
        )

        device_context = {}
        # urgent_needs 可能已在 _run_decision_core 中提前构建（软门控评分需要）
        if not ctx.urgent_needs:
            ctx.urgent_needs = checker._decision_executor.build_urgent_needs(
                ctx.life_stats, ctx.immune_stats, device_context, now
            )
        ctx.safe_device_context = checker._decision_executor.sanitize_device_context(device_context, now)

        ctx.priority_focus = checker._priority_analyzer.build_priority_focus(
            ctx.workspace_snapshot, now_dt,
            recent_history=ctx.recent_history,
            elapsed_seconds=int(ctx.elapsed),
        )

        # 注入双角色互聊信息到 priority_focus
        checker._state_detector.inject_peer_chat_info(ctx.priority_focus, ctx.state_data, now)

        if ctx.priority_focus.get("must_probe"):
            signature = checker._priority_analyzer.get_priority_probe_signature(ctx.priority_focus)
            cooldown_seconds = checker._priority_analyzer.get_priority_probe_cooldown_seconds(ctx.priority_focus)
            last_signature = str(ctx.state_data.get("last_priority_probe_signature") or "")
            last_probe_ts = float(ctx.state_data.get("last_priority_probe_ts") or 0.0)
            same_signature = bool(last_signature) and last_signature == signature
            if same_signature and (now - last_probe_ts) < cooldown_seconds:
                ctx.priority_focus["must_probe"] = False
                ctx.priority_focus["probe_throttled"] = True
                ctx.priority_focus["probe_wait_seconds"] = int(cooldown_seconds - (now - last_probe_ts))

        t0 = time.monotonic()
        priority_analysis_result = await checker._priority_analyzer.analyze_daily_push_priority(
            now=now,
            now_dt=now_dt,
            latest_user_signal_ts=ctx.latest_user_signal_ts,
            workspace_snapshot=ctx.workspace_snapshot,
            priority_focus=ctx.priority_focus,
            urgent_needs=ctx.urgent_needs,
            state_data=ctx.state_data,
            recent_history=ctx.recent_history,
        )
        logger.info("Active Care 计时: analyze_daily_push_priority=%.1fs", time.monotonic() - t0)

        ctx.priority_analysis = (
            priority_analysis_result.get("analysis")
            if isinstance(priority_analysis_result, dict)
            else {}
        )

        if isinstance(ctx.priority_analysis, dict) and ctx.priority_analysis.get("ranked"):
            try:
                # 保存到用户画像服务（独立于状态追踪）
                await checker.user_profile_service.save_daily_push_priority(
                    date=now_dt.strftime("%Y-%m-%d"),
                    ranked=ctx.priority_analysis.get("ranked") or [],
                    summary=str(ctx.priority_analysis.get("summary") or "")[:300],
                    raw_text=str(ctx.priority_analysis.get("raw_text") or "")[:8000],
                    reduced_mode=ctx.reduced_mode_active,
                    scope=checker.storage.get_runtime_scope(),
                )
            except Exception as e:
                logger.warning(f"Active Care: save daily push priority to user profile failed: {e}")

            try:
                await checker._priority_analyzer.persist_daily_push_priority_analysis(
                    now_dt=now_dt,
                    analysis=ctx.priority_analysis,
                    workspace_snapshot=ctx.workspace_snapshot,
                    priority_focus=ctx.priority_focus,
                    runtime_scope=checker.storage.get_runtime_scope(),
                )
            except Exception as e:
                logger.warning(f"Active Care: persist daily push priority files failed: {e}")

        if ctx.is_early_morning and not ctx.urgent_needs and ctx.quiet_mode_active:
            ctx.priority_focus["must_probe"] = False
            logger.info("Active Care: Early morning + quiet mode, suppressing proactive messages")
        elif ctx.is_early_morning and not ctx.urgent_needs:
            logger.info("Active Care: Early morning (00:00-06:00) but no quiet mode, allowing normal check")

        mood_intensity = float(ctx.emo_payload.get("intensity", 0))
        primary_emo = ctx.emo_payload.get("primary_emotion", "neutral")
        aveline_is_sick = bool(ctx.immune_stats.get("is_sick", False))
        aveline_energy = float(ctx.life_stats.get("energy", 100))

        available_actions = checker._decision_executor.build_available_actions(
            mood_intensity, primary_emo, aveline_is_sick, aveline_energy,
            ctx.priority_focus, ctx.sleep_session_active, ctx.probe_policy,
            reduced_mode_active=ctx.reduced_mode_active,
            reduced_mode_reason=ctx.reduced_mode_reason,
        )

        unified_decision_ctx = checker._state_detector.build_unified_decision_ctx(ctx)

        ctx.quiet_mode_active = (
            bool(ctx.state_data.get("last_goodnight_ts", 0) > 0)
            and not ctx.sleep_session_active
        )
        unified_decision_ctx["quiet_mode_active"] = ctx.quiet_mode_active

        try:
            t0 = time.monotonic()
            chosen_action = await checker._decision_executor.select_action(
                unified_decision_ctx, available_actions, ctx.priority_analysis, ctx.priority_focus, ctx.urgent_needs
            )
            logger.info("Active Care 计时: select_action=%.1fs", time.monotonic() - t0)
        except asyncio.TimeoutError:
            await checker.set_next_decision_ts(now + ctx.default_next_check, persona_filename=getattr(ctx, 'persona_filename', ''))
            logger.warning(f"Active Care: select_action_bandit timed out. Next check in {ctx.default_next_check}s.")
            return

        chosen_action, next_check_override = checker._decision_executor.apply_action_overrides(
            chosen_action, ctx
        )

        if chosen_action == "do_nothing":
            _pf = getattr(ctx, 'persona_filename', '')
            force_send, force_reason = checker._decision_executor.should_force_send(
                ctx, non_response_count=checker.executor.get_non_response_count(
                    checker.executor._resolve_persona_key_from_filename(_pf)
                )
            )
            if not force_send:
                checker.last_skip_reason = "do_nothing"
                await checker.set_next_decision_ts(now + ctx.default_next_check, persona_filename=getattr(ctx, 'persona_filename', ''))
                msg_logger.info(f"Active Care: Action 'do_nothing' selected. Next check in {ctx.default_next_check}s.")
                return
            logger.info(
                "Active Care: do_nothing overridden by force_send (%s), continuing to LLM decision.",
                force_reason,
            )

        try:
            t0 = time.monotonic()
            decision = await asyncio.wait_for(
                checker.decision.decide_proactive_content(
                    unified_decision_ctx, chosen_action, ctx.safe_device_context
                ),
                timeout=20.0,
            )
            logger.info("Active Care 计时: decide_proactive_content=%.1fs", time.monotonic() - t0)
        except asyncio.TimeoutError:
            await checker.set_next_decision_ts(now + ctx.default_next_check, persona_filename=getattr(ctx, 'persona_filename', ''))
            logger.warning(f"Active Care: decide_proactive_content timed out. Next check in {ctx.default_next_check}s.")
            return
        except Exception as e:
            await checker.set_next_decision_ts(now + ctx.default_next_check, persona_filename=getattr(ctx, 'persona_filename', ''))
            logger.error(f"Active Care: decide_proactive_content failed: {e}", exc_info=True)
            return

        logger.info(
            "Active Care: decision result: should_send=%s thought=%s intent=%s",
            decision.get("should_send"), str(decision.get("thought", ""))[:120], decision.get("intent"),
        )

        await self.execute_send_or_skip(ctx, decision, chosen_action, persona_filename=ctx.persona_filename)

    async def execute_send_or_skip(self, ctx: DecisionFlowContext, decision: Dict, chosen_action: str, persona_filename: str = ""):
        """根据决策结果执行发送或跳过

        Args:
            persona_filename: 人设文件名，双QQ模式下按 persona 独立触发
        """
        checker = self._checker
        now = ctx.now
        should_send = decision.get("should_send", True)
        thought = decision.get("thought", "")
        specific_instruction = str(decision.get("specific_instruction") or "").strip()
        next_check_seconds = float(decision.get("next_check_seconds") or ctx.default_next_check)
        non_response_count = checker.executor.get_non_response_count(
            checker.executor._resolve_persona_key_from_filename(persona_filename)
        )
        non_response_backoff = checker._non_response_backoff_multiplier(non_response_count)

        if non_response_count >= MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP:
            skip_wait = max(ctx.default_next_check * 4, 3600)
            checker.last_skip_reason = "too_many_non_responses"
            await checker.set_next_decision_ts(now + float(skip_wait), source="too_many_non_responses", persona_filename=persona_filename)
            logger.info(
                "Active Care: 连续%d次无回复，跳过本轮发送，%ds后再检查",
                non_response_count, int(skip_wait),
            )
            return

        latest_user_ts = ctx.last_interaction
        user_quiet_seconds = checker._get_config_value("active_care_user_quiet_seconds", 300)

        bypass_interaction_guard = False
        min_quiet_even_incomplete = MIN_QUIET_EVEN_INCOMPLETE_SECONDS
        if ctx.conversation_incomplete and not ctx.quiet_mode_active and not ctx.reduced_mode_active:
            if non_response_count >= 1:
                # 用户已连续不回复，不再绕过交互保护，避免自问自答
                logger.info(
                    "Active Care: conversation_incomplete 但用户已连续%d次不回复，不绕过交互保护。",
                    non_response_count,
                )
            elif latest_user_ts > 0 and (now - latest_user_ts) < min_quiet_even_incomplete:
                logger.info(
                    "Active Care: conversation_incomplete but user interacted only %ss ago (< %ss min quiet). Not bypassing.",
                    int(now - latest_user_ts), min_quiet_even_incomplete
                )
            else:
                bypass_interaction_guard = True
                logger.info("Active Care: Bypassing recent_user_interaction_guard due to conversation_incomplete.")

        if not bypass_interaction_guard and latest_user_ts > 0 and (now - latest_user_ts) < user_quiet_seconds:
            wait_seconds = max(int(user_quiet_seconds - max(0.0, now - latest_user_ts)), ctx.default_next_check)
            checker.last_skip_reason = "recent_user_interaction_guard"
            await checker.set_next_decision_ts(now + float(wait_seconds), source="recent_user_interaction_guard", persona_filename=persona_filename)
            logger.info(
                "Active Care: Skip send due to recent user interaction (%ss ago < %ss). Next check in %ss.",
                int(max(0.0, now - latest_user_ts)),
                int(user_quiet_seconds),
                int(wait_seconds),
            )
            return

        should_send, thought = checker._time_gate.apply_silence_overrides(ctx, should_send, thought, non_response_count)

        if should_send:
            required_gap = float(ctx.min_gap_seconds)
            if non_response_count > 0:
                required_gap = max(
                    required_gap,
                    float(ctx.min_gap_seconds) * float(min(non_response_count + 1, 6)),
                )

            last_sent_ts = float(ctx.state_data.get("last_sent_ts") or 0.0)
            last_attempt_ts = float(ctx.state_data.get("last_attempt_ts") or 0.0)
            last_activity_ts = max(last_sent_ts, last_attempt_ts)
            if last_activity_ts > 0 and (now - last_activity_ts) < required_gap:
                remaining = int(required_gap - (now - last_activity_ts))
                checker.last_skip_reason = "hard_min_gap_enforcement"
                await checker.set_next_decision_ts(now + float(remaining), source="hard_min_gap_enforcement", persona_filename=persona_filename)
                logger.info(
                    "Active Care: 发送被硬性间隔阻止，距上次活动仅%ds（需%ds），%ds后重试",
                    int(now - last_activity_ts), int(required_gap), remaining,
                )
                return

            intent = decision.get("intent", chosen_action)
            user_input_mock = f"[{intent.upper()}_TRIGGER]"

            # 提醒分工检查：如果当前 intent 是提醒类，检查跨 persona 分工共享池
            reminder_id = ""
            reminder_title = ""
            current_persona = _resolve_persona_from_filename(persona_filename)
            if intent in _REMINDER_INTENTS:
                reminder_id, reminder_title = _get_reminder_id_for_intent(
                    ctx.priority_analysis, intent
                )
                if reminder_id:
                    try:
                        from core.services.active_care.storage.reminder_assignment_registry import (
                            get_reminder_assignment_registry,
                        )
                        _registry = get_reminder_assignment_registry()
                        # 检查是否已分配给对方
                        if await _registry.is_assigned_to_other(reminder_id, current_persona):
                            checker.last_skip_reason = "reminder_assigned_to_peer"
                            skip_wait = max(ctx.min_gap_seconds, ctx.default_next_check)
                            await checker.set_next_decision_ts(
                                now + float(skip_wait),
                                source="reminder_assigned_to_peer",
                                persona_filename=persona_filename,
                            )
                            logger.info(
                                "Active Care: 提醒 %s 已由对方认领，跳过本轮发送，%ds 后重试",
                                reminder_id, int(skip_wait),
                            )
                            msg_logger.info(
                                "Active Care: Skip send (reminder_assigned_to_peer) "
                                "reminder_id=%s persona=%s",
                                reminder_id, current_persona,
                            )
                            return
                    except Exception as _e:
                        logger.warning(
                            "Active Care: 提醒分工检查失败，忽略检查继续发送: %s", _e
                        )

            # 主动关怀时段分工检查：非提醒类 intent 检查当前时段主导角色
            # 协商失败时走轮流制兜底（can_take_over 会根据 last_send_ts 判断）
            if intent not in _REMINDER_INTENTS:
                try:
                    from core.services.active_care.storage.proactive_assignment_registry import (
                        get_proactive_assignment_registry,
                    )
                    _proactive_registry = get_proactive_assignment_registry()
                    # 判断当前角色是否可以发（主导 or 主导超时后兜底接管，1.5h）
                    can_send = await _proactive_registry.can_take_over(
                        current_persona, timeout_seconds=5400.0
                    )
                    if not can_send:
                        checker.last_skip_reason = "proactive_slot_assigned_to_peer"
                        skip_wait = max(ctx.min_gap_seconds, ctx.default_next_check)
                        await checker.set_next_decision_ts(
                            now + float(skip_wait),
                            source="proactive_slot_assigned_to_peer",
                            persona_filename=persona_filename,
                        )
                        current_slot = await _proactive_registry.get_current_slot()
                        logger.info(
                            "Active Care: 当前时段(%s)主导是对方且未超时，跳过本轮发送，%ds 后重试",
                            current_slot, int(skip_wait),
                        )
                        msg_logger.info(
                            "Active Care: Skip send (proactive_slot_assigned_to_peer) "
                            "persona=%s slot=%s",
                            current_persona, current_slot,
                        )
                        return
                except Exception as _e:
                    logger.warning(
                        "Active Care: 主动关怀时段分工检查失败，忽略检查继续发送: %s", _e
                    )

            try:
                t0 = time.monotonic()
                delivered = await asyncio.shield(
                    checker.executor.trigger_message(
                        sys_prompt_type=intent,
                        user_input_mock=user_input_mock,
                        thought=thought,
                        client_type=ctx.client_type,
                        specific_instruction=specific_instruction,
                        persona_filename=persona_filename,
                        planned_topic=str(decision.get("planned_topic") or ""),
                        self_activity=False,
                    )
                )
                logger.info("Active Care 计时: trigger_message=%.1fs", time.monotonic() - t0)
            except asyncio.CancelledError:
                logger.warning(
                    "Active Care: perform_check cancelled during trigger_message, but message delivery is shielded."
                )
                delivered = False

            if delivered:
                checker.last_intent = intent
                # 强制应用 non_response 惩罚到 next_check，防止 LLM 返回过小的 next_check_seconds 绕过惩罚
                penalized_next_check = max(
                    next_check_seconds,
                    required_gap,
                    ctx.min_gap_seconds * non_response_backoff,
                )
                send_wait_seconds = checker._apply_interval_jitter(
                    penalized_next_check,
                    min_seconds=ctx.min_gap_seconds,
                    jitter_ratio=0.35,
                )
                await checker.set_next_decision_ts(now + float(send_wait_seconds), persona_filename=persona_filename)
                logger.info(
                    "Active Care: 发送成功，设置下次检查: next_check=%.0fs required_gap=%.0fs "
                    "non_response=%d backoff=%.2f final_wait=%.0fs",
                    next_check_seconds, required_gap, non_response_count,
                    non_response_backoff, send_wait_seconds,
                )

                # 提醒分工：发送成功后写入 registry（先到先得兜底）
                # 适用于协商失败/未协商完成时，第一个发送的 persona 自动认领
                if intent in _REMINDER_INTENTS and reminder_id:
                    try:
                        from core.services.active_care.storage.reminder_assignment_registry import (
                            get_reminder_assignment_registry,
                        )
                        _registry = get_reminder_assignment_registry()
                        await _registry.mark_assigned(
                            reminder_id=reminder_id,
                            title=reminder_title,
                            persona=current_persona,
                            reason="先到先得（协商未完成或失败时的兜底）",
                        )
                    except Exception as _e:
                        logger.warning(
                            "Active Care: 提醒分工写入 registry 失败: %s", _e
                        )

                # 主动关怀时段分工：记录发送时间戳（用于兜底接管判断）
                # 非提醒类 intent 才记录，提醒类有自己的分工机制
                if intent not in _REMINDER_INTENTS:
                    try:
                        from core.services.active_care.storage.proactive_assignment_registry import (
                            get_proactive_assignment_registry,
                        )
                        _proactive_registry = get_proactive_assignment_registry()
                        await _proactive_registry.record_send(current_persona)
                    except Exception as _e:
                        logger.warning(
                            "Active Care: 主动关怀发送记录失败: %s", _e
                        )
            else:
                checker.last_skip_reason = "trigger_message_failed"
                failed_wait = max(ctx.min_gap_seconds, ctx.default_next_check)
                await checker.set_next_decision_ts(now + float(failed_wait), source="trigger_message_failed", persona_filename=persona_filename)
        else:
            checker.last_skip_reason = "llm_decision_no_send"
            base_no_send_wait = max(float(ctx.default_next_check), float(next_check_seconds))
            penalized_no_send_wait = base_no_send_wait * non_response_backoff
            randomized_no_send_wait = checker._apply_interval_jitter(
                penalized_no_send_wait,
                min_seconds=ctx.default_next_check,
                jitter_ratio=0.40,
            )
            await checker.set_next_decision_ts(now + float(randomized_no_send_wait), persona_filename=persona_filename)

            try:
                if hasattr(checker.executor, "write_diary_entry"):
                    await checker.executor.write_diary_entry(
                        "no_send_check",
                        f"本轮未发送（reason=llm_decision_no_send, next_check_seconds={int(randomized_no_send_wait)}）",
                        thought=str(thought or "").strip(),
                    )
            except Exception as record_e:
                if is_debug_enabled("active_care"):
                    logger.info(f"Active Care: Failed to persist no-send check event: {record_e}")

            logger.info(
                "Active Care: no_send backoff applied: base=%ss multiplier=%.2f randomized=%ss non_response_count=%s",
                int(base_no_send_wait),
                float(non_response_backoff),
                int(randomized_no_send_wait),
                int(non_response_count),
            )
            msg_logger.info(f"Active Care: Decision was NOT to send. Thought: {thought}")
