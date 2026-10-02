from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Mapping


FAILURE_PLACEHOLDER_MARKERS = (
    "自动生成失败",
    "生成失败",
    "请稍后重试",
    "稍后重试",
    "系统提示稍后重试",
    "提示稍后重试",
    "服务暂时不可用",
    "请求失败",
    "无法生成",
)


def normalize_guard_text(text: Any) -> str:
    """归一化文本，便于做失败占位文案匹配。"""
    return " ".join(str(text or "").strip().split())


def contains_failure_placeholder(text: Any) -> bool:
    """判断文本是否包含明显的失败占位文案。"""
    normalized = normalize_guard_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in FAILURE_PLACEHOLDER_MARKERS)


def is_valid_daily_summary_text(text: Any) -> bool:
    """判断每日总结正文是否可用于持久化与入记忆。"""
    normalized = normalize_guard_text(text)
    return bool(normalized) and not contains_failure_placeholder(normalized)


def daily_summary_similarity(left: Any, right: Any) -> float:
    """计算两篇角色日记正文的字符级相似度。

    去掉空白和标点后再比较，避免只靠换标点或分段绕过角色撞稿检测。
    """
    left_text = re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_guard_text(left))
    right_text = re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_guard_text(right))
    if not left_text or not right_text:
        return 0.0
    return SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()


def is_overly_similar_daily_summary(
    left: Any,
    right: Any,
    *,
    threshold: float = 0.78,
) -> bool:
    """判断两个不同角色的日记是否已经接近同一篇稿子。"""
    left_text = normalize_guard_text(left)
    right_text = normalize_guard_text(right)
    if min(len(left_text), len(right_text)) < 80:
        return left_text == right_text and bool(left_text)
    return daily_summary_similarity(left_text, right_text) >= threshold


def _extract_stats(summary_obj: Any) -> Mapping[str, Any]:
    stats = getattr(summary_obj, "stats", None)
    if isinstance(summary_obj, Mapping):
        stats = summary_obj.get("stats", stats)
    if isinstance(stats, Mapping):
        return stats
    return {}


def is_polluted_daily_summary_payload(summary_obj: Any) -> bool:
    """判断 DailySummary 或其字典载荷是否属于失败污染数据。"""
    if summary_obj is None:
        return False

    summary_text = getattr(summary_obj, "summary", None)
    if isinstance(summary_obj, Mapping):
        summary_text = summary_obj.get("summary", summary_text)

    if contains_failure_placeholder(summary_text):
        return True

    stats = _extract_stats(summary_obj)
    if stats.get("generated") is False:
        return True
    return any(key in stats for key in ("error", "parse_error"))


def is_valid_daily_summary_obj(summary_obj: Any) -> bool:
    """判断 DailySummary 对象是否是可持久化的有效总结。"""
    if summary_obj is None:
        return False
    return not is_polluted_daily_summary_payload(summary_obj) and is_valid_daily_summary_text(
        getattr(summary_obj, "summary", None)
        if not isinstance(summary_obj, Mapping)
        else summary_obj.get("summary")
    )


def is_polluted_daily_summary_memory(memory: Mapping[str, Any] | None) -> bool:
    """判断 weighted memory 是否是被失败占位文案污染的每日总结记忆。"""
    if not isinstance(memory, Mapping):
        return False

    metadata = memory.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    entry_type = str(
        metadata.get("entry_type")
        or memory.get("entry_type")
        or memory.get("type")
        or ""
    ).strip().lower()
    thought = str(metadata.get("thought") or memory.get("thought") or "").strip().lower()

    if entry_type != "daily_summary" and thought != "auto_generated_daily_summary":
        return False

    return contains_failure_placeholder(memory.get("content")) or contains_failure_placeholder(
        memory.get("summary")
    )
