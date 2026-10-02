# -*- coding: utf-8 -*-
"""互聊调度器生命周期（从 PeerChatScheduler 拆出）。"""

from __future__ import annotations

import asyncio

from core.utils.logger import get_module_logger

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")


class PeerChatLifecycleMixin:
    """启动 / 停止 / 幂等保活。"""

    @staticmethod
    def _is_character_daily_active() -> bool:
        """检查 CharacterDailyEngine 是否正在运行"""
        try:
            from core.services.character_daily.engine import get_character_daily_engine
            engine = get_character_daily_engine()
            return engine is not None and engine._running
        except Exception:
            return False

    def start(self) -> bool:
        """启动调度循环（幂等）

        如果 CharacterDailyEngine 正在运行，则不启动独立循环
        （peer chat 触发由 CharacterDailyEngine 管理）。
        """
        if self._is_character_daily_active():
            logger.info(
                "PeerChatScheduler: CharacterDailyEngine 已接管 peer chat 调度，"
                "跳过独立循环启动"
            )
            self._running = True  # 标记为 running，保证 ensure_running 不反复尝试
            return True

        if self._running and self._task and not self._task.done():
            return True
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

        def _on_done(t: asyncio.Task):
            try:
                t.result()
            except asyncio.CancelledError:
                logger.info("PeerChatScheduler: 调度循环已取消")
            except Exception as e:
                logger.error("PeerChatScheduler: 调度循环异常退出: %s", e, exc_info=True)
                # 自动重启（最多延迟 60s）
                if self._running and not self._is_character_daily_active():
                    logger.warning("PeerChatScheduler: 60s 后自动重启调度循环")
                    # P1-1: 使用 asyncio.get_event_loop_policy().get_event_loop()
                    # 在 done_callback 中可能不在协程上下文，需用 policy 获取 loop
                    asyncio.get_event_loop_policy().get_event_loop().call_later(
                        60, self.start
                    )

        self._task.add_done_callback(_on_done)
        logger.info("PeerChatScheduler: 调度循环已启动 (interval=%ds)", self._check_interval)
        return True

    async def stop(self):
        """停止调度循环"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PeerChatScheduler: 调度循环已停止")

    def ensure_running(self) -> bool:
        """确保调度器正在运行（供 ProactiveChecker 心跳调用）

        如果 CharacterDailyEngine 已接管，则直接返回 True。
        """
        if self._is_character_daily_active():
            return True
        if not self._running:
            return self.start()
        if self._task and self._task.done():
            logger.warning("PeerChatScheduler: 调度器已停止，重启中")
            return self.start()
        return True
