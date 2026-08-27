#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置访问工具类
提供统一的配置访问接口，消除嵌套 getattr 调用
"""
from typing import Any


class ConfigAccessor:
    """
    配置访问器
    
    提供统一的配置访问接口，避免嵌套 getattr 调用
    
    使用方式：
        from core.utils.config_accessor import get_config
        
        # 获取嵌套配置
        value = get_config("life_simulation.active_care_min_gap_seconds", default=600)
        
        # 获取用户显示名称
        name = get_user_display_name()
    """
    
    _settings = None
    
    @classmethod
    def _get_settings(cls):
        """延迟加载配置"""
        if cls._settings is None:
            from config.integrated_config import get_settings
            cls._settings = get_settings()
        return cls._settings
    
    @classmethod
    def get(
        cls,
        path: str,
        default: Any = None,
        *,
        settings: Any = None,
    ) -> Any:
        """
        通过路径获取配置值
        
        Args:
            path: 配置路径，用点号分隔（如 "life_simulation.active_care_min_gap_seconds"）
            default: 默认值
            settings: 配置对象（可选，默认使用全局配置）
            
        Returns:
            配置值，未找到返回默认值
            
        Examples:
            >>> get_config("life_simulation.active_care_min_gap_seconds", default=600)
            600
            >>> get_config("user.display_name", default="用户")
            "用户"
        """
        obj = settings or cls._get_settings()
        if obj is None:
            return default
        
        parts = path.split(".")
        
        for part in parts:
            if obj is None:
                return default
            
            # 尝试多种获取方式
            if hasattr(obj, part):
                obj = getattr(obj, part, default)
            elif isinstance(obj, dict):
                obj = obj.get(part, default)
            else:
                return default
        
        return obj if obj is not None else default


# ==================== 便捷函数 ====================

def get_config(path: str, default: Any = None, *, settings: Any = None) -> Any:
    """
    通过路径获取配置值
    
    Args:
        path: 配置路径，用点号分隔
        default: 默认值
        settings: 配置对象（可选）
        
    Returns:
        配置值
    """
    return ConfigAccessor.get(path, default=default, settings=settings)


# ==================== 常用配置快捷访问 ====================

def get_user_display_name(settings: Any = None) -> str:
    """获取用户显示名称"""
    name = get_config("user.display_name", default="", settings=settings)
    return str(name or "").strip() or "用户"


def get_active_care_config(key: str, default: Any = None, settings: Any = None) -> Any:
    """
    获取 Active Care 配置
    
    Args:
        key: 配置键名（不含 life_simulation 前缀）
        default: 默认值
        settings: 配置对象
        
    Returns:
        
        配置值
        
    Examples:
        >>> get_active_care_config("active_care_min_gap_seconds", default=600)
        600
    """
    return get_config(f"life_simulation.{key}", default=default, settings=settings)
