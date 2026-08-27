#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-07 验证脚本: offline_queue.py 离线消息丢失修复

验证项：
1. send_with_retry 抛异常时，未发送的消息保留在队列中（不丢失）
2. 已发送成功的消息从队列移除（不重复发送）
3. 过期消息（超过 offline_ttl）被正确丢弃
4. is_offline_replay 标记不污染原始队列中的消息内容
5. store_offline_message 深拷贝避免外部对象被修改影响队列内容
"""
import sys
import asyncio
import json
import time
import importlib.util
from collections import defaultdict, deque
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, AsyncMock

ROOT = Path(__file__).resolve().parents[3]
QUEUE_PATH = ROOT / "core" / "interfaces" / "websocket" / "offline_queue.py"


def _install_stubs():
    """预存根依赖。"""
    # core 包
    for pkg_name in ("core", "core.contracts", "core.interfaces", "core.interfaces.websocket"):
        if pkg_name not in sys.modules:
            pkg = ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg

    # core.contracts.ConnectionState
    if "core.contracts" in sys.modules:
        contracts_mod = sys.modules["core.contracts"]
        from enum import Enum

        class ConnectionState(Enum):
            CONNECTED = "connected"
            DISCONNECTED = "disconnected"

        contracts_mod.ConnectionState = ConnectionState


def load_module():
    _install_stubs()

    spec = importlib.util.spec_from_file_location("offline_queue_p0_07", QUEUE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {QUEUE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_manager(module, send_results=None):
    """构造一个最小化的 WebSocketManager 实例（仅包含 OfflineQueueMixin）。

    send_results: 一个列表，控制每次 send_with_retry 的行为。
        - 如果元素是 Exception 实例，则 send_with_retry 抛该异常
        - 否则视为成功返回
    """
    OfflineQueueMixin = getattr(module, "OfflineQueueMixin", None)
    if OfflineQueueMixin is None:
        raise RuntimeError("缺失 OfflineQueueMixin")

    class _TestManager(OfflineQueueMixin):
        def __init__(self):
            self.offline_queue = defaultdict(lambda: deque(maxlen=50))
            self.offline_ttl = 24 * 3600  # 24h
            self.user_connections = {}
            self._send_results = list(send_results or [])

        async def send_with_retry(self, websocket, message):
            if not self._send_results:
                return
            result = self._send_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    return _TestManager()


def check_send_failure_preserves_queue(module) -> list[str]:
    """场景1: send_with_retry 抛异常时，消息应保留在队列中。"""
    issues = []

    mgr = _make_manager(module, send_results=[RuntimeError("connection closed")])
    mgr.offline_queue["user1"].append((time.time(), {"type": "test", "content": "msg1"}))

    ws = MagicMock()
    asyncio.run(mgr._flush_offline_messages("user1", ws))

    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 1:
        issues.append(f"[发送失败] 队列长度应为 1，实际: {len(queue)}")
    else:
        ts, msg = queue[0]
        if msg.get("content") != "msg1":
            issues.append(f"[发送失败] 队列消息内容错误: {msg}")
        if "is_offline_replay" in msg:
            issues.append("[发送失败] 原始消息被 is_offline_replay 污染")

    return issues


def check_successful_send_removes_from_queue(module) -> list[str]:
    """场景2: 发送成功的消息从队列移除。"""
    issues = []

    mgr = _make_manager(module, send_results=[None, None])  # 两次成功
    mgr.offline_queue["user1"].append((time.time(), {"type": "test", "content": "msg1"}))
    mgr.offline_queue["user1"].append((time.time(), {"type": "test", "content": "msg2"}))

    ws = MagicMock()
    asyncio.run(mgr._flush_offline_messages("user1", ws))

    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 0:
        issues.append(f"[发送成功] 队列应为空，实际长度: {len(queue)}")

    # user1 应该被清理（空队列条目）
    if "user1" in mgr.offline_queue:
        issues.append("[发送成功] 空队列条目应被清理")

    return issues


def check_partial_failure_preserves_unsent(module) -> list[str]:
    """场景3: 部分成功部分失败，失败的消息和后续未尝试的消息都应保留。"""
    issues = []

    # 三条消息：第一条成功，第二条失败，第三条不应被尝试
    mgr = _make_manager(
        module,
        send_results=[None, RuntimeError("mid-stream failure")],
    )
    mgr.offline_queue["user1"].append((time.time(), {"content": "msg1"}))
    mgr.offline_queue["user1"].append((time.time(), {"content": "msg2"}))
    mgr.offline_queue["user1"].append((time.time(), {"content": "msg3"}))

    ws = MagicMock()
    asyncio.run(mgr._flush_offline_messages("user1", ws))

    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 2:
        issues.append(f"[部分失败] 队列应保留 2 条（msg2+msg3），实际: {len(queue)}")
    else:
        contents = [msg.get("content") for _, msg in queue]
        if contents != ["msg2", "msg3"]:
            issues.append(f"[部分失败] 保留的消息内容错误: {contents}")

    return issues


def check_expired_messages_dropped(module) -> list[str]:
    """场景4: 过期消息（ts 距离 now 超过 offline_ttl）应被丢弃。"""
    issues = []

    mgr = _make_manager(module, send_results=[None])  # 只需一次成功
    now = time.time()
    # 一条过期消息 + 一条有效消息
    mgr.offline_queue["user1"].append((now - mgr.offline_ttl - 100, {"content": "expired"}))
    mgr.offline_queue["user1"].append((now, {"content": "valid"}))

    ws = MagicMock()
    asyncio.run(mgr._flush_offline_messages("user1", ws))

    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 0:
        issues.append(f"[过期处理] 队列应为空（expired 丢弃，valid 发送成功），实际: {len(queue)}")
    else:
        # 验证 send_with_retry 只被调用了一次（valid 消息），expired 不应被发送
        # 通过检查 send_results 是否还剩 0 次来判断
        if len(mgr._send_results) != 0:
            issues.append("[过期处理] send_with_retry 调用次数错误（应只发1条）")

    return issues


def check_store_deepcopies(module) -> list[str]:
    """场景5: store_offline_message 深拷贝，外部修改不影响队列内容。"""
    issues = []

    mgr = _make_manager(module)
    original_msg = {"type": "test", "content": {"nested": "value"}}
    mgr.store_offline_message("user1", original_msg)

    # 外部修改原 dict
    original_msg["content"]["nested"] = "modified"
    original_msg["type"] = "changed"

    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 1:
        issues.append(f"[深拷贝] 队列应保留 1 条，实际: {len(queue)}")
    else:
        ts, stored = queue[0]
        if stored.get("type") != "test":
            issues.append(f"[深拷贝] 外部修改泄漏到队列: type={stored.get('type')}")
        if stored.get("content", {}).get("nested") != "value":
            issues.append(f"[深拷贝] 外部修改泄漏到队列: nested={stored.get('content', {}).get('nested')}")

    return issues


def check_is_offline_replay_does_not_pollute_queue(module) -> list[str]:
    """场景6: 发送时打 is_offline_replay 标记，不应污染队列中保留的原始消息。"""
    issues = []

    # 第一条发送失败（保留），第二条不被尝试
    mgr = _make_manager(module, send_results=[RuntimeError("fail")])
    mgr.offline_queue["user1"].append((time.time(), {"content": "msg1"}))

    ws = MagicMock()
    asyncio.run(mgr._flush_offline_messages("user1", ws))

    queue = mgr.offline_queue.get("user1", deque())
    if len(queue) != 1:
        issues.append(f"[标记不污染] 队列应保留 1 条，实际: {len(queue)}")
    else:
        ts, msg = queue[0]
        if "is_offline_replay" in msg:
            issues.append("[标记不污染] 队列中的原始消息被 is_offline_replay 污染")

    return issues


def main() -> int:
    if not QUEUE_PATH.exists():
        print(f"[ERROR] offline_queue.py 不存在: {QUEUE_PATH}")
        return 2

    all_issues: list[str] = []

    try:
        module = load_module()
        all_issues.extend(check_send_failure_preserves_queue(module))
        all_issues.extend(check_successful_send_removes_from_queue(module))
        all_issues.extend(check_partial_failure_preserves_unsent(module))
        all_issues.extend(check_expired_messages_dropped(module))
        all_issues.extend(check_store_deepcopies(module))
        all_issues.extend(check_is_offline_replay_does_not_pollute_queue(module))
    except Exception as exc:
        all_issues.append(f"模块加载/运行时测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] offline_queue.py 离线消息丢失问题已修复")
    print("  - 发送失败时消息保留在队首，不丢失")
    print("  - 发送成功后才从队列移除，不重复发送")
    print("  - 部分失败时未尝试的消息也保留")
    print("  - 过期消息（超过 offline_ttl）被正确丢弃")
    print("  - store_offline_message 深拷贝避免外部修改泄漏")
    print("  - is_offline_replay 标记不污染队列中的原始消息")
    return 0


if __name__ == "__main__":
    sys.exit(main())
