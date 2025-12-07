#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
"""
import logging
import os
from typing import Dict, Any, Optional
from .data_manager import DataManager

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    配置管理器
    负责加载、管理和提供系统配置
    """
    
    def __init__(self, initial_config: Optional[Dict[str, Any]] = None):
        """
        初始化配置管理器
        
        Args:
            initial_config: 初始配置
        """
        # 初始化数据管理器
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        self.data_manager = DataManager(data_dir)
        
        # 从文件加载配置
        loaded_config = self.data_manager.load_config()
        self._config = loaded_config or (initial_config or {})
        
        self._default_config = {
            "server": {
                "host": "0.0.0.0",
                "port": 8000,
                "reload": False,
                "workers": 1
            },
            "model": {
                "path": os.path.join(os.path.dirname(__file__), "..", "models"),
                "max_models": 2,
                "memory_threshold": 0.7
            },
            "log": {
                "level": "info",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            },
            "data": {
                "path": data_dir
            }
        }
        
        # 合并默认配置
        self._merge_configs()
        
        logger.info("ConfigManager initialized")
    
    def _merge_configs(self):
        """
        合并配置
        """
        def merge_dict(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
            """
            递归合并字典
            """
            for key, value in b.items():
                if key in a and isinstance(a[key], dict) and isinstance(value, dict):
                    a[key] = merge_dict(a[key], value)
                else:
                    a[key] = value
            return a
        
        # 合并默认配置到初始配置
        self._config = merge_dict(self._default_config.copy(), self._config)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点分隔符，如 "server.host"
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        keys = key.split(".")
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_all_config(self) -> Dict[str, Any]:
        """
        获取所有配置
        
        Returns:
            完整配置字典
        """
        return self._config.copy()
    
    def update(self, key: str, value: Any):
        """
        更新配置
        
        Args:
            key: 配置键，支持点分隔符
            value: 配置值
        """
        keys = key.split(".")
        config = self._config
        
        for i, k in enumerate(keys[:-1]):
            if k not in config:
                config[k] = {}
            elif not isinstance(config[k], dict):
                # 如果中间键对应的值不是字典，创建新的字典结构
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
        logger.info(f"Config updated: {key} = {value}")
        
        # 保存配置到文件
        self.data_manager.save_config(self._config)
    
    def load_from_env(self):
        """
        从环境变量加载配置
        """
        prefix = "AI_CORE_"
        
        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                # 转换环境变量名为配置键
                config_key = env_key[len(prefix):].lower().replace("_", ".")
                
                # 尝试转换值类型
                try:
                    value: Any
                    if env_value.lower() in ["true", "false"]:
                        value = env_value.lower() == "true"
                    elif env_value.isdigit():
                        value = int(env_value)
                    elif "." in env_value and all(part.isdigit() for part in env_value.split(".")):
                        value = float(env_value)
                    else:
                        value = env_value
                    
                    self.update(config_key, value)
                    logger.info(f"Loaded config from env: {config_key} = {value}")
                except Exception as e:
                    logger.warning(f"Failed to parse env var {env_key}: {e}")
