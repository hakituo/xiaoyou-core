#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验「通用聊天断句/清洗」两端规则是否一致。

背景：QQ 端（Python）与安卓端（Kotlin）用的是同一套断句与清洗规则，但两份代码
物理上不可能共用一个文件，容易一边改了另一边没跟上。本脚本做两件事：

1. 常量对齐：Python 侧 `core/utils/text_segmenter*.py`（门面 + 子模块，规则常量单点在
   `text_segmenter_rules.py`）与安卓 `utils/text/TextSegmentRules.kt`
   的断句/清洗常量逐项比对（尾随标点集、硬气泡边界、时间戳正则、emoji 范围表，
   以及展示分组用的三个 Markdown/LaTeX 正则）。
2. 结构对齐：展示层拆分新增的「按结构分组」与「行内 span 修复」两端都必须存在，
   避免一边重构掉了另一边还留着。
3. 行为自测：对 Python 公共模块跑一批固定用例，确认规则本身没被改坏。

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\android_frontend\\verify_text_segmenter_parity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils.text_segmenter import (  # noqa: E402
    EMOJI_RANGES,
    HARD_BUBBLE_BOUNDARY_ENDINGS,
    TRAILING_PUNCT_CHARS,
    clean_chat_text,
    split_chat_message,
    split_for_display,
    strip_ai_timestamp,
    strip_trailing_punctuation,
)

PY_SEGMENTER_DIR = ROOT / "core" / "utils"
# 2026-09-24：Python 侧已按「薄壳门面 + 子模块」拆分，与安卓侧 utils/text/ 子包对齐
# （规则常量在 text_segmenter_rules.py、emoji 范围表在 text_segmenter_emoji.py、
# 展示分组在 text_segmenter_clean.py、行内 span 修复在 text_segmenter_force.py）。
# 本脚本做的是**源文本**扫描，必须覆盖整族文件，否则门面里只剩 import 会扫不到常量。
PY_SEGMENTER_GLOB = "text_segmenter*.py"
# 安卓端已按职责拆到 utils/text/ 子包，规则常量单点在 TextSegmentRules.kt，
# emoji 范围表在 EmojiRanges.kt
KT_TEXT_DIR = (
    ROOT
    / "clients"
    / "frontend"
    / "aveline-android"
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "aveline"
    / "ai"
    / "mobile"
    / "utils"
    / "text"
)
KT_RULES = KT_TEXT_DIR / "TextSegmentRules.kt"
KT_EMOJI_RANGES = KT_TEXT_DIR / "EmojiRanges.kt"
KT_TEXT_SEGMENTER = KT_TEXT_DIR / "TextSegmenter.kt"
KT_SPLITTER = KT_TEXT_DIR / "ChatMessageSplitter.kt"


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"找不到文件：{path}")
    return path.read_text(encoding="utf-8")


def _read_py_segmenter_family() -> str:
    """读取 Python 侧整族源文件（门面 + 全部子模块）的拼接文本。

    拆分后常量散落在各子模块，逐个指定文件名既啰嗦又容易漏；这里按 glob 全量拼接，
    并在每段前加注释头，便于断言失败时定位是哪个文件缺了定义。
    """
    paths = sorted(PY_SEGMENTER_DIR.glob(PY_SEGMENTER_GLOB))
    if not paths:
        raise AssertionError(f"找不到任何源文件：{PY_SEGMENTER_DIR}/{PY_SEGMENTER_GLOB}")
    return "".join(f"\n# ==== {path.name} ====\n{_read(path)}" for path in paths)


def _extract_string_const(source: str, name: str) -> str:
    """取出字符串常量（兼容 `name = "..."` 与 `name = (r"..." r"...")` 写法）。

    归一化：拼接隐式连接的字符串片段，去掉空白与反斜杠，
    这样 Python 的 `r"\\d"` 与 Kotlin 的 `"\\\\d"` 归一化后都是 `d`。
    """
    match = re.search(rf'{name}\s*=\s*\(?\s*((?:(?:r)?"[^"]*"\s*)+)', source)
    if not match:
        raise AssertionError(f"未找到常量 {name} 的定义")
    parts = re.findall(r'(?:r)?"([^"]*)"', match.group(1))
    return re.sub(r"[\s\\]", "", "".join(parts))


