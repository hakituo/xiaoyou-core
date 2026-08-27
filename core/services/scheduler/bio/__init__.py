"""
生物系统模块
负责生物系统的状态管理
"""

from .bio_state import build_biological_status
from .bio_system_manager import BioSystemManager

__all__ = ['build_biological_status', 'BioSystemManager']
