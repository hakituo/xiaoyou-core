from core.utils.logger import get_logger
import asyncio

from typing import Callable, Dict, List, Any, Optional
from functools import wraps
import inspect

logger = get_logger(__name__)


class EventBus:
    """
    事件总线系统，用于实现模块间的解耦通信
    支持：
    - 异步事件发布和订阅
    - 事件过滤器
    - 优先级订阅
    - 异常隔离
    - 装饰器注册
    """

    def __init__(self):
        self._subscribers: Dict[str, List[tuple]] = {}
        self._lock: Optional[asyncio.Lock] = None
        self._error_handlers: List[Callable] = []
        self._stats: Dict[str, Dict[str, int]] = {}
        self._default_timeout: Optional[float] = None

    async def _ensure_lock(self) -> asyncio.Lock:
        """确保 Lock 存在（懒加载，避免无 EventLoop 时创建）"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def on(
        self,
        event_name: str,
        priority: int = 0,
        filter_func: Optional[Callable] = None,
    ):
        """装饰器方式订阅事件

        用法:
            @event_bus.on("system.shutdown")
            async def handle_shutdown(**kwargs):
                ...

        Args:
            event_name: 事件名称
            priority: 优先级（数字越小优先级越高）
            filter_func: 过滤器函数
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

            setattr(wrapper, "__event_handler__", True)
            setattr(wrapper, "__event_name__", event_name)
            setattr(wrapper, "__priority__", priority)
            setattr(wrapper, "__filter_func__", filter_func)
            setattr(wrapper, "__original_func__", func)

            self._auto_subscribe(event_name, wrapper, priority, filter_func)
            return wrapper

        return decorator

    def _auto_subscribe(self, event_name: str, handler: Callable, priority: int, filter_func: Optional[Callable]):
        """同步注册订阅（用于装饰器场景，实际订阅延迟到首次 publish 时确认）"""
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
            self._stats[event_name] = {"published": 0, "handled": 0, "errors": 0}
        self._subscribers[event_name].append((handler, priority, filter_func))
        self._subscribers[event_name].sort(key=lambda x: x[1])

    async def subscribe(
        self,
        event_name: str,
        handler: Callable,
        priority: int = 0,
        filter_func: Optional[Callable] = None,
    ) -> None:
        """订阅事件

        Args:
            event_name: 事件名称
            handler: 事件处理函数（可以是同步或异步）
            priority: 优先级（数字越小优先级越高）
            filter_func: 过滤器函数，如果返回True才会执行handler
        """
        if not callable(handler):
            raise TypeError("处理器必须是可调用对象")

        lock = await self._ensure_lock()
        async with lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
                self._stats[event_name] = {"published": 0, "handled": 0, "errors": 0}
            self._subscribers[event_name].append((handler, priority, filter_func))
            self._subscribers[event_name].sort(key=lambda x: x[1])
        logger.debug(f"事件订阅成功: {event_name} -> {handler.__name__}")

    async def unsubscribe(self, event_name: str, handler: Callable) -> None:
        """取消订阅事件

        Args:
            event_name: 事件名称
            handler: 要取消的处理函数
        """
        lock = await self._ensure_lock()
        async with lock:
            if event_name in self._subscribers:
                self._subscribers[event_name] = [
                    sub for sub in self._subscribers[event_name] if sub[0] != handler
                ]
                if not self._subscribers[event_name]:
                    del self._subscribers[event_name]
                    del self._stats[event_name]
        logger.debug(f"事件取消订阅: {event_name} -> {handler.__name__}")

    async def publish(self, event_name: str, **kwargs) -> Dict[str, Any]:
        """发布事件

        Args:
            event_name: 事件名称
            **kwargs: 事件数据
        Returns:
            Dict: 包含处理结果的字典
        """
        handlers = []
        lock = await self._ensure_lock()
        async with lock:
            if event_name in self._stats:
                self._stats[event_name]["published"] += 1
            if event_name in self._subscribers:
                handlers = self._subscribers[event_name].copy()

        results = []
        errors = []

        for handler, _, filter_func in handlers:
            if filter_func and not filter_func(**kwargs):
                continue
            try:
                if inspect.iscoroutinefunction(handler):
                    if self._default_timeout:
                        result = await asyncio.wait_for(
                            handler(**kwargs), timeout=self._default_timeout
                        )
                    else:
                        result = await handler(**kwargs)
                else:
                    result = handler(**kwargs)
                results.append(
                    {"handler": handler.__name__, "result": result, "success": True}
                )
                if event_name in self._stats:
                    self._stats[event_name]["handled"] += 1
            except Exception as e:
                error_info = {
                    "handler": handler.__name__,
                    "error": str(e),
                    "success": False,
                }
                errors.append(error_info)
                if event_name in self._stats:
                    self._stats[event_name]["errors"] += 1
                logger.error(
                    f"事件处理错误: {event_name} -> {handler.__name__}: {str(e)}",
                    exc_info=True,
                )
                for error_handler in self._error_handlers:
                    try:
                        if inspect.iscoroutinefunction(error_handler):
                            await error_handler(event_name, handler, e, **kwargs)
                        else:
                            error_handler(event_name, handler, e, **kwargs)
                    except Exception as handler_error:
                        logger.error(
                            f"错误处理器本身出错: {str(handler_error)}", exc_info=True
                        )

        return {
            "event_name": event_name,
            "results": results,
            "errors": errors,
            "success": len(errors) == 0,
        }

    def set_default_timeout(self, timeout: Optional[float]):
        """设置处理器默认超时时间"""
        self._default_timeout = timeout

    def add_error_handler(self, handler: Callable):
        """添加全局错误处理器"""
        self._error_handlers.append(handler)

    def get_stats(self, event_name: Optional[str] = None) -> Dict[str, Any]:
        """获取事件统计信息"""
        if event_name:
            return self._stats.get(event_name, {})
        return dict(self._stats)

    async def clear(self) -> None:
        """清除所有订阅"""
        lock = await self._ensure_lock()
        async with lock:
            self._subscribers.clear()
            self._stats.clear()
        logger.info("事件总线已清空所有订阅")


