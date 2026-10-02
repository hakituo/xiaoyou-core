"""文本清洗与展示前分组：剥时间戳 / 去句尾多余标点 / 按 Markdown 结构分组。

从 ``text_segmenter.py`` 拆出。分组后每组的断句仍走 [split_chat_message]。
"""
from __future__ import annotations

import re

from core.utils.text_segmenter_core import split_chat_message
from core.utils.text_segmenter_rules import (
    AI_TIMESTAMP_PATTERN,
    TRAILING_PUNCT_CHARS,
    _LATEX_MARKER_RE,
    _MARKDOWN_BLOCK_START_RE,
    _MARKDOWN_TABLE_LINE_RE,
)


# ==========================================================================
# 文本清洗
# ==========================================================================

def strip_ai_timestamp(text: str) -> str:
    """剥离模型回复中模仿历史消息格式生成的时间戳。

    全局匹配，不仅匹配行首，也匹配回复中间出现的时间戳。
    """
    text = str(text or "")
    text = AI_TIMESTAMP_PATTERN.sub("", text)
    return text.strip()


def strip_trailing_punctuation(text: str) -> str:
    """去除消息末尾的尾随标点（句号、逗号等），让聊天消息更自然。

    - 去除括号前的句号（如"。（"→"（"）。
    - 去除括号内部末尾的句号（如"（xxx。）"→"（xxx）"）。
    - 去除句尾的尾随句号/逗号（如"好呀好呀。"→"好呀好呀"、"好呀好呀，"→"好呀好呀"）。
    - 仅清理末尾拖尾标点，句中逗号/句号等保留，不影响语义。
    """
    text = str(text or "")
    text = re.sub(r"[。.]\s*(?=[（(])", "", text)
    # 括号内部末尾的句号去除：（...。）→（...）
    text = re.sub(r"[。.]+\s*([）)])", r"\1", text)
    # 句尾尾随标点清理：保留最后一个非拖尾标点前的内容，
    # 例如"噢噢，好呀好呀，" -> "噢噢，好呀好呀"（结尾逗号去掉，句中逗号保留）
    text = text.rstrip(TRAILING_PUNCT_CHARS).strip()
    # 兜底：去掉可能因 rstrip 后仍残留的句尾英文点
    text = re.sub(r"[。.]+$", "", text)
    return text.strip()


def clean_chat_text(text: str) -> str:
    """断句前/展示前的统一清洗：剥时间戳 + 去句尾多余标点。"""
    text = strip_ai_timestamp(text)
    return strip_trailing_punctuation(text)


def _group_display_lines(text: str) -> list[tuple[str, bool]]:
    """按 Markdown 块级结构把清洗后的文本切成「组」，返回 `(文本, 是否整组保留)`。

    只有真正跨行连续的结构（代码围栏、块级公式、表格）和单行的块级标记
    （标题 / 列表项 / 引用 / 含 `$$` 的行）需要整组保留；普通段落行照常交给
    [split_chat_message] 按标点切气泡。

    旧实现是「命中任一标记就整条消息透传」：模型输出里只要出现一个 `- ` 列表项、
    一个 `#` 标题或一对 `|`，整条回复就退化成一个大气泡、换行原样显示，而同样
    措辞但没用 markdown 的另一条回复却被正常切成多个气泡。这就是「一会能断句
    一会不能断句」的来源。改成按行分组后，断句行为只取决于文本本身，与模型
    这一轮有没有用 markdown 无关。
    """
    lines = text.split("\n")
    groups: list[tuple[str, bool]] = []
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        # 1) 代码围栏：从 ``` / ~~~ 起一直到闭合围栏（流式未闭合就吃到结尾）。
        fence = None
        if stripped.startswith("```"):
            fence = "```"
        elif stripped.startswith("~~~"):
            fence = "~~~"
        if fence is not None:
            buf: list[str] = []
            cursor = index
            while cursor < total:
                buf.append(lines[cursor])
                cursor += 1
                # cursor - 1 == index 时刚收进去的是开启围栏本身，不能当闭合围栏
                if cursor > index + 1 and lines[cursor - 1].strip().startswith(fence):
                    break
            groups.append(("\n".join(buf), True))
            index = cursor
            continue

        # 2) 块级公式 $$ ... $$：整体保留，流式阶段未闭合也保留。
        if stripped == "$$":
            buf = []
            cursor = index
            while cursor < total:
                buf.append(lines[cursor])
                cursor += 1
                if cursor > index + 1 and lines[cursor - 1].strip() == "$$":
                    break
            groups.append(("\n".join(buf), True))
            index = cursor
            continue

        # 3) 连续的表格行：整组保留，否则表头/分隔行/数据行会被拆散。
        if _MARKDOWN_TABLE_LINE_RE.match(line):
            buf = []
            cursor = index
            while cursor < total and _MARKDOWN_TABLE_LINE_RE.match(lines[cursor]):
                buf.append(lines[cursor].strip())
                cursor += 1
            groups.append(("\n".join(buf), True))
            index = cursor
            continue

        # 4) 单行块级结构（标题 / 列表项 / 引用 / 含 $$）：整行保留。
        atomic = bool(
            _MARKDOWN_BLOCK_START_RE.search(stripped) or _LATEX_MARKER_RE.search(stripped)
        )
        groups.append((stripped, atomic))
        index += 1

    return groups


def split_for_display(
    text: str,
    max_len: int = 150,
    comma_split_prob: float = 0.2,
    min_split_len: int = 40,
) -> list[str]:
    """展示前的分段：清洗 -> 按结构分组 -> 每组断句 -> 每段再清一次句尾标点。

    与安卓端 `utils/TextSegmenter.kt` 的 `splitForDisplay` 等价，两步清洗都不能省：

    - 第一步剥掉模型模仿历史消息格式输出的时间戳；
    - 断句只在"断点处"吃掉句号，某段只产出 1 块时会原样返回带句号的原文
      （例如换行分段后的"你要求的。"），所以每段还要再 strip 一次。
      QQ 端同理：`transport.send_message` 是在 split 之后对每条消息单独 strip。

    分组规则见 [_group_display_lines]：整组保留的块（代码 / 公式 / 表格 / 单行块级
    标记）不再二次 strip，避免把代码末尾的点也吃掉。
    """
    cleaned = clean_chat_text(text)
    if not cleaned:
        return []
    result: list[str] = []
    for group_text, atomic in _group_display_lines(cleaned):
        if atomic:
            if group_text.strip():
                result.append(group_text)
            continue
        for chunk in split_chat_message(group_text, max_len, comma_split_prob, min_split_len):
            chunk = strip_trailing_punctuation(chunk)
            if chunk:
                result.append(chunk)
    return result