def _extract_paren_block(source: str, name: str) -> str:
    """取出 `name = xxx(...)` 括号内的原始文本。"""
    match = re.search(rf"{name}\s*=\s*(?:[A-Za-z_]+\s*)?\(", source)
    if not match:
        raise AssertionError(f"未找到常量 {name} 的定义")
    start = match.end() - 1
    depth = 0
    for idx in range(start, len(source)):
        if source[idx] == "(":
            depth += 1
        elif source[idx] == ")":
            depth -= 1
            if depth == 0:
                return source[start + 1 : idx]
    raise AssertionError(f"常量 {name} 的括号没有闭合")


def _extract_regex_pattern(source: str, name: str) -> str:
    """取出正则字面量（兼容 Python 的 `re.compile(r"...")` 与 Kotlin 的 `Regex("...")`）。

    归一化同 [_extract_string_const]：去掉空白与反斜杠，这样 Python 的 `r"\\s"` 与
    Kotlin 的 `"\\\\s"` 归一化后都是 `s`，可以直接比对。
    """
    # 前缀允许 `re.compile(` / `Regex(` 这类带点的调用名
    match = re.search(
        rf'{name}\s*=\s*(?:[A-Za-z_.]+\s*)?\(\s*((?:(?:r)?"[^"]*"\s*)+)', source
    )
    if not match:
        raise AssertionError(f"未找到正则 {name} 的定义")
    parts = re.findall(r'(?:r)?"([^"]*)"', match.group(1))
    return re.sub(r"[\s\\]", "", "".join(parts))


def _normalize_literal_block(block: str) -> str:
    """把元素列表字面量归一化成纯内容（去掉空白、引号、逗号）。

    Python 的 `("。", ".", ...)` 与 Kotlin 的 `charArrayOf('。', '.', ...)`
    归一化后应完全一致。
    """
    return re.sub(r"[\s'\",]", "", block)


