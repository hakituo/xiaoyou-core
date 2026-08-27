#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源管理器 - 兼容层
此文件保留用于向后兼容，所有功能已迁移到 core.resource 模块
"""

from core.utils.logger import get_logger


# 从新模块导入所有内容
from core.resource.manager import (
    ResourceManager,
    get_resource_manager,
    get_global_resource_manager,
    shutdown_global_resource_manager,
    get_current_memory_usage,
    cleanup_memory,
    is_system_under_memory_pressure,
)

# 导入依赖的类型和枚举
from core.contracts import ResourceType
from core.resource_components import (
    ResourcePriority,
    ResourceState,
    ResourceThreshold,
    ResourceMonitor,
    ModelResource,
)

logger = get_logger(__name__)

# 保持原有的便捷函数
__all__ = [
    "ResourceManager",
    "get_resource_manager",
    "get_global_resource_manager",
    "shutdown_global_resource_manager",
    "get_current_memory_usage",
    "cleanup_memory",
    "is_system_under_memory_pressure",
    "ResourcePriority",
    "ResourceState",
    "ResourceThreshold",
    "ResourceMonitor",
    "ModelResource",
    "ResourceType",
]

# 模块版本
__version__ = "2.0.0"
