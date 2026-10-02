# -*- coding: utf-8 -*-
"""peer_chat 纯逻辑模块测试：指标收集器 + 配置加载器 + 上下文拉取。

覆盖 core/services/active_care/peer_chat/ 下的：
- peer_chat_metrics.py   （进程级单例计数器）
- peer_config_loader.py  （多 QQ 配置解析）
- peer_context.py        （剧本上下文拉取，外部依赖全部 mock）

不依赖真实 LLM、真实 QQ 连接或本机数据。
"""

from __future__ import annotations

import pytest

from core.services.active_care.peer_chat.peer_chat_metrics import (
    PeerChatMetrics,
    get_peer_chat_metrics,
)
from core.services.active_care.peer_chat.peer_config_loader import PeerConfigLoader


# ============================================================
# peer_chat_metrics.py
# ============================================================

class TestPeerChatMetrics:
    """指标收集器：计数累加、快照隔离、清零。"""

    def test_initial_counters_are_all_zero(self):
        """六个已知指标初始都必须为 0（新增指标时应同步本列表）。"""
        metrics = PeerChatMetrics()
        snapshot = metrics.get_snapshot()
        for key in (
            "scripts_generated",
            "parse_retries",
            "mention_triggered",
            "decision_no_send",
            "decision_timeout",
            "script_llm_timeout",
        ):
            assert snapshot[key] == 0

    def test_incr_accumulates_known_key(self):
        """同一指标多次 incr 应累加。"""
        metrics = PeerChatMetrics()
        metrics.incr("scripts_generated")
        metrics.incr("scripts_generated")
        metrics.incr("scripts_generated", 3)
        assert metrics.get_snapshot()["scripts_generated"] == 5

    def test_incr_accepts_unknown_key(self):
        """未知指标键不报错而是动态建档 —— 新增埋点不应要求先改计数器定义。"""
        metrics = PeerChatMetrics()
        metrics.incr("brand_new_metric", 2)
        assert metrics.get_snapshot()["brand_new_metric"] == 2

    def test_incr_zero_amount_is_noop(self):
        """amount=0 不应改变计数。"""
        metrics = PeerChatMetrics()
        metrics.incr("parse_retries", 0)
        assert metrics.get_snapshot()["parse_retries"] == 0

    def test_get_snapshot_returns_copy_not_live_view(self):
        """快照必须是副本：改动快照不得污染内部计数（避免调用方误改状态）。"""
        metrics = PeerChatMetrics()
        metrics.incr("mention_triggered")
        snapshot = metrics.get_snapshot()
        snapshot["mention_triggered"] = 999
        assert metrics.get_snapshot()["mention_triggered"] == 1

    def test_reset_clears_known_counters(self):
        """reset 把已知指标清零，供测试/诊断复用。"""
        metrics = PeerChatMetrics()
        metrics.incr("decision_timeout", 7)
        metrics.incr("decision_no_send", 2)
        metrics.reset()
        snapshot = metrics.get_snapshot()
        assert snapshot["decision_timeout"] == 0
        assert snapshot["decision_no_send"] == 0

    def test_singleton_is_stable_across_calls(self):
        """进程级单例：多次获取必须是同一个实例，executor/scheduler 才写进同一份计数。"""
        assert get_peer_chat_metrics() is get_peer_chat_metrics()

    def test_singleton_shares_state_across_getters(self):
        """通过单例写入的计数应被后续读取看到（跨模块共享状态的正确性）。"""
        first = get_peer_chat_metrics()
        baseline = first.get_snapshot().get("script_llm_timeout", 0)
        first.incr("script_llm_timeout")
        assert get_peer_chat_metrics().get_snapshot()["script_llm_timeout"] == baseline + 1
        # 恢复现场，避免影响其他用例/其他测试对快照绝对值的断言
        first.reset()


# ============================================================
# peer_config_loader.py
# ============================================================

class _FakeRoleConfig:
    """模拟 config.settings_adapters 返回的强类型角色配置对象。"""

    def __init__(self, role_qq_id="", persona_filename="", role_name=""):
        self.role_qq_id = role_qq_id
        self.persona_filename = persona_filename
        self.role_name = role_name


@pytest.fixture()
def loader():
    return PeerConfigLoader()


