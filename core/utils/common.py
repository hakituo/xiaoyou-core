#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用工具函数模块
提供各种常用的工具函数
"""


from core.utils.logger import get_logger
import os
import sys
from pathlib import Path

logger = get_logger(__name__)


def get_project_root() -> Path:
    """获取项目根目录

    优先级：
    1. XIAOYOU_PROJECT_ROOT 环境变量
    2. PyInstaller frozen 模式（可执行文件所在目录）
    3. 默认：本文件的上两级目录
    """
    env_root = os.environ.get("XIAOYOU_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


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
