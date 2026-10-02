"""Active Care 启动推断处理器
负责启动时的延迟检查和睡眠推断
"""
import time
import asyncio

from core.utils.logger import get_module_logger
from core.utils.config_accessor import get_active_care_config

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")


class StartupHandler:
    """启动推断处理器，负责启动时的延迟检查和睡眠推断"""

    def __init__(self, service):
        """Args:
            service: ActiveCareService 实例，用于访问其属性和方法
        """
        self._service = service

    async def run_startup_check(self):
        """启动时检查（强制用 startup_delay 覆盖存储里的旧值）"""
        if not self._service.checker:
            return
        try:
            now = time.time()

            # probable_sleep 启动推断已于 2026-07-30 移除：
            # 程序重启后用户可能只是关了程序去做别的事，不能据此推断为睡觉。
            # 作息数据应由 UIE 从用户消息（早安/晚安）中抽取，或由 AI 调用
            # update_sleep_record 工具显式修正。

            startup_delay = get_active_care_config(
                "active_care_startup_delay_seconds", default=180, settings=self._service.settings
            )
            startup_delay = max(60, int(startup_delay or 180))

            quiet_mode = await self._is_quiet_mode()
            if quiet_mode:
                quiet_check_interval = get_active_care_config(
                    "quiet_check_interval", default=600, settings=self._service.settings
                )
                wait_seconds = max(startup_delay, quiet_check_interval)
                await self._service.checker.set_next_decision_ts(
                    time.time() + float(wait_seconds), source="startup_quiet_mode"
                )
                logger.info(
                    "Active Care: 启动时处于安静/睡眠模式，下次检查在 %ds 后",
                    int(wait_seconds),
                )
                return

            old_remaining = None
            if self._service.checker.next_decision_ts > now:
                old_remaining = int(self._service.checker.next_decision_ts - now)

            await self._service.checker.set_next_decision_ts(
                now + float(startup_delay), source="startup_delay"
            )

            if old_remaining is not None:
                logger.info(
                    "Active Care: 启动时设置延迟检查（覆盖存储旧值），旧剩余=%ds，新延迟=%ds",
                    old_remaining, startup_delay,
                )
            else:
                logger.info(
                    "Active Care: 启动时设置延迟检查，将在 %ds 后执行第一次决策",
                    startup_delay,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Active Care startup check error: {e}")

    async def _is_quiet_mode(self) -> bool:
        """检查是否处于安静模式"""
        try:
            state = await self._service.state_manager.sleep.get_current_state()
            sleep_active = bool(state.get("active"))
            last_goodnight_ts = float(state.get("last_goodnight_ts") or 0)
            reduced_mode_active = bool(state.get("reduced_mode_active"))
            quiet_mode = last_goodnight_ts > 0 and not sleep_active
            return quiet_mode or sleep_active or reduced_mode_active
        except Exception:
            return False

