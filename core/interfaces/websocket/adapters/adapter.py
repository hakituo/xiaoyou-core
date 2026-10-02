#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI WebSocket 适配器门面与生命周期管理。"""
# ruff: noqa: F401

from __future__ import annotations

import asyncio
from typing import Dict, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from core.utils.async_locks import LazyAsyncLock
from core.utils.logger import get_logger

from .fastapi.connection import WebSocketConnectionMixin
from .fastapi.demo import WebSocketDemoFlowMixin
from .fastapi.image_generation import WebSocketImageGenerationMixin
from .fastapi.resource_broadcast import WebSocketResourceBroadcastMixin
from .fastapi.routing import WebSocketMessageRouterMixin
from .handlers.main_handlers import MessageHandlers
from .streaming import StreamingHandler

logger = get_logger(__name__)
_instance = None
_instance_lock = asyncio.Lock()


class FastAPIWebSocketAdapter(
    WebSocketConnectionMixin,
    WebSocketMessageRouterMixin,
    WebSocketDemoFlowMixin,
    WebSocketImageGenerationMixin,
    WebSocketResourceBroadcastMixin,
):
    """将 FastAPI WebSocket 转换为项目统一管理器接口。"""

    def __init__(self) -> None:
        self.websocket_manager = None
        self._initialized = False
        self._chat_tasks: Dict[int, Dict[str, asyncio.Task]] = {}
        self._chat_tasks_lock = LazyAsyncLock()
        self._image_generation_tasks: Dict[str, asyncio.Task] = {}
        self._last_broadcast_hash: Optional[int] = None
        self._last_broadcast_time = 0.0
        self._min_broadcast_interval = 3.0
        self._last_logged_connection_count = -1
        self._last_logged_models_state: Optional[Dict] = None
        self.handlers = MessageHandlers(self)
        self.streaming = StreamingHandler(self)
        self.demo = None

    def _get_ws_key(self, websocket) -> int:
        return id(websocket)

    async def _register_chat_task(
        self, websocket, message_id: str, task: asyncio.Task
    ) -> None:
        ws_key = self._get_ws_key(websocket)
        async with self._chat_tasks_lock:
            bucket = self._chat_tasks.get(ws_key)
            if bucket is None:
                bucket = {}
                self._chat_tasks[ws_key] = bucket
            bucket[str(message_id)] = task

    async def _unregister_chat_task(self, websocket, message_id: str) -> None:
        ws_key = self._get_ws_key(websocket)
        async with self._chat_tasks_lock:
            bucket = self._chat_tasks.get(ws_key)
            if not bucket:
                return
            bucket.pop(str(message_id), None)
            if not bucket:
                self._chat_tasks.pop(ws_key, None)

    async def _cancel_chat_tasks(self, websocket) -> None:
        ws_key = self._get_ws_key(websocket)
        async with self._chat_tasks_lock:
            bucket = self._chat_tasks.pop(ws_key, {})
        tasks = [
            task
            for task in bucket.values()
            if isinstance(task, asyncio.Task) and not task.done()
        ]
        if tasks:
            for task in tasks:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=3.0
                )
            except Exception:  # noqa: BLE001
                logger.debug("取消聊天任务时部分任务超时", exc_info=True)
        await self._request_stop_current_inference()

    async def _request_stop_current_inference(self) -> None:
        try:
            from core.services.scheduler.cpp_scheduler_engine import get_scheduler_engine

            engine = get_scheduler_engine()
            if engine:
                await engine.request_stop_current_inference()
        except Exception:  # noqa: BLE001
            logger.debug("请求停止当前推理失败", exc_info=True)
        try:
            from core.resource_manager import (
                get_global_resource_manager,
                is_system_under_memory_pressure,
            )

            if await is_system_under_memory_pressure():
                resource_manager = await get_global_resource_manager()
                from core.utils.async_tasks import spawn_bg_task

                spawn_bg_task(resource_manager.optimize_resources(), name="resource_optimize")
        except Exception:  # noqa: BLE001
            logger.debug("内存压力检测或资源优化失败", exc_info=True)

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            from core.interfaces.websocket.websocket_manager import get_websocket_manager

            self.websocket_manager = get_websocket_manager()
            await self.websocket_manager.initialize()
            from core.core_engine.event_bus import get_event_bus

            await get_event_bus().subscribe(
                "resource.metrics_updated", self._handle_resource_update
            )
            from .demo import DemoHandler

            self.demo = DemoHandler(self)
            self._initialized = True
            logger.info("FastAPIWebSocketAdapter initialized successfully")
            try:
                from core.utils.ws_handshake_debug import log as ws_log

                ws_log("adapter_initialized_ok")
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:
            logger.error("Failed to initialize FastAPIWebSocketAdapter: %s", exc)
            try:
                from core.utils.ws_handshake_debug import log_exception

                log_exception("adapter_initialize_failed", exc=exc)
            except Exception:  # noqa: BLE001
                pass
            raise

    async def shutdown(self) -> None:
        logger.info("Shutting down FastAPIWebSocketAdapter...")
        if self.websocket_manager:
            try:
                await self.websocket_manager.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("停止 WebSocketManager 时出错: %s", exc)

        async with self._chat_tasks_lock:
            tasks = [
                task
                for bucket in self._chat_tasks.values()
                for task in bucket.values()
                if isinstance(task, asyncio.Task) and not task.done()
            ]
            self._chat_tasks.clear()
        if tasks:
            for task in tasks:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=5.0
                )
            except Exception:  # noqa: BLE001
                logger.debug("关闭适配器时部分任务取消超时", exc_info=True)
        self._initialized = False
        logger.info("FastAPIWebSocketAdapter shutdown complete")


async def get_fastapi_websocket_adapter() -> Optional[FastAPIWebSocketAdapter]:
    """获取 FastAPI WebSocket 适配器单例。"""
    global _instance
    if _instance is None:
        async with _instance_lock:
            if _instance is None:
                _instance = FastAPIWebSocketAdapter()
                await _instance.initialize()
    return _instance


async def initialize_websocket_adapter() -> Optional[FastAPIWebSocketAdapter]:
    return await get_fastapi_websocket_adapter()


async def shutdown_websocket_adapter() -> None:
    global _instance
    if _instance is None:
        return
    try:
        await _instance.shutdown()
    finally:
        _instance = None
