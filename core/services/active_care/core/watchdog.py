"""Active Care 看门狗与维护
负责看门狗循环（监控主循环存活）和维护循环（过期状态检查、生词测验）
"""
import time
import asyncio

from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")


class WatchdogManager:
    """看门狗与维护管理器"""

    def __init__(self, service):
        """Args:
            service: ActiveCareService 实例，用于访问其属性和方法
        """
        self._service = service

    async def run_maintenance_loop(self):
        """维护循环"""
        await asyncio.sleep(300)
        while self._service._running:
            try:
                # 检查过期状态
                expired = await self._service.state_manager.check_expired_states()
                if expired.get("focus_expired") or expired.get("sleep_expired"):
                    logger.info(f"Active Care: 状态已过期并自动退出 - {expired}")

                # 检查并推送每日生词测验
                try:
                    await self._service.vocab.check_daily_word_quiz()
                except Exception as e:
                    logger.warning(f"Active Care: 每日生词测验推送失败: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Active Care maintenance loop error: {e}")
            await asyncio.sleep(3600)

    async def run_watchdog_loop(self):
        """看门狗循环：监控主循环是否存活，自动重启已死亡的任务"""
        await asyncio.sleep(60)
        while self._service._running:
            try:
                now = time.time()

                if self._service._proactive_task is None or self._service._proactive_task.done():
                    if self._service._proactive_task is not None:
                        if self._service._proactive_task.cancelled():
                            logger.warning(
                                "Active Care 看门狗: _proactive_task 已被取消"
                            )
                        else:
                            exc = self._service._proactive_task.exception()
                            if exc:
                                logger.error(
                                    "Active Care 看门狗: _proactive_task 异常退出: %s", exc
                                )
                            else:
                                logger.warning(
                                    "Active Care 看门狗: "
                                    "_proactive_task 正常退出但服务仍在运行"
                                )

                    self._service._loop_restart_count += 1
                    logger.warning(
                        "Active Care 看门狗: 正在重启 _proactive_task (第%d次重启)",
                        self._service._loop_restart_count,
                    )
                    self._service._proactive_task = asyncio.create_task(self._service._proactive_loop())

                if self._service._maintenance_task is None or self._service._maintenance_task.done():
                    logger.warning(
                        "Active Care 看门狗: 正在重启 _maintenance_task"
                    )
                    self._service._maintenance_task = asyncio.create_task(
                        self._service._maintenance_loop()
                    )

                if self._service._last_loop_iteration_ts > 0:
                    elapsed_since_iteration = now - self._service._last_loop_iteration_ts
                    if self._service._expected_wakeup_ts > 0:
                        overdue_seconds = max(0.0, now - self._service._expected_wakeup_ts)
                    else:
                        overdue_seconds = elapsed_since_iteration

                    loop_phase_seconds = (
                        now - self._service._loop_phase_started_ts
                        if self._service._loop_phase_started_ts > 0
                        else 0.0
                    )

                    if overdue_seconds > 600:
                        logger.error(
                            "Active Care 看门狗: 主循环可能卡死"
                            " (overdue=%ds, elapsed=%ds, expected_wakeup_in=%ds, "
                            "phase=%s, phase_elapsed=%ds, lock.locked=%s)",
                            int(overdue_seconds),
                            int(elapsed_since_iteration),
                            int(self._service._expected_wakeup_ts - now)
                            if self._service._expected_wakeup_ts > 0 else 0,
                            self._service._loop_phase,
                            int(loop_phase_seconds),
                            self._service._proactive_lock.locked(),
                        )
                        if self._service._proactive_task and not self._service._proactive_task.done():
                            logger.error(
                                "Active Care 看门狗: 取消并重启卡住的 _proactive_task "
                                "(phase=%s)",
                                self._service._loop_phase,
                            )
                            self._service._proactive_task.cancel()
                            try:
                                await asyncio.wait_for(self._service._proactive_task, timeout=5)
                            except asyncio.TimeoutError:
                                logger.error(
                                    "Active Care 看门狗: 旧 _proactive_task 取消超时，"
                                    "仍将拉起新主循环"
                                )
                            except asyncio.CancelledError:
                                pass
                            except Exception as e:
                                logger.warning(
                                    "Active Care 看门狗: 旧 _proactive_task 退出异常: %s",
                                    e,
                                )

                            self._service._loop_restart_count += 1
                            self._service._expected_wakeup_ts = 0.0
                            self._service._proactive_task = asyncio.create_task(
                                self._service._proactive_loop()
                            )
                    elif overdue_seconds > 300:
                        logger.warning(
                            "Active Care 看门狗: 主循环响应缓慢"
                            " (overdue=%ds, elapsed=%ds, expected_wakeup_in=%ds, "
                            "phase=%s, phase_elapsed=%ds, lock.locked=%s)",
                            int(overdue_seconds),
                            int(elapsed_since_iteration),
                            int(self._service._expected_wakeup_ts - now)
                            if self._service._expected_wakeup_ts > 0 else 0,
                            self._service._loop_phase,
                            int(loop_phase_seconds),
                            self._service._proactive_lock.locked(),
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Active Care watchdog error: {e}")

            await asyncio.sleep(120)
