# -*- coding: utf-8 -*-
"""peer_chat 知识防火墙测试（peer_knowledge.py）。

覆盖 core/services/active_care/peer_chat/peer_knowledge.py 的：
- filter_secret_lines：主人私聊素材里的保密行剔除（逐行，不整段丢弃）
- _observable_desc / _private_desc：可观察状态 vs 内部状态的分层描述
- build_knowledge_buckets：按信息权限拆分成"谁知道什么"
- validate_peer_script：剧本级越权/泄漏检查

为什么这个模块重要：它挡的是 peer chat 的"两个角色共用一个数据库脑子"
（epistemic leakage）。一旦分桶或校验失效，表现是角色说出它本不该知道的事
（对方的精力/心情、主人明确要求保密的内容），这类问题在聊天记录里很难被察觉。

设计要点：
- 全部是纯函数，无外部依赖，不需要替身；
- 断言集中在"哪些信息进了哪个桶"和"哪些内容触发违规"这两类确定性质上。
"""

from __future__ import annotations

import pytest

from core.services.active_care.peer_chat.peer_knowledge import (
    build_knowledge_buckets,
    filter_secret_lines,
    validate_peer_script,
)


# ============================================================
# filter_secret_lines
# ============================================================

class TestFilterSecretLines:
    """保密行剔除：逐行过滤，保留其余内容。"""

    def test_empty_input_returns_empty(self):
        """空输入返回空串。"""
        assert filter_secret_lines("") == ""
        assert filter_secret_lines(None) == ""
        assert filter_secret_lines("   ") == ""

    def test_plain_text_passes_through(self):
        """无保密信号时原样保留。"""
        text = "今天去图书馆了\n买了新耳机"

        assert filter_secret_lines(text) == text

    @pytest.mark.parametrize(
        "marker",
        [
            "先别告诉",
            "别告诉",
            "不要告诉",
            "别告诉她",
            "别告诉他",
            "别跟她说",
            "别跟他说",
            "别和别人说",
            "保密",
            "只告诉你",
            "悄悄",
            "偷偷",
            "这是我们之间",
            "别说出去",
        ],
    )
    def test_secret_line_is_dropped(self, marker):
        """命中任一保密信号的整行被剔除。"""
        text = f"今天心情不错\n这件事{marker}啊\n晚上想吃火锅"
        result = filter_secret_lines(text)

        assert marker not in result
        assert "今天心情不错" in result
        assert "晚上想吃火锅" in result

    def test_only_remaining_lines_are_kept(self):
        """只剔除命中行，同段其余行完整保留（不整段丢弃）。"""
        text = "第一行正常\n第二行保密\n第三行正常"
        result = filter_secret_lines(text)

        assert result == "第一行正常\n第三行正常"

    def test_all_secret_returns_empty(self):
        """全部命中时返回空串（调用方据此判定素材为空）。"""
        text = "这个保密\n那个也别告诉别人"

        assert filter_secret_lines(text) == ""

    def test_single_line_without_newline(self):
        """单行输入也能正确判定。"""
        assert filter_secret_lines("这件事保密") == ""
        assert filter_secret_lines("普通一句话") == "普通一句话"


# ============================================================
# 可观察 / 内部状态分层
# ============================================================

