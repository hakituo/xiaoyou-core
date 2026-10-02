#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天消息合并批处理

把短时间内到达的多条用户消息合并成一条再交给后端处理，
避免分片输入（如 QQ 逐字推送）导致多次重复响应。
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from core.utils.async_locks import LazyAsyncLock
from core.utils.logger import get_logger

logger = get_logger(__name__)


class ChatMessageMerger:
    """管理每个 WebSocket 的待合并聊天消息桶。"""

    def __init__(self, adapter):
        self.adapter = adapter
        # 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._merge_lock = LazyAsyncLock()
        self._pending_chat_batches: Dict[int, Dict[str, Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # 配置读取
    # ------------------------------------------------------------------
    def _get_merge_wait_seconds(self) -> float:
        try:
            from config.integrated_config import get_settings

            wait_ms = int(
                getattr(
                    getattr(get_settings(), "server", None),
                    "ws_user_message_merge_wait_ms",
                    700,
                )
                or 700
            )
        except Exception:
            wait_ms = 700
        wait_ms = max(0, min(wait_ms, 3000))
        return float(wait_ms) / 1000.0

    def _should_skip_merge_wait(self, websocket: WebSocket, message: dict) -> bool:
        """按平台或显式标记跳过二次消息合并等待。"""
        if bool(message.get("skip_merge_wait")):
            return True
        platform = str(getattr(websocket, "platform", "") or "").strip().lower()
        if not platform:
            return False
        try:
            from config.integrated_config import get_settings

            raw_platforms = str(
                getattr(
                    getattr(get_settings(), "server", None),
                    "ws_skip_merge_wait_platforms",
                    "qq",
                )
                or ""
            )
        except Exception:
            raw_platforms = "qq"
        skip_platforms = {
            item.strip().lower()
            for item in raw_platforms.split(",")
            if str(item).strip()
        }
        return platform in skip_platforms

    # ------------------------------------------------------------------
    # 连接清理
    # ------------------------------------------------------------------
    async def cleanup_websocket(self, websocket: WebSocket):
        ws_key = self.adapter._get_ws_key(websocket)
        async with self._merge_lock:
            buckets = self._pending_chat_batches.pop(ws_key, {})
        tasks: List[asyncio.Task] = []
        for item in buckets.values():
            task = item.get("task")
            if isinstance(task, asyncio.Task) and not task.done():
                tasks.append(task)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            cleanup_sleep_recovery_tasks_for_ws,
        )
        await cleanup_sleep_recovery_tasks_for_ws(ws_key)

    # ------------------------------------------------------------------
    # 合并主流程
    # ------------------------------------------------------------------
    async def flush_merged_batch(
        self,
        websocket: WebSocket,
        conversation_bucket_key: str,
        streaming_handler,
        wait_seconds: float,
        handle_now,
    ):
        """等待合并窗口过去后，把桶内消息合并并交给 handle_now 处理。"""
        ws_key = self.adapter._get_ws_key(websocket)
        merged_messages: List[Dict[str, Any]] = []
        while True:
            await asyncio.sleep(wait_seconds)
            async with self._merge_lock:
                ws_buckets = self._pending_chat_batches.get(ws_key) or {}
                bucket = ws_buckets.get(conversation_bucket_key)
                if not bucket:
                    return
                last_update = float(bucket.get("last_update_ts") or 0.0)
                now = time.time()
                if (now - last_update) < wait_seconds:
                    continue
                merged_messages = list(bucket.get("messages") or [])
                ws_buckets.pop(conversation_bucket_key, None)
                if not ws_buckets:
                    self._pending_chat_batches.pop(ws_key, None)
                break

        if not merged_messages:
            return
        primary = dict(merged_messages[-1])

        has_list_content = any(
            isinstance(item.get("content"), list) for item in merged_messages
        )

        if has_list_content:
            combined_content = []
            for item in merged_messages:
                c = item.get("content")
                if isinstance(c, list):
                    combined_content.extend(c)
                elif c:
                    combined_content.append({"type": "text", "text": str(c).strip()})
            primary["content"] = combined_content
        else:
            parts: List[str] = []
            for item in merged_messages:
                text = str(item.get("content", "") or "").strip()
                if not text:
                    continue
                if parts and text == parts[-1]:
                    continue
                parts.append(text)
            primary["content"] = "\n".join(parts).strip()

        primary["merged_message_count"] = len(merged_messages)
        if merged_messages:
            primary["merged_message_ids"] = [
                str(m.get("message_id") or "") for m in merged_messages if m.get("message_id")
            ]
        await handle_now(websocket, primary, streaming_handler)

    async def enqueue(
        self,
        websocket: WebSocket,
        message: dict,
        streaming_handler,
        handle_now,
        wait_seconds: Optional[float] = None,
    ):
        """把一条消息放进合并桶，必要时启动合并 flush 任务。

        ``wait_seconds`` 可由调用方显式传入（便于测试 monkeypatch），
        缺省时从配置读取。
        """
        if wait_seconds is None:
            wait_seconds = self._get_merge_wait_seconds()
        if wait_seconds <= 0:
            await handle_now(websocket, message, streaming_handler)
            return
        conversation_id = (
            message.get("conversation_id")
            or getattr(websocket, "user_id", None)
            or "default"
        )
        bucket_key = str(conversation_id or "default").strip() or "default"
        ws_key = self.adapter._get_ws_key(websocket)
        async with self._merge_lock:
            ws_buckets = self._pending_chat_batches.setdefault(ws_key, {})
            bucket = ws_buckets.get(bucket_key)
            if not bucket:
                bucket = {
                    "messages": [],
                    "last_update_ts": 0.0,
                    "task": None,
                }
                ws_buckets[bucket_key] = bucket
            bucket["messages"].append(dict(message))
            bucket["last_update_ts"] = time.time()
            task = bucket.get("task")
            if not isinstance(task, asyncio.Task) or task.done():
                bucket["task"] = asyncio.create_task(
                    self.flush_merged_batch(
                        websocket, bucket_key, streaming_handler, wait_seconds, handle_now
                    )
                )
