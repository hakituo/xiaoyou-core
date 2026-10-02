"""
状态管理基类
提供状态管理的通用接口和工具方法
"""
import asyncio
import concurrent.futures
from functools import wraps
from abc import ABC, abstractmethod
from typing import Any, Dict

from core.utils.logger import get_module_logger
from core.utils.timestamp_utils import safe_timestamp, is_plausible_timestamp

logger = get_module_logger("STATE_BASE", "state_manager.log")


class StateBase(ABC):
    """
    状态管理基类
    
    所有状态管理器都继承此类，提供统一的接口
    """
    
    def __init__(self, storage=None):
        """
        初始化状态管理器
        
        Args:
            storage: ActiveCareStorage 实例（延迟加载）
        """
        self._storage = storage
    
    def _get_storage(self):
        """延迟加载 ActiveCareStorage"""
        if self._storage is None:
            from core.services.active_care.storage.storage import ActiveCareStorage
            self._storage = ActiveCareStorage()
        return self._storage
    
    def _safe_ts(self, value: Any) -> float:
        """
        安全地将值转换为时间戳（兼容旧代码）
        
        Args:
            value: 时间戳值（可能是毫秒或秒）
            
        Returns:
            float: 秒级时间戳
        """
        return safe_timestamp(value)
    
    def _is_plausible_ts(self, ts: float, now: float) -> bool:
        """
        检查时间戳是否合理（兼容旧代码）
        
        Args:
            ts: 待检查的时间戳
            now: 当前时间戳
            
        Returns:
            bool: 时间戳是否合理
        """
        return is_plausible_timestamp(ts, now)
    
    async def _save_state(self, updates: Dict[str, Any], immediate: bool = False) -> bool:
        """
        保存状态到存储
        
        Args:
            updates: 要更新的状态键值对
            immediate: 是否立即写入磁盘
            
        Returns:
            bool: 是否保存成功
        """
        try:
            storage = self._get_storage()
            await storage.save_proactive_state(updates, immediate=immediate)
            return True
        except Exception as e:
            logger.error(f"保存状态失败: {e}")
            return False
    
    async def _get_state(self) -> Dict[str, Any]:
        """
        获取当前状态
        
        Returns:
            Dict: 当前状态数据
        """
        try:
            storage = self._get_storage()
            return await storage.get_proactive_state()
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            return {}
    
    @abstractmethod
    async def get_current_state(self) -> Dict[str, Any]:
        """
        获取当前状态（子类实现）
        
        Returns:
            Dict: 当前状态的摘要信息
        """
        pass
    
    @abstractmethod
    async def reset(self) -> bool:
        """
        重置状态（子类实现）
        
        Returns:
            bool: 是否重置成功
        """
        pass


def sync_to_async_wrapper(async_func):
    """
    将异步函数包装为同步函数的装饰器

    用于在同步上下文中调用异步方法。
    如果当前线程已经在运行事件循环，不能再把协程塞回同一个循环后同步等待，
    否则会把事件循环线程阻塞到超时。这里改为在独立线程中创建新事件循环执行。
    """

    @wraps(async_func)
    def wrapper(self, *args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

                    def _run_in_new_loop():
                        return asyncio.run(async_func(self, *args, **kwargs))

                    return executor.submit(_run_in_new_loop).result(timeout=30.0)
            except Exception as e:
                logger.error(f"同步包装器执行失败: {e!r}", exc_info=True)
                return False
        else:
            try:
                return asyncio.run(async_func(self, *args, **kwargs))
            except Exception as e:
                logger.error(f"同步包装器执行失败: {e!r}", exc_info=True)
                return False
    return wrapper
