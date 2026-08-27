"""
异步锁工具

提供 LazyAsyncLock —— 懒加载的 asyncio.Lock 包装器。

问题背景：
    在 Python 3.10 之前，asyncio.Lock() 在 __init__/__new__ 中创建会
    绑定到当前事件循环。如果实例化时没有运行中的事件循环，会自动创建
    一个新的循环并绑定，导致后续在不同事件循环中使用时抛出
    "Future attached to a different loop" 错误。

    Python 3.10+ 已修复此问题（Lock 不再在创建时绑定循环），
    但为保持代码向后兼容、并避免某些边界场景下的事件循环绑定问题，
    统一使用 LazyAsyncLock 替代 asyncio.Lock() 在 __init__ 中的直接创建。

用法：
    直接替换 asyncio.Lock()：

        # 旧代码：
        self._lock = asyncio.Lock()
        async with self._lock:
            ...

        # 新代码：
        from core.utils.async_locks import LazyAsyncLock
        self._lock = LazyAsyncLock()
        async with self._lock:
            ...
"""

from __future__ import annotations

import asyncio
from typing import Optional


class LazyAsyncLock:
    """懒加载的 asyncio.Lock 包装器。

    特性：
    - 在 __init__ 中创建实例不需要运行中的事件循环
    - 底层的 asyncio.Lock 在首次使用时才会真正创建
    - 完全兼容 ``async with lock:`` 语法
    - 支持所有 asyncio.Lock 的方法：acquire / release / locked
    - asyncio 是单线程协作式调度，_get_lock() 同步执行不会被打断，
      因此无需额外加锁即可保证 _lock 只创建一次
    """

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        # 不在初始化时创建 Lock，等首次使用时再创建
        # 这样可以避免在没有事件循环时创建 Lock 的问题
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        """获取或创建底层的 asyncio.Lock（首次调用时创建）"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self) -> bool:
        """获取锁"""
        return await self._get_lock().acquire()

    def release(self) -> None:
        """释放锁"""
        if self._lock is None:
            # 与 asyncio.Lock 的行为一致：未持有时 release 抛 RuntimeError
            raise RuntimeError("Lock is not initialized.")
        self._lock.release()

    def locked(self) -> bool:
        """返回锁是否被持有"""
        return self._lock is not None and self._lock.locked()

    async def __aenter__(self) -> "LazyAsyncLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


__all__ = ["LazyAsyncLock"]
