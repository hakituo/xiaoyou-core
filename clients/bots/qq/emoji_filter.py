"""QQ 侧 emoji 文本规范化与可选白名单过滤。"""

from __future__ import annotations

import re
from typing import Optional

# emoji 判定是「所有聊天端通用」的能力，真源在 core，QQ 与安卓端共用同一套范围表，
# 避免两份表各自漂移（安卓端对应 utils/TextSegmenter.kt 的 EMOJI_RANGES）。
from core.utils.text_segmenter import is_emoji_char as _is_emoji_char

__all__ = [
    "EMOJI_ALLOWLIST_ENABLED",
    "_allowed_emoji_cache",
    "_collect_allowed_emojis_from_persona",
    "_extract_emojis_from_text",
    "_is_emoji_char",
    "clear_allowed_emoji_cache",
    "get_allowed_emojis",
    "strip_ooc_emoji",
]


# 功能实现保留，但当前全局不启用 emoji 白名单过滤。
EMOJI_ALLOWLIST_ENABLED = False

# 允许的 emoji 缓存：persona_filename -> set(emoji字符)；None 表示人设加载失败
_allowed_emoji_cache: dict[str, Optional[set[str]]] = {}


def _extract_emojis_from_text(text: str) -> set[str]:
    """从文本中提取所有 emoji 字符。"""
    return {ch for ch in str(text or "") if _is_emoji_char(ch)}


def _collect_allowed_emojis_from_persona(persona_data: dict) -> set[str]:
    """从角色配置数据中递归收集允许使用的 emoji。"""
    collected: set[str] = set()
    if not isinstance(persona_data, dict):
        return collected

    scan_fields = [
        ("language_style", "tone_examples"),
        ("language_style", "keywords"),
        ("persona_enhance", "language_markers"),
        ("persona_enhance", "visual_instructions"),
    ]

    def _scan_value(value: object) -> None:
        if isinstance(value, str):
            collected.update(_extract_emojis_from_text(value))
        elif isinstance(value, list):
            for item in value:
                _scan_value(item)
        elif isinstance(value, dict):
            for nested_value in value.values():
                _scan_value(nested_value)

    for path in scan_fields:
        current: object = persona_data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = None
                break
        _scan_value(current)

    system_prompt_template = str(persona_data.get("system_prompt_template") or "")
    if system_prompt_template:
        collected.update(_extract_emojis_from_text(system_prompt_template))

    interaction = persona_data.get("interaction_logic")
    if isinstance(interaction, dict):
        interaction_template = str(interaction.get("system_prompt_template") or "")
        if interaction_template:
            collected.update(_extract_emojis_from_text(interaction_template))

    return collected


def get_allowed_emojis(persona_filename: str) -> Optional[set[str]]:
    """获取指定角色允许使用的 emoji 集合。

    返回值语义：
    - ``None``：白名单未启用，或人设未成功加载；不做 emoji 过滤。
    - ``set()``：白名单启用且人设没有声明允许项；过滤全部 emoji。
    """
    if not EMOJI_ALLOWLIST_ENABLED:
        return None

    cache_key = str(persona_filename or "").strip()
    if cache_key in _allowed_emoji_cache:
        return _allowed_emoji_cache[cache_key]

    allowed: set[str] = set()
    persona_loaded = False

    try:
        from core.character.managers.persona_manager import get_persona_manager

        persona_manager = get_persona_manager()
        persona_data = (
            persona_manager.get_persona_by_filename(cache_key)
            if cache_key
            else persona_manager.get_current_persona()
        )
        if isinstance(persona_data, dict) and persona_data:
            persona_loaded = True
            allowed = _collect_allowed_emojis_from_persona(persona_data)
            extends = str(persona_data.get("extends") or "").strip()
            if extends:
                parent_data = persona_manager.get_persona_by_filename(extends)
                if isinstance(parent_data, dict) and parent_data:
                    allowed |= _collect_allowed_emojis_from_persona(parent_data)
    except Exception:
        persona_loaded = False

    resolved = allowed if persona_loaded else None
    _allowed_emoji_cache[cache_key] = resolved
    return resolved


def clear_allowed_emoji_cache() -> None:
    """清除允许 emoji 缓存。"""
    _allowed_emoji_cache.clear()


def _remove_period_before_emoji(text: str) -> str:
    """删除紧邻 emoji 之前的中英文句号，保留原有空格。"""
    result: list[str] = []
    for ch in text:
        if _is_emoji_char(ch):
            trailing_spaces: list[str] = []
            while result and result[-1].isspace():
                trailing_spaces.append(result.pop())
            if result and result[-1] in {"。", "."}:
                result.pop()
            result.extend(reversed(trailing_spaces))
        result.append(ch)
    return "".join(result)


def strip_ooc_emoji(text: str, persona_filename: str = "") -> str:
    """规范化 QQ 文本，并在开关启用时执行 emoji 白名单过滤。

    白名单当前默认关闭，因此不会删除任何 emoji。无论开关状态如何，都会
    删除 emoji 前的句号和省略号，以保持 QQ 文本格式一致。
    """
    normalized_text = str(text or "")
    if not normalized_text:
        return normalized_text

    normalized_text = _remove_period_before_emoji(normalized_text)
    allowed = get_allowed_emojis(persona_filename)
    if allowed is None:
        cleaned = re.sub(r"\.\.\.|\.\.\.\.|\u2026+", "", normalized_text)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    result: list[str] = []
    previous_emoji_kept = False
    for ch in normalized_text:
        if _is_emoji_char(ch):
            previous_emoji_kept = ch in allowed
            if previous_emoji_kept:
                result.append(ch)
        elif ch == "\ufe0f":
            if previous_emoji_kept:
                result.append(ch)
        else:
            previous_emoji_kept = False
            result.append(ch)

    cleaned = "".join(result)
    cleaned = re.sub(r"\.\.\.|\.\.\.\.|\u2026+", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()
