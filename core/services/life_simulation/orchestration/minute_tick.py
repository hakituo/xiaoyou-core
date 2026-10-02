"""生命模拟的每分钟任务职责（从 orchestrator.py 拆出）。

一分钟一次的角色状态衰减、过期食物清理、自动进食，
以及把「用户睡眠窗口」上报给日记统一调度入口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.utils.time_utils import get_current_time

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

logger = get_logger("LIFE_SIMULATION")


class LifeMinuteTickMixin:
    """每分钟执行的衰减与维护任务。"""

    async def _process_minute_tick(self, state: dict[str, Any], now: float) -> None:
        """每分钟执行的衰减与维护任务。"""
        if state["activity"] not in ["sleeping", "idle"]:
            self.active_minutes_today += 1

        sleep_summary = self.sleep_coordinator.get_sleep_summary(
            self._resolve_primary_role_id()
        )
        self.life_stats_manager.update_sleep_metrics(sleep_summary)
        self.life_stats_manager.decay_stats(
            str(state.get("activity") or "idle"),
            sleep_summary=sleep_summary,
        )
        self.life_stats_manager.decay_shyness()
        self.life_stats_manager.apply_sickness_penalty()

        self.actor_coordinator.tick_all_actors(
            str(state.get("activity") or "idle"),
            activity_by_role=state.get("activity_by_role"),
        )

        try:
            self.food_coordinator.cleanup_expired_food()
        except Exception as e:  # noqa: BLE001 - 单项维护失败不能中断本轮 tick
            logger.warning(f"清理过期食物失败: {e}")
        try:
            await self.food_coordinator.maybe_auto_eat(now)
        except Exception as e:  # noqa: BLE001 - 单项维护失败不能中断本轮 tick
            logger.warning(f"自动进食失败: {e}")
        try:
            self._report_diary_backfill_window(get_current_time())
        except Exception as e:  # noqa: BLE001 - 单项维护失败不能中断本轮 tick
            if is_debug_enabled("life_simulation"):
                logger.info(f"上报日记补写窗口失败: {e}")

        self.last_minute_check = now

        today = get_current_time().strftime("%Y-%m-%d")
        if today != self._active_minutes_date:
            self.active_minutes_today = 0
            self._active_minutes_date = today

    def _report_diary_backfill_window(self, now_dt: datetime) -> None:
        """把「用户是否睡着 + 当前时刻」报给日记统一调度入口。

        2026-09-27 收敛：这里原先自己维护了一份角色名单（写死 aveline/ling）、
        一套日期归属推理和 force 策略，等于在 nightly 之外又造了一套日记调度，
        注册角色摘掉 ling 后仍每天给她补写日记。

        现在本模块只提供本域事实（用户睡眠状态），
        「补不补、补谁、用不用 force」全部由 journal 的调度入口决定。
        """
        from core.services.journal.daily_summary_dispatch import (
            schedule_backfill_after_sleep,
        )

        from ..service_state_helpers import is_user_in_sleep_quiet

        schedule_backfill_after_sleep(now_dt, is_sleeping=is_user_in_sleep_quiet())
