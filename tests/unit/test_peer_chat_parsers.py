# -*- coding: utf-8 -*-
"""peer_chat 解析器测试：提醒分工 / 主动关怀时段分工。

覆盖：
- core/services/active_care/peer_chat/negotiation_parser.py
- core/services/active_care/peer_chat/proactive_assignment_parser.py

这两个模块是纯函数式的文本→结构解析器，无外部依赖，是 peer_chat 协商链路的
"最后一公里"：LLM 输出的 <assignment> 块解析不出来的话，分工协商会静默退化
成"先到先得"，线上只表现为"分工没生效"，很难从日志反推原因。

设计要点：
- 只断言确定性的解析结果，不做任何时间/随机依赖；
- 覆盖标签块 / 兜底裸 JSON / JSON 修复 / 非法项过滤四条路径；
- persona 名两种写法（无空格权威名 / 带空格历史写法）都必须能归一。
"""

from __future__ import annotations

import pytest

from core.services.active_care.peer_chat.negotiation_parser import (
    _safe_parse_assignments as _safe_parse_negotiation,
    build_reminder_list_text,
    parse_assignments_from_script,
)
from core.services.active_care.peer_chat.proactive_assignment_parser import (
    _safe_parse_assignments as _safe_parse_proactive,
    build_slot_list_text,
    parse_proactive_assignment_from_script,
)


# ============================================================
# negotiation_parser —— 提醒分工
# ============================================================