_global_event_bus = EventBus()


class EventTypes:
    """预定义事件类型枚举"""

    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"
    ERROR_OCCURRED = "error.occurred"

    CHAT_START = "chat.start"
    CHAT_END = "chat.end"
    MESSAGE_SEND = "message.send"
    MESSAGE_RECEIVE = "message.receive"
    USER_MESSAGE = "user.message"

    TASK_SCHEDULE = "task.schedule"
    TASK_START = "task.start"
    TASK_COMPLETE = "task.complete"
    TASK_ERROR = "task.error"

    MEMORY_SAVE = "memory.save"
    MEMORY_RETRIEVE = "memory.retrieve"

    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_ERROR = "llm.error"

    PREFERENCE_CHANGED = "preference.changed"


def get_event_bus() -> EventBus:
    """获取全局事件总线实例"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def event_handler(
    event_name: str, priority: int = 0, filter_func: Optional[Callable] = None
):
    """事件处理器装饰器 - 简化事件订阅

    注意：此装饰器会自动将函数注册到全局事件总线。
    如需自定义事件总线实例，请使用 bus.on() 装饰器。

    Args:
        event_name: 事件名称
        priority: 优先级（数字越小优先级越高）
        filter_func: 过滤器函数
    """
    bus = get_event_bus()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

        setattr(wrapper, "__event_handler__", True)
        setattr(wrapper, "__event_name__", event_name)
        setattr(wrapper, "__priority__", priority)
        setattr(wrapper, "__filter_func__", filter_func)
        setattr(wrapper, "__original_func__", func)

        bus._auto_subscribe(event_name, wrapper, priority, filter_func)
        return wrapper

    return decorator
