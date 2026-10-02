"""
统一单例工具
提供两种单例模式：
1. @singleton 类装饰器 —— 线程安全的 __new__ 单例
2. SingletonFactory —— 模块级 get_xxx() 工厂函数，支持 reset / async
"""

from __future__ import annotations

import asyncio
import threading
from functools import wraps
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


# ────────────────────────────────────────────
# 1. @singleton 类装饰器
# ────────────────────────────────────────────
def singleton(cls: type[T]) -> type[T]:
    """
    线程安全的类单例装饰器。

    用法::

        @singleton
        class MyService:
            def __init__(self):
                ...  # 只会执行一次

    - 第一次实例化时正常调用 __init__
    - 后续实例化直接返回已有实例，__init__ 不再执行
    - 通过 MyClass.clear_instance() 可重置（测试用）
    """
    _lock = threading.Lock()
    _instance: Optional[T] = None

    original_new = cls.__new__
    original_init = cls.__init__

    @wraps(original_new, updated=[])
    def __new__(subcls, *args, **kwargs):
        nonlocal _instance
        if _instance is None:
            with _lock:
                if _instance is None:
                    _instance = original_new(subcls)
                    _instance._singleton_initialized = False
        return _instance

    def __init__(self, *args, **kwargs):
        if getattr(self, "_singleton_initialized", False):
            return
        original_init(self, *args, **kwargs)
        self._singleton_initialized = True

    def clear_instance():
        """重置单例（仅用于测试）"""
        nonlocal _instance
        with _lock:
            _instance = None

    cls.__new__ = __new__
    cls.__init__ = __init__
    cls.clear_instance = staticmethod(clear_instance)
    return cls


# ────────────────────────────────────────────
# 2. SingletonFactory —— 模块级单例工厂
# ────────────────────────────────────────────
class SingletonFactory:
    """
    模块级单例工厂，替代手写的 get_xxx() 函数。

    用法::

        _factory = SingletonFactory(MyService)

        def get_my_service() -> MyService:
            return _factory.get()

        def reset_my_service():
            _factory.reset()

    支持：
    - 线程安全的懒初始化
    - 可选 async 初始化
    - reset / shutdown 生命周期管理
    """

    def __init__(
        self,
        factory: Callable[..., T],
        *,
        is_async: bool = False,
    ):
        self._factory = factory
        self._is_async = is_async
        self._instance: Optional[T] = None
        self._lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None

    def get(self, *args, **kwargs) -> T:
        """同步获取单例实例"""
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory(*args, **kwargs)
        return self._instance

    async def aget(self, *args, **kwargs) -> T:
        """异步获取单例实例"""
        if self._instance is None:
            if self._async_lock is None:
                self._async_lock = asyncio.Lock()
            async with self._async_lock:
                if self._instance is None:
                    self._instance = await self._factory(*args, **kwargs)
        return self._instance

    def reset(self):
        """重置单例（测试 / 生命周期管理）"""
        with self._lock:
            self._instance = None

    def shutdown(self):
        """关闭单例（调用 shutdown 方法如果存在）"""
        with self._lock:
            if self._instance is not None:
                shutdown_fn = getattr(self._instance, "shutdown", None)
                if callable(shutdown_fn):
                    shutdown_fn()
                self._instance = None

    @property
    def instance(self) -> Optional[T]:
        """获取当前实例（不触发创建）"""
        return self._instance
