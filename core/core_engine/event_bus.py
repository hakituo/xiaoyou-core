import asyncio
import logging
from typing import Callable, Dict, List, Any, Optional, Set
from functools import wraps
import inspect
logger = logging.getLogger(__name__)
class EventBus:
    """
    事件总线系统，用于实现模块间的解耦通信
    支持：
    - 异步事件发布和订阅
    - 事件过滤器
    - 优先级订阅
    - 异常隔离
    - 事件链和组合
    """
    def __init__(self):
        # 存储事件订阅关系 {event_name: [(handler, priority, filter_func)]}
        self._subscribers: Dict[str, List[tuple]] = {}
        # 保护_subscribers的锁
        # asyncio.RLock不可用，使用asyncio.Lock替代
        self._lock = asyncio.Lock()
        # 事件处理中的异常处理器
        self._error_handlers: List[Callable] = []
        # 事件执行超时设置
        self._default_timeout: Optional[float] = 30.0
        # 事件处理统计
        self._stats: Dict[str, Dict] = {}
    async def subscribe(self, event_name: str, handler: Callable, 
                        priority: int = 0, filter_func: Optional[Callable] = None) -> None:
        """
        订阅事件
        Args:
            event_name: 事件名称
            handler: 事件处理函数（可以是同步或异步）
            priority: 优先级（数字越小优先级越高）
            filter_func: 过滤器函数，如果返回True才会执行handler
        """
        if not callable(handler):
            raise TypeError("处理器必须是可调用对象")
        async with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
                self._stats[event_name] = {"published": 0, "handled": 0, "errors": 0}
            # 添加到订阅列表
            self._subscribers[event_name].append((handler, priority, filter_func))
            # 按优先级排序
            self._subscribers[event_name].sort(key=lambda x: x[1])
        logger.debug(f"事件订阅成功: {event_name} -> {handler.__name__}")
    async def unsubscribe(self, event_name: str, handler: Callable) -> None:
        """
        取消订阅事件
        Args:
            event_name: 事件名称
            handler: 要取消的处理函数
        """
        async with self._lock:
            if event_name in self._subscribers:
                self._subscribers[event_name] = [
                    sub for sub in self._subscribers[event_name] 
                    if sub[0] != handler
                ]
                # 如果没有订阅者了，清理
                if not self._subscribers[event_name]:
                    del self._subscribers[event_name]
                    del self._stats[event_name]
        logger.debug(f"事件取消订阅: {event_name} -> {handler.__name__}")
    async def publish(self, event_name: str, **kwargs) -> Dict[str, Any]:
        """
        发布事件
        Args:
            event_name: 事件名称
            **kwargs: 事件数据
        Returns:
            Dict: 包含处理结果的字典
        """
        handlers = []
        async with self._lock:
            # 更新统计信息
            if event_name in self._stats:
                self._stats[event_name]["published"] += 1
            # 获取所有订阅者的快照，避免在处理过程中修改列表
            if event_name in self._subscribers:
                handlers = self._subscribers[event_name].copy()
        results = []
        errors = []
        for handler, _, filter_func in handlers:
            # 应用过滤器
            if filter_func and not filter_func(**kwargs):
                continue
            try:
                # 执行处理函数（支持同步和异步）
                if inspect.iscoroutinefunction(handler):
                    # 异步函数
                    if self._default_timeout:
                        result = await asyncio.wait_for(
                            handler(**kwargs), 
                            timeout=self._default_timeout
                        )
                    else:
                        result = await handler(**kwargs)
                else:
                    # 同步函数
                    result = handler(**kwargs)
                results.append({
                    "handler": handler.__name__,
                    "result": result,
                    "success": True
                })
                # 更新统计
                if event_name in self._stats:
                    self._stats[event_name]["handled"] += 1
            except Exception as e:
                error_info = {
                    "handler": handler.__name__,
                    "error": str(e),
                    "success": False
                }
                errors.append(error_info)
                # 更新错误统计
                if event_name in self._stats:
                    self._stats[event_name]["errors"] += 1
                logger.error(f"事件处理错误: {event_name} -> {handler.__name__}: {str(e)}", exc_info=True)
                # 调用全局错误处理器
                for error_handler in self._error_handlers:
                    try:
                        if inspect.iscoroutinefunction(error_handler):
                            await error_handler(event_name, handler, e, **kwargs)
                        else:
                            error_handler(event_name, handler, e, **kwargs)
                    except Exception as handler_error:
                        logger.error(f"错误处理器本身出错: {str(handler_error)}", exc_info=True)
        return {
            "event_name": event_name,
            "results": results,
            "errors": errors,
            "success": len(errors) == 0
        }
    async def clear(self) -> None:
        """
        清除所有订阅
        """
        async with self._lock:
            self._subscribers.clear()
            self._stats.clear()
        logger.info("事件总线已清空所有订阅")
# 装饰器：将函数标记为事件处理器
# 全局事件总线实例
_global_event_bus = EventBus()

# 预定义事件类型（推荐使用）
class EventTypes:
    """预定义事件类型枚举"""
    # 系统事件
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"
    
    # 对话事件
    CHAT_START = "chat.start"
    CHAT_END = "chat.end"
    MESSAGE_SEND = "message.send"
    MESSAGE_RECEIVE = "message.receive"
    
    # 任务事件
    TASK_SCHEDULE = "task.schedule"
    TASK_START = "task.start"
    TASK_COMPLETE = "task.complete"
    TASK_ERROR = "task.error"
    
    # 内存事件
    MEMORY_SAVE = "memory.save"
    MEMORY_RETRIEVE = "memory.retrieve"
    
    # LLM事件
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_ERROR = "llm.error"

def get_event_bus() -> EventBus:
    """
    获取全局事件总线实例
    Returns:
        EventBus实例
    """
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus

def event_handler(event_name: str, priority: int = 0, filter_func: Optional[Callable] = None):
    """
    事件处理器装饰器 - 简化事件订阅
    
    Args:
        event_name: 事件名称
        priority: 优先级（数字越小优先级越高）
        filter_func: 过滤器函数
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        # 标记函数为事件处理器
        setattr(func, "__event_handler__", True)
        setattr(func, "__event_name__", event_name)
        setattr(func, "__priority__", priority)
        setattr(func, "__filter_func__", filter_func)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 异步包装器
            return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 同步包装器
            return func(*args, **kwargs)
        
        # 根据函数类型返回对应的包装器
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator