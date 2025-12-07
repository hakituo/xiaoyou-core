#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础适配器类，提供模型适配器的通用功能
所有特定类型的适配器（文本、图像、视觉等）都应该继承此类
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging
from core.utils.performance_tracker import PerformanceTracker

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """
    模型适配器基类，提供通用的模型管理功能
    """
    
    def __init__(self, model_manager, adapter_type: str, default_model_name: str):
        """
        初始化适配器
        
        Args:
            model_manager: 模型管理器实例
            adapter_type: 适配器类型（如'text', 'image', 'vision'等）
            default_model_name: 默认模型名称
        """
        self.model_manager = model_manager
        self.adapter_type = adapter_type
        self._model_name = default_model_name
        self._is_loaded = False
        self._performance_tracker = PerformanceTracker(f"{adapter_type}_adapter")
    
    @abstractmethod
    def _register_model(self):
        """
        注册模型到模型管理器
        子类必须实现此方法
        """
        pass
    
    def load_model(self) -> bool:
        """
        加载模型到内存
        
        Returns:
            bool: 加载是否成功
        """
        try:
            # 确保模型已注册
            self._register_model()
            
            # 准备加载参数
            load_kwargs = self._prepare_model_load_params()
            
            # 确保模型管理器有_model_locks属性
            if not hasattr(self.model_manager, '_model_locks'):
                logger.warning(f"模型管理器缺少_model_locks属性，正在创建")
                self.model_manager._model_locks = {}
            
            # 确保当前模型有锁
            if self._model_name not in self.model_manager._model_locks:
                logger.warning(f"模型 {self._model_name} 缺少锁，正在创建")
                import threading
                self.model_manager._model_locks[self._model_name] = threading.Lock()
            
            # 加载模型
            model = self.model_manager.load_model(self._model_name, **load_kwargs)
            
            if model:
                self._is_loaded = True
                logger.info(f"{self.adapter_type.capitalize()} model '{self._model_name}' loaded successfully")
                return True
            else:
                logger.error(f"Failed to load {self.adapter_type} model: {self._model_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error loading {self.adapter_type} model: {str(e)}")
            # 打印完整的异常堆栈以进行调试
            import traceback
            logger.error(f"Exception details: {traceback.format_exc()}")
            return False
    
    def _prepare_model_load_params(self) -> Dict[str, Any]:
        """
        准备模型加载参数
        子类可以覆盖此方法以提供特定的加载参数
        
        Returns:
            Dict: 模型加载参数
        """
        return {}
    
    def _ensure_model_loaded(self) -> bool:
        """
        确保模型已加载，如果未加载则尝试加载
        
        Returns:
            bool: 模型是否已加载
        """
        if not self._is_loaded:
            return self.load_model()
        return True
    
    def unload_model(self) -> bool:
        """
        卸载模型以释放内存
        
        Returns:
            bool: 卸载是否成功
        """
        try:
            if self._is_loaded:
                result = self.model_manager.unload_model(self._model_name)
                if result:
                    self._is_loaded = False
                    logger.info(f"{self.adapter_type.capitalize()} model '{self._model_name}' unloaded successfully")
                return result
            return True
        except Exception as e:
            logger.error(f"Error unloading {self.adapter_type} model: {str(e)}")
            return False
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        获取性能统计信息
        
        Returns:
            Dict: 性能统计信息
        """
        return self._performance_tracker.get_stats()
    
    def set_model_name(self, model_name: str):
        """
        设置要使用的模型名称
        
        Args:
            model_name: 新的模型名称
        """
        if self._model_name != model_name:
            # 如果模型已加载，需要先卸载
            if self._is_loaded:
                self.unload_model()
            self._model_name = model_name
    
    @property
    def is_loaded(self) -> bool:
        """
        检查模型是否已加载
        
        Returns:
            bool: 模型是否已加载
        """
        return self._is_loaded
    
    @property
    def model_name(self) -> str:
        """
        获取当前使用的模型名称
        
        Returns:
            str: 模型名称
        """
        return self._model_name