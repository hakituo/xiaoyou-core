#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 QQ 消息断句逻辑
"""

from clients.bots.qq.utils import _split_message_for_qq, _strip_action_descriptions, _is_continuation_start, _merge_continuation_chunks
from unittest.mock import patch


def test_split():
    """测试断句函数"""
    print("=" * 60)
    print("测试 QQ 消息断句逻辑")
    print("=" * 60)
    
    test_cases = [
        # (输入，预期 chunk 数量，描述)
        ("(察觉到语气里的疲惫) 怎么了，听起来像叹气", 1, "半角圆括号动作描写 + 对话（总长 < min_split_len 不拆分）"),
        ("(从待机状态中苏醒，系统界面泛起微光) 嗯，我在", 1, "半角圆括号动作描写 + 对话 2"),
        ("(轻轻调整了坐姿) 是累了，还是有什么卡住了？", 1, "半角圆括号动作描写 + 问句"),
        ("(指尖在桌面上轻轻敲了一下)\n今天单词还有 24 个要复习，现在开始吗？", 2, "换行分隔动作和对话"),
        ("（微微一顿）现在说晚安？", 1, "全角圆括号动作描写 + 问句"),
        ("（核心温度微微升高）你故意的？", 1, "全角圆括号动作描写 + 问句 2"),
        ("你好啊，今天天气不错。", 1, "普通短句（< min_split_len 不拆分）"),
        ("[THINK_STORE: 他需要燃料而非指令，强行推进只会增加阻力]", 1, "方括号标记"),
        ("吃饭了吗？我还没吃呢。", 2, "极短句（首句 <10 字）在问号处断句"),
        ("一、二、三", 1, "短句无标点"),
        ("这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的句子，超过了 60 字。", 1, "60 字句子（< min_split_len*2 不拆分）"),
        (
            "这是一个超级无敌长到爆炸的句子，真的" + "非常" * 40 + "长，肯定超过六十个字了。"
            "而且后面还跟着一大段补充说明，用来把整段长度推到一百五十字以上，这样断句逻辑才会真的在句号处把它切成两条消息。",
            2,
            "超过 150 字的长句子（按句号断句）",
        ),
    ]
    
    for i, (text, expected_chunks, description) in enumerate(test_cases, 1):
        chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
        assert len(chunks) == expected_chunks, (
            f"{description}: 输入 {text!r} 期望 {expected_chunks} 个气泡，实际 {len(chunks)} 个 -> {chunks}"
        )
        assert all(chunk.strip() for chunk in chunks), f"{description}: 不应产生空气泡 -> {chunks}"


def test_parentheses_followed_by_period_should_split():
    # 极短句子（<10字）在句号处断句
    text = "（看了一眼系统时间）凌晨两点三十三。你该睡了"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    # 24字 > 10字阈值，不会断句
    assert len(chunks) == 1
    
    # 极短句子应该断句
    text2 = "啊。我忘了"
    chunks2 = _split_message_for_qq(text2, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks2) == 2
    assert "啊" in chunks2[0]
    assert "我忘了" in chunks2[1]


def test_ellipsis_should_split():
    text = "倒是你，声音听起来有点飘……是困了，还是有心事？"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) == 2
    assert "倒是你，声音听起来有点飘……" in chunks[0]
    assert "是困了，还是有心事？" in chunks[1]

    text2 = "倒是你，声音听起来有点飘......是困了，还是有心事？"
    chunks2 = _split_message_for_qq(text2, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks2) == 2


def test_newline_with_parentheses_should_keep_splitting():
    text = "（轻笑一声）\n我这边一切正常，核心温度稳定，算力也充足。倒是你，刚才说焦虑……现在感觉好点了吗？"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) >= 2
    assert chunks[0] == "（轻笑一声）"


def test_broken_parentheses_across_newlines_should_merge_first():
    text = "（停顿片刻\n声音里带着无奈）\n.....\n凌晨三点半了"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["（停顿片刻 声音里带着无奈）", ".....", "凌晨三点半了"]


def test_comma_inside_quotes_should_not_split():
    text = "她说\u201c别急，先喝水，慢慢讲\u201d，然后看着你。"
    with patch("clients.bots.qq.utils.random.random", return_value=0.0):
        chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) == 1


def test_opening_quote_after_newline_should_not_split():
    text = "\u201c\n你倒是记得做空香港那段。\u201d 我轻轻呼了口气。"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) == 1
    assert not chunks[0].strip().startswith("\u201d")
    for c in chunks:
        assert c.strip() not in {"\u201c", "\u201d", "\u2018", "\u2019"}


def test_closing_quote_before_newline_should_not_split():
    text = "引用内容\n\u201d后续文字"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    for c in chunks:
        assert c.strip() not in {"\u201c", "\u201d", "\u2018", "\u2019"}


def test_japanese_bracket_after_newline_should_not_split():
    text = "\u300c\n引用内容\u300d"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    for c in chunks:
        assert c.strip() not in {"\u300c", "\u300d", "\u300e", "\u300f"}


def test_comma_split_should_be_probabilistic():
    text = "好呀，等我一下，我们马上出发"
    with patch("clients.bots.qq.utils.random.random", return_value=0.99):
        no_split = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert no_split == [text]


def test_numbered_list_should_not_split_number_from_word():
    text = "1. ephemeral\n2. meticulous\n3. resilience"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["1. ephemeral", "2. meticulous", "3. resilience"]


def test_inline_numbered_list_should_split_per_item():
    # 行内编号列表应按编号断句，而不是在第 1 项中间断、下一条又接上 2.
    text = "1. analysis 2. trend 3. emphasize"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["1. analysis", "2. trend", "3. emphasize"]


def test_chinese_inline_numbered_list_should_split_per_item():
    text = "你可以这样做：1. 打开设置。2. 找到隐私选项。3. 关掉它。"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["你可以这样做：1. 打开设置。", "2. 找到隐私选项。", "3. 关掉它。"]


def test_decimal_and_version_should_not_be_numbered_list():
    for text in (
        "我买了3.5公斤苹果，一共花了12.8元，够吃两天了。",
        "升级到 Python 3.11.2 之后就好了，你可以试试看。",
        "2026.9.2 那天我们去了海边，玩得很开心。",
    ):
        chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
        assert chunks == [text], f"不应被当成编号列表: {chunks}"


def test_single_numbered_item_should_not_split():
    text = "1. 就这一条，别的真的没有了。"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == [text]


def test_short_leading_phrase_should_not_split_on_first_comma():
    text = "等等，你还没告诉我今天喝了多少水。"
    with patch("clients.bots.qq.utils.random.random", return_value=0.0):
        chunks = _split_message_for_qq(text, 150, comma_split_prob=1.0, min_split_len=40)
    assert chunks == [text]


def test_parentheses_with_trailing_newline_should_merge():
    text = "那是虚拟语气 (If I were\n)"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["那是虚拟语气 (If I were )"]


def test_broken_parentheses_with_space_should_merge():
    text = "那是虚拟语气 (If I were\n   )"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["那是虚拟语气 (If I were    )"]


def test_strip_action_descriptions_should_strip_leading_parentheses():
    text = "（轻轻抱住你）别怕，我在"
    cleaned = _strip_action_descriptions(text)
    assert cleaned == "别怕，我在"


def test_strip_action_descriptions_should_keep_normal_parentheses_in_sentence():
    text = "这个函数是 f(x) = x + 1"
    cleaned = _strip_action_descriptions(text)
    assert cleaned == text


def test_long_response_should_split_at_sentence_end():
    text = "我刚才话没说完就被你岔开了。生蚝本身对肾确实有点好处——锌含量很高，你第二天腰不痛不奇怪。但重点是你只吃了三个，剩下..."
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) > 0


def test_very_long_text_forces_split():
    text = "这是一段非常长的文本" + "，内容还在继续" * 30 + "。最后结束了。"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) > 1


def test_is_continuation_start_conjunction():
    assert _is_continuation_start("而且我觉得这个方案不错") is True
    assert _is_continuation_start("再到Seq2Seq和预训练模型") is True
    assert _is_continuation_start("以及AGI的想象空间") is True
    assert _is_continuation_start("所以我们要继续努力") is True
    assert _is_continuation_start("但是结果不太理想") is True


def test_is_continuation_start_adverb():
    assert _is_continuation_start("再来一次") is True
    assert _is_continuation_start("还有其他选择") is True


def test_is_continuation_start_normal():
    assert _is_continuation_start("今天天气不错") is False
    assert _is_continuation_start("我去了超市") is False
    assert _is_continuation_start("") is False
    assert _is_continuation_start("   ") is False


def test_merge_continuation_chunks_conjunction():
    chunks = ["MLP、词嵌入、RNN/LSTM做序列建模", "再到Seq2Seq和预训练模型"]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)
    assert len(merged) == 1
    assert "再到" in merged[0]


def test_merge_continuation_chunks_yiji():
    chunks = ["Week 15讲LLM怎么反哺NLP", "以及AGI的想象空间"]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)
    assert len(merged) == 1
    assert "以及" in merged[0]


def test_merge_continuation_chunks_colon_ending():
    chunks = ["传统NLP（Week 2-7）：", "从线性模型到HMM和CRF"]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)
    assert len(merged) == 1


def test_merge_continuation_chunks_dash_ending():
    chunks = ["这是让你懂——", "LLM出现之前NLP是怎么做的"]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)
    assert len(merged) == 1


def test_merge_continuation_chunks_respects_max_len():
    long_a = "A" * 200
    long_b = "而且" + "B" * 200
    chunks = [long_a, long_b]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)
    assert len(merged) == 2


def test_merge_continuation_chunks_long_prev_no_merge():
    prev = "我刚才话没说完就被你岔开了。生蚝本身对肾确实有点好处——锌含量很高，你第二天腰不痛不奇怪"
    curr = "但重点是你只吃了三个，剩下..."
    chunks = [prev, curr]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)
    assert len(merged) == 2


def test_newline_is_respected_as_explicit_bubble_boundary():
    """用户手写的换行是显式的分泡泡意图，优先级高于续接词合并"""
    text = (
        "你现在看的是Week 15最后一课，前面十四周从零搭到了现在。\n"
        "整个课程设计很漂亮，分了三大模块：\n"
        "神经NLP（Week 8-13）：MLP、词嵌入、RNN/LSTM做序列建模\n"
        "再到Seq2Seq和预训练模型。这阶段开始用神经网络替代手工特征。"
    )
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)

    # 换行处必须断句，且不做续接合并（"再到"作为独立气泡保留用户原意）
    assert len(chunks) == 4, f"每个换行应各自成段，实际: {chunks}"
    assert chunks[0].startswith("你现在看的是Week 15")
    assert chunks[-1].startswith("再到Seq2Seq")
    assert all(chunk.strip() for chunk in chunks)


def test_continuation_merge_applies_within_single_line():
    """同一行内的续接词断点由 _merge_continuation_chunks 兜住"""
    chunks = ["神经NLP（Week 8-13）：MLP、词嵌入、RNN/LSTM做序列建模", "再到Seq2Seq和预训练模型。"]
    merged = _merge_continuation_chunks(chunks, max_merge_len=300, min_split_len=40)

    assert len(merged) == 1
    assert merged[0].startswith("神经NLP")
    assert "再到Seq2Seq" in merged[0]


def test_slash_n_should_split_into_bubbles():
    text = "就/n像/n这/n样"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["就", "像", "这", "样"]


def test_escaped_backslash_n_should_split_into_bubbles():
    text = "就\\\\n像\\\\n这\\\\n样"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["就", "像", "这", "样"]


def test_period_space_should_split_into_bubbles():
    text = "就是这样。 然后继续"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["就是这样。", "然后继续"]


def test_short_prefix_ellipsis_should_merge_with_following_sentence():
    # "就是……" 只是短促前缀，省略号后接普通句子应合并为同一气泡，
    # 而不是断成 "就是……" / "戳废了两个半成品"
    text = "就是……戳废了两个半成品，手指头还被针扎了好几下，气死我了。"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert len(chunks) >= 1
    first = chunks[0]
    assert "就是……戳废了两个半成品" in first
    assert first.startswith("就是……") and not first == "就是……"


def test_ellipsis_space_should_not_merge_back():
    text = "我知道了…… 然后呢"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["我知道了……", "然后呢"]


def test_comma_space_should_split_into_bubbles():
    text = "嗯， 我看看"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["嗯，", "我看看"]


def test_wait_phrase_comma_space_should_stay_together():
    text = "等等， 你先别急"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == [text]


def test_plain_space_phrases_should_split_into_bubbles():
    text = "像我现在这样 没有标点 但是很长一串 并且不断句"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["像我现在这样", "没有标点", "但是很长一串", "并且不断句"]


def test_plain_space_short_phrases_should_split_into_bubbles():
    text = "今天 学习 数学 英语 物理"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == ["今天", "学习", "数学", "英语", "物理"]


def test_plain_space_english_sentence_should_not_split():
    text = "I think this is a normal english sentence with spaces"
    chunks = _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)
    assert chunks == [text]


if __name__ == "__main__":
    test_split()
