"""通用聊天断句 / 清洗的**规则常量**（Python 侧单点）。

从 ``text_segmenter.py`` 拆出，对应安卓端 ``utils/text/TextSegmentRules.kt``：
两端规则常量必须一致，由 ``tests/scripts/android_frontend/verify_text_segmenter_parity.py``
逐项比对。**改这里的任何一个常量都等于改两端口径**，改完必须跑该脚本。
"""
from __future__ import annotations

import re


# 模型回复中模仿历史消息格式生成的时间戳（如 [05-22 01:45] / [今天 20:00] / [3天前 08:00]），全局匹配。
# 历史消息在喂给模型前会被加上 `[今天/昨天/X天前 HH:MM] ` 前缀（见
# core/agents/chat_agent_components/context_budget/history_fetch.py），
# 模型很容易把这个格式学过去并在回复里输出时间戳，所以所有端都要剥。
AI_TIMESTAMP_PATTERN_SOURCE = (
    r"\[(?:(?:\d{2,4}(?:-\d{2}){1,2}|今天|昨天|\d+天前)\s+)?"
    r"\d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*"
)
AI_TIMESTAMP_PATTERN = re.compile(AI_TIMESTAMP_PATTERN_SOURCE)

# 末尾尾随标点集合：句号、逗号、英文点/逗号、省略号、分号等。
# 仅当它们出现在句尾作为拖尾多余标点时清理，让气泡结尾更自然。
TRAILING_PUNCT_CHARS = "。.，,．、；;…"


# Markdown 单行块级结构：代码块 / 标题 / 列表 / 引用块。
# 这类内容被拆成多段渲染会破坏结构（列表续不上、代码块裂开）。
_MARKDOWN_BLOCK_START_RE = re.compile(r"(?m)^\s{0,3}(?:```|~~~|#{1,6}\s|[-*+]\s|>)")

# GFM 表格行：整行由 `|` 包裹，必须成组保留。
_MARKDOWN_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")

# 未转义的 `$$`：LaTeX 边界，所在行整行保留。
_LATEX_MARKER_RE = re.compile(r"(?<!\\)\$\$")


# ==========================================================================
# 断句常量
# ==========================================================================

CONTINUATION_ADVERBS = frozenset({"再", "又", "还", "更"})

CONTINUATION_ENDINGS = (
    "：",
    ":",
    "——",
    "—",
)

HARD_BUBBLE_BOUNDARY_ENDINGS = (
    "。",
    ".",
    "！",
    "!",
    "？",
    "?",
    "…",
)

EXPLICIT_SPACE_BOUNDARY_ENDINGS = HARD_BUBBLE_BOUNDARY_ENDINGS + (
    "，",
    ",",
    "；",
    ";",
)

PUNCTUATION_FOR_SPACE_GUARD = frozenset(
    "。.!！?？,，;；:：、…~～()（）[]【】{}<>《》\"'“”‘’"
)

# 省略号前若只是这么短（字符数）的"短促前缀"，不在省略号处断句，
# 而是与后续普通句子合并为同一气泡（例如"就是……戳废了"应合一，而非断成"就是……"）。
ELLIPSIS_MERGE_PREFIX_LIMIT = 6


# --------------------------------------------------------------------------
# 编号列表识别用的常量（消费方：text_segmenter_numbered）
# --------------------------------------------------------------------------

# 编号列表项：`1. xxx`、`2、xxx`、`3) xxx` 这类写法。
# 编号后必须接实际内容（字母或汉字），避免把 3.5、v1.2.3、2026.9.2 这类小数/版本号误判成编号。
_NUMBERED_ITEM_RE = re.compile(r"(?P<num>\d{1,2})(?P<sep>[.．、)）])")

# 编号前允许出现的字符：行首、空白或中英文标点（数字与句点会先被排除）
_NUMBERED_ITEM_ALLOWED_PREV = frozenset(
    "。.!！?？,，;；:：、…~～()（）[]【】{}<>《》\"'“”‘’——-—*·/|"
)

# 前言（编号列表之前的内容）与首个编号项合并的最大长度，超过则前言单独成气泡
_NUMBERED_LIST_LEAD_MERGE_LIMIT = 24

# 前言以这些符号结尾时，无论多长都与首个编号项合并（"你可以这样做：1. ..." 不该只发一个冒号）
_NUMBERED_LIST_LEAD_MERGE_ENDINGS = ("：", ":", "——", "—", "-", "～", "~")