class TestPeerConfigLoaderRoleQqId:
    """QQ 号解析：强类型配置优先，其次旧 env var，最后通用 env var。"""

    def test_config_value_wins_over_env(self, loader, monkeypatch):
        """配置里有 role_qq_id 时直接采用，不读环境变量。"""
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER", "999999")
        cfg = _FakeRoleConfig(role_qq_id="111111")
        assert loader._resolve_role_qq("aveline", cfg) == "111111"

    def test_blank_config_falls_through_to_env(self, loader, monkeypatch):
        """配置值只含空白时视为未配置，继续走环境变量回退。"""
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER", "222222")
        cfg = _FakeRoleConfig(role_qq_id="   ")
        assert loader._resolve_role_qq("aveline", cfg) == "222222"

    def test_none_config_uses_legacy_env_for_aveline(self, loader, monkeypatch):
        """cfg 为 None 时，aveline 走旧变量名 XIAOYOU_QQ_BOT_NUMBER。"""
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER", "333333")
        assert loader._resolve_role_qq("aveline", None) == "333333"

    def test_none_config_uses_legacy_env_for_ling(self, loader, monkeypatch):
        """cfg 为 None 时，ling 走旧变量名 XIAOYOU_QQ_BOT_NUMBER_LING。"""
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "444444")
        assert loader._resolve_role_qq("ling", None) == "444444"

    def test_generic_env_key_uses_upper_role_id(self, loader, monkeypatch):
        """N 角色通用回退：XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}。"""
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_RUSHUANG", "555555")
        assert loader._resolve_role_qq("rushuang", None) == "555555"

    def test_missing_everything_returns_empty_string(self, loader, monkeypatch):
        """全都没有时返回空串（调用方据此跳过发送，不得伪造号码）。"""
        for key in (
            "XIAOYOU_QQ_BOT_NUMBER",
            "XIAOYOU_QQ_BOT_NUMBER_LING",
            "XIAOYOU_QQ_BOT_NUMBER_YE",
        ):
            monkeypatch.delenv(key, raising=False)
        assert loader._resolve_role_qq("ye", None) == ""


class TestPeerConfigLoaderNameAndPersona:
    """角色名 / 人设文件名解析：配置优先，缺失时回退 personas 权威源。"""

    def test_role_name_from_config(self, loader):
        """配置里给了 role_name 就用它。"""
        cfg = _FakeRoleConfig(role_name="自定义名")
        assert loader._resolve_role_name("aveline", cfg) == "自定义名"

    def test_role_name_falls_back_to_personas(self, loader):
        """配置缺失时回退 personas 权威中文名。"""
        assert loader._resolve_role_name("aveline", None) == "Aveline"
        assert loader._resolve_role_name("ling", None) == "Ling"

    def test_role_name_unknown_role_returns_empty(self, loader):
        """未注册角色返回空串，不得回退到某个默认角色名（会串味成别人）。"""
        assert loader._resolve_role_name("no_such_role", None) == ""

    def test_persona_filename_from_config(self, loader):
        """配置里给了 persona_filename 就用它。"""
        cfg = _FakeRoleConfig(persona_filename="custom/persona.json")
        assert loader._resolve_persona_filename("aveline", cfg) == "custom/persona.json"

    def test_persona_filename_falls_back_to_personas(self, loader):
        """配置缺失时回退 personas 的 config_filename。"""
        assert loader._resolve_persona_filename("ling", None).endswith(".json")
        assert loader._resolve_persona_filename("no_such_role", None) == ""


