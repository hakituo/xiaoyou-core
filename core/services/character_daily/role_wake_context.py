"""同 role 跨人设共享的唤醒上下文。

背景：
    同一个 QQ 账号下，Ling（ling）的不同人设（日常 / QQ / love）会被编码成不同的
    conversation_id（`{session_id}__persona__{persona_stem}`）。而 reply_policy 的
    "连续 DND 累积计数"原本是 per-conversation 的（_DND_PENDING[cid] 的长度），
    导致用户在人设 A 把Ling吵醒后，切到人设 B 时 B 的累积计数从 0 开始，
    重新撞上 sleeping 又要慢慢攒消息才能强制唤醒。

    这里维护一个 per-scope（如 "ling"）的累积计数，让同 role 不同人设的会话
    共享"已经连发了多少条 DND 消息"，从而 force_wake 概率跨人设继承，
    不再每个会话从 0 攒。

    注意：只共享"计数"，不共享消息内容（消息内容仍按 cid 存，避免人设间串味）。
"""

from __future__ import annotations

import threading
from typing import Dict

from core.utils.logger import get_logger

logger = get_logger(__name__)

# per-scope 累积 DND 计数：{scope: count}
# scope 即 role_id（"ling" / "aveline" / "rushuang" / "mianmian" ...）
_ROLE_DND_COUNT: Dict[str, int] = {}
_LOCK = threading.Lock()


def get_role_dnd_count(scope: str) -> int:
    """读取同 role 跨人设的 DND 累积计数。"""
    s = str(scope or "").strip().lower()
    if not s:
        return 0
    with _LOCK:
        return int(_ROLE_DND_COUNT.get(s, 0))


def bump_role_dnd_count(scope: str) -> int:
    """同 role 静默累积 +1，返回累积后的值。"""
    s = str(scope or "").strip().lower()
    if not s:
        return 0
    with _LOCK:
        _ROLE_DND_COUNT[s] = int(_ROLE_DND_COUNT.get(s, 0)) + 1
        return _ROLE_DND_COUNT[s]


def reset_role_dnd_count(scope: str) -> None:
    """同 role 成功唤醒后重置累积计数。"""
    s = str(scope or "").strip().lower()
    if not s:
        return
    with _LOCK:
        _ROLE_DND_COUNT[s] = 0
    logger.info("RoleWakeCtx: scope=%s DND 累积计数已重置（成功唤醒）", s)


def clear_role_dnd_count(scope: str) -> None:
    """清理指定 scope 的计数（用于测试或下线）。"""
    s = str(scope or "").strip().lower()
    if not s:
        return
    with _LOCK:
        _ROLE_DND_COUNT.pop(s, None)
