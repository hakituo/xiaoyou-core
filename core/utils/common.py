#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用工具函数模块
提供各种常用的工具函数
"""


from core.utils.logger import get_logger
from core.utils.project_root import get_project_root  # noqa: F401 - 兼容旧的导入路径
import os

logger = get_logger(__name__)


def ensure_directory(directory_path: str) -> bool:
    """确保目录存在，如果不存在则创建

    Args:
        directory_path: 目录路径

    Returns:
        是否成功创建或目录已存在
    """
    try:
        os.makedirs(directory_path, exist_ok=True)
        logger.debug(f"确保目录存在: {directory_path}")
        return True
    except Exception as e:
        logger.error(f"创建目录失败: {directory_path}, 错误: {e}")
        return False
