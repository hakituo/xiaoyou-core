"""QQ 反应延迟标签（[DELAY:3s] / [WAIT:2s] / [REACTION:1s]）处理。

合并自原 utils.py 末尾的 reaction_delay 段。
"""

from __future__ import annotations

import re

DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS = 12.0

# 匹配单个延迟标签，捕获秒数
_REACTION_DELAY_TAG_RE = re.compile(
    r"\[(?:DELAY|WAIT|REACTION)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:s|秒)?\]",
    flags=re.IGNORECASE,
)
# 仅匹配气泡开头的连续延迟标签前缀
_LEADING_REACTION_DELAY_RE = re.compile(
    r"^\s*(?:(?:\[(?:DELAY|WAIT|REACTION)\s*:\s*[0-9]+(?:\.[0-9]+)?\s*(?:s|秒)?\])\s*)+",
    flags=re.IGNORECASE,
)


def extract_leading_reaction_delay(
    text: str,
    max_seconds: float = DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS,
) -> tuple[str, float]:
    """提取气泡开头的反应延迟标签，只影响当前气泡发送前的额外等待。

    返回 (去除前缀后的文本, 累计延迟秒数)。
    """
    content = str(text or "")
    matched = _LEADING_REACTION_DELAY_RE.match(content)
    if not matched:
        return content.strip(), 0.0

    delay_seconds = 0.0
    prefix = matched.group(0) or ""
    for item in _REACTION_DELAY_TAG_RE.finditer(prefix):
        try:
            delay_seconds += float(item.group(1) or 0.0)
        except Exception:
            continue

    safe_max = max(0.0, float(max_seconds or 0.0))
    if safe_max > 0:
        delay_seconds = min(delay_seconds, safe_max)
    return content[matched.end():].strip(), max(0.0, delay_seconds)


def strip_all_reaction_delay_tags(text: str) -> str:
    """全局剥离反应延迟标签，避免标签泄漏到最终展示文本。"""
    content = str(text or "")
    content = _REACTION_DELAY_TAG_RE.sub("", content)
    return content.strip()
