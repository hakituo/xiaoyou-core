"""编号列表识别：把行内 `1. xxx 2. xxx` 按编号切成多行。

从 ``text_segmenter.py`` 拆出。切成多行后交给换行断句逐行处理，
避免「第一项说了一半就断句、下一条又接上 2.」的割裂感。
"""
from __future__ import annotations

from core.utils.text_segmenter_rules import (
    _NUMBERED_ITEM_ALLOWED_PREV,
    _NUMBERED_ITEM_RE,
    _NUMBERED_LIST_LEAD_MERGE_ENDINGS,
    _NUMBERED_LIST_LEAD_MERGE_LIMIT,
)


# ==========================================================================
# 编号列表识别
# ==========================================================================

def is_numbered_item_start(s: str, idx: int) -> bool:
    """判断 idx 处的数字是否可能是编号列表项的起点。"""
    if idx <= 0:
        return True
    prev = s[idx - 1]
    if prev.isspace():
        return True
    if prev.isdigit() or prev == ".":
        return False
    return prev in _NUMBERED_ITEM_ALLOWED_PREV


def find_numbered_list_starts(s: str) -> list[int]:
    """找出编号列表各项的起始下标。

    只认编号严格递增的最长连续段（1. 2. 3.），
    至少两项才认为这是编号列表，避免误伤小数、版本号、日期等。
    """
    candidates: list[tuple[int, int]] = []
    for m in _NUMBERED_ITEM_RE.finditer(s):
        start = m.start()
        if not is_numbered_item_start(s, start):
            continue
        look = m.end()
        while look < len(s) and s[look].isspace():
            look += 1
        next_char = s[look] if look < len(s) else ""
        if not (next_char.isalpha() or "\u4e00" <= next_char <= "\u9fff"):
            continue
        candidates.append((start, int(m.group("num"))))

    if len(candidates) < 2:
        return []

    best: list[tuple[int, int]] = []
    idx = 0
    while idx < len(candidates):
        seq = [candidates[idx]]
        nxt = idx + 1
        while nxt < len(candidates) and candidates[nxt][1] > seq[-1][1]:
            seq.append(candidates[nxt])
            nxt += 1
        if len(seq) > len(best):
            best = seq
        idx = nxt

    if len(best) < 2:
        return []
    return [start for start, _ in best]


def normalize_numbered_list(s: str) -> str:
    """把行内编号列表（`1. xxx 2. xxx 3. xxx`）按编号切成多行。

    切成多行后由换行断句逻辑逐行处理，每个编号项成为独立气泡，
    不会出现"第一项说了一半就断句、下一条又接上 2."的割裂感。
    """
    starts = find_numbered_list_starts(s)
    if not starts:
        return s

    segments: list[str] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(s)
        segments.append(s[start:end])

    lead = s[: starts[0]]
    lead_stripped = lead.strip()
    # 前言与编号之间若已有显式换行，尊重原文，不与首个编号项合并
    lead_has_newline = lead.rstrip(" \t").endswith("\n")
    merge_lead = bool(lead_stripped) and not lead_has_newline and (
        len(lead_stripped) <= _NUMBERED_LIST_LEAD_MERGE_LIMIT
        or lead_stripped.endswith(_NUMBERED_LIST_LEAD_MERGE_ENDINGS)
    )

    if lead_stripped:
        if merge_lead:
            gap = " " if lead[-1:].isspace() else ""
            segments[0] = f"{lead_stripped}{gap}{segments[0]}"
        else:
            segments.insert(0, lead_stripped)

    return "\n".join(segment.strip() for segment in segments if segment.strip())
