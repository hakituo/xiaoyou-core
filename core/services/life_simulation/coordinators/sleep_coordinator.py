"""睡眠管理协调器。

封装 SleepManager 的睡眠状态查询、中断通知和恢复判定逻辑。
"""

from typing import Any, Dict, Optional

from core.services.life_simulation.sleep_manager import SleepManager


class SleepCoordinator:
    """睡眠管理协调器，负责角色睡眠状态与恢复判定。

    所有方法直接委托 SleepManager，不做额外包装调用，
    确保与原始 service.py 行为完全一致。
    """

    def __init__(self, sleep_manager: SleepManager):
        self._sleep_manager = sleep_manager

    @property
    def sleep_manager(self) -> SleepManager:
        return self._sleep_manager

    def get_sleep_state(self, role_id: str) -> Dict[str, Any]:
        """获取角色睡眠状态。"""
        return self._sleep_manager.get_summary(role_id)

    def get_sleep_summary(self, role_id: str) -> Dict[str, Any]:
        """获取角色睡眠摘要。"""
        return self._sleep_manager.get_summary(role_id)

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有角色的睡眠状态。"""
        return self._sleep_manager.get_all_states()

    def get_activity_override(
        self, role_id: str, now=None
    ) -> Optional[str]:
        """获取角色活动覆盖（睡眠/午睡等），可能返回 None。"""
        return self._sleep_manager.get_activity_override(role_id, now=now)

    def notify_sleep_interruption(
        self,
        role_id: str,
        message: str = "",
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """记录角色被吵醒。

        与原 service.py 行为一致：先调用 sleep_manager.notify_sleep_interruption
        获取 SleepRuntimeState，再调用 get_summary 返回摘要 dict。
        """
        state = self._sleep_manager.notify_sleep_interruption(
            role_id=role_id,
            message=message,
            conversation_id=conversation_id,
        )
        return self._sleep_manager.get_summary(state.role_id)

    def notify_sleep_chat_activity(
        self,
        role_id: str,
        message: str = "",
    ) -> Dict[str, Any]:
        """记录被吵醒后的继续聊天。

        与原 service.py 行为一致：先调用 sleep_manager.notify_sleep_chat_activity
        获取 SleepRuntimeState，再调用 get_summary 返回摘要 dict。
        """
        state = self._sleep_manager.notify_sleep_chat_activity(
            role_id=role_id,
            message=message,
        )
        return self._sleep_manager.get_summary(state.role_id)

    async def finalize_sleep_recovery_check(self, role_id: str) -> Dict[str, Any]:
        """执行静默窗口后的恢复判定。

        与原 service.py 行为一致：先调用 sleep_manager.finalize_sleep_recovery_check
        获取 SleepRuntimeState，再调用 get_summary 返回摘要 dict。
        """
        state = await self._sleep_manager.finalize_sleep_recovery_check(
            role_id=role_id
        )
        return self._sleep_manager.get_summary(state.role_id)
