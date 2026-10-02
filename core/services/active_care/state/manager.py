"""
统一状态管理器
整合睡眠、专注、模式等所有状态管理
"""
import asyncio
import threading
import time
from typing import Any, Dict, Optional

from core.services.active_care.state.base import StateBase
from core.services.active_care.state.sleep_state import SleepStateManager
from core.services.active_care.state.focus_state import FocusStateManager
from core.services.active_care.state.mode_state import ModeStateManager
from core.utils.logger import get_module_logger

logger = get_module_logger("STATE_MANAGER", "state_manager.log")


class StateManager(StateBase):
    """
    统一状态管理器
    
    整合所有状态管理：
    - 睡眠状态 (SleepStateManager)
    - 专注/学习状态 (FocusStateManager)
    - 模式状态 (ModeStateManager)
    
    提供统一的接口来管理所有用户状态
    """
    
    def __init__(self, storage=None):
        super().__init__(storage)
        
        # 初始化子管理器
        self._sleep_state = SleepStateManager(storage)
        self._focus_state = FocusStateManager(storage)
        self._mode_state = ModeStateManager(storage)
    
    @property
    def sleep(self) -> SleepStateManager:
        """获取睡眠状态管理器"""
        return self._sleep_state
    
    @property
    def focus(self) -> FocusStateManager:
        """获取专注状态管理器"""
        return self._focus_state
    
    @property
    def mode(self) -> ModeStateManager:
        """获取模式状态管理器"""
        return self._mode_state
    
    async def get_current_state(self) -> Dict[str, Any]:
        """
        获取所有状态的汇总
        
        Returns:
            {
                "sleep": {...},
                "focus": {...},
                "mode": {...},
                "summary": str,
            }
        """
        try:
            sleep_state = await self._sleep_state.get_current_state()
            focus_state = await self._focus_state.get_current_state()
            mode_state = await self._mode_state.get_current_state()
            
            # 生成摘要
            summary_parts = []
            if sleep_state.get("active"):
                summary_parts.append("睡眠中")
            elif focus_state.get("active"):
                summary_parts.append(f"专注中({focus_state.get('reason')})")
            else:
                summary_parts.append(f"模式:{mode_state.get('mode')}")
            
            return {
                "sleep": sleep_state,
                "focus": focus_state,
                "mode": mode_state,
                "summary": " | ".join(summary_parts),
            }
            
        except Exception as e:
            logger.error(f"获取状态汇总失败: {e}")
            return {
                "sleep": {},
                "focus": {},
                "mode": {},
                "summary": "未知",
            }
    
    async def reset(self) -> bool:
        """
        重置所有状态
        
        Returns:
            bool: 是否全部重置成功
        """
        results = await asyncio.gather(
            self._sleep_state.reset(),
            self._focus_state.reset(),
            self._mode_state.reset(),
            return_exceptions=True,
        )
        return all(r is True for r in results if not isinstance(r, Exception))
    
    async def reset_all(self) -> bool:
        """
        重置所有状态（reset 的别名，语义更清晰）
        
        Returns:
            bool: 是否全部重置成功
        """
        return await self.reset()
    
    async def process_user_message(
        self,
        text: str,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        处理用户消息，检测并更新状态
        
        这是状态管理的核心方法，自动检测用户消息中的意图并更新状态
        
        Args:
            text: 用户消息
            now_ts: 当前时间戳，默认使用当前时间
            
        Returns:
            {
                "intent": Dict,       # 检测到的意图
                "updates": Dict,      # 状态更新
                "sleep_changed": bool,
                "focus_changed": bool,
                "mode_changed": bool,
            }
        """
        now = now_ts or time.time()
        try:
            intent = await self._mode_state.detect_transition_intent(text)
            return await self.apply_transition_intent(intent, now_ts=now)
        except Exception as e:
            logger.error(f"处理用户消息失败: {e}")
            return {
                "intent": {},
                "updates": {},
                "sleep_changed": False,
                "focus_changed": False,
                "mode_changed": False,
            }

    async def apply_transition_intent(
        self,
        intent: Dict[str, Any],
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """应用已经识别出的模式切换意图，避免调用方重复运行 BERT。"""
        now = now_ts or time.time()
        result = {
            "intent": dict(intent or {}),
            "updates": {},
            "sleep_changed": False,
            "focus_changed": False,
            "mode_changed": False,
        }
        
        try:
            action = str(intent.get("action") or "none")
            reason = str(intent.get("reason") or "none")
            
            if action == "enter_reduced":
                if reason == "goodnight":
                    # 聊天只切换低打扰；真实入睡时间由 Samsung Health 同步。
                    await self._sleep_state.enter_low_disturbance_mode(
                        started_ts=now,
                        source="user_message",
                    )
                    result["sleep_changed"] = True
                elif reason in ["focus", "study", "work"]:
                    # 进入专注模式
                    duration = intent.get("expected_end_ts", 0) - now
                    if duration < 0:
                        duration = 0
                    await self._focus_state.enter_focus_mode(
                        reason=reason,
                        label=str(intent.get("label") or "focus"),
                        duration_seconds=int(duration) if duration > 0 else None,
                    )
                    result["focus_changed"] = True
                else:
                    # 其他减少模式
                    updates = self._mode_state.build_state_updates(intent, now)
                    await self._save_state(updates)
                    result["updates"] = updates
                result["mode_changed"] = True
                
            elif action == "exit_reduced":
                if reason == "morning":
                    # “我起来了”只恢复正常打扰，不写正式起床时间。
                    await self._sleep_state.exit_low_disturbance_mode(
                        exit_ts=now,
                        source="user_message",
                    )
                    result["sleep_changed"] = True
                elif reason == "done":
                    # 退出专注模式
                    await self._focus_state.exit_focus_mode()
                    result["focus_changed"] = True
                else:
                    # 其他退出
                    updates = self._mode_state.build_state_updates(intent, now)
                    await self._save_state(updates)
                    result["updates"] = updates
                result["mode_changed"] = True
            
            return result
            
        except Exception as e:
            logger.error(f"应用用户状态意图失败: {e}")
            return result
    
    async def check_expired_states(self) -> Dict[str, bool]:
        """
        检查并处理过期的状态
        
        Returns:
            {
                "sleep_expired": bool,
                "focus_expired": bool,
            }
        """
        results = {
            "sleep_expired": False,
            "focus_expired": False,
        }
        
        try:
            # 检查专注模式是否过期
            results["focus_expired"] = await self._focus_state.check_expired()
            
            # 检查睡眠模式是否过期（超过14小时）
            sleep_state = await self._sleep_state.get_current_state()
            if sleep_state.get("active"):
                duration = sleep_state.get("duration_seconds", 0)
                if duration > 14 * 3600:  # 超过14小时
                    await self._sleep_state.exit_low_disturbance_mode(
                        source="automatic_timeout"
                    )
                    results["sleep_expired"] = True
                    logger.info("睡眠模式已超过14小时，自动退出")
            
            return results
            
        except Exception as e:
            logger.error(f"检查过期状态失败: {e}")
            return results
    
    async def get_state_for_prompt(self) -> str:
        """
        获取用于提示的状态描述
        
        Returns:
            str: 状态描述文本
        """
        try:
            state = await self.get_current_state()
            
            parts = []
            
            # 睡眠状态
            if state["sleep"].get("active"):
                duration = state["sleep"].get("duration_seconds", 0)
                h = duration // 3600
                m = (duration % 3600) // 60
                if h > 0:
                    parts.append(f"用户已睡眠 {h}小时{m}分钟")
                else:
                    parts.append(f"用户已睡眠 {m}分钟")
            
            # 专注状态
            elif state["focus"].get("active"):
                elapsed = state["focus"].get("elapsed_seconds", 0)
                remaining = state["focus"].get("remaining_seconds", 0)
                reason = state["focus"].get("reason", "focus")
                reason_cn = {"focus": "专注", "study": "学习", "work": "工作"}.get(reason, reason)
                if remaining > 0:
                    r_min = remaining // 60
                    parts.append(f"用户正在{reason_cn}中，预计还有 {r_min} 分钟")
                else:
                    e_min = elapsed // 60
                    parts.append(f"用户正在{reason_cn}中，已持续 {e_min} 分钟")
            
            # 模式状态
            mode = state["mode"].get("mode", "daily")
            mode_cn = {
                "daily": "日常模式",
                "study_teaching": "学习模式",
                "low_presence": "低打扰模式",
            }.get(mode, mode)
            parts.append(f"当前模式: {mode_cn}")
            
            return " | ".join(parts)
            
        except Exception as e:
            logger.error(f"获取状态描述失败: {e}")
            return "状态未知"


# 全局单例
_state_manager: Optional[StateManager] = None
_state_manager_lock = threading.Lock()


def get_state_manager() -> StateManager:
    """获取状态管理器单例（线程安全）"""
    global _state_manager
    if _state_manager is None:
        with _state_manager_lock:
            if _state_manager is None:
                _state_manager = StateManager()
    return _state_manager


# 为了向后兼容，提供旧的接口
def get_sleep_state_manager() -> SleepStateManager:
    """获取睡眠状态管理器（向后兼容）"""
    return get_state_manager().sleep
