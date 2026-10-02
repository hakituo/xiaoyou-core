#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务生命周期辅助函数
"""

from core.utils.logger import get_logger
import os


logger = get_logger(__name__)


def _is_env_enabled(env_var: str) -> bool:
    """检查环境变量是否为启用状态"""
    return str(os.getenv(env_var, "")).strip().lower() in {"1", "true", "yes", "on"}


async def shutdown_all_services():
    """关闭所有服务（用于信号处理）"""
    from core.core_engine.lifecycle_manager import get_lifecycle_manager
    lifecycle = get_lifecycle_manager()
    await lifecycle.shutdown_all()
