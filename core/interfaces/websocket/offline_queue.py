#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线消息队列 Mixin

为 WebSocketManager 提供离线消息存储与重放能力。
当目标用户不在线时，消息暂存到队列，待用户重连后批量推送。
"""

from core.utils.logger import get_logger
import asyncio
import copy
import json

import time
from typing import Any, Dict

from core.contracts import ConnectionState
from .message_sending import qq_connection_accepts_message

logger = get_logger(__name__)


class OfflineQueueMixin:
    """离线消息队列相关方法"""

    def store_offline_message(self, user_id: str, message: Dict[str, Any]):
        """存储离线消息

        使用 copy.deepcopy 防止外部后续修改影响已入队的消息内容。
        offline_queue 是 defaultdict，会自动创建 deque，无需手动初始化。
        """
        try:
            timestamp = time.time()
            # 深拷贝避免外部对象后续被修改导致队列内容被污染
            safe_msg = copy.deepcopy(message)
            self.offline_queue[user_id].append((timestamp, safe_msg))
            logger.info(
                f"[WebSocket] Stored offline message for user {user_id}, "
                f"queue size: {len(self.offline_queue[user_id])}"
            )
        except Exception as e:
            logger.error(f"[WebSocket] Failed to store offline message: {e}")

    def is_user_online(self, user_id: str) -> bool:
        """检查用户是否有活跃的WebSocket连接"""
        conns = self.user_connections.get(user_id, [])
        return any(c.state == ConnectionState.CONNECTED for c in conns)

    # per-user flush 互斥锁，防止同一用户的多个 flush 协程并发操作同一 deque
    # 导致 pop from an empty deque（await 挂起期间队列被其他协程清空）
    _offline_flush_locks: Dict[str, asyncio.Lock] = {}

    def _get_flush_lock(self, user_id: str) -> "asyncio.Lock":
        """获取指定用户的 flush 互斥锁（惰性创建）"""
        if user_id not in self._offline_flush_locks:
            self._offline_flush_locks[user_id] = asyncio.Lock()
        return self._offline_flush_locks[user_id]

    async def _flush_offline_messages(self, user_id: str, websocket: Any):
        """推送离线消息

        原子性保证：只有发送成功的消息才从队列移除，发送失败的消息会被推回队首，
        等待下次重连或下次 flush 重试。避免因 send_with_retry 抛异常导致消息丢失。

        并发安全：使用 per-user 互斥锁，防止多个 flush 协程并发操作同一 deque
        时出现 IndexError('pop from an empty deque')。
        """
        if user_id not in self.offline_queue or not self.offline_queue[user_id]:
            return

        lock = self._get_flush_lock(user_id)
        async with lock:
            # 拿到锁后再次检查，可能在等待锁期间队列已被其他 flush 清空
            if user_id not in self.offline_queue or not self.offline_queue[user_id]:
                return

            logger.info(
                f"[WebSocket] Flushing {len(self.offline_queue[user_id])} "
                f"offline messages to {user_id}"
            )

            now = time.time()
            queue = self.offline_queue[user_id]

            # 按顺序处理：每条消息发送成功后才从队列移除；
            # 发送失败则把消息推回队首并停止后续发送，等待下次重试。
            sent_count = 0
            dropped_expired = 0
            failed_count = 0

            # 只扫描本次拿锁时已有的消息。双 QQ 共用同一 user_id，某个角色
            # 重连时只能取走发给自己的消息，其他角色消息保留到对应连接重连。
            scan_count = len(queue)
            skipped_other_role = 0
            for _ in range(scan_count):
                ts, msg = queue.popleft()

                # 先处理过期消息：直接移除
                if now - ts >= self.offline_ttl:
                    dropped_expired += 1
                    logger.debug(f"[WebSocket] Dropping expired offline message from {ts}")
                    continue

                if not qq_connection_accepts_message(websocket, msg):
                    queue.append((ts, msg))
                    skipped_other_role += 1
                    continue

                # 复制一份用于发送，避免 is_offline_replay 标记污染原始消息
                msg_to_send = copy.deepcopy(msg)
                msg_to_send["is_offline_replay"] = True

                try:
                    send_succeeded = await self.send_with_retry(
                        websocket, json.dumps(msg_to_send, ensure_ascii=False)
                    )
                    if not send_succeeded:
                        raise ConnectionError("离线消息发送返回失败")
                except Exception as e:
                    # 发送失败：保留消息在队首，等待下次 flush 重试
                    queue.appendleft((ts, msg))
                    logger.warning(
                        f"[WebSocket] Failed to flush offline message to {user_id}: {e}. "
                        f"Message kept in queue for retry."
                    )
                    failed_count += 1
                    break

                sent_count += 1

            logger.info(
                f"[WebSocket] Offline flush done for {user_id}: "
                f"sent={sent_count}, expired={dropped_expired}, failed={failed_count}, "
                f"skipped_other_role={skipped_other_role}, remaining={len(queue)}"
            )

            # 清理空的条目
            if user_id in self.offline_queue and not self.offline_queue[user_id]:
                del self.offline_queue[user_id]
