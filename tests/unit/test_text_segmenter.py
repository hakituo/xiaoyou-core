#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 core 公共断句/清洗模块（QQ 与安卓端共用同一套规则）。

这里的用例与安卓端 `utils/text/TextSegmenterTest.kt` 一一对应，期望值同源；
两端常量是否漂移由
`tests/scripts/android_frontend/verify_text_segmenter_parity.py` 校验。
"""

from core.utils.text_segmenter import (
    clean_chat_text,
    split_chat_message,
    split_for_display,
    strip_ai_timestamp,
    strip_trailing_punctuation,
)

# 逗号断句是概率性的，本文件只断言确定性行为，固定概率为 0
NO_COMMA_SPLIT = 0.0


def test_strip_ai_timestamp():
    """模型会模仿历史消息格式输出时间戳，必须全局剥掉。"""
    assert strip_ai_timestamp("前面[09-11 23:40] 后面") == "前面后面"
    assert strip_ai_timestamp("[09-11 23:40] 好呀") == "好呀"
    assert strip_ai_timestamp("没有时间戳") == "没有时间戳"
    # 相对时间戳（今天/昨天/X天前）同样要剥
    assert strip_ai_timestamp("[今天 20:00] 好呀") == "好呀"
    assert strip_ai_timestamp("[昨天 23:40] 早点睡吧") == "早点睡吧"
    assert strip_ai_timestamp("[3天前 08:00] 记得按时吃饭") == "记得按时吃饭"


def test_strip_trailing_punctuation():
    """只清句尾拖尾标点，句中逗号/句号保留。"""
    assert strip_trailing_punctuation("好呀好呀。") == "好呀好呀"
    assert strip_trailing_punctuation("好呀好呀，") == "好呀好呀"
    assert strip_trailing_punctuation("噢噢，好呀好呀，") == "噢噢，好呀好呀"
    assert strip_trailing_punctuation("（摸了摸头。）") == "（摸了摸头）"


def test_clean_chat_text():
    assert clean_chat_text("[09-11 23:40] 好呀。") == "好呀"


def test_split_very_short_sentence():
    assert split_chat_message("啊。我忘了", comma_split_prob=NO_COMMA_SPLIT) == ["啊", "我忘了"]


def test_split_after_ellipsis():
    chunks = split_chat_message(
        "倒是你，声音听起来有点飘……是困了，还是有心事？",
        comma_split_prob=NO_COMMA_SPLIT,
    )
    assert chunks == ["倒是你，声音听起来有点飘……", "是困了，还是有心事？"]


def test_short_sentence_and_bracket_tag_keep_intact():
    assert split_chat_message("你好啊，今天天气不错。", comma_split_prob=NO_COMMA_SPLIT) == ["你好啊，今天天气不错。"]
    assert split_chat_message("[THINK_STORE: 他需要燃料]", comma_split_prob=NO_COMMA_SPLIT) == [
        "[THINK_STORE: 他需要燃料]"
    ]


def test_newline_is_hard_bubble_boundary():
    chunks = split_chat_message(
        "（轻笑一声）\n我这边一切正常。倒是你，刚才说焦虑……现在感觉好点了吗？",
        comma_split_prob=NO_COMMA_SPLIT,
    )
    assert chunks[0] == "（轻笑一声）"
    assert chunks[-1] == "现在感觉好点了吗？"


def test_bracketed_math_interval_with_spaced_comma_not_split():
    """方括号/花括号参与括号配对跟踪：数学区间 [1, 3]、集合 {1, 2} 是英文排版习惯
    （逗号后带空格），不能被"逗号+空格=用户主动分泡"的显式边界规则误断成 [1 / 3]。"""
    interval = "1. 已知 f(x) = x^2 - 2ax + 3 在区间 [1, 3] 上的最小值为 g(a)，求 g(a)"
    assert split_chat_message(interval, comma_split_prob=NO_COMMA_SPLIT) == [interval]
    assert split_for_display(interval, comma_split_prob=NO_COMMA_SPLIT) == [interval]
    assert split_chat_message("集合 {1, 2, 3} 的并集", comma_split_prob=NO_COMMA_SPLIT) == [
        "集合 {1, 2, 3} 的并集"
    ]
    # 显式空格分泡对普通文本仍然生效（对照：不带括号时逗号+空格照常断句，逗号保留在段尾）
    assert split_chat_message("写完作业， 早点睡", comma_split_prob=NO_COMMA_SPLIT) == [
        "写完作业，",
        "早点睡",
    ]


def test_display_pipeline_matches_android():
    """安卓端 splitForDisplay 的等价链路：clean -> split -> 每段再清一次句尾。"""
    assert split_for_display("好呀。那你早点睡吧。晚安哦。", comma_split_prob=NO_COMMA_SPLIT) == [
        "好呀",
        "那你早点睡吧",
        "晚安哦",
    ]
    # 断句只吃掉断点处的句号，单段会原样带句号返回，必须每段再清一次，
    # 否则气泡里会残留"你要求的。"这类句末句号（QQ 是 split 后逐条 strip）
    assert split_for_display(
        "你要求的。\n\n以前那套我也没打算收着，是你嫌吵。", comma_split_prob=NO_COMMA_SPLIT
    ) == ["你要求的", "以前那套我也没打算收着，是你嫌吵"]
    # 单段短句同样不能留句末句号
    assert split_for_display("你好啊，今天天气不错。", comma_split_prob=NO_COMMA_SPLIT) == [
        "你好啊，今天天气不错"
    ]


def test_display_pipeline_keeps_markdown_blocks_intact():
    """跨行连续的 Markdown 结构（代码块/块公式/表格）整组保留，不被拆散。"""
    code = "```kotlin\nval a = 1\nval b = 2\n```"
    assert split_for_display(code, comma_split_prob=NO_COMMA_SPLIT) == [code]

    math = "$$\nE = mc^2\n$$"
    assert split_for_display(math, comma_split_prob=NO_COMMA_SPLIT) == [math]

    table = "| 列一 | 列二 |\n| --- | --- |\n| a | b |"
    assert split_for_display(table, comma_split_prob=NO_COMMA_SPLIT) == [table]

    # 代码块里的句号不能被当成断句点，也不能被 strip 掉
    code_with_dots = "```\nx = 1.5\n```"
    assert split_for_display(code_with_dots, comma_split_prob=NO_COMMA_SPLIT) == [code_with_dots]


def test_display_pipeline_keeps_latex_blocks_whole():
    """块级公式自身完整成段，前后正文照常各成一段（与安卓 MarkdownLatexSegmenterTest 同源）。"""
    assert split_for_display(
        "胡克定律是\n\n$$\nF=-kx\n$$\n\n负号表示方向相反", comma_split_prob=NO_COMMA_SPLIT
    ) == ["胡克定律是", "$$\nF=-kx\n$$", "负号表示方向相反"]

    # 流式阶段只有起始 $$（尚未闭合）时也不能把公式切开
    assert split_for_display("下面开始推导\n$$\nF=-k", comma_split_prob=NO_COMMA_SPLIT) == [
        "下面开始推导",
        "$$\nF=-k",
    ]

    assert split_for_display("结果：\n$$E=mc^2$$\n继续说明", comma_split_prob=NO_COMMA_SPLIT) == [
        "结果：",
        "$$E=mc^2$$",
        "继续说明",
    ]


def test_display_pipeline_splits_every_line_not_just_plain_text():
    """单行块级标记（标题/列表项/引用）只保住自己那一行，不再拖累整条消息。

    回归用例：旧实现命中任一 markdown 标记就整条透传，模型这一轮只要用了 `- `
    列表，整条回复就退化成一个大气泡、换行原样显示；同一套措辞没用 markdown 时
    却又被正常切成多个气泡——"一会能断句一会不能断句"就是这么来的。
    """
    # 标题行自身完整保留，正文行照常断句
    assert split_for_display(
        "## 标题\n\n第一行。\n\n第二行。", comma_split_prob=NO_COMMA_SPLIT
    ) == ["## 标题", "第一行", "第二行"]

    # 列表项整行保留（拆开会丢掉 `- ` 前缀），但列表项之外的正文照常切
    assert split_for_display(
        "你看这两点。\n- 莲 → 主语\n- 出淤泥而不染 → 谓语",
        comma_split_prob=NO_COMMA_SPLIT,
    ) == ["你看这两点", "- 莲 → 主语", "- 出淤泥而不染 → 谓语"]


def test_display_pipeline_does_not_tear_inline_spans():
    """加粗里自带句号时，断点顺延到 span 闭合之后，`**` 不会落单。"""
    # 旧行为：切成 "**古之人 / 不 / 余 / 欺" + "** 顺便…"，两段各剩一个 `**`
    text = (
        "所以整句主语就是「古之人」这三个字，一个整体： **古之人 / 不 / 余 / 欺。** "
        "顺便给你一个判断顺序，以后见到「之」先过一遍："
    )
    segments = split_for_display(text, comma_split_prob=NO_COMMA_SPLIT)
    # 切不开就并回一段，但绝不能留下落单的 `**`
    assert all(segment.count("**") % 2 == 0 for segment in segments)
    assert "**古之人 / 不 / 余 / 欺**" in "".join(segments)


def test_generic_entry_does_not_depend_on_channel():
    """公共入口不接 preprocess / pass_through_markers 时也应正常工作。"""
    assert split_chat_message("", comma_split_prob=NO_COMMA_SPLIT) == []
    assert split_chat_message("**加粗**在这里", comma_split_prob=NO_COMMA_SPLIT) == ["**加粗**在这里"]
