#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证脚本: 离线队列重放去重（主动消息不再"启动 QQ 又发一遍"）

背景：主动关怀消息在 QQ 离线时进入离线队列，同时通过手机 App 端补投，
用户已在手机上看到过；QQ 重连时队列按 24h TTL 原样重放，表现为同一条
"困了先睡了"被发第二遍。

验证项：
1. 主动消息超过 proactive_offline_ttl（10 分钟）后重连，被丢弃且不再发送
2. 主动消息在 TTL 内重连，仍正常发送（不误杀）
3. 同一 message_id 重复入队只保留一条
4. App 端已投递后 discard_offline_message 能移除副本，flush 不再发送
5. 普通（非主动）消息仍按 24h TTL 保留，行为不回归
6. QQ 接收端 _offline_replay_age：非重放返回 None，过期重放超过阈值
7. 重放消息带 offline_queued_at，且不污染队列中的原始消息
"""

import asyncio
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces.websocket.offline_queue import (  # noqa: E402
    PROACTIVE_OFFLINE_TTL,
    OfflineQueueMixin,
)


def _make_manager():
    """构造最小化的 WebSocketManager（仅包含 OfflineQueueMixin）。"""

    class _TestManager(OfflineQueueMixin):
        def __init__(self):
            self.offline_queue = defaultdict(lambda: deque(maxlen=50))
            self.offline_ttl = 24 * 3600
            self.proactive_offline_ttl = PROACTIVE_OFFLINE_TTL
            self.user_connections = {}
            self.sent_messages = []

        async def send_with_retry(self, websocket, message):
            self.sent_messages.append(message)
            return True

    return _TestManager()


def _queue_with(mgr, user_id, message, age_seconds):
    mgr.offline_queue[user_id].append((time.time() - age_seconds, message))


def check_stale_proactive_dropped() -> list:
    """场景1: 超过主动消息 TTL 的重放应被丢弃，不发送。"""
    issues = []
    mgr = _make_manager()
    _queue_with(
        mgr,
        "user1",
        {"type": "proactive_message", "content": "困了先睡了", "message_id": "m1"},
        age_seconds=PROACTIVE_OFFLINE_TTL + 60,
    )
    asyncio.run(mgr._flush_offline_messages("user1", MagicMock()))
    if mgr.sent_messages:
        issues.append(f"[过期主动消息] 不应发送，实际发送 {len(mgr.sent_messages)} 条")
    if mgr.offline_queue.get("user1"):
        issues.append("[过期主动消息] 队列应已被清空")
    return issues


def check_fresh_proactive_sent() -> list:
    """场景2: TTL 内的主动消息仍应正常重放（不误杀）。"""
    issues = []
    mgr = _make_manager()
    _queue_with(
        mgr,
        "user1",
        {"type": "proactive_message", "content": "早安", "message_id": "m2"},
        age_seconds=60,
    )
    asyncio.run(mgr._flush_offline_messages("user1", MagicMock()))
    if len(mgr.sent_messages) != 1:
        issues.append(f"[新鲜主动消息] 应发送 1 条，实际 {len(mgr.sent_messages)} 条")
    else:
        if '"is_offline_replay": true' not in mgr.sent_messages[0]:
            issues.append("[新鲜主动消息] 重放消息缺少 is_offline_replay 标记")
        if "offline_queued_at" not in mgr.sent_messages[0]:
            issues.append("[新鲜主动消息] 重放消息缺少 offline_queued_at 字段")
    return issues


def check_duplicate_enqueue() -> list:
    """场景3: 同一 message_id 不应重复入队。"""
    issues = []
    mgr = _make_manager()
    payload = {"type": "proactive_message", "content": "晚安", "message_id": "m3"}
    mgr.store_offline_message("user1", payload)
    mgr.store_offline_message("user1", dict(payload))
    size = len(mgr.offline_queue.get("user1", deque()))
    if size != 1:
        issues.append(f"[入队去重] 队列应只有 1 条，实际 {size} 条")
    return issues


def check_discard_after_app_delivery() -> list:
    """场景4: 已在 App 端投递后，QQ 重连不应再重放同一条。"""
    issues = []
    mgr = _make_manager()
    payload = {"type": "proactive_message", "content": "困了先睡了", "message_id": "m4"}
    mgr.store_offline_message("user1", payload)
    removed = mgr.discard_offline_message("user1", "m4")
    if removed != 1:
        issues.append(f"[App 已投] 应丢弃 1 条，实际 {removed} 条")
    asyncio.run(mgr._flush_offline_messages("user1", MagicMock()))
    if mgr.sent_messages:
        issues.append(f"[App 已投] 不应再发送，实际发送 {len(mgr.sent_messages)} 条")
    return issues


def check_normal_message_keeps_ttl() -> list:
    """场景5: 普通消息仍按 24h TTL 保留，不因主动消息改动而误丢。"""
    issues = []
    mgr = _make_manager()
    _queue_with(
        mgr,
        "user1",
        {"type": "message", "subtype": "response_done", "message_id": "m5"},
        age_seconds=PROACTIVE_OFFLINE_TTL + 60,
    )
    asyncio.run(mgr._flush_offline_messages("user1", MagicMock()))
    if len(mgr.sent_messages) != 1:
        issues.append(f"[普通消息] 20 分钟前的普通消息应仍重放，实际 {len(mgr.sent_messages)} 条")
    return issues


def check_receiver_age_guard() -> list:
    """场景6: QQ 接收端对过期重放消息能算出超阈值年龄。"""
    issues = []
    try:
        from clients.bots.qq.session.replay_guard import (
            OFFLINE_REPLAY_MAX_AGE_SECONDS,
            is_stale_offline_replay,
            offline_replay_age,
        )
    except Exception as exc:  # pragma: no cover - 仅本地/CI 环境差异
        issues.append(f"[QQ 接收端] 无法导入 replay_guard: {exc}")
        return issues

    now = time.time()
    if offline_replay_age({"type": "proactive_message"}) is not None:
        issues.append("[QQ 接收端] 非重放消息应返回 None")
    if is_stale_offline_replay({"type": "proactive_message"}):
        issues.append("[QQ 接收端] 非重放消息不应判为过期")
    fresh = offline_replay_age({"is_offline_replay": True, "offline_queued_at": now - 60})
    if fresh is None or fresh > OFFLINE_REPLAY_MAX_AGE_SECONDS:
        issues.append(f"[QQ 接收端] 60s 的重放消息不应判为过期，实际 age={fresh}")
    stale = offline_replay_age({"is_offline_replay": True, "offline_queued_at": now - 3600})
    if stale is None or stale <= OFFLINE_REPLAY_MAX_AGE_SECONDS:
        issues.append(f"[QQ 接收端] 1 小时前的重放消息应判为过期，实际 age={stale}")
    if not is_stale_offline_replay({"is_offline_replay": True, "offline_queued_at": now - 3600}):
        issues.append("[QQ 接收端] is_stale_offline_replay 应判定 1 小时前的重放为过期")
    # 兼容只有 timestamp 的旧 payload
    legacy = offline_replay_age({"is_offline_replay": True, "timestamp": now - 3600})
    if legacy is None or legacy <= OFFLINE_REPLAY_MAX_AGE_SECONDS:
        issues.append(f"[QQ 接收端] 仅有 timestamp 的旧重放消息应判为过期，实际 age={legacy}")
    return issues


def check_replay_marker_not_polluted() -> list:
    """场景7: 重放失败保留的消息不应带上 is_offline_replay / offline_queued_at。"""

    class _FailManager(OfflineQueueMixin):
        def __init__(self):
            self.offline_queue = defaultdict(lambda: deque(maxlen=50))
            self.offline_ttl = 24 * 3600
            self.proactive_offline_ttl = PROACTIVE_OFFLINE_TTL
            self.user_connections = {}

        async def send_with_retry(self, websocket, message):
            raise RuntimeError("connection closed")

    issues = []
    mgr = _FailManager()
    mgr.store_offline_message(
        "user1", {"type": "proactive_message", "content": "晚安", "message_id": "m7"}
    )
    asyncio.run(mgr._flush_offline_messages("user1", MagicMock()))
    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 1:
        issues.append(f"[标记不污染] 发送失败后队列应保留 1 条，实际 {len(queue)}")
    else:
        _, msg = queue[0]
        if "is_offline_replay" in msg or "offline_queued_at" in msg:
            issues.append("[标记不污染] 队列中的原始消息被重放标记污染")
    return issues


def main() -> int:
    checks = [
        ("过期主动消息被丢弃", check_stale_proactive_dropped),
        ("TTL 内主动消息正常发送", check_fresh_proactive_sent),
        ("同一 message_id 不重复入队", check_duplicate_enqueue),
        ("App 已投后不再重放", check_discard_after_app_delivery),
        ("普通消息 TTL 不回归", check_normal_message_keeps_ttl),
        ("QQ 接收端时效判断", check_receiver_age_guard),
        ("重放标记不污染队列", check_replay_marker_not_polluted),
    ]

    all_issues = []
    for name, check in checks:
        try:
            issues = check()
        except Exception as exc:
            issues = [f"执行异常: {exc}"]
        status = "PASS" if not issues else "FAIL"
        print(f"[{status}] {name}")
        for issue in issues:
            print(f"    - {issue}")
        all_issues.extend(issues)

    if all_issues:
        print(f"\n验证失败，共 {len(all_issues)} 项问题")
        return 1
    print("\n全部通过：主动消息不再隔夜重放，且已在其他端投递的副本不再重复发送")
    return 0


if __name__ == "__main__":
    sys.exit(main())
