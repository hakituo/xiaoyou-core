"""每日总结输出解析辅助。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from core.utils.json_utils import extract_json_object


def _unwrap_daily_summary_dict(data: Any) -> Optional[Dict[str, Any]]:
    """从常见包裹层中提取真正的 DailySummary 载荷。"""
    if not isinstance(data, dict):
        return None
    if "date" in data and "summary" in data:
        return dict(data)
    for key in ("daily_summary", "result", "data", "output", "payload"):
        nested = data.get(key)
        if isinstance(nested, dict) and "date" in nested and "summary" in nested:
            return dict(nested)
    for value in data.values():
        if isinstance(value, dict) and "date" in value and "summary" in value:
            return dict(value)
    return None


def _decode_json_string_fragment(fragment: str) -> str:
    """尽量按 JSON 字符串规则解码字段片段。"""
    try:
        return json.loads(f'"{fragment}"')
    except Exception:
        return str(fragment or "").replace('\\"', '"').replace("\\n", "\n").strip()


def _extract_daily_summary_from_text(raw_out: str) -> Optional[Dict[str, Any]]:
    """当外层 JSON 破损时，从原始文本回收 DailySummary 关键字段。"""
    text = str(raw_out or "").strip()
    if not text:
        return None
    date_match = re.search(r'"date"\s*:\s*"([^"]+)"', text)
    summary_match = re.search(r'"summary"\s*:\s*"([\s\S]*?)"\s*,\s*"stats"\s*:', text)
    stats_match = re.search(
        r'"stats"\s*:\s*(\{[\s\S]*?\})\s*(?:,\s*"tomorrow_tone"|}\s*$)',
        text,
    )
    tone_match = re.search(r'"tomorrow_tone"\s*:\s*["“]([\s\S]*?)["”]\s*}\s*$', text)
    if not date_match or not summary_match:
        return None

    data: Dict[str, Any] = {
        "date": _decode_json_string_fragment(date_match.group(1)),
        "summary": _decode_json_string_fragment(summary_match.group(1)),
    }
    if stats_match:
        try:
            data["stats"] = json.loads(stats_match.group(1))
        except Exception:
            pass
    if tone_match:
        data["tomorrow_tone"] = _decode_json_string_fragment(tone_match.group(1))
    return data


def parse_daily_summary_payload(raw_out: str) -> Dict[str, Any]:
    """解析每日总结输出，优先整块 JSON，失败后回收到关键字段。"""
    normalized = _unwrap_daily_summary_dict(extract_json_object(raw_out))
    if normalized:
        return normalized
    recovered = _extract_daily_summary_from_text(raw_out)
    if recovered:
        return recovered
    raise ValueError("LLM returned invalid daily summary payload")
