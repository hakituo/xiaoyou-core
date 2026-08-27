"""QQ 侧 OOC emoji 过滤。"""

from __future__ import annotations

import re
from typing import Optional

# 允许的 emoji 缓存：persona_filename -> set(emoji字符)；None 表示人设加载失败
_allowed_emoji_cache: dict[str, Optional[set[str]]] = {}

# Emoji Unicode 范围（用于检测文本中的 emoji 字符）
# 注意：范围要精确，避免误伤中文标点等非 emoji 字符
_EMOJI_RANGES = [
    (0x1F600, 0x1F64F),
    (0x1F300, 0x1F5FF),
    (0x1F680, 0x1F6FF),
    (0x1F1E0, 0x1F1FF),
    (0x1F900, 0x1F9FF),
    (0x1FA00, 0x1FA6F),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
    (0x2300, 0x23FF),
    (0x2B50, 0x2B55),
    (0x203C, 0x2049),
    (0x2122, 0x2122),
    (0x2194, 0x21AA),
    (0x231A, 0x231B),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2614, 0x2615),
    (0x2648, 0x2653),
    (0x267F, 0x267F),
    (0x2693, 0x2693),
    (0x26A1, 0x26A1),
    (0x26AA, 0x26AB),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26CE, 0x26CE),
    (0x26D4, 0x26D4),
    (0x26EA, 0x26EA),
    (0x26F2, 0x26F3),
    (0x26F5, 0x26F5),
    (0x26FA, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0xE0020, 0xE007F),
]


def _is_emoji_char(ch: str) -> bool:
    """判断单个字符是否是 emoji。"""
    cp = ord(ch)
    for start, end in _EMOJI_RANGES:
        if start <= cp <= end:
            return True
    return False


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
    - `None`：人设未成功加载，保守地不做过滤，避免误伤。
    - `set()`：人设成功加载，但没有声明任何允许 emoji，此时应过滤掉全部 emoji。
    """
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


def strip_ooc_emoji(text: str, persona_filename: str = "") -> str:
    """剥离人设之外的 emoji，以及省略号。

    会删除：
    - 人设之外的 emoji
    - 中文省略号 "…" 和 "……"（U+2026）
    """
    normalized_text = str(text or "")
    if not normalized_text:
        return normalized_text

    allowed = get_allowed_emojis(persona_filename)
    if allowed is None:
        # 人设加载失败时，仅删除省略号，不删除 emoji
        cleaned = re.sub(r"\.\.\.|\.\.\.\.|\u2026+", "", normalized_text)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    result: list[str] = []
    for ch in normalized_text:
        if _is_emoji_char(ch):
            if ch in allowed:
                result.append(ch)
        else:
            result.append(ch)

    cleaned = "".join(result)
    # 删除省略号（包括中文省略号 … 和连续的多个）
    cleaned = re.sub(r"\.\.\.|\.\.\.\.|\u2026+", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()
