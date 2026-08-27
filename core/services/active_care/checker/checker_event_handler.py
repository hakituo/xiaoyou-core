"""
主动关怀检查器 - 事件检测

负责处理到期提醒事件，包括：
- 检查并处理到期提醒（起床提醒、过期提醒等）
- 提醒发送失败的重试策略
- 提醒间隔保护

依赖通过构造函数注入 checker 实例，方法内通过 checker.xxx 访问原 self 属性，
参考 SleepSessionManager 的依赖注入模式。
"""
# ruff: noqa: E401,E702,F401
import asyncio
import time
from typing import Any

from core.services.active_care.core.trigger_result import (
    TriggerMessageResult,
    TriggerOutcome,
)
from core.services.active_care.checker.sleep_recovery_guard_support import (
    build_sleep_recovery_guard,
    should_attempt_sleep_recovery_refresh,
)
from core.utils.logger import get_module_logger
from core.utils.timestamp_utils import safe_timestamp
from core.services.active_care.decision.decision_context import DecisionFlowContext
from core.services.active_care.shared.reminder_injection import get_reminder_injection_store

logger = get_module_logger("ACTIVE_CARE_CHECKER", "active_care_schedule.log")


def is_legacy_auto_plan_reminder(metadata: Any) -> bool:
    """判断是否为旧版自动计划生成、但未明确要求硬推送的提醒。"""
    if not isinstance(metadata, dict):
        return False
    return (
        str(metadata.get("source") or "").strip().lower() == "daily_task"
        and str(metadata.get("delivery_mode") or "").strip().lower() != "hard"
    )


