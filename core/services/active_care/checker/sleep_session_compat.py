"""
主动关怀检查器 - 睡眠会话兼容 mixin

提供睡眠会话相关方法的兼容垫片，所有方法都委托给 self._sleep_session_manager。
ProactiveChecker 通过继承此 mixin 保持向后兼容（外部代码可能直接调用
checker._process_sleep_session_state 等方法）。

实现方式：mixin 类，方法体不变，仍转发到 self._sleep_session_manager。
"""
from typing import Dict

from core.services.active_care.core.sleep_session_manager import SleepSessionManager


class SleepSessionCompatMixin:
    """睡眠会话兼容 mixin

    所有方法都是委托给 self._sleep_session_manager 的兼容垫片，
    ProactiveChecker 继承此 mixin 以保持向后兼容。
    子类必须先实例化 self._sleep_session_manager 再调用这些方法。
    """

    async def _process_sleep_session_state(
        self,
        now: float,
        state_data: Dict,
        inferred_goodnight: bool,
        inferred_goodmorning: bool,
        inferred_ts: float,
        inferred_text: str,
        workspace_snapshot: Dict,
        is_assistant_goodnight: bool = False,
        inferred_sleep_hint: bool = False,
    ) -> Dict:
        """处理睡眠会话状态更新（转发到 SleepSessionManager）"""
        return await self._sleep_session_manager._process_sleep_session_state(
            now, state_data, inferred_goodnight, inferred_goodmorning, inferred_ts,
            inferred_text, workspace_snapshot,
            is_assistant_goodnight=is_assistant_goodnight,
            inferred_sleep_hint=inferred_sleep_hint,
        )

    async def _try_exit_goodnight_on_awake_signals(
        self,
        now: float,
        state_data: Dict,
        reduced_mode_active: bool,
        reduced_mode_reason: str,
        inferred_goodmorning: bool,
        inferred_awake_presence: bool,
        inferred_signal_after_goodnight: bool,
        recent_user_signal_after_goodnight: bool,
        current_last_goodnight_ts: float,
        latest_user_signal_ts: float,
        inferred_ts: float,
    ) -> Dict:
        """检测清醒信号并尝试退出晚安模式（转发到 SleepSessionManager）"""
        return await self._sleep_session_manager._try_exit_goodnight_on_awake_signals(
            now, state_data, reduced_mode_active, reduced_mode_reason,
            inferred_goodmorning, inferred_awake_presence, inferred_signal_after_goodnight,
            recent_user_signal_after_goodnight, current_last_goodnight_ts,
            latest_user_signal_ts, inferred_ts,
        )

    async def _try_enter_goodnight_on_intent(
        self,
        now: float,
        state_data: Dict,
        inferred_goodnight: bool,
        inferred_goodmorning: bool,
        inferred_ts: float,
        is_assistant_goodnight: bool = False,
    ) -> Dict:
        """检测晚安意图并尝试进入晚安模式（转发到 SleepSessionManager）"""
        return await self._sleep_session_manager._try_enter_goodnight_on_intent(
            now, state_data, inferred_goodnight, inferred_goodmorning, inferred_ts,
            is_assistant_goodnight=is_assistant_goodnight,
        )

    async def _try_infer_probable_sleep(
        self,
        now: float,
        state_data: Dict,
        inferred_goodnight: bool,
        inferred_goodmorning: bool,
        inferred_awake_presence: bool,
        latest_user_signal_ts: float,
        inferred_sleep_hint: bool = False,
    ) -> Dict:
        """处理 sleep_hint 模式的进入与退出（转发到 SleepSessionManager）

        注：probable_sleep 已于 2026-07-30 移除，方法名保留以兼容调用签名。
        """
        return await self._sleep_session_manager._try_infer_probable_sleep(
            now, state_data, inferred_goodnight, inferred_goodmorning,
            inferred_awake_presence, latest_user_signal_ts,
            inferred_sleep_hint=inferred_sleep_hint,
        )

    @staticmethod
    def _is_adaptive_daytime(now_hour: int, adaptive_params: Dict) -> bool:
        """根据自适应参数判断当前是否为白天（转发到 SleepSessionManager）"""
        return SleepSessionManager._is_adaptive_daytime(now_hour, adaptive_params)

    async def _clear_disabled_reduced_modes(
        self,
        state_data: Dict,
        reduced_mode_active: bool,
        reduced_mode_reason: str,
    ) -> tuple:
        """清理被配置禁用的 reduced mode（转发到 SleepSessionManager）"""
        return await self._sleep_session_manager._clear_disabled_reduced_modes(
            state_data, reduced_mode_active, reduced_mode_reason
        )

    @staticmethod
    def _check_signal_after_goodnight(
        latest_user_signal_ts: float, last_goodnight_ts: float
    ) -> bool:
        """检查用户信号是否在晚安之后（转发到 SleepSessionManager）"""
        return SleepSessionManager._check_signal_after_goodnight(
            latest_user_signal_ts, last_goodnight_ts
        )

    async def _exit_goodnight_mode(
        self, state_data: Dict, now: float, wakeup_ts: float
    ) -> Dict:
        """退出晚安模式并归档睡眠会话（转发到 SleepSessionManager）"""
        return await self._sleep_session_manager._exit_goodnight_mode(
            state_data, now, wakeup_ts
        )

    async def _sync_goodnight_sleep_to_daily_record(
        self, state_data: Dict, wakeup_ts: float
    ):
        """将晚安模式的睡眠/起床时间同步到 Daily Record（转发到 SleepSessionManager）"""
        return await self._sleep_session_manager._sync_goodnight_sleep_to_daily_record(
            state_data, wakeup_ts
        )
    # _sync_probable_sleep_to_daily_record 已于 2026-07-30 移除（probable_sleep 机制删除）