def check_constant_parity() -> None:
    py_source = _read_py_segmenter_family()
    kt_source = _read(KT_RULES)

    # 1. 尾随标点集合
    py_trailing = _extract_string_const(py_source, "TRAILING_PUNCT_CHARS")
    kt_trailing = _extract_string_const(kt_source, "TRAILING_PUNCT_CHARS")
    assert py_trailing == kt_trailing, (
        f"TRAILING_PUNCT_CHARS 两端不一致：Python={py_trailing!r} Kotlin={kt_trailing!r}"
    )
    assert py_trailing == TRAILING_PUNCT_CHARS, "Python 常量与导入值不一致，脚本取值逻辑有误"

    # 2. 硬气泡边界标点
    py_hard = _normalize_literal_block(_extract_paren_block(py_source, "HARD_BUBBLE_BOUNDARY_ENDINGS"))
    kt_hard = _normalize_literal_block(_extract_paren_block(kt_source, "HARD_BUBBLE_BOUNDARY_ENDINGS"))
    assert py_hard == kt_hard, f"HARD_BUBBLE_BOUNDARY_ENDINGS 两端不一致：Python={py_hard!r} Kotlin={kt_hard!r}"
    assert py_hard == "".join(HARD_BUBBLE_BOUNDARY_ENDINGS), "Python 常量与导入值不一致，脚本取值逻辑有误"

    # 3. 时间戳正则（模型模仿历史格式输出的时间戳）
    py_ts = _extract_string_const(py_source, "AI_TIMESTAMP_PATTERN_SOURCE")
    kt_ts = _extract_string_const(kt_source, "AI_TIMESTAMP_PATTERN_SOURCE")
    assert py_ts == kt_ts, f"AI_TIMESTAMP_PATTERN_SOURCE 两端不一致：Python={py_ts!r} Kotlin={kt_ts!r}"

    # 4. 省略号短促前缀阈值
    py_limit = re.search(r"ELLIPSIS_MERGE_PREFIX_LIMIT\s*=\s*(\d+)", py_source).group(1)
    kt_limit = re.search(r"ELLIPSIS_MERGE_PREFIX_LIMIT\s*=\s*(\d+)", kt_source).group(1)
    assert py_limit == kt_limit, f"ELLIPSIS_MERGE_PREFIX_LIMIT 两端不一致：{py_limit} vs {kt_limit}"

    # 5. emoji 范围表逐项比对（Kotlin 侧的表在 EmojiRanges.kt，名为 RANGES）
    kt_block = _extract_paren_block(_read(KT_EMOJI_RANGES), "RANGES")
    kt_ranges = [int(value, 16) for value in re.findall(r"0x([0-9A-Fa-f]+)", kt_block)]
    py_ranges = [value for rng in EMOJI_RANGES for value in rng]
    assert kt_ranges == py_ranges, (
        f"EMOJI_RANGES 两端不一致：Python {len(py_ranges)} 个数，Kotlin {len(kt_ranges)} 个数"
    )

    # 6. 展示分组用的 Markdown / LaTeX 正则（跨行结构判定，两端必须同源）
    #    Python 侧在 core/utils/text_segmenter_rules.py，Kotlin 侧在 utils/text/TextSegmenter.kt
    kt_display = _read(KT_TEXT_SEGMENTER)
    for py_name, kt_name, desc in (
        ("_MARKDOWN_BLOCK_START_RE", "MARKDOWN_BLOCK_START_REGEX", "单行块级结构"),
        ("_MARKDOWN_TABLE_LINE_RE", "MARKDOWN_TABLE_LINE_REGEX", "表格行"),
        ("_LATEX_MARKER_RE", "LATEX_MARKER_REGEX", "LaTeX marker"),
    ):
        py_value = _extract_regex_pattern(py_source, re.escape(py_name))
        kt_value = _extract_regex_pattern(kt_display, kt_name)
        assert py_value == kt_value, (
            f"{desc}正则两端不一致：Python {py_name}={py_value!r} Kotlin {kt_name}={kt_value!r}"
        )

    print("  [1] 常量对齐 OK：尾随标点 / 硬气泡边界 / 时间戳正则 / 省略号阈值 / emoji 范围表 / 展示分组正则")


def check_structure_parity() -> None:
    """展示层拆分的两个新增能力两端都必须存在，防止一边重构掉了另一边还留着。

    - 「按结构分组」取代了旧的全有全无守卫（模型用一个 `- ` 列表项就整条透传，
      导致断句时好时坏）；
    - 「行内 span 修复」负责把被断句切坏的 `**加粗**` 并回同一段。
    """
    py_source = _read_py_segmenter_family()
    kt_display = _read(KT_TEXT_SEGMENTER)
    kt_splitter = _read(KT_SPLITTER)

    for py_fragment, kt_path, kt_fragment, desc in (
        ("_group_display_lines", KT_TEXT_SEGMENTER, "groupByStructure", "按 Markdown 结构分组"),
        ("repair_broken_inline_spans", KT_SPLITTER, "repairBrokenInlineSpans", "行内 span 修复"),
    ):
        assert py_fragment in py_source, f"Python 侧缺少{desc}：{py_fragment}"
        assert kt_fragment in _read(kt_path), f"Kotlin 侧缺少{desc}：{kt_fragment}（{kt_path.name}）"

    for fragment in ("has_unclosed_inline_span",):
        assert fragment in py_source, f"Python 侧缺少判定函数：{fragment}"
    for fragment in ("hasUnclosedInlineSpan",):
        assert fragment in kt_splitter, f"Kotlin 侧缺少判定函数：{fragment}"

    # 旧的全有全无守卫不能回来：Kotlin 侧不应再有「命中标记就整条直返」
    assert "if (MARKDOWN_BLOCK_START_REGEX.containsMatchIn(cleaned))" not in kt_display, (
        "Kotlin 侧退回了「命中标记就整条透传」的旧实现"
    )

    print("  [2] 结构对齐 OK：按结构分组 / 行内 span 修复 两端均存在")


