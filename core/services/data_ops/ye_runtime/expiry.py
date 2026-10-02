"""叶运行态时限解析与过期清理。"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Mapping, Optional

from core.services.data_ops.ye_runtime.document import _clean_text


def _prune_expired(state: dict[str, Any], now: datetime) -> set[str]:
    changed: set[str] = set()
    for field in ("active_rules", "time_constraints"):
        items = state.get(field) if isinstance(state.get(field), list) else []
        kept = [item for item in items if not _is_expired(item, now)]
        if len(kept) != len(items):
            state[field] = kept
            changed.add(field)
    return changed


def _is_expired(item: Any, now: datetime) -> bool:
    if not isinstance(item, Mapping):
        return False
    raw = str(item.get("expires_at") or "").strip()
    if not raw:
        return False
    try:
        expires = datetime.fromisoformat(raw)
        if expires.tzinfo is None and now.tzinfo is not None:
            expires = expires.replace(tzinfo=now.tzinfo)
        return expires <= now
    except ValueError:
        return False


def _parse_expiry(text: str, now: datetime) -> Optional[str]:
    match = re.search(
        r"(?:(上午|中午|下午|晚上|凌晨|早上))?\s*"
        r"([0-2]?\d|[一二两三四五六七八九十]+)\s*[点:：]([0-5]?\d)?",
        text,
    )
    if not match:
        return None
    period = match.group(1) or ""
    hour = _cn_number(match.group(2))
    minute = int(match.group(3) or 0)
    if hour is None or hour > 23:
        return None
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    if period in {"凌晨", "早上", "上午"} and hour == 12:
        hour = 0
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat(timespec="minutes")


def _cn_number(text: str) -> Optional[int]:
    if text.isdigit():
        return int(text)
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + digits.get(text[1:], 0)
    if "十" in text:
        left, right = text.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    return digits.get(text)


def _strip_tail(text: str, tails: tuple[str, ...]) -> str:
    value = _clean_text(text)
    changed = True
    while changed:
        changed = False
        for tail in tails:
            if value.endswith(tail):
                value = value[: -len(tail)].strip()
                changed = True
    return value
