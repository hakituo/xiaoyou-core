"""
状态管理模块
统一管理用户状态：睡眠、专注/学习、模式切换等
"""
from core.services.active_care.state.base import StateBase
from core.services.active_care.state.sleep_state import SleepStateManager
from core.services.active_care.state.focus_state import FocusStateManager
from core.services.active_care.state.mode_state import ModeStateManager
from core.services.active_care.state.manager import StateManager, get_state_manager, get_sleep_state_manager

__all__ = [
    "StateBase",
    "SleepStateManager",
    "FocusStateManager",
    "ModeStateManager",
    "StateManager",
    "get_state_manager",
    "get_sleep_state_manager",
]
