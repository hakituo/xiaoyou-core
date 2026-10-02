# -*- coding: utf-8 -*-
"""双角色互识关系隔离语义测试（T2 必测项）。

背景：``knows_role`` / ``resolve_role_id`` 是整套"关系感知"架构的唯一判据 —— 凡是要把
A 的信息交给 B 的地方（同伴关系行、人物档案、记忆 scope、生日…）都先问它。历史上出过
"角色凭空认识另一个角色"的 OOC：未注册互识关系的单角色被拉进互聊、或解析不出当前是谁时
猜了一个角色顶上，把别人的信息喂给当前角色。

因此这里锁死两条不变量：
1. ``knows_role(viewer, target)``：只有自己与注册表里登记了互识关系的 peer 才返回 True；
   单角色（ye / lin / yeye / rushuang）对任何人必须返回 False。
2. ``resolve_role_id`` 认不出时必须返回空串，绝不猜默认值。

当前只有 aveline ↔ ling 一对互识（以 personas.ROOMMATE_RELATIONS 为准），
新增互聊关系时本测试的"单角色"参数化列表需要同步复核。
"""

from __future__ import annotations

import pytest

from core.services.dual_role import personas

# 未注册互识关系的单角色（对任何人都不该"认识"）
SINGLE_ROLE_IDS = ("ye", "lin", "yeye", "rushuang")

# 已注册双向互识关系的角色对
PEER_ROLE_IDS = ("aveline", "ling")


class TestKnowsRoleIsolation:
    """knows_role 的隔离语义：单角色对任何人返回 False。"""

    @pytest.mark.parametrize("viewer", SINGLE_ROLE_IDS)
    @pytest.mark.parametrize("target", (*PEER_ROLE_IDS, *SINGLE_ROLE_IDS))
    def test_single_role_knows_nobody_including_itself_peers(self, viewer, target):
        """单角色对**任何人**都不认识（包括 aveline/ling 与其他单角色）。

        这条是防 OOC 的核心：Ye（ye）不该知道Aveline的档案，Frost不该被拉进Aveline/Ling的互聊。
        """
        if viewer == target:
            pytest.skip("viewer == target 由 self-knowledge 用例单独覆盖")
        assert personas.knows_role(viewer, target) is False

    @pytest.mark.parametrize("role_id", (*PEER_ROLE_IDS, *SINGLE_ROLE_IDS))
    def test_role_always_knows_itself(self, role_id):
        """任何角色（含单角色）都必须认识自己 —— 自己看自己的信息永远合法。"""
        assert personas.knows_role(role_id, role_id) is True

    @pytest.mark.parametrize("a, b", [("aveline", "ling"), ("ling", "aveline")])
    def test_registered_peer_pair_knows_each_other(self, a, b):
        """aveline ↔ ling 是当前唯一注册的互识对，双向都必须为 True。"""
        assert personas.knows_role(a, b) is True

    @pytest.mark.parametrize(
        "viewer, target",
        [
            ("", ""),
            ("aveline", ""),
            ("", "ling"),
            ("   ", "ling"),
            (None, "ling"),
            ("aveline", None),
        ],
    )
    def test_empty_inputs_never_know(self, viewer, target):
        """空 / 空白 / None 入参一律返回 False，不得因为归一化退化成"认识所有人"。"""
        assert personas.knows_role(viewer, target) is False

    def test_case_and_whitespace_are_normalized(self):
        """大小写与首尾空白需归一化，不能因此漏判互识关系。"""
        assert personas.knows_role("  AVELINE  ", "Ling") is True
        assert personas.knows_role("ling", " Aveline ") is True


class TestResolveRoleIdRefusesToGuess:
    """resolve_role_id 认不出时返回空串，绝不猜默认值。"""

    @pytest.mark.parametrize(
        "garbage",
        ["", "   ", None, "某个不存在的角色", "unknown_role", "???"],
    )
    def test_unknown_reference_returns_empty_string(self, garbage):
        """无法识别的引用必须返回空串。

        与 resolve_role_id_from_persona（兼容旧调用方、兜底 aveline）不同：
        本函数用于"必须知道当前是谁"的场景，猜一个角色顶上等于把别人的信息
        喂给当前角色，属于严重串味。
        """
        assert personas.resolve_role_id(garbage) == ""

    @pytest.mark.parametrize(
        "ref, expected",
        [
            ("aveline", "aveline"),
            ("ling", "ling"),
            ("ye", "ye"),
            ("lin", "lin"),
            ("yeye", "yeye"),
            ("rushuang", "rushuang"),
            ("七濑 Aveline", "aveline"),
            ("Aveline", "aveline"),
            ("Aveline", "aveline"),
            ("Ling", "ling"),
            ("Ye", "ye"),
            ("Coco", "yeye"),
            ("Frost", "rushuang"),
            ("Lin", "lin"),
        ],
    )
    def test_known_reference_resolves_to_role_id(self, ref, expected):
        """已注册的 role_id / 权威名 / 别名都应能解析出正确 role_id。"""
        assert personas.resolve_role_id(ref) == expected

    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("core_aveline.json", "aveline"),
            ("core_ling.json", "ling"),
            ("core_ye.json", "ye"),
            ("qq/Yeye.json", "yeye"),
            ("core_lin.json", "lin"),
        ],
    )
    def test_persona_filename_hint_resolves(self, filename, expected):
        """人设文件名提示也应能解析 —— 且 core_ye.json 必须归 ye 而不是 yeye。"""
        assert personas.resolve_role_id(filename) == expected

    def test_resolve_role_id_never_falls_back_to_default(self):
        """回归：确认本函数与 resolve_role_id_from_persona 的兜底行为不同。

        resolve_role_id_from_persona 解析不出时返回 "aveline"（历史兼容），
        resolve_role_id 必须返回 ""。两者混用会让"当前是谁"悄悄变成Aveline。
        """
        garbage = "完全不认识的名字"
        assert personas.resolve_role_id(garbage) == ""
        assert personas.resolve_role_id_from_persona(garbage) == "aveline"

    def test_unregistered_single_role_is_not_a_peer_of_anyone(self):
        """单角色的 get_peer_role_ids 必须为空 —— 这是 knows_role 返回 False 的根因。"""
        for rid in SINGLE_ROLE_IDS:
            assert personas.get_peer_role_ids(rid) == []

    def test_registered_pair_lists_each_other(self):
        """互识对必须互为 peer（symmetry 保证双向一致性）。"""
        assert personas.get_peer_role_ids("aveline") == ["ling"]
        assert personas.get_peer_role_ids("ling") == ["aveline"]


class TestPeerAddressTermIsolation:
    """未注册互识关系时不得凭空给出称呼（OOC 的另一来源）。"""

    @pytest.mark.parametrize("role_id", SINGLE_ROLE_IDS)
    def test_single_role_has_no_peer_address_term(self, role_id):
        """单角色没有 peer，称呼必须为空串，调用方据此跳过整段注入。"""
        assert personas.get_peer_address_term(role_id, "") == ""

    def test_registered_pair_address_terms_are_configured(self):
        """互识对的称呼按 PEER_ADDRESS_TERMS 返回，方向不能反。"""
        assert personas.get_peer_address_term("aveline", "ling") == "Ling"
        assert personas.get_peer_address_term("ling", "aveline") == "Aveline"

    def test_single_role_peer_name_is_empty(self):
        """单角色的 get_peer_name 必须为空串，不得回退到某个默认角色名。"""
        for rid in SINGLE_ROLE_IDS:
            assert personas.get_peer_name(rid) == ""