class TestParseAssignmentsFromScript:
    """提醒分工解析：标签块 / 兜底 / 容错。"""

    def test_parses_tagged_block(self):
        """标准 <assignment> 块能解析出完整分工。"""
        raw = (
            "Ling：今天那条复习提醒要发吗？\n"
            "Aveline：我来发吧，我熟。\n"
            "<assignment>\n"
            '{"assignments": [\n'
            '  {"reminder_id": "study:review_due", "assigned_to": "aveline",'
            ' "reason": "Aveline 学科背景更适合"},\n'
            '  {"reminder_id": "task:xxx", "assigned_to": "ling",'
            ' "reason": "Ling 跟进过这个任务"}\n'
            "]}\n"
            "</assignment>\n"
        )
        result = parse_assignments_from_script(raw)

        assert len(result) == 2
        assert result[0]["reminder_id"] == "study:review_due"
        assert result[0]["assigned_to"] == "aveline"
        assert result[0]["reason"] == "Aveline 学科背景更适合"
        assert result[1]["assigned_to"] == "ling"

    def test_tag_block_is_case_insensitive(self):
        """标签大小写不敏感（LLM 有时会大写）。"""
        raw = '<ASSIGNMENT>{"assignments": [{"reminder_id": "r1", "assigned_to": "ling"}]}</ASSIGNMENT>'
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["assigned_to"] == "ling"

    def test_falls_back_to_bare_json(self):
        """没有标签时走兜底裸 JSON 匹配。"""
        raw = 'Aveline：那我发这条。\n{"assignments": [{"reminder_id": "r9", "assigned_to": "aveline"}]}\n'
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["reminder_id"] == "r9"
        assert result[0]["assigned_to"] == "aveline"

    def test_tagged_block_wins_over_bare_json(self):
        """标签块优先于兜底块（两者共存时取标签块）。"""
        raw = (
            '{"assignments": [{"reminder_id": "bare", "assigned_to": "ling"}]}\n'
            '<assignment>{"assignments": [{"reminder_id": "tagged", "assigned_to": "aveline"}]}</assignment>'
        )
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["reminder_id"] == "tagged"

    def test_bare_list_inside_tag_is_not_supported(self):
        """已知限制：标签内直接写裸列表不会被识别。

        ``_ASSIGNMENT_PATTERN`` 的分组是 ``(\\{.*?\\})``，要求块以 ``{`` 开头；
        而 ``_FALLBACK_JSON_PATTERN`` 同样要求 ``{``。所以
        ``_safe_parse_assignments`` 里 ``isinstance(data, list)`` 那条分支
        在当前的标签/兜底两条路径下都走不到。

        这里锁定现状而不是"修正"它：prompt 明确要求 LLM 输出
        ``{"assignments": [...]}`` 结构，裸列表属离规范输入，为此放宽正则会
        扩大匹配面（非贪婪 ``\\[.*?\\]`` 遇到嵌套方括号会误截断），风险大于收益。
        若将来确实出现裸列表，应改 prompt 而不是改这里。
        """
        raw = '<assignment>[{"reminder_id": "r1", "assigned_to": "aveline"}]</assignment>'

        assert parse_assignments_from_script(raw) == []

    def test_empty_input_returns_empty(self):
        """空输入返回空列表，不抛异常。"""
        assert parse_assignments_from_script("") == []
        assert parse_assignments_from_script(None) == []

    def test_no_json_block_returns_empty(self):
        """找不到任何 JSON 块时返回空列表（调用方走先到先得兜底）。"""
        raw = "Ling：今天没什么要发的吧。\nAveline：嗯，就这样。"
        assert parse_assignments_from_script(raw) == []

    def test_malformed_json_returns_empty(self):
        """JSON 语法错误且无法修复时返回空列表。"""
        raw = "<assignment>{not valid json at all}</assignment>"
        assert parse_assignments_from_script(raw) == []

    def test_dict_without_assignments_key_returns_empty(self):
        """JSON 是合法 dict 但没有 assignments 列表时返回空列表。"""
        raw = '<assignment>{"foo": "bar"}</assignment>'
        assert parse_assignments_from_script(raw) == []

    def test_trailing_comma_is_repaired(self):
        """尾随逗号能被修复（LLM 常见错误）。"""
        raw = (
            "<assignment>"
            '{"assignments": [{"reminder_id": "r1", "assigned_to": "ling"},]}'
            "</assignment>"
        )
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["reminder_id"] == "r1"

    def test_single_quotes_are_repaired(self):
        """纯单引号 JSON 能被修复。"""
        raw = "<assignment>{'assignments': [{'reminder_id': 'r1', 'assigned_to': 'ling'}]}</assignment>"
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["assigned_to"] == "ling"

    def test_unknown_persona_is_dropped(self):
        """未知 assigned_to 的条目被丢弃，不污染分工表。"""
        raw = (
            "<assignment>"
            '{"assignments": ['
            '{"reminder_id": "r1", "assigned_to": "Ye"},'
            '{"reminder_id": "r2", "assigned_to": "ling"}'
            "]}</assignment>"
        )
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["reminder_id"] == "r2"

    def test_missing_required_fields_are_dropped(self):
        """缺 reminder_id 或 assigned_to 的条目被丢弃。"""
        raw = (
            "<assignment>"
            '{"assignments": ['
            '{"assigned_to": "ling"},'
            '{"reminder_id": "r2"},'
            '{"reminder_id": "r3", "assigned_to": "ling"}'
            "]}</assignment>"
        )
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["reminder_id"] == "r3"

    def test_non_dict_entries_are_dropped(self):
        """列表里混入非 dict 元素时跳过而不是崩。"""
        raw = (
            '<assignment>{"assignments": ["字符串", 123, '
            '{"reminder_id": "r1", "assigned_to": "ling"}]}</assignment>'
        )
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["reminder_id"] == "r1"

    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("aveline", "aveline"),
            ("AVELINE", "aveline"),
            ("Aveline", "aveline"),
            ("七濑 Aveline", "aveline"),
            ("Aveline", "aveline"),
            ("ling", "ling"),
            ("LING", "ling"),
            ("Ling", "ling"),
            ("ling", "ling"),
        ],
    )
    def test_persona_aliases_normalize(self, alias, expected):
        """两种写法 + 大小写都要归一到 role_id（改名兼容性的核心保证）。"""
        raw = f'<assignment>{{"assignments": [{{"reminder_id": "r1", "assigned_to": "{alias}"}}]}}</assignment>'
        result = parse_assignments_from_script(raw)

        assert len(result) == 1
        assert result[0]["assigned_to"] == expected

    def test_missing_reason_defaults_to_empty(self):
        """reason 缺失时补空串，保证下游键一定存在。"""
        raw = '<assignment>{"assignments": [{"reminder_id": "r1", "assigned_to": "ling"}]}</assignment>'
        result = parse_assignments_from_script(raw)

        assert result[0]["reason"] == ""

    def test_whitespace_is_stripped(self):
        """字段两侧空白被剔除。"""
        raw = (
            '<assignment>{"assignments": ['
            '{"reminder_id": "  r1  ", "assigned_to": "  LING  ", "reason": "  原因  "}'
            "]}</assignment>"
        )
        result = parse_assignments_from_script(raw)

        assert result[0]["reminder_id"] == "r1"
        assert result[0]["assigned_to"] == "ling"
        assert result[0]["reason"] == "原因"

    def test_non_string_reminder_id_is_coerced(self):
        """数字类型的 reminder_id 被转成字符串。"""
        raw = '<assignment>{"assignments": [{"reminder_id": 12345, "assigned_to": "ling"}]}</assignment>'
        result = parse_assignments_from_script(raw)

        assert result[0]["reminder_id"] == "12345"