class CheckerEventHandler:
    """主动关怀检查器 - 事件检测

    封装到期提醒事件的处理逻辑，由 ProactiveChecker 委托调用。
    方法签名与原 ProactiveChecker 中对应方法保持一致（去掉 _ 前缀变公开方法）。
    """

    def __init__(self, checker):
        """
        Args:
            checker: ProactiveChecker 实例，用于访问 executor/set_next_decision_ts 等依赖
        """
        self._checker = checker

    def _resolve_scope(self, ctx: DecisionFlowContext) -> str:
        """根据 persona 解析当前 Active Care 的角色 scope。"""
        checker = self._checker
        persona_filename = str(getattr(ctx, "persona_filename", "") or "").strip()
        if persona_filename and getattr(checker, "storage", None) is not None:
            try:
                scope = checker.storage.resolve_scope_from_persona_filename(
                    persona_filename
                )
                if scope:
                    return str(scope).strip().lower()
            except Exception:
                pass
        lowered = persona_filename.lower()
        if "ling" in lowered:
            return "ling"
        return "aveline"

    def _get_role_sleep_summary(self, ctx: DecisionFlowContext) -> dict:
        """读取当前角色的睡眠摘要。"""
        try:
            from core.services.life_simulation import get_life_simulation_service

            life_sim = get_life_simulation_service()
            if not life_sim:
                return {}
            return life_sim.get_sleep_summary(self._resolve_scope(ctx)) or {}
        except Exception:
            return {}

    def _get_role_current_activity(self, ctx: DecisionFlowContext) -> str:
        """读取当前角色在 character_daily 中的活动。"""
        try:
            from core.services.character_daily.engine import get_character_daily_engine

            engine = get_character_daily_engine()
            if engine is None:
                return ""
            activity = engine.get_current_activity(self._resolve_scope(ctx))
            return str(getattr(activity, "value", activity) or "").strip().lower()
        except Exception:
            return ""

    def _get_sleep_recovery_guard(
        self,
        role_sleep_summary: dict,
        now_ts: float | None = None,
    ) -> dict:
        """判断当前角色是否仍处于夜间被叫醒后的恢复保护期。"""
        return build_sleep_recovery_guard(
            role_sleep_summary or {},
            float(now_ts if now_ts is not None else time.time()),
        )

    async def _refresh_role_sleep_summary_if_needed(
        self,
        ctx: DecisionFlowContext,
        role_sleep_summary: dict,
    ) -> dict:
        """必要时主动推进一次睡眠恢复状态，避免 night_awake 长时间残留。"""
        summary = role_sleep_summary or {}
        if not should_attempt_sleep_recovery_refresh(summary, ctx.now):
            return summary

        try:
            from core.services.life_simulation import get_life_simulation_service

            life_sim = get_life_simulation_service()
            if not life_sim:
                return summary
            refreshed = await life_sim.finalize_sleep_recovery_check(
                self._resolve_scope(ctx)
            )
            if isinstance(refreshed, dict) and refreshed:
                logger.info(
                    "Active Care: 检测到睡眠恢复状态可能残留，已先主动刷新 "
                    "(before=%s, after=%s)",
                    str(summary.get("phase") or ""),
                    str(refreshed.get("phase") or ""),
                )
                return refreshed
        except Exception as exc:
            logger.warning("Active Care: 主动刷新角色睡眠恢复状态失败: %s", exc)
        return summary

    async def _defer_due_reminder(
        self,
        ctx: DecisionFlowContext,
        due_reminder,
        *,
        defer_reason: str,
        allow_nudge: bool,
    ) -> bool:
        """把提醒转为推迟提醒，不直接发送主动消息。"""
        checker = self._checker
        reminder_id = str(getattr(due_reminder, "id", "") or "")
        reminder_msg = str(getattr(due_reminder, "message", "") or "").strip()
        reminder_meta = getattr(due_reminder, "metadata", None) or {}
        reminder_type = str(reminder_meta.get("type") or "start").strip().lower()
        task_title = str(reminder_meta.get("task_title") or "").strip()

        wakeup_keywords = ["起床", "起来", "醒醒", "别装死", "起床了", "该起了"]
        if any(keyword in reminder_msg for keyword in wakeup_keywords):
            await checker.executor.complete_reminder(reminder_id, triggered_at=ctx.now)
            # 起床提醒被推迟路径下，同样自动标记对应计划项完成，避免下次又生成同样的提醒
            await self._auto_complete_wakeup_plan_item(due_reminder, ctx.now)
            return True

        nudge_sent = False
        resolved_scope = self._resolve_scope(ctx)
        try:
            deferred = list(ctx.state_data.get("deferred_plan_reminders") or [])
            existing_ids = {item.get("id") for item in deferred if isinstance(item, dict)}
            if reminder_id not in existing_ids:
                deferred.append(
                    {
                        "id": reminder_id,
                        "message": reminder_msg,
                        "type": reminder_type,
                        "task_title": task_title,
                        "deferred_ts": ctx.now,
                    }
                )
                if hasattr(checker, "executor") and hasattr(checker.executor, "storage"):
                    await checker.executor.storage.save_proactive_state(
                        {"deferred_plan_reminders": deferred},
                        scope=resolved_scope or None,
                    )
                ctx.state_data["deferred_plan_reminders"] = deferred
                logger.info(
                    "Active Care: due_reminder 已推迟（%s），累积 %d 条: %s",
                    defer_reason,
                    len(deferred),
                    task_title or reminder_msg[:30],
                )
                if allow_nudge and len(deferred) >= 3:
                    try:
                        titles = [
                            item.get("task_title") or ""
                            for item in deferred
                            if isinstance(item, dict) and item.get("task_title")
                        ]
                        if titles:
                            nudge_msg = (
                                f"有 {len(titles)} 项计划提醒还没送到，你那边还好吗？"
                            )
                            delivered = await asyncio.shield(
                                checker.executor.trigger_message(
                                    sys_prompt_type="reminder",
                                    user_input_mock="[SLEEP_NUDGE]",
                                    reminder_msg=nudge_msg,
                                    thought="sleep_nudge_threshold",
                                    client_type=ctx.client_type,
                                    persona_filename=getattr(ctx, "persona_filename", ""),
                                )
                            )
                            nudge_sent = bool(delivered)
                            logger.info(
                                "Active Care: 睡眠催促已发送（累积%d条），delivered=%s",
                                len(deferred),
                                delivered,
                            )
                    except Exception as nudge_err:
                        logger.warning("Active Care: 睡眠催促发送失败: %s", nudge_err)
            else:
                logger.info(
                    "Active Care: due_reminder 已在推迟列表中，跳过重复: %s",
                    reminder_id,
                )
        except Exception as exc:
            logger.warning("Active Care: 存储推迟提醒失败: %s", exc)

        await checker.executor.complete_reminder(reminder_id, triggered_at=ctx.now)
        if nudge_sent:
            await checker.set_next_decision_ts(
                ctx.now + max(ctx.default_next_check, ctx.min_gap_seconds),
                source="sleep_nudge_sent",
                persona_filename=getattr(ctx, "persona_filename", ""),
            )
        return True

    async def _auto_complete_wakeup_plan_item(self, reminder, now: float) -> None:
        """起床提醒被跳过/推迟时，自动把对应的计划项标记为完成。

        场景：用户已经起床（last_goodmorning_ts > 0），起床提醒无需再发送。
        此时只标记 reminder 完成是不够的——对应的 PlanItem 仍是 pending，
        下次重新生成计划时可能又生成同样的提醒；同时结束提醒（end_reminder）
        仍会触发，让用户起床后还收到"该休息了"的奇怪消息。

        本方法从 reminder.metadata 读取 plan_item_id / plan_date，
        把对应 PlanItem 标记为 completed，并一并清理 end_reminder。
        所有异常都吞掉只记日志，不影响主流程。
        """
        metadata = getattr(reminder, "metadata", None) or {}
        if not isinstance(metadata, dict):
            return
        plan_item_id = str(metadata.get("plan_item_id") or "").strip()
        plan_date = str(metadata.get("plan_date") or "").strip() or None
        if not plan_item_id:
            return
        try:
            from core.services.journal.service import get_journal_service
            journal = get_journal_service()
            # 先取 PlanItem，拿到 end_reminder_id 以便一并完成
            plan = await journal.get_plan(plan_date)
            if plan is not None:
                for it in plan.items:
                    if it.id == plan_item_id and it.end_reminder_id:
                        try:
                            await self._checker.executor.complete_reminder(
                                it.end_reminder_id, triggered_at=now
                            )
                        except Exception as e:
                            logger.warning(
                                "Active Care: 起床提醒跳过时清理 end_reminder 失败: %s", e
                            )
                        break
            updated = await journal.mark_plan_item_status(
                plan_date, plan_item_id, "completed"
            )
            if updated is not None:
                logger.info(
                    "Active Care: 用户已起床，自动标记计划项为 completed: item_id=%s date=%s",
                    plan_item_id, plan_date or "today",
                )
        except Exception as e:
            logger.warning(
                "Active Care: 起床提醒跳过时自动标记计划项完成失败: %s", e
            )

    async def handle_due_reminder(self, ctx: DecisionFlowContext) -> bool:
        """检查并处理到期提醒，返回 True 表示已处理（应终止当前决策流程）"""
        checker = self._checker
        from core.services.active_care.shared.constants import (
            REMINDER_MAX_CONSECUTIVE_RETRIES,
            REMINDER_RETRY_BACKOFF_BASE_SECONDS,
        )

        role_sleep_summary = self._get_role_sleep_summary(ctx)
        role_sleep_summary = await self._refresh_role_sleep_summary_if_needed(
            ctx, role_sleep_summary
        )
        role_phase = str(role_sleep_summary.get("phase") or "").strip().lower()
        role_sleeping = bool(role_sleep_summary.get("is_sleeping")) or role_phase in {
            "sleeping",
            "napping",
        }
        # role_night_awake 已移除：用户睡觉时不再发 nudge，提醒累积到醒来后统一发
        role_activity = self._get_role_current_activity(ctx)

        try:
            from core.services.character_daily.activity_model import HARD_BUSY_ACTIVITIES

            hard_busy_values = {
                str(getattr(activity, "value", activity) or "").strip().lower()
                for activity in HARD_BUSY_ACTIVITIES
            }
        except Exception:
            hard_busy_values = {"studying"}
        role_hard_busy = role_activity in hard_busy_values
        sleep_recovery_guard = self._get_sleep_recovery_guard(role_sleep_summary, ctx.now)

        if role_sleeping:
            due_reminder = await checker.executor.check_reminders()
            if not due_reminder:
                logger.info(
                    "Active Care: 当前角色处于睡眠中，跳过主动关怀决策 (phase=%s)",
                    role_phase or "sleeping",
                )
                return True
            return await self._defer_due_reminder(
                ctx,
                due_reminder,
                defer_reason=f"role_sleep:{role_phase or 'sleeping'}",
                allow_nudge=False,
            )

        if ctx.reduced_mode_active and ctx.reduced_mode_reason in ("goodnight", "sleep", "sleep_hint"):
            # 用户睡眠模式下：检出到期提醒，全部推迟到用户醒来后统一发送
            # 不再发 nudge 催促，避免用户睡觉时被多条 nudge 打扰
            due_reminder = await checker.executor.check_reminders()
            if not due_reminder:
                logger.info(
                    "Active Care: due_reminder 跳过（无到期提醒），用户处于低打扰模式 (reason=%s)",
                    ctx.reduced_mode_reason,
                )
                return True
            return await self._defer_due_reminder(
                ctx,
                due_reminder,
                defer_reason=ctx.reduced_mode_reason,
                allow_nudge=False,  # 用户睡觉时永远不发 nudge，提醒累积到醒来后统一发
            )

        if role_hard_busy:
            due_reminder = await checker.executor.check_reminders()
            if not due_reminder:
                return False
            logger.info(
                "Active Care: 当前角色处于硬忙碌活动，推迟 due_reminder (activity=%s)",
                role_activity or "busy",
            )
            return await self._defer_due_reminder(
                ctx,
                due_reminder,
                defer_reason=f"role_busy:{role_activity or 'busy'}",
                allow_nudge=False,
            )

        if sleep_recovery_guard:
            due_reminder = await checker.executor.check_reminders()
            if not due_reminder:
                return False
            logger.info(
                "Active Care: 当前角色仍在睡眠恢复期，推迟 due_reminder "
                "(phase=%s, debt=%.1fh, inertia=%.1f, impact=%s)",
                sleep_recovery_guard["phase"],
                sleep_recovery_guard["sleep_debt_hours"],
                sleep_recovery_guard["sleep_inertia_score"],
                sleep_recovery_guard["impact_level"],
            )
            return await self._defer_due_reminder(
                ctx,
                due_reminder,
                defer_reason=f"role_sleep_recovery:{sleep_recovery_guard['phase']}",
                allow_nudge=False,
            )

        last_sent_ts = float(ctx.state_data.get("last_sent_ts") or 0.0)
        last_attempt_ts = float(ctx.state_data.get("last_attempt_ts") or 0.0)
        last_activity_ts = max(last_sent_ts, last_attempt_ts)
        if last_activity_ts > 0 and (ctx.now - last_activity_ts) < ctx.min_gap_seconds:
            remaining = int(ctx.min_gap_seconds - (ctx.now - last_activity_ts))
            logger.info(
                "Active Care: due_reminder 被硬性间隔阻止，距上次活动仅%ds（需%ds），%ds后重试",
                int(ctx.now - last_activity_ts), int(ctx.min_gap_seconds), remaining,
            )
            await checker.set_next_decision_ts(ctx.now + float(remaining), source="reminder_min_gap_blocked", persona_filename=getattr(ctx, 'persona_filename', ''))
            return True

        due_reminder = await checker.executor.check_reminders()
        if not due_reminder:
            return False

        reminder_msg = str(getattr(due_reminder, "message", "") or "").strip()
        reminder_id = str(getattr(due_reminder, "id", "") or "")
        reminder_ts = float(getattr(due_reminder, "trigger_ts", 0) or 0)
        reminder_metadata = getattr(due_reminder, "metadata", None) or {}

        # 历史版本会把 AI 自动生成的每个时间块都注册为硬提醒，导致整天按
        # 计划表逐项催促并绕过 MDP 的未回复退避。只有显式标记 hard 的提醒
        # 才独立发送；旧自动计划提醒静默完成，普通计划跟进交回 MDP。
        if is_legacy_auto_plan_reminder(reminder_metadata):
            await checker.executor.complete_reminder(reminder_id, triggered_at=ctx.now)
            logger.info(
                "Active Care: 旧自动计划硬提醒已静默完成，交回 MDP 决策: %s",
                reminder_msg[:80],
            )
            return False

        if (reminder_ts > 0) and (ctx.now - reminder_ts) > 86400:
            logger.info(
                "Active Care: due_reminder 已过期超过24h（创建于%.1fd前），跳过并标记完成: %s",
                (ctx.now - reminder_ts) / 86400,
                reminder_msg[:50],
            )
            await checker.executor.complete_reminder(reminder_id, triggered_at=ctx.now)
            return False

        wakeup_keywords = ["起床", "起来", "醒醒", "别装死", "起床了", "该起了"]
        if any(kw in reminder_msg for kw in wakeup_keywords):
            last_goodmorning_ts = safe_timestamp(ctx.state_data.get("last_goodmorning_ts"))
            if last_goodmorning_ts > 0:
                logger.info(
                    "Active Care: due_reminder 是起床提醒但用户已起床（goodmorning_ts=%.0f），跳过: %s",
                    last_goodmorning_ts,
                    reminder_msg[:50],
                )
                await checker.executor.complete_reminder(reminder_id, triggered_at=ctx.now)
                # 用户已起床，自动把对应的计划项标记为完成，避免下次又生成同样的提醒，
                # 同时清理结束提醒，避免用户起床后还收到"该休息了"
                await self._auto_complete_wakeup_plan_item(due_reminder, ctx.now)
                return False

        reminder_text = checker.executor.format_due_reminder_message(due_reminder)

        # 检查用户是否正在聊天，如果是则注入到主程序上下文而非发送独立消息
        injection_store = get_reminder_injection_store()
        from config.integrated_config import get_settings
        settings = get_settings()
        life_settings = settings.life_simulation
        if getattr(life_settings, 'active_care_reminder_inject_to_chat', True):
            inject_window = getattr(life_settings, 'active_care_reminder_inject_window_seconds', 600)
            if injection_store.is_user_recently_active(threshold_seconds=inject_window):
                # 用户正在聊天或刚聊完不久，注入到主程序上下文
                task_title = str(
                    getattr(due_reminder, "title", "")
                    or (getattr(due_reminder, "metadata", None) or {}).get("task_title")
                    or ""
                )
                recent_history = injection_store.get_recent_chat_context() or ""
                await injection_store.set_pending_reminder(
                    reminder_text=reminder_text,
                    task_title=task_title,
                    recent_chat_summary=recent_history,
                )
                await checker.executor.complete_reminder(reminder_id, triggered_at=ctx.now)
                logger.info(
                    "Active Care: 用户正在聊天（窗口%ds），提醒已注入到主程序上下文: %s",
                    inject_window, reminder_msg[:50],
                )
                return True

        try:
            t0 = time.monotonic()
            result = await asyncio.shield(
                checker.executor.trigger_message_with_result(
                    sys_prompt_type="reminder",
                    user_input_mock="[REMINDER_TRIGGER]",
                    reminder_msg=reminder_text,
                    thought="workspace_due_reminder",
                    client_type=ctx.client_type,
                    persona_filename=getattr(ctx, 'persona_filename', ''),
                )
            )
            logger.info("Active Care 计时: reminder_trigger_message=%.1fs", time.monotonic() - t0)
        except asyncio.CancelledError:
            logger.warning("Active Care: perform_check cancelled during reminder trigger_message, shielded.")
            result = TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.EXECUTION_EXCEPTION,
                detail="cancelled",
            )

        if result.outcome is TriggerOutcome.DELIVERED:
            await checker.executor.complete_reminder(
                str(getattr(due_reminder, "id", "") or ""),
                triggered_at=ctx.now,
            )
            await checker.set_next_decision_ts(
                ctx.now + max(ctx.default_next_check, ctx.min_gap_seconds),
                source="due_reminder_sent",
                persona_filename=getattr(ctx, 'persona_filename', ''),
            )
            checker.last_intent = "reminder"
            checker.last_skip_reason = "due_reminder_sent"
            checker._consecutive_reminder_retries = 0
            return True

        if result.outcome is TriggerOutcome.OVERLAP_BLOCKED:
            retry_backoff = max(ctx.min_gap_seconds - int(ctx.now - max(
                float(ctx.state_data.get("last_sent_ts") or 0.0),
                float(ctx.state_data.get("last_attempt_ts") or 0.0),
            )), 60)
            await checker.set_next_decision_ts(ctx.now + float(retry_backoff), source="reminder_interval_blocked", persona_filename=getattr(ctx, 'persona_filename', ''))
            checker.last_skip_reason = "reminder_interval_blocked"
            logger.info(
                "Active Care: due_reminder 被间隔保护拦住，%ds 后重试（不计入重试次数）",
                retry_backoff,
            )
            return True

        if result.outcome is TriggerOutcome.GENERATION_FAILED:
            checker._consecutive_reminder_retries = getattr(checker, "_consecutive_reminder_retries", 0) + 1
            logger.warning(
                "Active Care: due_reminder LLM生成失败（第%d次），重试中",
                checker._consecutive_reminder_retries,
            )
        elif result.outcome is TriggerOutcome.DISPATCH_FAILED:
            checker._consecutive_reminder_retries = getattr(checker, "_consecutive_reminder_retries", 0) + 1
            logger.warning(
                "Active Care: due_reminder 分发失败（第%d次），重试中",
                checker._consecutive_reminder_retries,
            )
        elif result.outcome is TriggerOutcome.EXECUTION_EXCEPTION:
            checker._consecutive_reminder_retries = getattr(checker, "_consecutive_reminder_retries", 0) + 1
            logger.warning(
                "Active Care: due_reminder 发送异常（第%d次），重试中: %s",
                checker._consecutive_reminder_retries,
                result.detail or "unknown",
            )
        else:
            checker._consecutive_reminder_retries = getattr(checker, "_consecutive_reminder_retries", 0) + 1

        if checker._consecutive_reminder_retries >= REMINDER_MAX_CONSECUTIVE_RETRIES:
            logger.warning(
                "Active Care: due_reminder 已连续失败 %d 次，放弃重试，转为正常决策流程",
                checker._consecutive_reminder_retries,
            )
            checker._consecutive_reminder_retries = 0
            checker.last_skip_reason = "due_reminder_abandoned"
            return False

        retry_backoff = min(
            REMINDER_RETRY_BACKOFF_BASE_SECONDS * checker._consecutive_reminder_retries,
            1800,
        )
        await checker.set_next_decision_ts(
            ctx.now + retry_backoff,
            source="due_reminder_retry",
            persona_filename=getattr(ctx, 'persona_filename', ''),
        )
        checker.last_skip_reason = "due_reminder_retry"
        logger.info(
            "Active Care: due_reminder 发送失败，第 %d/%d 次重试，%ds 后重试",
            checker._consecutive_reminder_retries,
            REMINDER_MAX_CONSECUTIVE_RETRIES,
            retry_backoff,
        )
        return True

    async def guard_general_proactive_during_sleep_recovery(
        self,
        ctx: DecisionFlowContext,
    ) -> bool:
        """夜间被叫醒且仍困时，压住普通主动话题，避免突然聊计划。"""
        checker = self._checker
        role_sleep_summary = self._get_role_sleep_summary(ctx)
        role_sleep_summary = await self._refresh_role_sleep_summary_if_needed(
            ctx, role_sleep_summary
        )
        sleep_recovery_guard = self._get_sleep_recovery_guard(role_sleep_summary, ctx.now)
        if not sleep_recovery_guard:
            return False

        wait_seconds = max(
            sleep_recovery_guard["wait_seconds"],
            int(ctx.default_next_check or 300),
        )
        source = f"role_sleep_recovery_blocked:{sleep_recovery_guard['phase']}"
        checker.last_skip_reason = source
        logger.info(
            "Active Care: 当前角色仍在睡眠恢复期，跳过普通主动关怀 "
            "(phase=%s, debt=%.1fh, inertia=%.1f, impact=%s, wait=%ds)",
            sleep_recovery_guard["phase"],
            sleep_recovery_guard["sleep_debt_hours"],
            sleep_recovery_guard["sleep_inertia_score"],
            sleep_recovery_guard["impact_level"],
            wait_seconds,
        )
        await checker.set_next_decision_ts(
            ctx.now + float(wait_seconds),
            source=source,
            persona_filename=getattr(ctx, "persona_filename", ""),
        )
        return True