class TestObservableAndPrivateDesc:
    """分层描述：可观察（活动/生病）vs 内部（精力/心情/饥饿）。"""

    def test_observable_activity_is_described(self):
        """当前活动对室友可观察。"""
        from core.services.active_care.peer_chat.peer_knowledge import _observable_desc

        assert _observable_desc({"life": {"current_activity": "看书"}}) == "在看书"

    @pytest.mark.parametrize("placeholder", ["unknown", "idle", "none", "UNKNOWN", ""])
    def test_placeholder_activity_is_skipped(self, placeholder):
        """占位活动名不产生描述（否则会说"在unknown"）。"""
        from core.services.active_care.peer_chat.peer_knowledge import _observable_desc

        assert _observable_desc({"life": {"current_activity": placeholder}}) == ""

    def test_observable_sick_is_described(self):
        """生病对室友可观察。"""
        from core.services.active_care.peer_chat.peer_knowledge import _observable_desc

        assert _observable_desc({"life": {"is_sick": True}}) == "身体不太舒服"

    def test_observable_activity_and_sick_combined(self):
        """活动与生病同时存在时用中文逗号拼接。"""
        from core.services.active_care.peer_chat.peer_knowledge import _observable_desc

        result = _observable_desc(
            {"life": {"current_activity": "躺着", "is_sick": True}}
        )

        assert result == "在躺着，身体不太舒服"

    def test_observable_accepts_flat_bio_state(self):
        """旧结构（life 平铺）也要兼容。"""
        from core.services.active_care.peer_chat.peer_knowledge import _observable_desc

        assert _observable_desc({"current_activity": "跑步"}) == "在跑步"

    def test_observable_non_dict_returns_empty(self):
        """非 dict 输入返回空串而不是崩。"""
        from core.services.active_care.peer_chat.peer_knowledge import _observable_desc

        assert _observable_desc("not-a-dict") == ""
        assert _observable_desc(None) == ""

    @pytest.mark.parametrize(
        "energy,expected",
        [
            (10, "很累"),
            (19.9, "很累"),
            (20, "有点疲惫"),
            (49.9, "有点疲惫"),
            (50, ""),
            (80, ""),
            (80.1, "精力不错"),
            (95, "精力不错"),
        ],
    )
    def test_private_energy_buckets(self, energy, expected):
        """精力分档边界：<20 很累 / <50 有点疲惫 / >80 精力不错。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        assert _private_desc({"life": {"energy": energy}}) == expected

    def test_private_energy_default_when_missing(self):
        """精力字段缺失时用默认值 50（落在"无描述"档，不误报）。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        assert _private_desc({"life": {}}) == ""

    def test_private_mood_is_described(self):
        """心情作为内部状态被描述。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        assert _private_desc({"life": {"energy": 50, "mood": "开心"}}) == "心情开心"

    @pytest.mark.parametrize(
        "placeholder", ["neutral", "normal", "unknown", "none", "NEUTRAL", ""]
    )
    def test_private_mood_placeholders_skipped(self, placeholder):
        """占位心情值不产生描述。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        assert _private_desc({"life": {"energy": 50, "mood": placeholder}}) == ""

    def test_private_mood_score_fallback(self):
        """mood 缺失时回退到 mood_score 字段。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        result = _private_desc({"life": {"energy": 50, "mood_score": "低落"}})

        assert result == "心情低落"

    @pytest.mark.parametrize(
        "hunger,expected",
        [(10, "很饿"), (29.9, "很饿"), (30, "有点饿了"), (59.9, "有点饿了"), (60, "")],
    )
    def test_private_hunger_buckets(self, hunger, expected):
        """饥饿分档边界：<30 很饿 / <60 有点饿了。

        注意 hunger 语义是"饱腹度"（越大越不饿），所以默认值是 100。
        """
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        assert _private_desc({"life": {"energy": 50, "hunger": hunger}}) == expected

    def test_private_hunger_default_is_not_hungry(self):
        """饥饿字段缺失时默认 100（不饿），不产生误报。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        assert _private_desc({"life": {"energy": 50}}) == ""

    def test_private_invalid_values_use_defaults(self):
        """非数值字段回退到默认值而不是崩。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        result = _private_desc(
            {"life": {"energy": "bad", "hunger": "bad", "mood": ""}}
        )

        assert result == ""

    def test_private_combined_fields(self):
        """多个内部状态按固定顺序拼接。"""
        from core.services.active_care.peer_chat.peer_knowledge import _private_desc

        result = _private_desc(
            {"life": {"energy": 10, "mood": "烦躁", "hunger": 20}}
        )

        assert result == "很累，心情烦躁，很饿"


# ============================================================
# build_knowledge_buckets
# ============================================================

class TestBuildKnowledgeBuckets:
    """知识分桶：谁可以看到什么。"""

    def _build(self, **overrides):
        kwargs = {
            "role_id": "aveline",
            "peer_role_id": "ling",
            "role_name": "Aveline",
            "peer_name": "Ling",
            "bio_state": {"life": {"energy": 90, "current_activity": "看书"}},
            "peer_bio_state": {"life": {"energy": 10, "current_activity": "做饭"}},
            "master_history_by_role": {
                "aveline": "主人说要买显示器",
                "ling": "主人说要买键盘",
            },
            "time_str": "2026-09-23 04:20",
        }
        kwargs.update(overrides)
        return build_knowledge_buckets(**kwargs)

    def test_returns_all_expected_keys(self):
        """返回结构必须含全部键，缺键会让 prompt 组装 KeyError。"""
        result = self._build()

        assert set(result) == {
            "time_str",
            "shared_context",
            "role",
            "peer",
            "role_id",
            "peer_role_id",
        }
        assert set(result["role"]) == {
            "private_state",
            "known_about_peer",
            "master_material",
        }
        assert set(result["peer"]) == {
            "private_state",
            "known_about_peer",
            "master_material",
        }

    def test_role_ids_are_echoed(self):
        """role_id / peer_role_id 回显，供 Validator 判断说话者。"""
        result = self._build()

        assert result["role_id"] == "aveline"
        assert result["peer_role_id"] == "ling"

    def test_time_is_in_shared_context(self):
        """时间属于双方共同可见的公共事实。"""
        result = self._build()

        assert "当前时间：2026-09-23 04:20" in result["shared_context"]

    def test_observable_activities_are_shared(self):
        """双方正在做什么是可观察公共事实（住在一起）。"""
        result = self._build()
        shared = result["shared_context"]

        assert "你看到Ling：在做饭" in shared
        assert "Ling看到你：在看书" in shared

    def test_private_state_does_not_leak_into_shared(self):
        """内部状态（精力/心情）绝不能进公共上下文。"""
        result = self._build()

        assert "精力不错" not in result["shared_context"]
        assert "很累" not in result["shared_context"]

    def test_each_side_gets_own_private_state(self):
        """各自只看到自己的内部状态。"""
        result = self._build()

        assert result["role"]["private_state"] == "精力不错"
        assert result["peer"]["private_state"] == "很累"

    def test_known_about_peer_is_observable_only(self):
        """"我知道对方什么"只包含可观察信息，不含对方内部状态。"""
        result = self._build()

        assert result["role"]["known_about_peer"] == "在做饭"
        assert result["peer"]["known_about_peer"] == "在看书"

    def test_master_material_is_per_role(self):
        """主人私聊素材按角色分桶，互不串味。"""
        result = self._build()

        assert result["role"]["master_material"] == "主人说要买显示器"
        assert result["peer"]["master_material"] == "主人说要买键盘"

    def test_secret_lines_are_filtered_per_role(self):
        """保密行在进桶前就被剔除。"""
        result = self._build(
            master_history_by_role={
                "aveline": "主人说要买显示器\n这事先别告诉Ling",
                "ling": "主人说要买键盘",
            }
        )

        assert "先别告诉" not in result["role"]["master_material"]
        assert "主人说要买显示器" in result["role"]["master_material"]

    def test_missing_master_material_yields_empty(self):
        """某角色没有素材时该桶为空串，不抛 KeyError。"""
        result = self._build(master_history_by_role={"aveline": "只有我的"})

        assert result["role"]["master_material"] == "只有我的"
        assert result["peer"]["master_material"] == ""

    def test_empty_time_str_omits_time_segment(self):
        """无时间字符串时不产生时间段。"""
        result = self._build(time_str="")

        assert result["time_str"] == ""
        assert "当前时间" not in result["shared_context"]

    def test_no_observable_activity_yields_empty_shared(self):
        """双方都无可观察状态且无时间时，公共上下文为空串。"""
        result = self._build(
            bio_state={"life": {"energy": 50}},
            peer_bio_state={"life": {"energy": 50}},
            time_str="",
        )

        assert result["shared_context"] == ""

    def test_non_dict_bio_states_do_not_crash(self):
        """非 dict 的生理状态安全降级。"""
        result = self._build(bio_state=None, peer_bio_state="bad")

        assert result["role"]["private_state"] == ""
        assert result["peer"]["private_state"] == ""
        assert result["shared_context"].startswith("当前时间")


# ============================================================
# validate_peer_script
# ============================================================

class TestValidatePeerScript:
    """剧本校验：越权 / 隐私泄漏。"""

    def _knowledge(self, **overrides):
        base = {
            "role_id": "aveline",
            "peer_role_id": "ling",
            "role": {"private_state": "精力不错", "known_about_peer": "在做饭"},
            "peer": {"private_state": "很累", "known_about_peer": "在看书"},
        }
        base.update(overrides)
        return base

    def test_empty_script_passes(self):
        """空剧本无违规。"""
        assert validate_peer_script([], self._knowledge()) == []
        assert validate_peer_script(None, self._knowledge()) == []

    def test_clean_script_passes(self):
        """无越权内容的剧本通过校验。"""
        script = [
            {"role": "aveline", "content": "今天晚饭吃什么"},
            {"role": "ling", "content": "随便，你想吃啥"},
        ]

        assert validate_peer_script(script, self._knowledge()) == []

    def test_speaker_mentioning_peer_private_state_is_violation(self):
        """角色提到对方的私有状态（对方很累）→ 越权。"""
        script = [
            {"role": "aveline", "content": "你今天是不是很累啊"},
        ]
        violations = validate_peer_script(script, self._knowledge())

        assert len(violations) == 1
        assert "越权" in violations[0]
        assert "很累" in violations[0]

    def test_speaker_may_mention_own_private_state(self):
        """角色说自己的内部状态不违规（自己当然知道）。"""
        script = [
            {"role": "ling", "content": "我今天有点疲惫"},
        ]

        assert validate_peer_script(script, self._knowledge()) == []

    def test_known_observable_state_is_not_violation(self):
        """对方可观察到的信息不构成越权。

        这里让 peer 的私有描述与"role 已知对方"的描述都含"很累"，
        表示这件事本来就可观察，说出来不算越权。
        """
        knowledge = self._knowledge()
        knowledge["role"]["known_about_peer"] = "在做饭，很累"
        script = [{"role": "aveline", "content": "你很累吧"}]

        assert validate_peer_script(script, knowledge) == []

    def test_secrecy_signal_in_script_is_violation(self):
        """剧本里出现保密信号 → 隐私风险。"""
        script = [
            {"role": "aveline", "content": "这件事你别告诉他"},
        ]
        violations = validate_peer_script(script, self._knowledge())

        assert len(violations) == 1
        assert "隐私风险" in violations[0]

    @pytest.mark.parametrize(
        "marker",
        ["别告诉", "别和别人说", "保密", "只告诉你", "别跟", "不要告诉"],
    )
    def test_each_secrecy_marker_detected(self, marker):
        """每个保密信号都要被识别。"""
        script = [{"role": "aveline", "content": f"这件事{marker}啊"}]

        assert len(validate_peer_script(script, self._knowledge())) == 1

    def test_empty_content_lines_are_skipped(self):
        """空内容行不参与校验（不误报）。"""
        script = [
            {"role": "aveline", "content": ""},
            {"role": "ling", "content": "   "},
        ]

        assert validate_peer_script(script, self._knowledge()) == []

    def test_violation_message_contains_line_number(self):
        """违规信息带行号，便于定位（第 N 条）。"""
        script = [
            {"role": "aveline", "content": "正常一句"},
            {"role": "aveline", "content": "你是不是很累"},
        ]
        violations = validate_peer_script(script, self._knowledge())

        assert len(violations) == 1
        assert "第2条" in violations[0]

    def test_role_ids_from_knowledge_used_when_not_passed(self):
        """未显式传 role_id 时从 knowledge 里取。"""
        script = [{"role": "aveline", "content": "你今天是不是很累"}]

        assert len(validate_peer_script(script, self._knowledge())) == 1

    def test_explicit_role_ids_override_knowledge(self):
        """显式传入的 role_id 优先于 knowledge 里的值。"""
        script = [{"role": "aveline", "content": "你今天是不是很累"}]
        violations = validate_peer_script(
            script, self._knowledge(), role_id="aveline", peer_role_id="ling"
        )

        assert len(violations) == 1

    def test_empty_private_desc_skips_check(self):
        """对方没有私有描述时不触发越权判定（无可泄漏内容）。"""
        knowledge = self._knowledge()
        knowledge["peer"]["private_state"] = ""
        script = [{"role": "aveline", "content": "你很累吧"}]

        assert validate_peer_script(script, knowledge) == []

    def test_empty_knowledge_does_not_crash(self):
        """knowledge 为空 dict 时安全返回。"""
        assert validate_peer_script([{"role": "a", "content": "x"}], {}) == []

    def test_both_violation_types_can_coexist(self):
        """同一条内容既越权又含保密信号时，两类违规都报出。"""
        knowledge = self._knowledge()
        # 让越权判定成立：对方私有含"很累"，而已知对方里没有
        script = [{"role": "aveline", "content": "你很累吧，这事别告诉他"}]
        violations = validate_peer_script(script, knowledge)

        assert len(violations) == 2
        kinds = " ".join(violations)
        assert "越权" in kinds
        assert "隐私风险" in kinds
