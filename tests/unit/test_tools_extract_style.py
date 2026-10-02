# -*- coding: utf-8 -*-
"""``tools/extract_style.py`` 的单元测试。

该模块是一个独立的 CLI 工具（argparse + ``__main__`` 入口），不被仓库其它代码
import，因此这里既覆盖其中的纯函数（文本清洗、样式统计、特征提取、JSON 抽取），
也覆盖两个 DeepSeek 精修协作者与 ``main()`` 的完整命令行流程。

所有外部依赖（OpenAIClient / dotenv / 真实网络）都在测试内被替换为不触网的桩，
文件 IO 一律落在 ``tmp_path``，不写入仓库目录。
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import warnings

import pytest

from tools import extract_style as mod


# --------------------------------------------------------------------------
# 通用桩与数据构造
# --------------------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(mod.__file__), ".."))


def _make_fake_client(
    *,
    chunks=(),
    chat_result="",
    init_error=None,
    chat_error=None,
    shutdown_error=None,
    calls=None,
):
    """构造一个不触网的 OpenAIClient 替身，并把调用记录写进 ``calls``。"""
    record = {} if calls is None else calls

    class _FakeClient:
        def __init__(self, **kwargs):
            record["ctor_kwargs"] = kwargs

        async def initialize(self):
            record["initialize"] = True
            if init_error is not None:
                raise init_error

        async def stream_chat(self, messages, **kwargs):
            record["stream_messages"] = messages
            record["stream_kwargs"] = kwargs
            for c in chunks:
                yield {"content": c}

        async def chat(self, messages, **kwargs):
            record["chat_messages"] = messages
            record["chat_kwargs"] = kwargs
            if chat_error is not None:
                raise chat_error
            return chat_result

        async def shutdown(self):
            record["shutdown"] = True
            if shutdown_error is not None:
                raise shutdown_error

    return _FakeClient, record


def _install_fake_client(monkeypatch, fake_cls):
    """把 ``core.llm.openai_compat.OpenAIClient`` 换成桩。"""
    import core.llm.openai_compat as oc

    monkeypatch.setattr(oc, "OpenAIClient", fake_cls)


def _rec(ts, role, text, msg_type="文本消息", local_id=0):
    """构造一条 CleanRecord，便于直接驱动 _build_pairs。"""
    return mod.CleanRecord(
        ts=ts, role=role, text=text, msg_type=msg_type, local_id=local_id
    )


def _sample_messages():
    """一份能稳定产生 1 条 user/ling 配对的样例消息。"""
    return [
        {
            "senderUsername": "wxid_me",
            "isSend": 1,
            "type": "文本消息",
            "content": "今天天气不错",
            "createTime": 1000,
            "localId": 1,
        },
        {
            "senderUsername": "wxid_ling",
            "isSend": 0,
            "type": "文本消息",
            "content": "是呀，适合出去走走",
            "createTime": 1010,
            "localId": 2,
        },
        {
            "senderUsername": "wxid_me",
            "isSend": 1,
            "type": "图片消息",
            "content": "[图片]",
            "createTime": 1020,
            "localId": 3,
        },
        {
            "senderUsername": "wxid_other",
            "isSend": 0,
            "type": "文本消息",
            "content": "路人甲在说话",
            "createTime": 1030,
            "localId": 4,
        },
        {
            "senderUsername": "wxid_me",
            "isSend": 1,
            "type": "文本消息",
            "content": "   ",
            "createTime": 1040,
            "localId": 5,
        },
    ]


def _write_input(tmp_path, *, messages=None, session=None, name="in.json"):
    """把样例输入写成 JSON 文件，返回路径字符串。"""
    if session is None:
        session = {"wxid": "wxid_ling", "displayName": "玲"}
    payload = {"session": session, "messages": _sample_messages() if messages is None else messages}
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------
# _clean_text / _has_substantial / _is_low_value_text
# --------------------------------------------------------------------------


def test_clean_text_normalizes_newlines_and_zero_width():
    """CRLF/CR 统一为 \n，零宽字符被移除，连续空白折叠并 strip。"""
    raw = "  a\u200b\t\tb\r\nc\rd  "
    assert mod._clean_text(raw) == "a b\nc\nd"


def test_clean_text_handles_none_and_non_str():
    """None 与非字符串输入被安全转成字符串（空输入返回空串）。"""
    assert mod._clean_text(None) == ""
    assert mod._clean_text(12345) == "12345"


def test_has_substantial_detects_alnum_and_cjk():
    """字母、数字、汉字视为有实质内容；纯符号/空白不算。"""
    assert mod._has_substantial("abc") is True
    assert mod._has_substantial("12") is True
    assert mod._has_substantial("汉字") is True
    assert mod._has_substantial("!!!") is False
    assert mod._has_substantial("") is False
    assert mod._has_substantial(None) is False


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", True),          # 空串
        ("   ", True),       # 纯空白
        ("!!!", True),       # 无实质内容
        ("a", True),         # 长度 <= 2
        ("ab", True),        # 长度 <= 2
        ("abc", False),      # 正常短句
        ("你好呀", False),    # 正常中文短句
    ],
)
def test_is_low_value_text_boundaries(text, expected):
    """低价值文本的各类边界判定。"""
    assert mod._is_low_value_text(text) is expected


def test_is_low_value_text_none_is_low_value():
    """None 视为低价值。"""
    assert mod._is_low_value_text(None) is True


# --------------------------------------------------------------------------
# CleanRecord
# --------------------------------------------------------------------------


def test_clean_record_to_json_maps_field_names():
    """to_json 使用约定的键名（type/localId 与 dataclass 字段名不同）。"""
    r = _rec(ts=7, role="user", text="你好", msg_type="引用消息", local_id=9)
    assert r.to_json() == {
        "ts": 7,
        "role": "user",
        "text": "你好",
        "type": "引用消息",
        "localId": 9,
    }


# --------------------------------------------------------------------------
# _infer_my_wxid
# --------------------------------------------------------------------------


def test_infer_my_wxid_prefers_most_common_sender_of_sent_messages():
    """优先取「自己发出」消息里出现次数最多的 sender。"""
    messages = [
        {"senderUsername": "wxid_a", "isSend": 1},
        {"senderUsername": "wxid_b", "isSend": 1},
        {"senderUsername": "wxid_a", "isSend": 1},
        {"senderUsername": "wxid_ling", "isSend": 1},  # 对方不算
        {"senderUsername": "", "isSend": 1},            # 空 sender 不算
    ]
    assert mod._infer_my_wxid(messages, "wxid_ling") == "wxid_a"


def test_infer_my_wxid_falls_back_to_first_other_sender():
    """没有任何 isSend=1 记录时，回退到第一个非对方的 sender。"""
    messages = [
        {"senderUsername": "wxid_ling", "isSend": 0},
        {"senderUsername": "wxid_x", "isSend": 0},
        {"senderUsername": "wxid_y", "isSend": 0},
    ]
    assert mod._infer_my_wxid(messages, "wxid_ling") == "wxid_x"


def test_infer_my_wxid_returns_empty_when_only_partner():
    """只有对方消息时无法推断，返回空串。"""
    messages = [
        {"senderUsername": "wxid_ling", "isSend": 0},
        {"senderUsername": "", "isSend": 1},
    ]
    assert mod._infer_my_wxid(messages, "wxid_ling") == ""


def test_infer_my_wxid_empty_message_list():
    """空消息列表返回空串。"""
    assert mod._infer_my_wxid([], "wxid_ling") == ""


# --------------------------------------------------------------------------
# _iter_clean_records
# --------------------------------------------------------------------------


def test_iter_clean_records_filters_and_sorts():
    """类型不符 / 未知发送者 / 空文本被丢弃，结果按 (ts, localId) 排序。"""
    messages = [
        {"senderUsername": "wxid_me", "type": "文本消息", "content": "第二条", "createTime": 20, "localId": 2},
        {"senderUsername": "wxid_ling", "type": "文本消息", "content": "第一条", "createTime": 10, "localId": 1},
        {"senderUsername": "wxid_me", "type": "图片消息", "content": "[图片]", "createTime": 30, "localId": 3},
        {"senderUsername": "wxid_ghost", "type": "文本消息", "content": "路人", "createTime": 40, "localId": 4},
        {"senderUsername": "wxid_me", "type": "文本消息", "content": "   ", "createTime": 50, "localId": 5},
    ]
    records, stats = mod._iter_clean_records(
        messages=messages,
        my_wxid="wxid_me",
        partner_wxid="wxid_ling",
        partner_label="玲",
        include_types=["文本消息"],
        max_dup_per_sender_text=3,
    )

    assert [r.text for r in records] == ["第一条", "第二条"]
    assert [r.role for r in records] == ["ling", "user"]
    assert stats["input_messages"] == 5
    assert stats["kept_messages"] == 2
    assert stats["dropped"]["type:图片消息"] == 1
    assert stats["dropped"]["unknown_sender"] == 1
    assert stats["dropped"]["empty"] == 1
    assert stats["my_wxid"] == "wxid_me"
    assert stats["partner_wxid"] == "wxid_ling"
    assert stats["partner_label"] == "玲"


def test_iter_clean_records_caps_duplicates_per_role_and_text():
    """同一 (role, text) 超过 max_dup_per_sender_text 的部分被丢弃。"""
    messages = [
        {"senderUsername": "wxid_me", "type": "文本消息", "content": "哈哈哈", "createTime": i, "localId": i}
        for i in range(5)
    ]
    records, stats = mod._iter_clean_records(
        messages=messages,
        my_wxid="wxid_me",
        partner_wxid="wxid_ling",
        partner_label="玲",
        include_types=["文本消息"],
        max_dup_per_sender_text=2,
    )
    assert len(records) == 2
    assert stats["dropped"]["dup_capped"] == 3


def test_iter_clean_records_missing_fields_use_defaults():
    """缺字段的消息被安全降级（type 为空、时间/ID 为 0），content 缺失则被丢弃。"""
    messages = [
        {"senderUsername": "wxid_ling", "content": "只有内容"},
        {"senderUsername": "wxid_ling"},  # 缺 content → 清洗后为空 → 丢弃
    ]
    records, stats = mod._iter_clean_records(
        messages=messages,
        my_wxid="wxid_me",
        partner_wxid="wxid_ling",
        partner_label="玲",
        include_types=[""],
        max_dup_per_sender_text=3,
    )
    assert len(records) == 1
    assert records[0].ts == 0
    assert records[0].local_id == 0
    assert records[0].role == "ling"
    assert stats["kept_messages"] == 1
    assert stats["dropped"] == {"empty": 1}


def test_iter_clean_records_empty_input():
    """空输入返回空记录与全零统计。"""
    records, stats = mod._iter_clean_records(
        messages=[],
        my_wxid="a",
        partner_wxid="b",
        partner_label="玲",
        include_types=["文本消息"],
        max_dup_per_sender_text=3,
    )
    assert records == []
    assert stats["kept_messages"] == 0
    assert stats["dropped"] == {}


# --------------------------------------------------------------------------
# _build_pairs
# --------------------------------------------------------------------------


def test_build_pairs_forms_pair_and_resets_buffer():
    """user 缓冲 + 紧随其后的 ling 消息构成一条配对，之后缓冲清空。"""
    records = [
        _rec(100, "user", "你在干嘛"),
        _rec(105, "user", "在忙吗"),
        _rec(110, "ling", "我在看书呢"),
    ]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=3, min_user_len=2, min_ling_len=2
    )
    assert len(pairs) == 1
    assert pairs[0]["user"] == "你在干嘛\n在忙吗"
    assert pairs[0]["ling"] == "我在看书呢"
    assert pairs[0]["ts"] == 110
    assert stats == {"pairs": 1, "dropped": {}}


def test_build_pairs_trims_user_buffer_to_max():
    """user 缓冲超过 max_user_messages 时只保留最近的若干条。"""
    records = [
        _rec(1, "user", "第一条"),
        _rec(2, "user", "第二条"),
        _rec(3, "user", "第三条"),
        _rec(4, "ling", "好的呀"),
    ]
    pairs, _ = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=2, min_user_len=2, min_ling_len=2
    )
    assert pairs[0]["user"] == "第二条\n第三条"


def test_build_pairs_drops_ling_without_user_context():
    """没有 user 上文时，ling 消息被记为 no_user_context。"""
    records = [_rec(10, "ling", "在吗")]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=3, min_user_len=2, min_ling_len=2
    )
    assert pairs == []
    assert stats["dropped"] == {"no_user_context": 1}


def test_build_pairs_drops_and_resets_on_gap_too_large():
    """与最新 user 消息间隔过大时丢弃并清空缓冲。"""
    records = [
        _rec(1, "user", "很久以前"),
        _rec(10000, "ling", "隔了太久"),
    ]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=60, max_user_messages=3, min_user_len=2, min_ling_len=2
    )
    assert pairs == []
    assert stats["dropped"] == {"gap_too_large": 1}


def test_build_pairs_zero_timestamp_skips_gap_check():
    """任一侧时间为 0（缺失）时不做间隔判断。"""
    records = [
        _rec(0, "user", "没有时间戳"),
        _rec(999999, "ling", "也照样配对"),
    ]
    pairs, _ = mod._build_pairs(
        records, max_gap_seconds=1, max_user_messages=3, min_user_len=2, min_ling_len=2
    )
    assert len(pairs) == 1


def test_build_pairs_drops_user_too_short_and_resets():
    """user 文本过短时丢弃并清空缓冲（避免污染下一条配对）。"""
    records = [
        _rec(1, "user", "a"),
        _rec(2, "ling", "这条会被丢弃"),
        _rec(3, "user", "这次够长了"),
        _rec(4, "ling", "这条可以配对"),
    ]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=3, min_user_len=4, min_ling_len=2
    )
    assert [p["user"] for p in pairs] == ["这次够长了"]
    assert stats["dropped"] == {"user_too_short": 1}


def test_build_pairs_drops_ling_too_short():
    """ling 文本过短时丢弃。"""
    records = [
        _rec(1, "user", "你好呀朋友"),
        _rec(2, "ling", "嗯"),
    ]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=3, min_user_len=2, min_ling_len=5
    )
    assert pairs == []
    assert stats["dropped"] == {"ling_too_short": 1}


def test_build_pairs_ignores_unknown_role():
    """既不是 user 也不是 ling 的角色被直接跳过。"""
    records = [
        _rec(1, "user", "你好呀朋友"),
        _rec(2, "system", "系统提示"),
        _rec(3, "ling", "我在呢"),
    ]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=3, min_user_len=2, min_ling_len=2
    )
    assert len(pairs) == 1
    assert stats["dropped"] == {}


def test_build_pairs_user_text_without_substantial_is_dropped():
    """user 文本长度够但没有实质字符（如纯表情符号）也会被丢弃。"""
    records = [
        _rec(1, "user", "。。。。。。"),
        _rec(2, "ling", "我在呢"),
    ]
    pairs, stats = mod._build_pairs(
        records, max_gap_seconds=3600, max_user_messages=3, min_user_len=2, min_ling_len=2
    )
    assert pairs == []
    assert stats["dropped"] == {"user_too_short": 1}


# --------------------------------------------------------------------------
# _write_jsonl / _median / _percentile
# --------------------------------------------------------------------------


def test_write_jsonl_creates_dirs_and_returns_count(tmp_path):
    """自动创建父目录，逐行写 JSONL 并返回写入行数。"""
    path = str(tmp_path / "nested" / "deep" / "out.jsonl")
    n = mod._write_jsonl(path, [{"a": 1}, {"b": "中文"}])
    assert n == 2
    lines = open(path, "r", encoding="utf-8").read().splitlines()
    assert lines == ['{"a": 1}', '{"b": "中文"}']


def test_write_jsonl_empty_iterable(tmp_path):
    """空迭代器写出空文件并返回 0。"""
    path = str(tmp_path / "empty.jsonl")
    assert mod._write_jsonl(path, []) == 0
    assert open(path, "r", encoding="utf-8").read() == ""


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], 0),           # 空输入
        ([5], 5),          # 单元素
        ([3, 1, 2], 2),    # 奇数个取中间
        ([1, 2, 3, 4], 2), # 偶数个取平均后取整
        ([1, 2], 1),       # 偶数个，平均为 1.5 → 1
    ],
)
def test_median(values, expected):
    """中位数：空输入 0，奇数取中间，偶数取中间两者均值取整。"""
    assert mod._median(values) == expected


@pytest.mark.parametrize(
    "values,p,expected",
    [
        ([], 0.9, 0),          # 空输入
        ([1, 2, 3, 4, 5], 0.9, 5),  # 常规 p90
        ([1, 2, 3, 4, 5], 0.0, 1),  # 下界
        ([1, 2, 3, 4, 5], 1.0, 5),  # 上界
        ([1, 2, 3, 4, 5], 2.0, 5),  # p 超界被 clamp 到末尾
        ([1, 2, 3, 4, 5], -1.0, 1), # p 为负被 clamp 到开头
    ],
)
def test_percentile(values, p, expected):
    """分位数：空输入 0，索引越界时被 clamp 到合法区间。"""
    assert mod._percentile(values, p) == expected


# --------------------------------------------------------------------------
# _select_few_shot
# --------------------------------------------------------------------------


def test_select_few_shot_scores_and_limits():
    """按 (ling 长度*3 + min(user 长度,120)) 降序挑选，并受 n 限制。"""
    pairs = [
        {"user": "短问题", "ling": "短回答", "ts": 1},
        {"user": "长一点的问题呀", "ling": "长很多的回答内容在这里", "ts": 2},
    ]
    picked = mod._select_few_shot(pairs, n=1)
    assert len(picked) == 1
    assert picked[0]["ling"] == "长很多的回答内容在这里"
    assert picked[0]["ts"] == 2


def test_select_few_shot_skips_low_value_and_too_long():
    """低价值文本、超长 user（>300）/ling（>260）都被跳过。"""
    pairs = [
        {"user": "", "ling": "有效回答内容", "ts": 1},                       # user 低价值
        {"user": "有效问题内容", "ling": "嗯", "ts": 2},                     # ling 低价值
        {"user": "问" * 301, "ling": "够长的回答内容", "ts": 3},              # user 超长
        {"user": "够长的问题内容", "ling": "答" * 261, "ts": 4},              # ling 超长
        {"user": "合格的问题", "ling": "合格的回答内容", "ts": 5},
    ]
    picked = mod._select_few_shot(pairs, n=10)
    assert [p["ts"] for p in picked] == [5]


def test_select_few_shot_dedupes_identical_ling():
    """ling 文本相同的样本只保留得分最高的那条。"""
    pairs = [
        {"user": "问题一", "ling": "一模一样的回答", "ts": 1},
        {"user": "问题二更长一些", "ling": "一模一样的回答", "ts": 2},
    ]
    picked = mod._select_few_shot(pairs, n=10)
    assert len(picked) == 1
    assert picked[0]["ts"] == 2


def test_select_few_shot_missing_fields_are_tolerated():
    """缺 user/ling/ts 字段时安全降级，不抛异常。"""
    picked = mod._select_few_shot([{"ling": "只有回答内容"}], n=5)
    assert picked == []


def test_select_few_shot_empty_input():
    """空输入返回空列表。"""
    assert mod._select_few_shot([], n=5) == []


def test_select_few_shot_n_zero_still_returns_one():
    """n=0 时仍会返回 1 条（先 append 再判断上限的既有行为）。"""
    pairs = [{"user": "合格的问题", "ling": "合格的回答内容", "ts": 1}]
    assert len(mod._select_few_shot(pairs, n=0)) == 1


# --------------------------------------------------------------------------
# _build_style_profile
# --------------------------------------------------------------------------


def test_build_style_profile_basic_statistics():
    """统计条数、平均长度、分位数、开头/结尾与口头禅。"""
    profile = mod._build_style_profile(["你好呀朋友", "今天很开心呢", "你好呀朋友"])
    assert profile["count"] == 3
    assert profile["avg_len"] == 5          # (5 + 6 + 5) // 3
    assert profile["p50_len"] == 5          # 排序后 [5, 5, 6] 取中间
    assert profile["p90_len"] == 6          # round(2 * 0.9) = 2 → 6
    assert profile["top_openers"][0] == "你好"
    assert profile["top_endings"][0] == "朋友"
    assert "你好呀朋友" in profile["catchphrases"]


def test_build_style_profile_filters_blank_and_low_value():
    """空白、纯符号、无实质内容的文本先被过滤，不进入统计。"""
    profile = mod._build_style_profile(["", "   ", "!!!", "。。。", "有效内容在这里"])
    assert profile["count"] == 1
    assert profile["top_openers"] == ["有效"]


def test_build_style_profile_empty_input():
    """空输入返回全零统计且不抛异常。"""
    profile = mod._build_style_profile([])
    assert profile == {
        "count": 0,
        "avg_len": 0,
        "p50_len": 0,
        "p90_len": 0,
        "top_openers": [],
        "top_endings": [],
        "catchphrases": [],
    }


def test_build_style_profile_single_char_has_no_opener():
    """长度为 1 的文本不参与开头/结尾统计。"""
    profile = mod._build_style_profile(["好"])
    assert profile["count"] == 1
    assert profile["top_openers"] == []
    assert profile["top_endings"] == []


def test_build_style_profile_catchphrase_length_window():
    """只有 4~26 字的文本才进入口头禅候选。"""
    short = "短句"                    # len 2，窗口外
    ok = "这是一个刚好合适的句子"      # 窗口内
    long_text = "很长" * 20            # len 40，窗口外
    profile = mod._build_style_profile([short, ok, long_text])
    assert profile["catchphrases"] == [ok]


# --------------------------------------------------------------------------
# _extract_json_object
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", None),                                   # 空串
        ("   ", None),                                # 纯空白
        ("没有任何大括号", None),                       # 无大括号
        ("}{", None),                                 # end <= start
        ("{不是合法 json}", None),                     # 解析失败
        ("{}", {}),                                   # 空对象
        ('{"a": 1}', {"a": 1}),                       # 正常
        ('前缀 {"a": 1} 后缀', {"a": 1}),               # 前后有噪声
        ('{"a": {"b": 2}}', {"a": {"b": 2}}),         # 嵌套
    ],
)
def test_extract_json_object(text, expected):
    """从任意文本中抽取第一个到最后一个大括号之间的 JSON 对象。"""
    assert mod._extract_json_object(text) == expected


def test_extract_json_object_none_input():
    """None 输入返回 None。"""
    assert mod._extract_json_object(None) is None


# --------------------------------------------------------------------------
# _deepseek_r1_refine_prompt_pack
# --------------------------------------------------------------------------

_R1_OK = json.dumps(
    {
        "system_prompt": "  你是玲，说话简短。  ",
        "do": ["保持简短", "   "],
        "dont": ["不要长篇大论"],
        "notes": ["注意语气"],
    },
    ensure_ascii=False,
)


def _run_r1(monkeypatch, fake_cls, **kwargs):
    """同步跑一遍 R1 精修协作者。"""
    import asyncio

    _install_fake_client(monkeypatch, fake_cls)
    params = {
        "base_url": "https://example.invalid/v1",
        "api_key": "k",
        "model": "deepseek-reasoner",
        "partner_label": "玲",
        "style_profile": {},
        "few_shot": [],
    }
    params.update(kwargs)
    return asyncio.run(mod._deepseek_r1_refine_prompt_pack(**params))


def test_r1_refine_success_filters_stream_and_parses_json(monkeypatch):
    """只累积 --- 分隔符之后的正文，跳过思考行与空 chunk，并清洗字段。"""
    chunks = [
        "> **Thinking:** 先想一想",
        '{"system_prompt": "这段在分隔符之前，应被忽略"}',
        "\n\n---\n\n",
        "",
        _R1_OK,
    ]
    fake, calls = _make_fake_client(chunks=chunks)
    result = _run_r1(monkeypatch, fake)

    assert result["system_prompt"] == "你是玲，说话简短。"
    assert result["do"] == ["保持简短"]      # 空白项被过滤
    assert result["dont"] == ["不要长篇大论"]
    assert result["notes"] == ["注意语气"]
    assert calls["initialize"] is True
    assert calls["shutdown"] is True
    assert calls["stream_kwargs"] == {"temperature": 0.15, "max_tokens": 650}
    assert calls["ctor_kwargs"] == {
        "api_key": "k",
        "base_url": "https://example.invalid/v1",
        "model": "deepseek-reasoner",
    }


def test_r1_refine_non_json_output_returns_error(monkeypatch):
    """输出不是 JSON 时返回 error + raw_preview。"""
    fake, _ = _make_fake_client(chunks=["\n\n---\n\n", "这根本不是 JSON"])
    result = _run_r1(monkeypatch, fake)
    assert result["error"] == "DeepSeek-R1 输出非 JSON"
    assert result["raw_preview"] == "这根本不是 JSON"


def test_r1_refine_missing_system_prompt_returns_error(monkeypatch):
    """JSON 合法但缺少 system_prompt 时返回对应 error。"""
    payload = json.dumps({"do": ["a"]}, ensure_ascii=False)
    fake, _ = _make_fake_client(chunks=["\n\n---\n\n", payload])
    result = _run_r1(monkeypatch, fake)
    assert result["error"] == "DeepSeek-R1 输出缺少 system_prompt"
    assert "do" in result["raw_preview"]


def test_r1_refine_non_list_fields_become_empty_lists(monkeypatch):
    """do/dont/notes 不是列表时降级为空列表。"""
    payload = json.dumps(
        {"system_prompt": "有效提示词", "do": "字符串", "dont": 5, "notes": None},
        ensure_ascii=False,
    )
    fake, _ = _make_fake_client(chunks=["\n\n---\n\n", payload])
    result = _run_r1(monkeypatch, fake)
    assert result == {
        "system_prompt": "有效提示词",
        "do": [],
        "dont": [],
        "notes": [],
    }


def test_r1_refine_truncates_oversized_lists(monkeypatch):
    """do/dont/notes 各最多保留 20 条。"""
    payload = json.dumps(
        {
            "system_prompt": "有效提示词",
            "do": [f"d{i}" for i in range(25)],
            "dont": [f"n{i}" for i in range(25)],
            "notes": [f"t{i}" for i in range(25)],
        },
        ensure_ascii=False,
    )
    fake, _ = _make_fake_client(chunks=["\n\n---\n\n", payload])
    result = _run_r1(monkeypatch, fake)
    assert len(result["do"]) == 20
    assert len(result["dont"]) == 20
    assert len(result["notes"]) == 20


def test_r1_refine_filters_few_shot_and_profile(monkeypatch):
    """few_shot 里的低价值样本被剔除，profile 缺字段时按空列表降级。"""
    fake, calls = _make_fake_client(chunks=["\n\n---\n\n", _R1_OK])
    few_shot = [
        {"user": "有效提问内容", "ling": "有效回答内容"},
        {"user": "", "ling": "回答"},          # user 低价值，剔除
        {"user": "提问", "ling": "嗯"},          # ling 低价值，剔除
    ]
    result = _run_r1(monkeypatch, fake, style_profile={}, few_shot=few_shot)
    assert "error" not in result

    messages = calls["stream_messages"]
    payload = json.loads(messages[1]["content"])
    assert payload["persona_name"] == "玲"
    assert payload["few_shot"] == [{"user": "有效提问内容", "ling": "有效回答内容"}]
    assert payload["style_profile"] == {
        "avg_len": None,
        "p50_len": None,
        "p90_len": None,
        "top_openers": [],
        "top_endings": [],
        "catchphrases": [],
    }


def test_r1_refine_truncates_profile_and_few_shot(monkeypatch):
    """profile 列表截到 20/60 条，few_shot 最多取 18 条且单条截到 220 字。"""
    fake, calls = _make_fake_client(chunks=["\n\n---\n\n", _R1_OK])
    style_profile = {
        "avg_len": 10,
        "p50_len": 9,
        "p90_len": 20,
        "top_openers": [f"o{i}" for i in range(30)],
        "top_endings": [f"e{i}" for i in range(30)],
        "catchphrases": [f"c{i}" for i in range(80)],
    }
    few_shot = [
        {"user": "问" * 300, "ling": "答" * 300} for _ in range(25)
    ]
    result = _run_r1(monkeypatch, fake, style_profile=style_profile, few_shot=few_shot)
    assert "error" not in result

    payload = json.loads(calls["stream_messages"][1]["content"])
    assert len(payload["style_profile"]["top_openers"]) == 20
    assert len(payload["style_profile"]["top_endings"]) == 20
    assert len(payload["style_profile"]["catchphrases"]) == 60
    assert len(payload["few_shot"]) == 18
    assert len(payload["few_shot"][0]["user"]) == 220
    assert len(payload["few_shot"][0]["ling"]) == 220


def test_r1_refine_shutdown_error_is_swallowed(monkeypatch):
    """shutdown 抛异常时被 finally 内的 try/except 吞掉，不影响返回值。"""
    fake, calls = _make_fake_client(
        chunks=["\n\n---\n\n", _R1_OK], shutdown_error=RuntimeError("shutdown boom")
    )
    result = _run_r1(monkeypatch, fake)
    assert result["system_prompt"] == "你是玲，说话简短。"
    assert calls["shutdown"] is True


def test_r1_refine_import_fallback_when_package_unavailable(monkeypatch):
    """core.llm.openai_compat 不可用时走 sys.path 兜底分支并重新导入。"""
    monkeypatch.setitem(sys.modules, "core.llm.openai_compat", None)
    monkeypatch.setattr(
        sys,
        "path",
        [p for p in sys.path if os.path.normcase(os.path.abspath(p)) != os.path.normcase(PROJECT_ROOT)],
    )
    import asyncio

    with pytest.raises(ImportError):
        asyncio.run(
            mod._deepseek_r1_refine_prompt_pack(
                base_url="u",
                api_key="k",
                model="m",
                partner_label="玲",
                style_profile={},
                few_shot=[],
            )
        )
    # 兜底分支把项目根目录补回了 sys.path
    assert any(
        os.path.normcase(os.path.abspath(p)) == os.path.normcase(PROJECT_ROOT)
        for p in sys.path
    )


# --------------------------------------------------------------------------
# _deepseek_chat_refine_prompt_pack
# --------------------------------------------------------------------------

_CHAT_OK = json.dumps(
    {
        "system_prompt": "你是玲。",
        "do": ["保持简短"],
        "dont": ["别啰嗦"],
        "notes": ["语气自然"],
    },
    ensure_ascii=False,
)


def _run_chat(monkeypatch, fake_cls, **kwargs):
    """同步跑一遍 chat 版精修协作者。"""
    import asyncio

    _install_fake_client(monkeypatch, fake_cls)
    params = {
        "base_url": "https://example.invalid/v1",
        "api_key": "k",
        "model": "deepseek-chat",
        "partner_label": "玲",
        "style_profile": {},
        "few_shot": [],
    }
    params.update(kwargs)
    return asyncio.run(mod._deepseek_chat_refine_prompt_pack(**params))


def test_chat_refine_success_with_string_result(monkeypatch):
    """chat 返回字符串 JSON 时正常解析出四个字段。"""
    fake, calls = _make_fake_client(chat_result=_CHAT_OK)
    result = _run_chat(monkeypatch, fake)
    assert result == {
        "system_prompt": "你是玲。",
        "do": ["保持简短"],
        "dont": ["别啰嗦"],
        "notes": ["语气自然"],
    }
    assert calls["chat_kwargs"] == {"temperature": 0.2, "max_tokens": 700}
    assert calls["shutdown"] is True


def test_chat_refine_dict_result_uses_response_key(monkeypatch):
    """chat 返回 dict 且含 response 时取该字段内容。"""
    fake, _ = _make_fake_client(chat_result={"response": _CHAT_OK})
    result = _run_chat(monkeypatch, fake)
    assert result["system_prompt"] == "你是玲。"


def test_chat_refine_dict_result_without_response_key(monkeypatch):
    """chat 返回 dict 但没有 response 时退化为 str(dict)，解析失败并报错。"""
    fake, _ = _make_fake_client(chat_result={"other": "x"})
    result = _run_chat(monkeypatch, fake)
    assert result["error"] == "DeepSeek-chat 输出非 JSON"


def test_chat_refine_non_json_output_returns_error(monkeypatch):
    """非 JSON 输出返回 error + raw_preview。"""
    fake, _ = _make_fake_client(chat_result="完全不是 JSON")
    result = _run_chat(monkeypatch, fake)
    assert result["error"] == "DeepSeek-chat 输出非 JSON"
    assert result["raw_preview"] == "完全不是 JSON"


def test_chat_refine_missing_system_prompt_returns_error(monkeypatch):
    """JSON 合法但缺 system_prompt 时返回对应 error。"""
    fake, _ = _make_fake_client(chat_result=json.dumps({"notes": []}))
    result = _run_chat(monkeypatch, fake)
    assert result["error"] == "DeepSeek-chat 输出缺少 system_prompt"


def test_chat_refine_non_list_and_oversized_fields(monkeypatch):
    """非列表字段降级为空列表，超长列表截到 20 条。"""
    payload = json.dumps(
        {
            "system_prompt": "提示词",
            "do": [f"d{i}" for i in range(30)],
            "dont": "不是列表",
            "notes": 3,
        },
        ensure_ascii=False,
    )
    fake, _ = _make_fake_client(chat_result=payload)
    result = _run_chat(monkeypatch, fake)
    assert len(result["do"]) == 20
    assert result["dont"] == []
    assert result["notes"] == []


def test_chat_refine_filters_low_value_few_shot(monkeypatch):
    """few_shot 中的低价值样本在 chat 版同样被剔除。"""
    fake, calls = _make_fake_client(chat_result=_CHAT_OK)
    few_shot = [
        {"user": "有效提问内容", "ling": "有效回答内容"},
        {"user": "嗯", "ling": "有效回答内容"},   # user 低价值
        {"user": "有效提问内容", "ling": "。"},    # ling 低价值
    ]
    result = _run_chat(monkeypatch, fake, few_shot=few_shot)
    assert "error" not in result
    payload = json.loads(calls["chat_messages"][1]["content"])
    assert payload["few_shot"] == [{"user": "有效提问内容", "ling": "有效回答内容"}]


def test_chat_refine_shutdown_error_is_swallowed(monkeypatch):
    """shutdown 异常被吞掉，返回值不受影响。"""
    fake, _ = _make_fake_client(
        chat_result=_CHAT_OK, shutdown_error=RuntimeError("boom")
    )
    assert _run_chat(monkeypatch, fake)["system_prompt"] == "你是玲。"


def test_chat_refine_import_fallback_when_package_unavailable(monkeypatch):
    """core.llm.openai_compat 不可用时走 sys.path 兜底分支。"""
    monkeypatch.setitem(sys.modules, "core.llm.openai_compat", None)
    monkeypatch.setattr(
        sys,
        "path",
        [p for p in sys.path if os.path.normcase(os.path.abspath(p)) != os.path.normcase(PROJECT_ROOT)],
    )
    import asyncio

    with pytest.raises(ImportError):
        asyncio.run(
            mod._deepseek_chat_refine_prompt_pack(
                base_url="u",
                api_key="k",
                model="m",
                partner_label="玲",
                style_profile={},
                few_shot=[],
            )
        )
    assert any(
        os.path.normcase(os.path.abspath(p)) == os.path.normcase(PROJECT_ROOT)
        for p in sys.path
    )


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------


def _run_main(monkeypatch, argv):
    """注入 argv 后调用 main()。"""
    monkeypatch.setattr(sys, "argv", ["extract_style.py", *argv])
    return mod.main()


def test_main_default_out_prefix_and_outputs(tmp_path, monkeypatch, capsys):
    """不给 --out_prefix 时以输入文件路径为前缀，三类产物 + prompt_pack 均生成。"""
    inp = _write_input(tmp_path, name="sess.json")
    assert _run_main(monkeypatch, ["--input", inp]) == 0

    for suffix in (".clean.jsonl", ".ling_texts.jsonl", ".pairs.jsonl", ".prompt_pack.json"):
        assert (tmp_path / f"sess{suffix}").exists(), suffix

    clean_rows = [
        json.loads(line)
        for line in (tmp_path / "sess.clean.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    # 类型过滤 / 未知发送者 / 空文本各丢一条
    assert len(clean_rows) == 2
    assert {row["role"] for row in clean_rows} == {"user", "ling"}

    ling_rows = [
        json.loads(line)
        for line in (tmp_path / "sess.ling_texts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert ling_rows == [{"ts": 1010, "text": "是呀，适合出去走走"}]

    pairs = [
        json.loads(line)
        for line in (tmp_path / "sess.pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert pairs == [
        {"ts": 1010, "user": "今天天气不错", "ling": "是呀，适合出去走走"}
    ]

    pack = json.loads((tmp_path / "sess.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["meta"] == {
        "generator": "xiaoyou-core.tools.extract_style",
        "source": "sess.json",
    }
    assert pack["persona"] == {"name": "玲", "partner_wxid": "wxid_ling"}
    assert pack["deepseek_r1"] is None
    assert pack["deepseek_v3"] is None
    assert pack["files"]["clean_jsonl"] == str(tmp_path / "sess.clean.jsonl")
    assert "玲" in pack["system_prompt"]
    assert pack["style_profile"]["count"] == 1

    out = capsys.readouterr().out
    assert json.loads(out.splitlines()[0]) == {"clean": 2, "ling_texts": 1, "pairs": 1}
    assert json.loads(out.splitlines()[1])["stats"]["kept_messages"] == 2


def test_main_explicit_out_prefix_and_include_types(tmp_path, monkeypatch):
    """显式 --out_prefix 与自定义 --include_types / 去重上限生效。"""
    inp = _write_input(tmp_path, name="sess.json")
    out_prefix = str(tmp_path / "sub" / "result")
    assert (
        _run_main(
            monkeypatch,
            [
                "--input",
                inp,
                "--out_prefix",
                out_prefix,
                "--include_types",
                " 文本消息 , 图片消息 ,, ",
                "--max_dup_per_text",
                "1",
            ],
        )
        == 0
    )
    assert (tmp_path / "sub" / "result.prompt_pack.json").exists()
    clean_rows = [
        json.loads(line)
        for line in (tmp_path / "sub" / "result.clean.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    # 图片消息这次被包含，"   " 仍因清洗后为空被丢弃
    assert len(clean_rows) == 3


def test_main_prompt_examples_zero_disables_extra_examples(tmp_path, monkeypatch):
    """--prompt_examples 0 时 few_shot 至多 1 条（既有边界行为）。"""
    inp = _write_input(tmp_path, name="sess.json")
    assert _run_main(monkeypatch, ["--input", inp, "--out_prefix", str(tmp_path / "o"), "--prompt_examples", "0"]) == 0
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert len(pack["few_shot"]) == 1


def test_main_display_name_falls_back_to_nickname(tmp_path, monkeypatch):
    """session 无 displayName 时用 nickname，二者都无则用默认 "玲"。"""
    inp = _write_input(
        tmp_path,
        session={"wxid": "wxid_ling", "nickname": "Ling"},
        name="sess.json",
    )
    assert _run_main(monkeypatch, ["--input", inp, "--out_prefix", str(tmp_path / "o")]) == 0
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["persona"]["name"] == "Ling"

    inp2 = _write_input(tmp_path, session={"wxid": "wxid_ling"}, name="sess2.json")
    assert _run_main(monkeypatch, ["--input", inp2, "--out_prefix", str(tmp_path / "o2")]) == 0
    pack2 = json.loads((tmp_path / "o2.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack2["persona"]["name"] == "玲"


def test_main_missing_session_raises_system_exit(tmp_path, monkeypatch):
    """无法识别对方 wxid 时以 SystemExit 终止。"""
    inp = _write_input(tmp_path, session={}, name="sess.json")
    monkeypatch.setattr(sys, "argv", ["extract_style.py", "--input", inp])
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert "无法识别双方 wxid" in str(excinfo.value)


def test_main_messages_not_a_list_raises_system_exit(tmp_path, monkeypatch):
    """messages 字段不是列表时以 SystemExit 终止。"""
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps({"session": {"wxid": "wxid_ling"}, "messages": "不是列表"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["extract_style.py", "--input", str(path)])
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert "messages 格式不正确" in str(excinfo.value)


def test_main_r1_refine_replaces_system_prompt(tmp_path, monkeypatch):
    """开启 --deepseek_r1_refine 且调用成功时，system_prompt 被模型结果替换。"""
    inp = _write_input(tmp_path, name="sess.json")
    fake, calls = _make_fake_client(chunks=["\n\n---\n\n", _R1_OK])
    _install_fake_client(monkeypatch, fake)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    assert (
        _run_main(
            monkeypatch,
            [
                "--input",
                inp,
                "--out_prefix",
                str(tmp_path / "o"),
                "--deepseek_r1_refine",
                "--deepseek_base_url",
                "https://example.invalid/v1",
            ],
        )
        == 0
    )
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["system_prompt"] == "你是玲，说话简短。"
    assert pack["deepseek_r1"]["do"] == ["保持简短"]
    assert calls["ctor_kwargs"]["model"] == "deepseek-reasoner"


def test_main_r1_refine_failure_is_recorded_as_error(tmp_path, monkeypatch):
    """R1 精修抛异常时被捕获，写进 deepseek_r1.error，不影响主流程。"""
    inp = _write_input(tmp_path, name="sess.json")
    fake, _ = _make_fake_client(init_error=RuntimeError("init boom"))
    _install_fake_client(monkeypatch, fake)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    assert (
        _run_main(
            monkeypatch,
            ["--input", inp, "--out_prefix", str(tmp_path / "o"), "--deepseek_r1_refine"],
        )
        == 0
    )
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["deepseek_r1"] == {"error": "init boom"}
    assert "玲" in pack["system_prompt"]  # 回退到内置提示词


def test_main_v3_refine_replaces_system_prompt(tmp_path, monkeypatch):
    """开启 --deepseek_v3_refine 且调用成功时替换 system_prompt。"""
    inp = _write_input(tmp_path, name="sess.json")
    fake, calls = _make_fake_client(chat_result=_CHAT_OK)
    _install_fake_client(monkeypatch, fake)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    assert (
        _run_main(
            monkeypatch,
            [
                "--input",
                inp,
                "--out_prefix",
                str(tmp_path / "o"),
                "--deepseek_v3_refine",
                "--deepseek_v3_model",
                "deepseek-chat-x",
            ],
        )
        == 0
    )
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["system_prompt"] == "你是玲。"
    assert pack["deepseek_v3"]["notes"] == ["语气自然"]
    assert calls["ctor_kwargs"]["model"] == "deepseek-chat-x"


def test_main_v3_refine_error_keeps_default_prompt(tmp_path, monkeypatch):
    """V3 精修返回 error 字典时不覆盖 system_prompt。"""
    inp = _write_input(tmp_path, name="sess.json")
    fake, _ = _make_fake_client(chat_result="不是 JSON")
    _install_fake_client(monkeypatch, fake)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    assert (
        _run_main(
            monkeypatch,
            ["--input", inp, "--out_prefix", str(tmp_path / "o"), "--deepseek_v3_refine"],
        )
        == 0
    )
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["deepseek_v3"]["error"] == "DeepSeek-chat 输出非 JSON"
    assert "你正在扮演" in pack["system_prompt"]


def test_main_v3_refine_exception_is_recorded_as_error(tmp_path, monkeypatch):
    """V3 精修调用抛异常时被捕获，写进 deepseek_v3.error，不影响主流程。"""
    inp = _write_input(tmp_path, name="sess.json")
    fake, _ = _make_fake_client(chat_error=RuntimeError("chat boom"))
    _install_fake_client(monkeypatch, fake)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    assert (
        _run_main(
            monkeypatch,
            ["--input", inp, "--out_prefix", str(tmp_path / "o"), "--deepseek_v3_refine"],
        )
        == 0
    )
    pack = json.loads((tmp_path / "o.prompt_pack.json").read_text(encoding="utf-8"))
    assert pack["deepseek_v3"] == {"error": "chat boom"}
    assert "你正在扮演" in pack["system_prompt"]


@pytest.mark.parametrize("flag", ["--deepseek_r1_refine", "--deepseek_v3_refine"])
def test_main_refine_dotenv_import_failure_falls_back_to_env(tmp_path, monkeypatch, flag):
    """dotenv 不可用时走 except 兜底再读一次环境变量（仍缺 key 则终止）。"""
    import dotenv  # noqa: F401  （先确保模块已加载，再模拟它不可用）

    inp = _write_input(tmp_path, name="sess.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "dotenv", None)

    monkeypatch.setattr(sys, "argv", ["extract_style.py", "--input", inp, flag])
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert "DEEPSEEK_API_KEY 未配置" in str(excinfo.value)


def test_main_refine_without_api_key_exits(tmp_path, monkeypatch):
    """开启精修但环境与 .env 都没有 key 时以 SystemExit 终止。"""
    import dotenv

    inp = _write_input(tmp_path, name="sess.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # 避免仓库根目录的真实 .env 注入 key
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(dotenv, "find_dotenv", lambda *a, **k: "")

    monkeypatch.setattr(
        sys, "argv", ["extract_style.py", "--input", inp, "--deepseek_r1_refine"]
    )
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert "DEEPSEEK_API_KEY 未配置" in str(excinfo.value)


def test_main_v3_refine_without_api_key_exits(tmp_path, monkeypatch):
    """V3 分支同样在缺 key 时终止。"""
    import dotenv

    inp = _write_input(tmp_path, name="sess.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(dotenv, "find_dotenv", lambda *a, **k: "")

    monkeypatch.setattr(
        sys, "argv", ["extract_style.py", "--input", inp, "--deepseek_v3_refine"]
    )
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert "DEEPSEEK_API_KEY 未配置" in str(excinfo.value)


def test_main_uses_env_var_without_touching_dotenv(tmp_path, monkeypatch):
    """环境变量已存在时不再读 .env（load_dotenv 不应被调用）。"""
    import dotenv

    inp = _write_input(tmp_path, name="sess.json")
    fake, _ = _make_fake_client(chunks=["\n\n---\n\n", _R1_OK])
    _install_fake_client(monkeypatch, fake)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")

    called = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: called.append(True))

    assert (
        _run_main(
            monkeypatch,
            ["--input", inp, "--out_prefix", str(tmp_path / "o"), "--deepseek_r1_refine"],
        )
        == 0
    )
    assert called == []


# --------------------------------------------------------------------------
# __main__ 入口
# --------------------------------------------------------------------------


def test_run_as_main_exits_zero(tmp_path, monkeypatch, capsys):
    """以 __main__ 身份执行源码时，走完 main() 并以退出码 0 结束。"""
    inp = _write_input(tmp_path, name="sess.json")
    out_prefix = str(tmp_path / "mainrun")
    monkeypatch.setattr(
        sys,
        "argv",
        ["extract_style.py", "--input", inp, "--out_prefix", out_prefix],
    )
    with warnings.catch_warnings():
        # runpy 对「模块已在 sys.modules 中」固定发 RuntimeWarning，忽略即可
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module("tools.extract_style", run_name="__main__")

    assert excinfo.value.code == 0
    assert (tmp_path / "mainrun.clean.jsonl").exists()
    assert (tmp_path / "mainrun.prompt_pack.json").exists()
    out = capsys.readouterr().out
    assert '"clean": 2' in out
