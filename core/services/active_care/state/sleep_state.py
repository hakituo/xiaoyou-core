"""
睡眠状态管理器
负责管理用户的睡眠状态：入睡、起床、睡眠时长等
"""
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.services.active_care.state.base import StateBase, sync_to_async_wrapper
from core.services.active_care.shared.constants import StateKeys
from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time

logger = get_module_logger("SLEEP_STATE", "state_manager.log")


class SleepStateManager(StateBase):
    """
    睡眠状态管理器
    
    职责：
    1. 同步睡眠时间到状态存储
    2. 同步起床时间到状态存储
    3. 查询睡眠会话状态
    4. 计算睡眠时长
    """

    async def _save_state(self, updates: Dict[str, Any], immediate: bool = False) -> bool:
        """把睡眠事实写入用户级状态，而不是当前 persona 状态。"""
        try:
            storage = self._get_storage()
            await storage.save_user_sleep_state(updates, immediate=immediate)
            return True
        except Exception as e:
            logger.error(f"保存用户级睡眠状态失败: {e}")
            return False

    async def _get_state(self) -> Dict[str, Any]:
        """读取合并后的状态；用户级睡眠事实会覆盖 persona 的旧副本。"""
        try:
            storage = self._get_storage()
            return await storage.get_proactive_state()
        except Exception as e:
            logger.error(f"获取用户级睡眠状态失败: {e}")
            return {}
    
    async def sync_sleep_time(
        self,
        time_str: Optional[str] = None,
        target_date: Optional[str] = None,
        *,
        sleep_ts: Optional[float] = None,
    ) -> bool:
        try:
            now = time.time()
            
            if sleep_ts is not None:
                final_sleep_ts = sleep_ts
            elif time_str:
                final_sleep_ts = self._parse_sleep_time(time_str, target_date)
            else:
                final_sleep_ts = now
            
            state = await self._get_state()
            end_ts = self._safe_ts(state.get(StateKeys.LAST_SLEEP_SESSION_END_TS))
            
            duration = int(end_ts - final_sleep_ts) if end_ts > final_sleep_ts else 0
            if duration > 16 * 3600:
                duration = 0
            
            updates = {
                StateKeys.LAST_GOODNIGHT_TS: final_sleep_ts,
                StateKeys.LAST_GOODNIGHT_PROBE_TS: 0.0,
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: "goodnight",
                StateKeys.REDUCED_MODE_LABEL: "sleep",
                StateKeys.REDUCED_MODE_STARTED_TS: final_sleep_ts,
                StateKeys.LAST_USER_INTERACTION_TS: now,
                StateKeys.LAST_SLEEP_SESSION_START_TS: final_sleep_ts,
                StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS: duration,
            }
            
            await self._save_state(updates, immediate=True)
            logger.info(
                f"睡眠时间已同步: {time_str or 'now'} "
                f"(ts={final_sleep_ts:.0f}, duration={duration}s)"
            )
            return True
            
        except Exception as e:
            logger.error(f"同步睡眠时间失败: {e}")
            return False

    async def enter_low_disturbance_mode(
        self,
        *,
        started_ts: Optional[float] = None,
        source: str = "user_message",
    ) -> bool:
        """进入晚安低打扰，但不把聊天时刻当成真实入睡时间。"""
        now = time.time()
        final_ts = float(started_ts or now)
        updates = {
            StateKeys.LAST_GOODNIGHT_TS: final_ts,
            StateKeys.LAST_GOODNIGHT_PROBE_TS: 0.0,
            StateKeys.REDUCED_MODE_ACTIVE: True,
            StateKeys.REDUCED_MODE_REASON: "goodnight",
            StateKeys.REDUCED_MODE_LABEL: "sleep",
            StateKeys.REDUCED_MODE_STARTED_TS: final_ts,
            StateKeys.LAST_USER_INTERACTION_TS: now,
            StateKeys.LAST_LOW_DISTURBANCE_EXIT_SOURCE: "",
        }
        saved = await self._save_state(updates, immediate=True)
        if saved:
            logger.info("已进入晚安低打扰: ts=%.0f source=%s", final_ts, source)
        return saved

    async def exit_low_disturbance_mode(
        self,
        *,
        exit_ts: Optional[float] = None,
        source: str = "user_message",
    ) -> bool:
        """退出晚安低打扰，不改写 Samsung Health 的睡眠会话事实。"""
        final_ts = float(exit_ts or time.time())
        updates = {
            StateKeys.LAST_GOODNIGHT_TS: 0.0,
            StateKeys.LAST_GOODNIGHT_PROBE_TS: 0.0,
            StateKeys.REDUCED_MODE_ACTIVE: False,
            StateKeys.REDUCED_MODE_REASON: "none",
            StateKeys.REDUCED_MODE_LABEL: "",
            StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
            StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
            StateKeys.LAST_LOW_DISTURBANCE_EXIT_TS: final_ts,
            StateKeys.LAST_LOW_DISTURBANCE_EXIT_SOURCE: str(source or "unknown"),
        }
        saved = await self._save_state(updates, immediate=True)
        if saved:
            logger.info("已退出晚安低打扰: ts=%.0f source=%s", final_ts, source)
        return saved
    
    sync_sleep_time_sync = sync_to_async_wrapper(sync_sleep_time)
    
    async def sync_wakeup_time(
        self,
        time_str: Optional[str] = None,
        *,
        wakeup_ts: Optional[float] = None,
    ) -> bool:
        try:
            now = time.time()
            
            if wakeup_ts is not None:
                final_wakeup_ts = wakeup_ts
            elif time_str:
                final_wakeup_ts = self._parse_wakeup_time(time_str)
            else:
                final_wakeup_ts = now
            
            state = await self._get_state()
            start_ts = self._safe_ts(state.get(StateKeys.LAST_SLEEP_SESSION_START_TS))
            
            duration = (
                int(final_wakeup_ts - start_ts)
                if start_ts > 0 and final_wakeup_ts > start_ts
                else 0
            )
            if duration > 16 * 3600:
                duration = 0
            
            updates = {
                StateKeys.LAST_GOODMORNING_TS: final_wakeup_ts,
                StateKeys.LAST_GOODNIGHT_TS: 0.0,
                StateKeys.LAST_GOODNIGHT_PROBE_TS: 0.0,
                StateKeys.REDUCED_MODE_ACTIVE: False,
                StateKeys.REDUCED_MODE_REASON: "none",
                StateKeys.REDUCED_MODE_LABEL: "",
                StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
                StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
                StateKeys.LAST_SLEEP_SESSION_END_TS: final_wakeup_ts,
                StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS: duration,
            }
            
            await self._save_state(updates, immediate=True)
            logger.info(
                f"起床时间已同步: {time_str or 'now'} "
                f"(ts={final_wakeup_ts:.0f}, duration={duration}s)"
            )
            return True
            
        except Exception as e:
            logger.error(f"同步起床时间失败: {e}")
            return False
    
    sync_wakeup_time_sync = sync_to_async_wrapper(sync_wakeup_time)
    
    async def get_current_state(self) -> Dict[str, Any]:
        try:
            state = await self._get_state()
            
            last_goodnight_ts = self._safe_ts(state.get(StateKeys.LAST_GOODNIGHT_TS))
            last_goodmorning_ts = self._safe_ts(state.get(StateKeys.LAST_GOODMORNING_TS))
            reduced_mode_active = bool(state.get(StateKeys.REDUCED_MODE_ACTIVE))
            
            sleep_session_active = self.is_sleep_session_active_from_state(
                last_goodnight_ts, last_goodmorning_ts
            )
            quiet_mode = last_goodnight_ts > 0 and not sleep_session_active
            
            now = time.time()
            current_duration = 0
            if sleep_session_active and last_goodnight_ts > 0:
                current_duration = int(now - last_goodnight_ts)
            
            return {
                "active": sleep_session_active,
                "last_goodnight_ts": last_goodnight_ts,
                "last_goodmorning_ts": last_goodmorning_ts,
                "duration_seconds": current_duration,
                "reduced_mode_active": reduced_mode_active,
                "reduced_mode_reason": str(state.get(StateKeys.REDUCED_MODE_REASON) or "none"),
                "quiet_mode": quiet_mode,
            }
            
        except Exception as e:
            logger.error(f"获取睡眠状态失败: {e}")
            return {
                "active": False,
                "last_goodnight_ts": 0.0,
                "last_goodmorning_ts": 0.0,
                "duration_seconds": 0,
                "reduced_mode_active": False,
                "reduced_mode_reason": "none",
                "quiet_mode": False,
            }
    
    @staticmethod
    def is_sleep_session_active_from_state(
        last_goodnight_ts: float, last_goodmorning_ts: float
    ) -> bool:
        """统一判断睡眠会话是否活跃"""
        return last_goodnight_ts > 0 and last_goodmorning_ts < last_goodnight_ts
    
    async def reset(self) -> bool:
        updates = {
            StateKeys.LAST_GOODNIGHT_TS: 0.0,
            StateKeys.LAST_GOODMORNING_TS: 0.0,
            StateKeys.LAST_GOODNIGHT_PROBE_TS: 0.0,
            StateKeys.LAST_SLEEP_SESSION_START_TS: 0.0,
            StateKeys.LAST_SLEEP_SESSION_END_TS: 0.0,
            StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS: 0,
            StateKeys.REDUCED_MODE_ACTIVE: False,
            StateKeys.REDUCED_MODE_REASON: "none",
            StateKeys.REDUCED_MODE_LABEL: "",
            StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
            StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
        }
        return await self._save_state(updates)
    
    def _parse_sleep_time(
        self,
        time_str: str,
        target_date: Optional[str] = None,
    ) -> float:
        try:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1])

            if target_date:
                date_parts = target_date.split("-")
                dt = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]), h, m)
            else:
                now = get_current_time()
                if h >= 18:
                    # 晚上18点后睡觉，用当天日期
                    dt = datetime(now.year, now.month, now.day, h, m)
                elif h < 6:
                    # 凌晨0-6点睡觉，判断是当天还是前一天
                    candidate_today = datetime(now.year, now.month, now.day, h, m)
                    candidate_yesterday = candidate_today - timedelta(days=1)
                    if (now - candidate_today).total_seconds() < 3600:
                        dt = candidate_today
                    else:
                        dt = candidate_yesterday
                elif 6 <= h < 9:
                    # 6-9点睡觉：可能是熬夜到凌晨的用户，也可能是白天补觉
                    # 如果当前时间接近这个时间（1小时内），用当天；否则归到前一天
                    candidate_today = datetime(now.year, now.month, now.day, h, m)
                    if (now - candidate_today).total_seconds() < 3600:
                        dt = candidate_today
                    else:
                        dt = candidate_today - timedelta(days=1)
                else:
                    # 9-18点睡觉：白天补觉，归到前一天（因为这是"昨晚"的延续）
                    candidate_today = datetime(now.year, now.month, now.day, h, m)
                    dt = candidate_today - timedelta(days=1)

            return dt.timestamp()

        except Exception as e:
            logger.warning(f"解析睡眠时间失败 '{time_str}': {e}")
            return time.time()
    
    def _parse_wakeup_time(self, time_str: str) -> float:
        try:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            
            now = get_current_time()
            candidate_today = datetime(now.year, now.month, now.day, h, m)
            
            if h >= 18:
                dt = candidate_today - timedelta(days=1)
            elif h < 6:
                if (now - candidate_today).total_seconds() < 0:
                    dt = candidate_today - timedelta(days=1)
                else:
                    dt = candidate_today
            else:
                dt = candidate_today
            
            return dt.timestamp()
            
        except Exception as e:
            logger.warning(f"解析起床时间失败 '{time_str}': {e}")
            return time.time()
    
    async def update_probe_ts(self, ts: Optional[float] = None) -> bool:
        return await self._save_state({
            StateKeys.LAST_GOODNIGHT_PROBE_TS: ts or time.time()
        })