class TestBuildReminderListText:
    """待发提醒 → prompt 文本。"""

    def test_empty_reminders_placeholder(self):
        """空列表给出明确占位文案，避免 prompt 里出现空白段。"""
        assert build_reminder_list_text([]) == "（今日暂无待发提醒）"

    def test_numbered_lines(self):
        """多项提醒按序号排列，格式为 ``N. [id] title``。"""
        text = build_reminder_list_text(
            [
                {"reminder_id": "study:review_due", "title": "学习复习提醒：3个知识点到期"},
                {"reminder_id": "task:xxx", "title": "跟进任务：xxx"},
            ]
        )
        lines = text.splitlines()

        assert len(lines) == 2
        assert lines[0] == "1. [study:review_due] 学习复习提醒：3个知识点到期"
        assert lines[1] == "2. [task:xxx] 跟进任务：xxx"

    def test_missing_fields_do_not_crash(self):
        """缺字段时用空串占位，不抛 KeyError。"""
        text = build_reminder_list_text([{}])

        assert text == "1. [] "


# ============================================================
# proactive_assignment_parser —— 主动关怀时段分工
# ============================================================

class TestParseProactiveAssignmentFromScript:
    """时段分工解析：时段校验 + persona 归一。"""

    def test_parses_tagged_block(self):
        """标准 <proactive_assignment> 块能解析出三个时段分工。"""
        raw = (
            "Aveline：那我们分一下。\n"
            "<proactive_assignment>\n"
            '{"assignments": [\n'
            '  {"time_slot": "morning", "lead": "aveline", "reason": "Aveline 上午精神好"},\n'
            '  {"time_slot": "afternoon", "lead": "ling", "reason": "Ling 下午有空"},\n'
            '  {"time_slot": "evening", "lead": "aveline", "reason": "Aveline 晚上更适合陪主人"}\n'
            "]}\n"
            "</proactive_assignment>\n"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 3
        assert [r["time_slot"] for r in result] == ["morning", "afternoon", "evening"]
        assert result[0]["lead"] == "aveline"
        assert result[1]["lead"] == "ling"

    def test_tag_is_case_insensitive(self):
        """标签大小写不敏感。"""
        raw = (
            '<PROACTIVE_ASSIGNMENT>{"assignments": ['
            '{"time_slot": "evening", "lead": "ling"}]}</PROACTIVE_ASSIGNMENT>'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["lead"] == "ling"

    def test_falls_back_to_bare_json(self):
        """无标签时走兜底裸 JSON（要求含 time_slot / lead 特征）。"""
        raw = (
            "Aveline：分好了。\n"
            '{"assignments": [{"time_slot": "morning", "lead": "ling", "reason": "早上她起得来"}]}\n'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["time_slot"] == "morning"

    def test_empty_input_returns_empty(self):
        """空输入返回空列表。"""
        assert parse_proactive_assignment_from_script("") == []
        assert parse_proactive_assignment_from_script(None) == []

    def test_no_block_returns_empty(self):
        """找不到块时返回空列表（调用方走轮流制兜底）。"""
        assert parse_proactive_assignment_from_script("Aveline：随便聊聊吧。") == []

    def test_invalid_slot_is_dropped(self):
        """非法时段名被丢弃（防止写入不存在的时段）。"""
        raw = (
            "<proactive_assignment>"
            '{"assignments": ['
            '{"time_slot": "midnight", "lead": "aveline"},'
            '{"time_slot": "morning", "lead": "ling"}'
            "]}</proactive_assignment>"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["time_slot"] == "morning"

    @pytest.mark.parametrize("slot", ["morning", "afternoon", "evening"])
    def test_all_valid_slots_accepted(self, slot):
        """三个合法时段都要被接受。"""
        raw = (
            f'<proactive_assignment>{{"assignments": ['
            f'{{"time_slot": "{slot}", "lead": "ling"}}]}}</proactive_assignment>'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["time_slot"] == slot

    def test_unknown_lead_is_dropped(self):
        """未知 lead 被丢弃。"""
        raw = (
            "<proactive_assignment>"
            '{"assignments": ['
            '{"time_slot": "morning", "lead": "Ye"},'
            '{"time_slot": "evening", "lead": "ling"}'
            "]}</proactive_assignment>"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["time_slot"] == "evening"

    def test_alternative_field_names_accepted(self):
        """slot/assigned_to/persona 这些别名字段也接受。"""
        raw = (
            "<proactive_assignment>"
            '{"assignments": [{"slot": "afternoon", "persona": "aveline"}]}'
            "</proactive_assignment>"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["time_slot"] == "afternoon"
        assert result[0]["lead"] == "aveline"

    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("aveline", "aveline"),
            ("Aveline", "aveline"),
            ("七濑 Aveline", "aveline"),
            ("Aveline", "aveline"),
            ("ling", "ling"),
            ("Ling", "ling"),
            ("ling", "ling"),
        ],
    )
    def test_persona_aliases_normalize(self, alias, expected):
        """两种写法都要归一到 role_id（改名兼容性保证）。"""
        raw = (
            f'<proactive_assignment>{{"assignments": ['
            f'{{"time_slot": "morning", "lead": "{alias}"}}]}}</proactive_assignment>'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["lead"] == expected

    def test_substring_alias_match(self):
        """名字里含别名片段时也能匹配（如 "Aveline：" 带标点）。"""
        raw = (
            "<proactive_assignment>"
            '{"assignments": [{"time_slot": "morning", "lead": "Aveline（Aveline）"}]}'
            "</proactive_assignment>"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["lead"] == "aveline"

    def test_trailing_comma_is_repaired(self):
        """尾随逗号能被修复。"""
        raw = (
            "<proactive_assignment>"
            '{"assignments": [{"time_slot": "morning", "lead": "ling"},]}'
            "</proactive_assignment>"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["lead"] == "ling"

    def test_single_quotes_are_repaired(self):
        """纯单引号 JSON 能被修复（覆盖 _fix_common_json_errors 的引号替换分支）。"""
        raw = (
            "<proactive_assignment>"
            "{'assignments': [{'time_slot': 'morning', 'lead': 'ling'}]}"
            "</proactive_assignment>"
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["lead"] == "ling"

    def test_unrepairable_json_returns_empty(self):
        """修复后仍不是合法 JSON 时返回空列表（不抛异常）。"""
        raw = "<proactive_assignment>{{ not json }}</proactive_assignment>"
        assert parse_proactive_assignment_from_script(raw) == []

    def test_dict_without_assignments_key_returns_empty(self):
        """JSON 是合法 dict 但没有 assignments 列表时返回空列表。"""
        raw = '<proactive_assignment>{"foo": "bar"}</proactive_assignment>'
        assert parse_proactive_assignment_from_script(raw) == []

    def test_non_dict_entries_are_dropped(self):
        """列表里混入非 dict 元素时跳过，其余条目照常解析。"""
        raw = (
            '<proactive_assignment>{"assignments": [null, "x", '
            '{"time_slot": "evening", "lead": "ling"}]}</proactive_assignment>'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert len(result) == 1
        assert result[0]["time_slot"] == "evening"

    def test_reason_missing_defaults_to_empty(self):
        """reason 缺失补空串。"""
        raw = (
            '<proactive_assignment>{"assignments": ['
            '{"time_slot": "morning", "lead": "ling"}]}</proactive_assignment>'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert result[0]["reason"] == ""

    def test_slot_and_lead_are_lowercased(self):
        """时段名与 lead 统一转小写后再校验/归一。"""
        raw = (
            '<proactive_assignment>{"assignments": ['
            '{"time_slot": "  MORNING  ", "lead": "  LING  "}]}</proactive_assignment>'
        )
        result = parse_proactive_assignment_from_script(raw)

        assert result[0]["time_slot"] == "morning"
        assert result[0]["lead"] == "ling"


class TestBuildSlotListText:
    """时段列表 prompt 文本。"""

    def test_contains_three_slots(self):
        """三个时段都要出现在 prompt 文本里，且带时间范围说明。"""
        text = build_slot_list_text()
        lines = text.splitlines()

        assert len(lines) == 3
        assert "morning" in lines[0] and "06:00-12:00" in lines[0]
        assert "afternoon" in lines[1] and "12:00-18:00" in lines[1]
        assert "evening" in lines[2] and "18:00-24:00" in lines[2]


# ============================================================
# _safe_parse_assignments —— 两个解析器共用的私有 JSON 入口
# ============================================================

class TestSafeParseAssignmentsContract:
    """直接校验两个模块级私有 helper 的文档化契约。

    公开入口 ``parse_*_from_script`` 只把 ``{`` 开头的片段喂给 helper
    （两条正则都要求 ``{``），因此 ``isinstance(data, list)`` 那条分支
    走不到（见 ``test_bare_list_inside_tag_is_not_supported`` 的说明）。

    但两个 helper 的 docstring 明确写了「形如 {"assignments": [...]}
    **或直接 [...]**」，裸列表是它们自己声明的输入形态。这里按契约直接调用
    helper 覆盖该分支：既锁住 helper 的对外行为，也不动公开路径的正则。
    """

    @pytest.mark.parametrize(
        "helper, payload, expected_key, expected_value",
        [
            (
                _safe_parse_negotiation,
                '[{"reminder_id": "r1", "assigned_to": "aveline"}]',
                "reminder_id",
                "r1",
            ),
            (
                _safe_parse_proactive,
                '[{"time_slot": "morning", "lead": "aveline"}]',
                "time_slot",
                "morning",
            ),
        ],
        ids=["negotiation", "proactive"],
    )
    def test_bare_list_is_normalized(self, helper, payload, expected_key, expected_value):
        """裸列表输入按契约被规范化，而不是被丢弃。"""
        result = helper(payload)

        assert len(result) == 1
        assert result[0][expected_key] == expected_value

    @pytest.mark.parametrize(
        "helper, payload, expected_key, expected_value",
        [
            (
                _safe_parse_negotiation,
                '{"assignments": [{"reminder_id": "r2", "assigned_to": "ling"}]}',
                "reminder_id",
                "r2",
            ),
            (
                _safe_parse_proactive,
                '{"assignments": [{"time_slot": "evening", "lead": "ling"}]}',
                "time_slot",
                "evening",
            ),
        ],
        ids=["negotiation", "proactive"],
    )
    def test_dict_form_still_works(self, helper, payload, expected_key, expected_value):
        """对象形态（``{"assignments": [...]}``）不受影响。"""
        result = helper(payload)

        assert len(result) == 1
        assert result[0][expected_key] == expected_value

    @pytest.mark.parametrize(
        "helper",
        [_safe_parse_negotiation, _safe_parse_proactive],
        ids=["negotiation", "proactive"],
    )
    def test_scalar_json_returns_empty(self, helper):
        """标量 JSON 既不是列表也不是对象，返回空列表。"""
        assert helper("42") == []
        assert helper('"just a string"') == []
        assert helper("null") == []
