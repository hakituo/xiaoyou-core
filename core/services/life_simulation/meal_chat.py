"""进食场景触发互聊的辅助逻辑。"""

from __future__ import annotations

import asyncio
from logging import Logger


def trigger_meal_chat_check(*, logger: Logger, debug_enabled: bool) -> None:
    """尝试触发边吃边聊，不阻塞主进食流程。"""
    try:
        from core.services.active_care.peer_chat.peer_chat_scheduler import (
            get_peer_chat_scheduler,
        )

        scheduler = get_peer_chat_scheduler()
        if scheduler is None:
            if debug_enabled:
                logger.info("边吃边聊: PeerChatScheduler 未初始化，跳过")
            return
        if not scheduler._running:
            if debug_enabled:
                logger.info("边吃边聊: PeerChatScheduler 未运行，跳过")
            return

        logger.info("LLM决策: 边吃边聊，触发 PeerChat 检查")
        # P1-2: 保存任务引用，避免被 GC 后边吃边聊检查静默失败
        task = asyncio.ensure_future(scheduler.run_single_check())
        scheduler._pending_persist_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            scheduler._pending_persist_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("边吃边聊 PeerChat 检查异常: %r", exc, exc_info=exc)

        task.add_done_callback(_on_done)
    except Exception as e:
        logger.warning(f"触发边吃边聊失败: {e}")
