"""Active Care 主动关怀主循环
负责主循环调度、保底检查、睡眠间隔计算、安静模式判断
"""
import time
import asyncio
import random

from core.utils.logger import get_module_logger
from core.utils.config_accessor import get_active_care_config

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")


class ProactiveLoopRunner:
    """主动关怀主循环运行器"""

    def __init__(self, service):
        """Args:
            service: ActiveCareService 实例，用于访问其属性和方法
        """
        self._service = service

    async def run_proactive_loop(self):
        """主动关怀主循环"""
        logger.info("Active Care proactive loop started")

        self._service._set_loop_phase("startup_delay")
        try:
            await asyncio.wait_for(self._service._wakeup_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
        finally:
            self._service._wakeup_event.clear()

        loop_count = 0
        while self._service._running:
            loop_count += 1
            self._service._last_loop_iteration_ts = time.time()
            self._service._expected_wakeup_ts = 0.0
            try:
                self._service._set_loop_phase("process_user_response")
                try:
                    await asyncio.wait_for(self._service._process_user_response(), timeout=60)
                except asyncio.TimeoutError:
                    logger.warning("Active Care: process_user_response 超时(60s)，跳过本轮")

                try:
                    from core.services.journal.service import get_journal_service

                    await asyncio.wait_for(
                        get_journal_service().maybe_reassess_today_plan(),
                        timeout=45,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Active Care: 今日计划检查点复盘超时(45s)，跳过本轮")
                except Exception as exc:
                    logger.debug("Active Care: 今日计划检查点复盘失败: %s", exc)

                if self._service.checker:
                    lock_acquired = False
                    try:
                        self._service._set_loop_phase("waiting_lock")
                        await asyncio.wait_for(self._service._proactive_lock.acquire(), timeout=120.0)
                        lock_acquired = True
                    except asyncio.TimeoutError:
                        logger.error(
                            "Active Care: 获取 _proactive_lock 超时(120s)，跳过本轮 "
                            "(lock.locked=%s)", self._service._proactive_lock.locked()
                        )
                        await asyncio.sleep(10)
                        continue

                    try:
                        self._service._set_loop_phase("perform_check")
                        await asyncio.wait_for(
                            self._service.checker.perform_check(is_startup=False), timeout=150
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Active Care: perform_check 超时(150s)")
                        if self._service.checker:
                            await self._service.checker.set_next_decision_ts(
                                time.time() + 60, source="perform_check_timeout"
                            )
                    finally:
                        if lock_acquired:
                            self._service._proactive_lock.release()
                else:
                    self._service._set_loop_phase("fallback_check")
                    try:
                        await asyncio.wait_for(
                            self.fallback_proactive_check(), timeout=150
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Active Care: fallback_proactive_check 超时(150s)")
            except asyncio.CancelledError:
                if self._service._running:
                    logger.warning("Active Care: proactive loop 被意外取消")
                else:
                    logger.info("Active Care: proactive loop 正常取消，准备关闭")
                break
            except Exception as e:
                logger.error(f"Active Care loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

            self._service._set_loop_phase("calculate_sleep_interval")
            try:
                sleep_seconds = await asyncio.wait_for(
                    self.calculate_sleep_interval(), timeout=30
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Active Care: calculate_sleep_interval 超时(30s)，使用保底睡眠60s"
                )
                sleep_seconds = 60
            self.log_schedule_status(sleep_seconds)

            next_decision_in = 0
            if self._service.checker:
                next_decision_in = max(0, int(self._service.checker.next_decision_ts - time.time()))
            logger.info(
                "Active Care: 循环第%d轮完成，下次检查在%ds后，睡眠%ds",
                loop_count, next_decision_in, int(sleep_seconds),
            )

            try:
                self._service._last_sleep_started_ts = time.time()
                self._service._last_sleep_seconds = float(sleep_seconds)
                self._service._expected_wakeup_ts = self._service._last_sleep_started_ts + float(
                    sleep_seconds
                )
                self._service._set_loop_phase("sleep")
                await asyncio.wait_for(self._service._wakeup_event.wait(), timeout=sleep_seconds)
            except asyncio.TimeoutError:
                pass
            finally:
                self._service._wakeup_event.clear()
                self._service._expected_wakeup_ts = 0.0

        self._service._set_loop_phase("stopped")
        logger.info("Active Care proactive loop exited (running=%s)", self._service._running)

    async def fallback_proactive_check(self):
        """保底主动关怀检查（当 checker 未启用时使用）"""
        now = time.time()
        try:
            state_data = await self._service.storage.get_proactive_state()
        except Exception:
            state_data = {}

        last_sent_ts = float(state_data.get("last_sent_ts") or 0.0)
        last_user_ts = float(state_data.get("last_user_interaction_ts") or 0.0)
        elapsed_since_sent = (now - last_sent_ts) if last_sent_ts > 0 else 999999.0
        elapsed_since_user = (now - last_user_ts) if last_user_ts > 0 else 999999.0

        min_gap = int(
            get_active_care_config("active_care_min_gap_seconds", default=600, settings=self._service.settings)
            or 600
        )
        fallback_threshold = max(min_gap * 2, 1200)

        if elapsed_since_sent < fallback_threshold:
            return

        if elapsed_since_user < max(min_gap, 300):
            return

        quiet_mode = await self.is_quiet_mode()
        if quiet_mode:
            return

        logger.info(
            "Active Care: 保底触发 (last_sent=%.0fs前, last_user=%.0fs前, threshold=%ds)",
            elapsed_since_sent, elapsed_since_user, fallback_threshold,
        )

        # 根据时段和沉默时长选择更合适的保底意图
        fallback_intents = ["share_thought", "curious_question"]
        # 如果用户已经很久没互动，优先用好奇提问而非单纯分享
        if elapsed_since_user > fallback_threshold * 2:
            fallback_intent = random.choice(fallback_intents)
        else:
            fallback_intent = "share_thought"

        try:
            from core.utils.client_utils import probe_client_type
            delivered = await self._service.executor.trigger_message(
                sys_prompt_type=fallback_intent,
                user_input_mock="[FALLBACK_PROACTIVE_TRIGGER]",
                thought="fallback_proactive_no_checker",
                client_type=probe_client_type(),
            )
            if delivered:
                self._service.last_intent = fallback_intent
                logger.info("Active Care: 保底消息发送成功")
            else:
                logger.warning("Active Care: 保底消息发送失败")
        except Exception as e:
            logger.error(f"Active Care: 保底消息发送异常: {e}")

    async def _get_seconds_until_next_pending_reminder(self, now: float) -> float | None:
        """返回距离最近待触发提醒还剩多少秒。"""
        try:
            from core.services.workspace.service import get_workspace_service

            workspace = get_workspace_service()
            pending_messages = await workspace.get_pending_messages()
            if not pending_messages:
                return None

            next_wait: float | None = None
            for item in pending_messages:
                trigger_ts = float(getattr(item, "trigger_ts", 0.0) or 0.0)
                if trigger_ts <= 0:
                    continue
                wait_seconds = max(1.0, trigger_ts - now)
                if next_wait is None or wait_seconds < next_wait:
                    next_wait = wait_seconds
            return next_wait
        except Exception as exc:
            logger.debug("Active Care: 获取最近提醒触发时间失败: %s", exc)
            return None

    async def calculate_sleep_interval(self) -> float:
        """计算睡眠间隔"""
        bio_state = {}
        try:
            sim = self._service.life_sim_service
            if sim:
                bio_state = sim.get_state()
        except Exception:
            pass

        emotion_state = None
        try:
            emotion_state = self._service.emotion_manager.get_effective_state("default_user")
        except Exception:
            pass

        quiet_mode = await self.is_quiet_mode()

        dynamic_interval = self._service.scheduler_logic.calculate_dynamic_interval(
            bio_state, emotion_state, self._service.consecutive_non_responses, quiet_mode=quiet_mode
        )

        sleep_seconds = dynamic_interval
        now = time.time()

        llm_wait: float | None = None
        if self._service.checker and self._service.checker.next_decision_ts > now:
            llm_wait = max(1.0, self._service.checker.next_decision_ts - now)
            sleep_seconds = min(float(sleep_seconds), float(llm_wait))
            if getattr(self._service.checker, "last_skip_reason", "") == "manual_delay":
                # 手动延迟窗口内本轮不会做任何主动决策，直接睡到下次允许决策时间。
                # 新的用户消息、提醒任务或外部事件会通过 wakeup_event 提前唤醒，不会错过实时交互。
                sleep_seconds = float(llm_wait)

        reminder_wait = await self._get_seconds_until_next_pending_reminder(now)
        if reminder_wait is not None:
            # 如果提醒已经到点，但检查器还处于手动延迟窗口内，
            # 提前每秒轮询也处理不了任何东西，只会制造日志风暴。
            if llm_wait is not None and reminder_wait <= 1.0 and llm_wait > 1.0:
                logger.info(
                    "Active Care: 最近提醒已到点，但 next_decision_ts 还有 %.0fs，"
                    "跳过 1s 轮询，直接睡到下次可决策时间",
                    llm_wait,
                )
            else:
                sleep_seconds = min(float(sleep_seconds), float(reminder_wait))

        return max(1.0, float(sleep_seconds))

    async def is_quiet_mode(self) -> bool:
        """检查是否处于安静模式（晚安后未确认入睡，或正在睡眠中，或专注模式中）"""
        try:
            state = await self._service.state_manager.sleep.get_current_state()
            sleep_active = bool(state.get("active"))
            last_goodnight_ts = float(state.get("last_goodnight_ts") or 0)
            reduced_mode_active = bool(state.get("reduced_mode_active"))
            quiet_mode = last_goodnight_ts > 0 and not sleep_active
            return quiet_mode or sleep_active or reduced_mode_active
        except Exception:
            return False

    def log_schedule_status(self, sleep_seconds: float):
        """记录调度状态"""
        now = time.time()
        next_decision_in = 0
        persona_schedule = {}
        if self._service.checker:
            next_decision_in = max(0, int(self._service.checker.next_decision_ts - now))
            persona_schedule = self._build_persona_schedule_snapshot(now)

        if now - self._service._last_schedule_log_ts >= 60:
            self._service._last_schedule_log_ts = now
            if persona_schedule:
                logger.info(
                    "Active Care 调度: next_in=%ss sleep=%ss per_persona=%s",
                    next_decision_in,
                    int(sleep_seconds),
                    persona_schedule,
                )
            else:
                logger.info(
                    "Active Care 调度: next_in=%ss sleep=%ss",
                    next_decision_in,
                    int(sleep_seconds),
                )

    def _build_persona_schedule_snapshot(self, now: float) -> dict[str, int]:
        """构建 per-persona 的剩余等待时间，帮助区分全局调度与单角色状态。"""
        checker = getattr(self._service, "checker", None)
        if checker is None:
            return {}
        try:
            persona_waits = {}
            for key in checker.get_all_persona_keys():
                ts = float(checker._next_decision_ts_by_persona.get(key, 0.0) or 0.0)
                if ts <= 0:
                    continue
                persona_waits[str(key)] = max(0, int(ts - now))
            return persona_waits
        except Exception:
            return {}
