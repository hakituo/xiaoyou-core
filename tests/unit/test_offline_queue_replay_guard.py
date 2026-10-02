"""离线队列重放守卫单测。

背景：主动关怀消息在 QQ 离线时进队、同时从手机 App 端补投，QQ 重连时被
按 24h TTL 原样重放，用户会看到同一条消息出现两次。这里守住三条约束：
主动消息短 TTL、同 message_id 不重复入队、其他端已投递即可丢弃。
"""

import asyncio
import time
from collections import defaultdict, deque

import pytest

from core.interfaces.websocket.offline_queue import (
    PROACTIVE_OFFLINE_TTL,
    OfflineQueueMixin,
)


class _Manager(OfflineQueueMixin):
    """最小化 WebSocketManager，只具备离线队列所需成员。"""

    def __init__(self, send_ok: bool = True):
        self.offline_queue = defaultdict(lambda: deque(maxlen=50))
        self.offline_ttl = 24 * 3600
        self.proactive_offline_ttl = PROACTIVE_OFFLINE_TTL
        self.user_connections = {}
        self.send_ok = send_ok
        self.sent_messages: list = []

    async def send_with_retry(self, websocket, message):
        if not self.send_ok:
            raise RuntimeError("connection closed")
        self.sent_messages.append(message)
        return True


def _enqueue(mgr, message, age_seconds=0.0, user_id="user1"):
    mgr.offline_queue[user_id].append((time.time() - age_seconds, message))


def _proactive(message_id="m1", content="困了先睡了"):
    return {"type": "proactive_message", "content": content, "message_id": message_id}


def test_stale_proactive_message_not_replayed():
    """超过主动消息 TTL 的消息重连时直接丢弃。"""
    mgr = _Manager()
    _enqueue(mgr, _proactive(), age_seconds=PROACTIVE_OFFLINE_TTL + 60)

    asyncio.run(mgr._flush_offline_messages("user1", object()))

    assert mgr.sent_messages == []
    assert not mgr.offline_queue.get("user1")


def test_fresh_proactive_message_still_replayed():
    """TTL 内的主动消息仍正常重放，并带上重放标记与入队时刻。"""
    mgr = _Manager()
    _enqueue(mgr, _proactive(message_id="m2"), age_seconds=60)

    asyncio.run(mgr._flush_offline_messages("user1", object()))

    assert len(mgr.sent_messages) == 1
    assert '"is_offline_replay": true' in mgr.sent_messages[0]
    assert "offline_queued_at" in mgr.sent_messages[0]


def test_normal_message_keeps_long_ttl():
    """普通消息仍按 24h TTL 保留，不因主动消息短 TTL 被误丢。"""
    mgr = _Manager()
    _enqueue(
        mgr,
        {"type": "message", "subtype": "response_done", "message_id": "m3"},
        age_seconds=PROACTIVE_OFFLINE_TTL + 60,
    )

    asyncio.run(mgr._flush_offline_messages("user1", object()))

    assert len(mgr.sent_messages) == 1


def test_same_message_id_enqueued_once():
    """同一 message_id 重复入队只保留一条。"""
    mgr = _Manager()
    mgr.store_offline_message("user1", _proactive(message_id="m4"))
    mgr.store_offline_message("user1", _proactive(message_id="m4"))

    assert len(mgr.offline_queue["user1"]) == 1


def test_discard_after_delivered_elsewhere():
    """已在其他端投递的消息从队列移除，重连不再重放。"""
    mgr = _Manager()
    mgr.store_offline_message("user1", _proactive(message_id="m5"))

    assert mgr.discard_offline_message("user1", "m5") == 1

    asyncio.run(mgr._flush_offline_messages("user1", object()))
    assert mgr.sent_messages == []


def test_discard_unknown_message_is_noop():
    """丢弃不存在的 message_id 不影响队列。"""
    mgr = _Manager()
    mgr.store_offline_message("user1", _proactive(message_id="m6"))

    assert mgr.discard_offline_message("user1", "not-exist") == 0
    assert len(mgr.offline_queue["user1"]) == 1


def test_replay_marker_does_not_pollute_queue():
    """发送失败保留的消息不带重放标记。"""
    mgr = _Manager(send_ok=False)
    mgr.store_offline_message("user1", _proactive(message_id="m7"))

    asyncio.run(mgr._flush_offline_messages("user1", object()))

    _, msg = mgr.offline_queue["user1"][0]
    assert "is_offline_replay" not in msg
    assert "offline_queued_at" not in msg


@pytest.mark.parametrize(
    "message,expected_short_ttl",
    [
        ({"type": "proactive_message"}, True),
        ({"type": "message", "is_proactive": True}, True),
        ({"type": "message"}, False),
    ],
)
def test_ttl_selected_by_message_type(message, expected_short_ttl):
    """主动类消息走短 TTL，其他消息走 24h。"""
    mgr = _Manager()
    ttl = mgr._offline_ttl_for(message)

    assert ttl == (PROACTIVE_OFFLINE_TTL if expected_short_ttl else 24 * 3600)
