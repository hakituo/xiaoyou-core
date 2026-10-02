#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源管理配置模块
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class ResourceConfig:
    """资源配置类"""
    
    # 基础配置
    auto_optimization: bool = True
    max_memory_usage_percent: float = 99.0
    max_cpu_usage_percent: float = 98.0
    max_gpu_memory_usage_percent: float = 98.0
    min_free_memory_mb: int = 128
    model_unload_timeout: int = 300
    aggressive_cleanup_threshold: float = 98.0
    monitor_interval: float = 1.0
    cache_size_limit_mb: int = 256
    auto_precision_adjust: bool = True
    low_memory_mode: bool = True
    cache_cleanup_interval: int = 300
    
    # 清理冷却时间（秒）
    cleanup_cooldown: Dict[str, float] = field(default_factory=lambda: {
        "emergency": 12.0,
        "critical": 6.0,
        "regular": 3.0,
    })
    
    # 典型显存占用映射 (MB)
    typical_vram_usage: Dict[str, int] = field(default_factory=lambda: {
        "llm_engine": 5800,
        "image_gen_module": 4200,
        "vision_module": 1200,
        "tts_engine": 450,
        "stt_engine": 300,
        "embedding_model": 150,
    })
    
    @classmethod
    def from_dict(cls, config: Optional[Dict[str, Any]] = None) -> "ResourceConfig":
        """从字典创建配置"""
        if config is None:
            return cls()
        
        instance = cls()
        for key, value in config.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        return instance
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "auto_optimization": self.auto_optimization,
            "max_memory_usage_percent": self.max_memory_usage_percent,
            "max_cpu_usage_percent": self.max_cpu_usage_percent,
            "max_gpu_memory_usage_percent": self.max_gpu_memory_usage_percent,
            "min_free_memory_mb": self.min_free_memory_mb,
            "model_unload_timeout": self.model_unload_timeout,
            "aggressive_cleanup_threshold": self.aggressive_cleanup_threshold,
            "monitor_interval": self.monitor_interval,
            "cache_size_limit_mb": self.cache_size_limit_mb,
            "auto_precision_adjust": self.auto_precision_adjust,
            "low_memory_mode": self.low_memory_mode,
            "cache_cleanup_interval": self.cache_cleanup_interval,
            "cleanup_cooldown": self.cleanup_cooldown,
            "typical_vram_usage": self.typical_vram_usage,
        }
