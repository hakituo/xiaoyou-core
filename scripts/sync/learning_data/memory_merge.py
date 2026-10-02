"""记忆文件的并集合并：按条目身份取并集，同一条目取更新的一份。

记忆与聊天记录同源问题：两个系统各自累积（加权记忆、短期记忆、会话列表、
按指纹索引的持久状态），整文件「谁新用谁」会丢掉另一边的积累。

三种落盘形状都能覆盖：

- 顶层数组（``short_term/*_short.json``、``sessions.json``）：按 ``id`` 取并集，
  缺 ``id`` 的条目用内容指纹当身份；
- 顶层对象且含条目数组（``weighted/*/*_weighted.json`` 的 ``weighted_memories``）：
  列表字段按条目并集，其余标量键取「更新」的一方（如 ``last_updated`` 取更晚的）；
- 「指纹 → 条目」映射（``persistent_states_*.json``）：按键取并集，同一键取更新的一份。

「更新」的判据是 ``timestamp`` / ``last_access_time`` / ``updated_at`` / ``created_at`` /
``last_updated`` 里的最大值（统一成可排序字符串，数字与时间串混排也不报错），
并列时再用规范化内容兜底，所以合并结果与先后顺序无关，且对已合并结果幂等。

只在「两端都相对基线改过」时才会走到这里；只有一端改过时仍是普通复制，
因此「删除」仍能正常传播。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

_RECENCY_FIELDS = (
    "timestamp",
    "last_access_time",
    "updated_at",
    "created_at",
    "last_updated",
)
_IDENTITY_FIELDS = ("id", "event_id")


def union_memory_json(left: bytes, right: bytes) -> Optional[bytes]:
    """两侧记忆 JSON 的并集；任一侧不是合法 JSON 时返回 None（由调用方报失败）。"""
    if not left:
        return right
    if not right:
        return left
    mine = _load(left)
    theirs = _load(right)
    if mine is None or theirs is None:
        return None
    return _dump(union_root(mine, theirs))


def union_root(mine: Any, theirs: Any) -> Any:
    """顶层合并：同形状时按键 / 按条目取并集，形状不一致时取更新的一方。"""
    if isinstance(mine, list) and isinstance(theirs, list):
        return _union_entries(mine, theirs)
    if isinstance(mine, dict) and isinstance(theirs, dict):
        return _union_mapping(mine, theirs)
    return _pick_later(mine, theirs)


def _union_mapping(mine: Dict[str, Any], theirs: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key in sorted(set(mine) | set(theirs)):
        if key not in mine:
            merged[key] = theirs[key]
        elif key not in theirs:
            merged[key] = mine[key]
        else:
            merged[key] = _union_field(mine[key], theirs[key])
    return merged


def _union_field(mine: Any, theirs: Any) -> Any:
    """同一个键：列表按键内条目并集，其余（含条目对象本身）取更新的一方。"""
    if mine == theirs:
        return mine
    if isinstance(mine, list) and isinstance(theirs, list):
        return _union_entries(mine, theirs)
    return _pick_later(mine, theirs)


def _union_entries(mine: List[Any], theirs: List[Any]) -> List[Any]:
    """按身份取并集，同一身份保留更新的一份，最后按时间键重排。"""
    index: Dict[str, Any] = {}
    for item in list(mine) + list(theirs):
        key = _identity(item)
        current = index.get(key)
        if current is None or _rank(item) > _rank(current):
            index[key] = item
    return sorted(index.values(), key=lambda item: (_rank(item), _identity(item)))


def _identity(item: Any) -> str:
    if isinstance(item, dict):
        for field in _IDENTITY_FIELDS:
            value = str(item.get(field) or "").strip()
            if value:
                return f"{field}:{value}"
    return "sha:" + _sha1(_canonical(item))


def _rank(item: Any) -> Tuple[str, str]:
    """排序键：先比时间（越晚越大），并列再比规范化内容，保证可交换且幂等。"""
    return (_recency(item), _canonical(item))


def _pick_later(mine: Any, theirs: Any) -> Any:
    return mine if _rank(mine) >= _rank(theirs) else theirs


def _recency(item: Any) -> str:
    if isinstance(item, dict):
        stamps = [_stamp(item.get(field)) for field in _RECENCY_FIELDS]
        return max((stamp for stamp in stamps if stamp), default="")
    if isinstance(item, list) and item:
        return max((_recency(entry) for entry in item), default="")
    return ""


def _stamp(raw: Any) -> str:
    """把时间字段统一成可排序字符串：数字左补零定长，时间串原样（同格式可直接比大小）。"""
    if raw is None or isinstance(raw, bool):
        return ""
    if isinstance(raw, (int, float)):
        return f"{float(raw):020.6f}"
    return str(raw).strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):  # pragma: no cover - JSON 解析结果必然可序列化
        return repr(value)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load(raw: bytes) -> Optional[Any]:
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def _dump(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