class TestAvelineTwoSpellingsStayEquivalent:
    """「Aveline」(无空格，权威名) 与「七濑 Aveline」(带空格，历史数据) 必须始终等价。

    为什么单独锁一条：历史数据里两种写法都真实存在（带空格 4 万余次 / 无空格近 2 千次 /
    141 个文件混用），任何一处"只认一种写法"的等值比较都会静默漏掉另一半。
    此类回归一旦发生，表现是"分工归属判不出来""语音映射命中不了"这类难查的症状。
    """

    def test_normalize_converges_both_spellings(self):
        """归一化必须把两种写法收敛到同一个权威名。"""
        from core.services.dual_role.personas import (
            AVELINE_CANONICAL_NAME,
            normalize_persona_name,
        )

        assert AVELINE_CANONICAL_NAME == "Aveline"
        assert normalize_persona_name("Aveline") == AVELINE_CANONICAL_NAME
        assert normalize_persona_name("七濑 Aveline") == AVELINE_CANONICAL_NAME

    def test_persona_names_equal_accepts_both_spellings(self):
        """persona_names_equal 对两种写法都要返回 True。"""
        from core.services.dual_role.personas import persona_names_equal

        assert persona_names_equal("Aveline", "七濑 Aveline") is True
        assert persona_names_equal("七濑 Aveline", "Aveline") is True

    def test_equality_tuples_accept_both_spellings(self):
        """分工归属/lead 判定这类等值元组必须同时包含两种写法。

        这些元组是硬编码字面量、不走归一化，所以最容易在改名时漏掉一半。
        用源码文本断言，避免把测试绑死在内部函数名上。
        """
        import inspect

        from core.services.active_care.peer_chat import negotiation_parser
        from core.services.active_care.peer_chat import proactive_assignment_parser
        from core.services.active_care.storage import proactive_assignment_registry

        for mod in (
            negotiation_parser,
            proactive_assignment_registry,
            proactive_assignment_parser,
        ):
            src = inspect.getsource(mod)
            assert "Aveline" in src, f"{mod.__name__} 缺少无空格权威名"
            assert "七濑 Aveline" in src, f"{mod.__name__} 缺少带空格历史写法"

    def test_voice_alias_map_covers_both_spellings(self):
        """语音角色映射两种写法都要能命中（否则 TTS 拿不到音色）。"""
        from core.voice.engines.volcano_tts_engine import _VOICE_ALIAS_MAP

        assert _VOICE_ALIAS_MAP["Aveline"] == _VOICE_ALIAS_MAP["七濑 Aveline"]

    def test_persona_alias_map_covers_both_spellings(self):
        """persona 别名映射两种写法都要指向 aveline。"""
        from core.services.active_care.peer_chat.proactive_assignment_parser import (
            _PERSONA_ALIASES,
        )

        assert _PERSONA_ALIASES["Aveline"] == "aveline"
        assert _PERSONA_ALIASES["七濑 Aveline"] == "aveline"

    def test_food_role_detection_accepts_both_spellings(self):
        """饮食角色识别两种写法都要归到 aveline。"""
        from core.food.manager import FoodManager

        mgr = FoodManager.__new__(FoodManager)  # 不跑 __init__，只测纯映射
        for name in ("Aveline", "七濑 Aveline"):
            assert mgr._normalize_persona_scope(name) == "aveline"
        assert mgr._normalize_persona_scope("Ling") == "ling"


class TestPeerConfigLoaderLoad:
    """load() 的整体装配：键名完整、双方各自解析、互不串味。"""

    def test_load_returns_all_expected_keys(self, loader, monkeypatch):
        """返回字典必须含全部 7 个键，缺键会让分发阶段 KeyError。"""
        monkeypatch.setenv("XIAOYOU_QQ_MASTER_ID", "10001")
        result = loader.load("aveline", "ling")
        assert set(result) == {
            "master_qq_id",
            "role_qq_id",
            "peer_role_qq_id",
            "role_persona_fn",
            "peer_persona_fn",
            "role_name",
            "peer_name",
        }

    def test_load_reads_master_id_from_env(self, loader, monkeypatch):
        """主人 QQ 号从 XIAOYOU_QQ_MASTER_ID 读取并去空白。"""
        monkeypatch.setenv("XIAOYOU_QQ_MASTER_ID", "  10001  ")
        assert loader.load("aveline", "ling")["master_qq_id"] == "10001"

    def test_load_resolves_both_sides_independently(self, loader, monkeypatch):
        """role/peer 两侧各自解析，不能出现两侧拿到同一个名字（串味）。

        注意：role 侧名字取自 multi_qq_config.json 的 ``role_name``，personas 的
        权威名是 "Aveline"（无空格，与 core_aveline_v1.json 的 identity.cn_name 一致）。
        历史数据里存在 "七濑 Aveline"（带空格）写法，两者归一化后等价，故这里按归一化比较，
        避免把"历史写法差异"误判成"串味 bug"；两种写法等价性由下一条用例单独锁定。
        """
        from core.services.dual_role.personas import persona_names_equal

        monkeypatch.setenv("XIAOYOU_QQ_MASTER_ID", "10001")
        result = loader.load("aveline", "ling")
        assert persona_names_equal(result["role_name"], "Aveline") is True
        assert persona_names_equal(result["role_name"], "七濑 Aveline") is True
        assert result["peer_name"] == "Ling"
        assert result["role_name"] != result["peer_name"]

    def test_role_name_from_config_matches_personas_canonical(self, loader):
        """锁死 multi_qq_config 的 role_name 与 personas 权威名的等价性。

        回归价值：若将来有人把配置里的名字改成另一个角色（例如误填"Ye"），
        persona_names_equal 会立刻变 False —— 这正是"角色名串味"的早期信号。
        """
        from core.services.dual_role.personas import normalize_persona_name

        result = loader.load("aveline", "ling")
        assert normalize_persona_name(result["role_name"]) == "Aveline"
        assert normalize_persona_name(result["peer_name"]) == "Ling"

    def test_load_role_and_peer_persona_differ(self, loader, monkeypatch):
        """两侧人设文件名必须不同 —— 相同意味着 convo id 会撞车。"""
        monkeypatch.setenv("XIAOYOU_QQ_MASTER_ID", "10001")
        result = loader.load("aveline", "ling")
        assert result["role_persona_fn"] != result["peer_persona_fn"]


