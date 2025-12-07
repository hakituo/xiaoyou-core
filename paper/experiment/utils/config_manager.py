#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一配置管理模块
为实验脚本提供集中的配置管理、错误处理和日志记录功能
"""

import os
import json
import logging
import traceback
from typing import Dict, Any, Optional, Union
from datetime import datetime


class ConfigManager:
    """
    统一配置管理器
    功能：
    1. 集中管理配置项
    2. 支持配置文件、环境变量和默认值
    3. 提供统一的错误处理和日志记录
    4. 确保目录结构一致性
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径（可选）
        """
        self._config = {}
        self._defaults = self._get_default_config()
        self._logger = self._setup_logger()
        
        # 加载配置
        if config_file and os.path.exists(config_file):
            self._load_config_file(config_file)
        
        # 加载环境变量
        self._load_env_vars()
        
        # 合并默认配置
        self._merge_defaults()
        
        # 确保必要的目录存在
        self._ensure_directories()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'result_dir': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'experiment_results', 'data'),
            'picture_dir': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'experiment_results', 'charts'),
            'log_dir': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs'),
            
            # 实验配置
            'max_concurrency': 50,
            'task_timeout': 300,
            'retry_count': 3,
            'retry_delay': 1.0,
            
            # 系统监控配置
            'monitor_interval': 1.0,
            'max_memory_percent': 80.0,
            'max_cpu_percent': 90.0,
            
            # 缓存配置
            'cache_max_size': 100,
            'cache_ttl': 300,
            
            # 日志配置
            'log_level': 'INFO',
            'log_file': True,
        }
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('experiment')
        logger.setLevel(logging.DEBUG)
        
        # 清空已有的handler
        logger.handlers.clear()
        
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def _load_config_file(self, config_file: str):
        """从配置文件加载配置"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                self._config.update(file_config)
                self.log_info(f"成功加载配置文件: {config_file}")
        except Exception as e:
            self.log_error(f"加载配置文件失败: {str(e)}")
    
    def _load_env_vars(self):
        """从环境变量加载配置"""
        env_mapping = {
            'RESULT_DIR': 'result_dir',
            'PICTURE_DIR': 'picture_dir',
            'LOG_DIR': 'log_dir',
            'MAX_CONCURRENCY': ('max_concurrency', int),
            'TASK_TIMEOUT': ('task_timeout', int),
            'RETRY_COUNT': ('retry_count', int),
            'LOG_LEVEL': 'log_level',
        }
        
        for env_var, config_key in env_mapping.items():
            if env_var in os.environ:
                if isinstance(config_key, tuple):
                    key, converter = config_key
                    try:
                        self._config[key] = converter(os.environ[env_var])
                    except (ValueError, TypeError):
                        self.log_warning(f"环境变量转换失败: {env_var}")
                else:
                    self._config[config_key] = os.environ[env_var]
    
    def _merge_defaults(self):
        """合并默认配置"""
        for key, value in self._defaults.items():
            if key not in self._config:
                self._config[key] = value
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        directories = [
            self._config['result_dir'],
            self._config['picture_dir'],
            self._config['log_dir'],
        ]
        
        for directory in directories:
            try:
                os.makedirs(directory, exist_ok=True)
                self.log_debug(f"确保目录存在: {directory}")
            except Exception as e:
                self.log_error(f"创建目录失败: {directory} - {str(e)}")
    
    def setup_file_logger(self):
        """设置文件日志记录"""
        if self._config.get('log_file', True):
            log_dir = self._config['log_dir']
            log_filename = f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            log_path = os.path.join(log_dir, log_filename)
            
            try:
                file_handler = logging.FileHandler(log_path, encoding='utf-8')
                log_level = getattr(logging, self._config.get('log_level', 'INFO'), logging.INFO)
                file_handler.setLevel(log_level)
                
                file_formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                file_handler.setFormatter(file_formatter)
                
                self._logger.addHandler(file_handler)
                self.log_info(f"文件日志已设置: {log_path}")
            except Exception as e:
                self.log_error(f"设置文件日志失败: {str(e)}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        self._config[key] = value
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self._config.copy()
    
    def log_debug(self, message: str):
        """记录调试日志"""
        self._logger.debug(message)
    
    def log_info(self, message: str):
        """记录信息日志"""
        self._logger.info(message)
    
    def log_warning(self, message: str):
        """记录警告日志"""
        self._logger.warning(message)
    
    def log_error(self, message: str, exception: Optional[Exception] = None):
        """记录错误日志"""
        if exception:
            full_message = f"{message}\n{traceback.format_exc()}"
        else:
            full_message = message
        self._logger.error(full_message)
    
    def log_critical(self, message: str, exception: Optional[Exception] = None):
        """记录严重错误日志"""
        if exception:
            full_message = f"{message}\n{traceback.format_exc()}"
        else:
            full_message = message
        self._logger.critical(full_message)
    
    def handle_exception(self, exception: Exception, context: str = "") -> bool:
        """统一处理异常
        
        Args:
            exception: 捕获的异常
            context: 异常发生的上下文
            
        Returns:
            bool: 是否应该继续执行
        """
        error_type = type(exception).__name__
        error_message = str(exception)
        
        self.log_error(f"在{context}时发生{error_type}: {error_message}", exception)
        
        # 根据异常类型决定是否继续执行
        if isinstance(exception, (KeyboardInterrupt, SystemExit)):
            return False
        
        # 资源不足类异常
        if "memory" in error_message.lower() or "resource" in error_message.lower():
            self.log_warning("资源不足，建议降低并发或增加系统资源")
            return False
        
        return True
    
    def get_result_file_path(self, experiment_name: str, extension: str = "json") -> str:
        """获取结果文件路径
        
        Args:
            experiment_name: 实验名称
            extension: 文件扩展名
            
        Returns:
            str: 完整的文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{experiment_name}_{timestamp}.{extension}"
        return os.path.join(self._config['result_dir'], filename)
    
    def get_picture_file_path(self, experiment_name: str, filename: str = "") -> str:
        """获取图片文件路径
        
        Args:
            experiment_name: 实验名称
            filename: 文件名（可选）
            
        Returns:
            str: 完整的文件路径
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{experiment_name}_{timestamp}.png"
        return os.path.join(self._config['picture_dir'], filename)


class ExperimentError(Exception):
    """实验异常基类"""
    pass


class ConfigurationError(ExperimentError):
    """配置错误异常"""
    pass


class ResourceError(ExperimentError):
    """资源不足异常"""
    pass


class TaskError(ExperimentError):
    """任务执行异常"""
    pass


# 创建全局配置管理器实例
config_manager = None

def get_config() -> ConfigManager:
    """获取配置管理器实例（单例模式）"""
    global config_manager
    if config_manager is None:
        config_manager = ConfigManager()
        config_manager.setup_file_logger()
    return config_manager


def setup_config(config_file: Optional[str] = None):
    """设置配置文件并初始化配置管理器"""
    global config_manager
    config_manager = ConfigManager(config_file)
    config_manager.setup_file_logger()
    return config_manager
