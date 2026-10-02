"""生命模拟的生命周期与主监控循环（从 orchestrator.py 拆出）。"""

from __future__ import annotations

import asyncio
import time

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

logger = get_logger("LIFE_SIMULATION")


class LifeRuntimeMixin:
    """监控任务的启停与每秒主循环。"""

    async def start(self) -> None:
        """启动监控任务。"""
        await self.start_monitor()

    async def stop(self) -> None:
        """停止监控任务。"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("Life Simulation service stopped")

    async def start_monitor(self) -> None:
        """启动监控循环。"""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Life Simulation monitor task started")

    @property
    def is_running(self) -> bool:
        return self._monitor_task is not None and not self._monitor_task.done()

    async def _monitor_loop(self) -> None:
        """每秒执行的监控循环。"""
        ws_manager = self.websocket_coordinator.ws_manager
        logger.info(
            "Life Simulation monitor loop started. "
            f"WebSocket Manager: {id(ws_manager)}"
        )

        while True:
            try:
                self.food_coordinator.tick_digestion()
                await self.health_monitor.maybe_poll_health()
                state = self.build_state()

                await self._apply_emotion_influence(state)

                now = time.time()
                if now - self.last_minute_check >= 60:
                    await self._process_minute_tick(state, now)

                await self.websocket_coordinator.broadcast_state(state)

                ritual = self.reaction_coordinator.check_rituals(
                    self.active_minutes_today
                )
                if ritual:
                    if is_debug_enabled("life_simulation"):
                        logger.info(f"Triggering ritual: {ritual}")
                    await self.websocket_coordinator.broadcast_ritual(ritual)

                reaction = await self.reaction_coordinator.check_spontaneous_reaction(
                    state, self.last_interaction_time
                )

                if reaction:
                    if is_debug_enabled("life_simulation"):
                        logger.info(f"Triggering spontaneous reaction: {reaction}")
                    await self.websocket_coordinator.broadcast_reaction(reaction)
                    self.reaction_coordinator.record_reaction()

                self._consecutive_errors = 0

            except Exception as e:
                self._consecutive_errors += 1
                backoff = min(1.0 * (2 ** min(self._consecutive_errors - 1, 5)), 30.0)
                logger.error(  # noqa: G201 - 保持原有 error + exc_info 输出格式
                    f"Error in life simulation monitor (连续第{self._consecutive_errors}次, "
                    f"退避{backoff:.1f}s): {e}",
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(1)