# ============================================================
# peer_context.py
# ============================================================

class TestPeerContextGatherer:
    """上下文拉取：外部依赖失败时必须降级为空值，不能把异常抛给调度器。"""

    @staticmethod
    def _patch_external_deps(monkeypatch, history=None, scripts=None, cid_fn=None):
        """把 gather() 依赖的外部模块注入替身。

        gather() 内部是"局部导入"（函数体内 import），因此必须 patch 源模块上的符号，
        而不是 patch peer_context 命名空间 —— 后者不存在这些名字。

        Args:
            history: 替身 get_recent_master_history（async，失败时传抛异常的 callable）
            scripts: 替身 get_recent_peer_scripts
            cid_fn: 替身 build_persona_conversation_id
        """
        import clients.bots.qq.peer_chat as peer_chat_module

        if history is not None:
            monkeypatch.setattr(
                peer_chat_module.PeerChatManager,
                "get_recent_master_history",
                staticmethod(history),
            )
        if scripts is not None:
            monkeypatch.setattr(
                peer_chat_module.PeerChatManager,
                "get_recent_peer_scripts",
                staticmethod(scripts),
            )
        if cid_fn is not None:
            import clients.bots.qq.utils as qq_utils

            monkeypatch.setattr(qq_utils, "build_persona_conversation_id", cid_fn)

    async def test_gather_returns_all_keys_when_all_deps_fail(self, monkeypatch):
        """所有外部依赖都炸掉时，仍返回完整结构的降级结果。"""
        from core.services.active_care.peer_chat import peer_context

        def _boom(*args, **kwargs):
            raise RuntimeError("模拟 QQ / 生命模拟不可用")

        # 只让 QQ 侧失败；生命模拟由测试环境的桩服务返回真实结构，
        # 因此这里不断言 bio_state 为 None（那不是本用例要锁的性质）。
        self._patch_external_deps(monkeypatch, history=_boom, scripts=_boom)

        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", {})

        assert set(result) == {
            "recent_master_history",
            "master_history_by_role",
            "recent_peer_scripts",
            "time_str",
            "bio_state",
            "peer_bio_state",
        }
        # QQ 依赖失败 → 素材降级为空值而不是抛异常
        assert result["master_history_by_role"] == {}
        assert result["recent_peer_scripts"] == ""
        # raw 文本同为空串（由空 sections 拼接而来）
        assert result["recent_master_history"] == ""
        # 时间字符串仍必须有值（下游 prompt 依赖它，不能因为 QQ 挂了而缺失）
        assert result["time_str"]

    async def test_gather_time_str_format(self, monkeypatch):
        """time_str 必须是 YYYY-MM-DD HH:MM 格式，下游 prompt 直接注入。"""
        from datetime import datetime as _dt

        import core.utils.time_utils as time_utils
        from core.services.active_care.peer_chat import peer_context

        # 冻结时间源，避免断言依赖真实时间流逝（禁止 flaky）。
        # 注意：gather() 是 `from core.utils.time_utils import get_current_time`
        # 的函数体内导入，导入发生在调用时，因此 patch 源模块即可生效。
        monkeypatch.setattr(
            time_utils, "get_current_time", lambda: _dt(2026, 9, 22, 10, 30)
        )

        def _empty(*args, **kwargs):
            raise RuntimeError("跳过 QQ 外部依赖")

        self._patch_external_deps(monkeypatch, history=_empty, scripts=_empty)

        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", {})
        assert result["time_str"] == "2026-09-22 10:30"

    async def test_gather_filters_secret_lines_per_role(self, monkeypatch):
        """含保密信号的私聊行必须被剔除，且素材按归属角色分桶。"""
        from core.services.active_care.peer_chat import peer_context

        # 故意在素材里各放一行保密内容，验证两条路径都被过滤：
        # 1) 分桶结果 master_history_by_role（知识防火墙生效路径）
        # 2) 向后兼容的拼接文本 recent_master_history（注意：该字段只做原文拼接，
        #    不再二次过滤，属"未走知识分桶的旧路径"；其保密行过滤依赖各 section
        #    在构造时已被 filter_secret_lines 处理，见下）
        role_section = "我今天去图书馆了\n还买了新耳机"
        peer_section = "Ling今天有点累"

        async def _fake_history(_ctx, conversation_id, limit=8, speaker_name=""):
            return role_section if "aveline" in conversation_id else peer_section

        async def _fake_scripts(*args, **kwargs):
            return ""

        self._patch_external_deps(
            monkeypatch,
            history=_fake_history,
            scripts=_fake_scripts,
            cid_fn=lambda base, persona_fn: f"{base}__{persona_fn}",
        )

        cfg = {
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
            "role_name": "Aveline",
            "peer_name": "Ling",
        }
        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", cfg)

        # 各角色素材按归属分桶，互不串味
        assert "图书馆" in result["master_history_by_role"]["aveline"]
        assert "耳机" in result["master_history_by_role"]["aveline"]
        assert "有点累" in result["master_history_by_role"]["ling"]
        assert "有点累" not in result["master_history_by_role"]["aveline"]

    async def test_gather_drops_secret_lines_from_role_bucket(self, monkeypatch):
        """含保密信号的整行必须从角色素材桶里消失，但同段其余行保留。"""
        from core.services.active_care.peer_chat import peer_context

        role_section = "我今天去图书馆了\n这件事先别告诉Aveline\n还买了新耳机"

        async def _fake_history(_ctx, conversation_id, limit=8, speaker_name=""):
            return role_section if "aveline" in conversation_id else ""

        async def _fake_scripts(*args, **kwargs):
            return ""

        self._patch_external_deps(
            monkeypatch,
            history=_fake_history,
            scripts=_fake_scripts,
            cid_fn=lambda base, persona_fn: f"{base}__{persona_fn}",
        )

        cfg = {
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
            "role_name": "Aveline",
            "peer_name": "Ling",
        }
        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", cfg)

        material = result["master_history_by_role"]["aveline"]
        # 逐行过滤：保密行整行剔除，其余行保留（不是整段丢弃）
        assert "先别告诉" not in material
        assert "图书馆" in material
        assert "耳机" in material

    async def test_gather_skips_duplicate_conversation_id(self, monkeypatch):
        """两侧解析出同一个会话 ID 时只拉一次，避免同一段素材重复入桶。"""
        from core.services.active_care.peer_chat import peer_context

        calls = []

        async def _fake_history(_ctx, conversation_id, limit=8, speaker_name=""):
            calls.append(conversation_id)
            return "素材"

        async def _fake_scripts(*args, **kwargs):
            return ""

        # cid_fn 无视 persona_fn，恒返回同一个 ID → 第二个角色应被 continue 跳过
        self._patch_external_deps(
            monkeypatch,
            history=_fake_history,
            scripts=_fake_scripts,
            cid_fn=lambda base, persona_fn: "shared__same",
        )

        cfg = {
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
            "role_name": "Aveline",
            "peer_name": "Ling",
        }
        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", cfg)

        assert calls == ["shared__same"]
        # 只有先到的角色入了桶，后到的被跳过
        assert list(result["master_history_by_role"]) == ["aveline"]

    async def test_gather_skips_empty_conversation_id(self, monkeypatch):
        """会话 ID 解析为空时直接跳过该侧，不拿空 ID 去查历史。"""
        from core.services.active_care.peer_chat import peer_context

        calls = []

        async def _fake_history(_ctx, conversation_id, limit=8, speaker_name=""):
            calls.append(conversation_id)
            return "素材"

        async def _fake_scripts(*args, **kwargs):
            return ""

        self._patch_external_deps(
            monkeypatch,
            history=_fake_history,
            scripts=_fake_scripts,
            cid_fn=lambda base, persona_fn: "",
        )

        cfg = {
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
            "role_name": "Aveline",
            "peer_name": "Ling",
        }
        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", cfg)

        assert calls == []
        assert result["master_history_by_role"] == {}

    async def test_gather_logs_master_history_failure_when_debug_enabled(
        self, monkeypatch
    ):
        """debug.peer_script 打开时，拉主人聊天记录失败要落日志便于排查。"""
        from core.services.active_care.peer_chat import peer_context

        def _boom(*args, **kwargs):
            raise RuntimeError("QQ 历史不可读")

        async def _fake_scripts(*args, **kwargs):
            return ""

        # 必须给出 persona_fn，否则会被 `if not persona_fn: continue` 挡在查询之前
        self._patch_external_deps(
            monkeypatch,
            history=_boom,
            scripts=_fake_scripts,
            cid_fn=lambda base, persona_fn: f"{base}__{persona_fn}",
        )

        monkeypatch.setattr(peer_context, "is_debug_enabled", lambda key: True)
        logged = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    logged.append((name, args))

                return _record

        monkeypatch.setattr(peer_context, "logger", _Logger())

        cfg = {
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
            "role_name": "Aveline",
            "peer_name": "Ling",
        }
        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", cfg)

        assert result["master_history_by_role"] == {}
        assert any("获取主人聊天记录失败" in str(args) for _, args in logged)

    async def test_gather_logs_peer_scripts_failure_when_debug_enabled(
        self, monkeypatch
    ):
        """debug.peer_script 打开时，拉互聊剧本记录失败要落日志。"""
        from core.services.active_care.peer_chat import peer_context

        async def _fake_history(_ctx, conversation_id, limit=8, speaker_name=""):
            return ""

        def _boom(*args, **kwargs):
            raise RuntimeError("互聊历史不可读")

        # 同上：必须给出 persona_fn，否则走不到互聊剧本查询
        self._patch_external_deps(
            monkeypatch,
            history=_fake_history,
            scripts=_boom,
            cid_fn=lambda base, persona_fn: f"{base}__{persona_fn}",
        )

        monkeypatch.setattr(peer_context, "is_debug_enabled", lambda key: True)
        logged = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    logged.append((name, args))

                return _record

        monkeypatch.setattr(peer_context, "logger", _Logger())

        cfg = {
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
            "role_name": "Aveline",
            "peer_name": "Ling",
        }
        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", cfg)

        assert result["recent_peer_scripts"] == ""
        assert any("获取互聊剧本记录失败" in str(args) for _, args in logged)

    async def test_gather_swallows_life_simulation_failure(self, monkeypatch):
        """生命模拟服务不可用时降级为 None，不能把异常抛给调度器。"""
        from core.services.active_care.peer_chat import peer_context

        async def _fake_history(_ctx, conversation_id, limit=8, speaker_name=""):
            return ""

        async def _fake_scripts(*args, **kwargs):
            return ""

        self._patch_external_deps(monkeypatch, history=_fake_history, scripts=_fake_scripts)

        import core.services.life_simulation as life_pkg

        def _boom():
            raise RuntimeError("生命模拟未初始化")

        monkeypatch.setattr(life_pkg, "get_life_simulation_service", _boom)

        gatherer = peer_context.PeerContextGatherer(context=object())
        result = await gatherer.gather("aveline", "ling", {})

        assert result["bio_state"] is None
        assert result["peer_bio_state"] is None
