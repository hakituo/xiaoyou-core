"""回归消息等待期的 pending 状态管理。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class PendingReturn:
    """一次待处理的回归状态。"""

    conversation_id: str
    role_id: str
    activity: str
    return_type: Literal["work", "sleep"]
    source: str
    message_sent_ts: float = 0.0
    grace_expire_ts: float = 0.0
    resolved: bool = False
    decision: Literal["pending", "stay", "leave"] = "pending"


# 内存状态（按会话）
_pending_returns: dict[str, PendingReturn] = {}
_lock = threading.Lock()

# 发消息后多久内用户回复可影响决策
DEFAULT_GRACE_SECONDS = 90.0


def get_pending_return(conversation_id: str) -> dict[str, Any] | None:
    """获取指定会话的 pending return 状态。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return None
    with _lock:
        pending = _pending_returns.get(cid)
        if not pending:
            return None
        now = time.time()
        if pending.resolved or now > pending.grace_expire_ts:
            return None
        return {
            "conversation_id": pending.conversation_id,
            "role_id": pending.role_id,
            "activity": pending.activity,
            "return_type": pending.return_type,
            "source": pending.source,
            "message_sent_ts": pending.message_sent_ts,
            "grace_expire_ts": pending.grace_expire_ts,
            "decision": pending.decision,
        }


def resolve_pending_return(
    conversation_id: str,
    decision: Literal["stay", "leave"],
) -> PendingReturn | None:
    """标记 pending return 已解决并返回状态。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return None
    with _lock:
        pending = _pending_returns.get(cid)
        if not pending:
            return None
        pending.resolved = True
        pending.decision = decision
        return pending


def clear_pending_return(conversation_id: str) -> None:
    """清理指定会话的 pending return 状态。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return
    with _lock:
        _pending_returns.pop(cid, None)


def reset_all_pending_returns() -> None:
    """重置所有 pending return 状态（测试用）。"""
    with _lock:
        _pending_returns.clear()