def check_behavior() -> None:
    # 时间戳：历史消息喂模型时带 [今天/昨天/X天前 HH:MM] 前缀（兼容旧 [MM-DD HH:MM]），模型会学去，必须剥掉
    assert strip_ai_timestamp("前面[09-11 23:40] 后面") == "前面后面"
    assert strip_ai_timestamp("[09-11 23:40] 好呀") == "好呀"
    assert strip_ai_timestamp("没有时间戳") == "没有时间戳"
    assert strip_ai_timestamp("[今天 20:00] 好呀") == "好呀"
    assert strip_ai_timestamp("[昨天 23:40] 早点睡吧") == "早点睡吧"
    assert strip_ai_timestamp("[3天前 08:00] 记得按时吃饭") == "记得按时吃饭"

    # 句末多余标点
    assert strip_trailing_punctuation("好呀好呀。") == "好呀好呀"
    assert strip_trailing_punctuation("好呀好呀，") == "好呀好呀"
    assert strip_trailing_punctuation("噢噢，好呀好呀，") == "噢噢，好呀好呀"
    assert strip_trailing_punctuation("（摸了摸头。）") == "（摸了摸头）"

    # 组合清洗
    assert clean_chat_text("[09-11 23:40] 好呀。") == "好呀"

    # 断句：极短句在句号处断句且不保留句号
    assert split_chat_message("啊。我忘了", comma_split_prob=0.0) == ["啊", "我忘了"]
    # 省略号后接普通句子时在省略号处断句
    assert split_chat_message("倒是你，声音听起来有点飘……是困了，还是有心事？", comma_split_prob=0.0) == [
        "倒是你，声音听起来有点飘……",
        "是困了，还是有心事？",
    ]
    # 短句不拆、方括号标记整段直返
    assert split_chat_message("你好啊，今天天气不错。", comma_split_prob=0.0) == ["你好啊，今天天气不错。"]
    assert split_chat_message("[THINK_STORE: 他需要燃料]", comma_split_prob=0.0) == ["[THINK_STORE: 他需要燃料]"]

    # 换行是硬气泡边界：括号内舞台描写单独成泡
    chunks = split_chat_message(
        "（轻笑一声）\n我这边一切正常。倒是你，刚才说焦虑……现在感觉好点了吗？",
        comma_split_prob=0.0,
    )
    assert chunks[0] == "（轻笑一声）", f"换行分段首段不符：{chunks}"
    assert chunks[-1] == "现在感觉好点了吗？", f"换行分段末段不符：{chunks}"

    # 展示前的完整链路（安卓端 TextSegmenter.splitForDisplay 的等价实现）：
    # 必须对**每个气泡**清一次句尾——断句只在断点处吃掉句号，
    # 单段会原样返回带句号的原文（QQ 是 split 之后逐条 strip 再发送）
    assert split_for_display("好呀。那你早点睡吧。晚安哦。", comma_split_prob=0.0) == [
        "好呀",
        "那你早点睡吧",
        "晚安哦",
    ]
    assert split_for_display("你要求的。\n\n以前那套我也没打算收着，是你嫌吵。", comma_split_prob=0.0) == [
        "你要求的",
        "以前那套我也没打算收着，是你嫌吵",
    ]
    assert split_for_display("你好啊，今天天气不错。", comma_split_prob=0.0) == ["你好啊，今天天气不错"]

    print("  [3] 行为自测 OK：时间戳 / 句末标点 / 断句 / 换行分段 / 逐气泡去句尾")


def main() -> int:
    print("=" * 60)
    print("通用聊天断句规则：QQ(Python) 与 安卓(Kotlin) 对齐校验")
    print("=" * 60)
    try:
        check_constant_parity()
        check_structure_parity()
        check_behavior()
    except AssertionError as exc:
        print(f"❌ 校验失败：{exc}")
        return 1
    print("\n✅ 两端规则一致，公共模块行为符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
