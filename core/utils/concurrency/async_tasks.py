"""后台任务工具：统一管理 fire-and-forget asyncio.create_task 调用。

提供 spawn_bg_task 函数，保存任务引用防止 GC 回收，
并在任务异常时自动记录日志。
"""
from __future__ import annotations

import asyncio
from typing import Set

from core.utils.logger import get_logger

logger = get_logger("async_tasks")

_pending_bg_tasks: Set[asyncio.Task] = set()


def spawn_bg_task(coro, *, name: str = "") -> asyncio.Task:
    """提交后台任务并保存引用，完成后自动清理并记录异常。

    用法：
        spawn_bg_task(some_coroutine(), name="描述")
    替代：
        asyncio.create_task(some_coroutine())  # 无引用、无异常处理
    """
    task = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    _pending_bg_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _pending_bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error(
                "后台任务异常 (name=%s): %r", t.get_name(), exc, exc_info=exc
            )

    task.add_done_callback(_on_done)
    return task
