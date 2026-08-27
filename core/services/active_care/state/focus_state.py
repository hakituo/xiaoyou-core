"""
专注/学习状态管理器
负责管理用户的专注模式、学习模式状态
"""
import time
from typing import Any, Dict, Optional

from core.services.active_care.state.base import StateBase, sync_to_async_wrapper
from core.services.active_care.shared.constants import (
    FocusEnterKeywords,
    FocusExitKeywords,
    is_focus_presence_statement,
    extract_duration_seconds,
    StateKeys,
)
from core.utils.logger import get_module_logger

logger = get_module_logger("FOCUS_STATE", "state_manager.log")


class FocusStateManager(StateBase):
    """
    专注/学习状态管理器
    
    职责：
    1. 进入专注模式
    2. 退出专注模式
    3. 解析专注时长
    4. 检测专注意图
    """
    
    async def enter_focus_mode(
        self,
        reason: str = "focus",
        label: str = "focus",
        duration_seconds: Optional[int] = None,
    ) -> bool:
        try:
            now = time.time()
            expected_end_ts = 0.0
            if duration_seconds and duration_seconds > 0:
                expected_end_ts = now + duration_seconds
            
            updates = {
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: reason,
                StateKeys.REDUCED_MODE_LABEL: label,
                StateKeys.REDUCED_MODE_STARTED_TS: now,
                StateKeys.REDUCED_MODE_EXPECTED_END_TS: expected_end_ts,
            }
            
            await self._save_state(updates)
            logger.info(
                f"已进入专注模式: reason={reason}, label={label}, "
                f"duration={duration_seconds}s"
            )
            return True
            
        except Exception as e:
            logger.error(f"进入专注模式失败: {e}")
            return False
    
    enter_focus_mode_sync = sync_to_async_wrapper(enter_focus_mode)
    
    async def exit_focus_mode(self) -> bool:
        try:
            updates = {
                StateKeys.REDUCED_MODE_ACTIVE: False,
                StateKeys.REDUCED_MODE_REASON: "none",
                StateKeys.REDUCED_MODE_LABEL: "",
                StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
                StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
            }
            
            await self._save_state(updates)
            logger.info("已退出专注模式")
            return True
            
        except Exception as e:
            logger.error(f"退出专注模式失败: {e}")
            return False
    
    exit_focus_mode_sync = sync_to_async_wrapper(exit_focus_mode)
    
    async def get_current_state(self) -> Dict[str, Any]:
        try:
            state = await self._get_state()
            
            active = bool(state.get(StateKeys.REDUCED_MODE_ACTIVE))
            reason = str(state.get(StateKeys.REDUCED_MODE_REASON) or "none")
            
            if reason not in ["focus", "study", "work"]:
                active = False
            
            started_ts = self._safe_ts(state.get(StateKeys.REDUCED_MODE_STARTED_TS))
            expected_end_ts = self._safe_ts(state.get(StateKeys.REDUCED_MODE_EXPECTED_END_TS))
            label = str(state.get(StateKeys.REDUCED_MODE_LABEL) or "")
            
            now = time.time()
            elapsed_seconds = int(now - started_ts) if active and started_ts > 0 else 0
            remaining_seconds = int(expected_end_ts - now) if expected_end_ts > now else 0
            
            return {
                "active": active,
                "reason": reason,
                "label": label,
                "started_ts": started_ts,
                "expected_end_ts": expected_end_ts,
                "elapsed_seconds": elapsed_seconds,
                "remaining_seconds": remaining_seconds,
            }
            
        except Exception as e:
            logger.error(f"获取专注状态失败: {e}")
            return {
                "active": False,
                "reason": "none",
                "label": "",
                "started_ts": 0.0,
                "expected_end_ts": 0.0,
                "elapsed_seconds": 0,
                "remaining_seconds": 0,
            }
    
    async def reset(self) -> bool:
        return await self.exit_focus_mode()
    
    def detect_enter_intent(self, text: str) -> Optional[Dict[str, Any]]:
        lower = str(text or "").strip().lower()
        
        for kw in FocusEnterKeywords.ALL:
            if kw in lower:
                duration = extract_duration_seconds(text)
                return {
                    "reason": "focus",
                    "label": "focus",
                    "duration_seconds": duration,
                }
        
        if is_focus_presence_statement(text):
            duration = extract_duration_seconds(text)
            return {
                "reason": "focus",
                "label": "focus",
                "duration_seconds": duration,
            }
        
        return None
    
    def detect_exit_intent(self, text: str) -> bool:
        lower = str(text or "").strip().lower()
        return any(kw in lower for kw in FocusExitKeywords.ALL)
    
    async def check_expired(self) -> bool:
        try:
            state = await self._get_state()
            
            active = bool(state.get(StateKeys.REDUCED_MODE_ACTIVE))
            reason = str(state.get(StateKeys.REDUCED_MODE_REASON) or "none")
            
            if not active or reason not in ["focus", "study", "work"]:
                return False
            
            expected_end_ts = self._safe_ts(state.get(StateKeys.REDUCED_MODE_EXPECTED_END_TS))
            if expected_end_ts <= 0:
                return False
            
            now = time.time()
            if now >= expected_end_ts:
                await self.exit_focus_mode()
                logger.info("专注模式已过期，自动退出")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"检查专注模式过期失败: {e}")
            return False
