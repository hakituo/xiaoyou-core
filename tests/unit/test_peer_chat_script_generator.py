# -*- coding: utf-8 -*-
"""PeerScriptGenerator 编排测试（peer_script_generator.py）。

覆盖 core/services/active_care/peer_chat/peer_script_generator.py 的：
- generate_peer_script 的 5 阶段编排与各条提前返回路径
- 协商模式（提醒分工 / 主动关怀时段分工）的分工落库时机
- _persist_negotiation_assignments / _persist_proactive_assignment 的成功/失败分支
- 兼容入口（_load_peer_config / _gather_peer_context / _generate_script_llm）

设计要点：
- 5 个阶段各自已被单独测过，这里只测"编排"：阶段顺序、何时跳过、
  失败时是否降级、分工结果在什么时机写 registry。
- 全部子模块用替身，不调真实 LLM、不读真实配置、不写真实 registry。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.services.active_care.peer_chat import peer_script_generator as gen_mod
from core.services.active_care.peer_chat.peer_script_generator import (
    PeerScriptGenerator,
)


class _StubConfigLoader:
    """替身配置加载器。"""

    def __init__(self, cfg=None):
        self._cfg = cfg or {
            "master_qq_id": "10001",
            "role_name": "Aveline",
            "peer_name": "Ling",
            "role_persona_fn": "core_aveline.json",
            "peer_persona_fn": "core_ling.json",
        }
        self.calls: List[tuple] = []

    def load(self, role_id, peer_role_id):
        self.calls.append((role_id, peer_role_id))
        return dict(self._cfg)


class _StubContextGatherer:
    """替身上下文拉取器。"""

    def __init__(self):
        self.calls: List[tuple] = []

    async def gather(self, role_id, peer_role_id, cfg):
        self.calls.append((role_id, peer_role_id))
        return {"time_str": "2026-09-23 04:20", "bio_state": {}, "peer_bio_state": {}}


class _StubScriptLLM:
    """替身剧本生成器：可编程返回值，并记录调用参数。

    raw_text 语义：真实实现在生成过程中通过 ``generator.record_raw_text()`` 回填
    原文（供协商模式解析分工）。这里用 ``raw_text`` 参数模拟这一行为 ——
    注意必须在 generate 期间回填，而不是提前设置：generate_peer_script 会在
    入口清空 _last_raw_text。
    """

    def __init__(self, script=None, raw_text=None, recorder=None):
        self._script = script if script is not None else [
            {"role": "aveline", "content": "今天吃什么"},
            {"role": "ling", "content": "随便"},
        ]
        self._raw_text = raw_text
        self._recorder = recorder
        self.calls: List[Dict[str, Any]] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._raw_text is not None and self._recorder is not None:
            self._recorder(self._raw_text)
        return list(self._script) if self._script else []


class _StubHost:
    """替身宿主（ActiveCareExecutor 的最小接口）。"""

    def __init__(self):
        self.context = object()
        self.settings = object()
        self.storage = object()


def _make_generator(
    monkeypatch, *, script=None, cfg=None, sent=(True, False, ""), raw_text=None
):
    """构造带替身子模块的生成器，并替换掉分发 / hooks / personas 解析。"""
    gen = PeerScriptGenerator(_StubHost())
    gen._config_loader = _StubConfigLoader(cfg)
    gen._context_gatherer = _StubContextGatherer()
    gen._script_llm = _StubScriptLLM(
        script, raw_text=raw_text, recorder=gen.record_raw_text
    )

    # personas.get_peer_role_id
    import core.services.dual_role.personas as personas

    monkeypatch.setattr(
        personas, "get_peer_role_id", lambda rid: "ling" if rid == "aveline" else ""
    )

    # dispatch_script
    dispatched = {"calls": []}

    async def _fake_dispatch(*, script, role_id, peer_role_id, cfg):
        dispatched["calls"].append(
            {"script": script, "role_id": role_id, "peer_role_id": peer_role_id}
        )
        return sent

    monkeypatch.setattr(gen_mod, "dispatch_script", _fake_dispatch)

    # run_peer_post_hooks
    hooks = {"calls": []}

    async def _fake_hooks(**kwargs):
        hooks["calls"].append(kwargs)

    monkeypatch.setattr(gen_mod, "run_peer_post_hooks", _fake_hooks)

    gen._test_dispatched = dispatched
    gen._test_hooks = hooks
    return gen


# ============================================================
# 主流程编排
# ============================================================

class TestGeneratePeerScriptHappyPath:
    """正常路径：五阶段依次执行。"""

    async def test_returns_true_on_successful_send(self, monkeypatch):
        """分发成功时返回 True。"""
        gen = _make_generator(monkeypatch)

        assert await gen.generate_peer_script(role_id="aveline", peer_qq_id="222") is True

    async def test_all_stages_executed_in_order(self, monkeypatch):
        """配置 → 上下文 → LLM → 分发 → hooks 依次执行。"""
        gen = _make_generator(monkeypatch)

        await gen.generate_peer_script(role_id="aveline", peer_qq_id="222")

        assert gen._config_loader.calls == [("aveline", "ling")]
        assert gen._context_gatherer.calls == [("aveline", "ling")]
        assert len(gen._script_llm.calls) == 1
        assert len(gen._test_dispatched["calls"]) == 1
        assert len(gen._test_hooks["calls"]) == 1

    async def test_llm_receives_resolved_names(self, monkeypatch):
        """LLM 阶段收到的是配置解析出的角色名。"""
        gen = _make_generator(monkeypatch)

        await gen.generate_peer_script(role_id="aveline", peer_qq_id="222")
        call = gen._script_llm.calls[0]

        assert call["role_name"] == "Aveline"
        assert call["peer_name"] == "Ling"
        assert call["peer_role_id"] == "ling"

    async def test_hooks_receive_notify_flags(self, monkeypatch):
        """hooks 收到分发的三个返回值（是否发送/是否通知/通知内容）。"""
        gen = _make_generator(
            monkeypatch, sent=(True, True, "记得吃药")
        )

        await gen.generate_peer_script(role_id="aveline", peer_qq_id="222")
        hook_call = gen._test_hooks["calls"][0]

        assert hook_call["should_notify_user"] is True
        assert hook_call["notify_content"] == "记得吃药"

    async def test_returns_false_when_dispatch_fails(self, monkeypatch):
        """分发失败时返回 False。"""
        gen = _make_generator(monkeypatch, sent=(False, False, ""))

        assert await gen.generate_peer_script(role_id="aveline", peer_qq_id="222") is False

    async def test_hooks_skipped_when_nothing_sent(self, monkeypatch):
        """一条都没发出去时跳过 hooks（避免为失败剧本写日记/社交事件）。"""
        gen = _make_generator(monkeypatch, sent=(False, False, ""))

        await gen.generate_peer_script(role_id="aveline", peer_qq_id="222")

        assert gen._test_hooks["calls"] == []

    async def test_dispatch_not_called_when_script_empty(self, monkeypatch):
        """剧本为空时不进入分发阶段。"""
        gen = _make_generator(monkeypatch, script=[])

        assert await gen.generate_peer_script(role_id="aveline", peer_qq_id="222") is False
        assert gen._test_dispatched["calls"] == []


class TestGeneratePeerScriptEarlyReturns:
    """各条提前返回路径。"""

    async def test_returns_false_when_no_peer_role(self, monkeypatch):
        """角色没有互聊对象时直接返回 False，不加载配置。"""
        gen = _make_generator(monkeypatch)
        import core.services.dual_role.personas as personas

        monkeypatch.setattr(personas, "get_peer_role_id", lambda rid: "")

        assert await gen.generate_peer_script(role_id="ye", peer_qq_id="222") is False
        assert gen._config_loader.calls == []

    async def test_returns_false_when_master_qq_id_missing(self, monkeypatch):
        """主人 QQ 号为空时返回 False（无法定位会话）。"""
        cfg = {
            "master_qq_id": "",
            "role_name": "Aveline",
            "peer_name": "Ling",
            "role_persona_fn": "",
            "peer_persona_fn": "",
        }
        gen = _make_generator(monkeypatch, cfg=cfg)

        assert await gen.generate_peer_script(role_id="aveline", peer_qq_id="222") is False
        assert gen._context_gatherer.calls == []

    async def test_exception_is_caught_and_returns_false(self, monkeypatch):
        """任意阶段抛异常都被捕获并返回 False（不把异常抛给调度主循环）。"""
        gen = _make_generator(monkeypatch)

        async def _boom(**kwargs):
            raise RuntimeError("LLM 挂了")

        gen._script_llm.generate = _boom

        assert await gen.generate_peer_script(role_id="aveline", peer_qq_id="222") is False


class TestNegotiationMode:
    """提醒分工协商模式。"""

    async def test_reminders_forwarded_to_llm(self, monkeypatch):
        """待发提醒透传给 LLM 阶段。"""
        gen = _make_generator(monkeypatch)
        reminders = [{"reminder_id": "r1", "title": "吃药"}]

        await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            negotiation_reminders=reminders,
        )

        assert gen._script_llm.calls[0]["negotiation_reminders"] == reminders

    async def test_persists_assignments_after_dispatch(self, monkeypatch):
        """分发成功后解析 raw_text 并写 registry。"""
        raw = (
            "<assignment>"
            '{"assignments": [{"reminder_id": "r1", "assigned_to": "aveline"}]}'
            "</assignment>"
        )
        gen = _make_generator(monkeypatch, raw_text=raw)
        persisted = {"calls": []}

        async def _spy(raw_text, role_id, peer_role_id):
            persisted["calls"].append(raw_text)

        gen._persist_negotiation_assignments = _spy
        await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            negotiation_reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )

        assert len(persisted["calls"]) == 1
        assert persisted["calls"][0] == raw

    async def test_persists_from_raw_text_when_script_empty(self, monkeypatch):
        """剧本生成失败时仍尝试从 raw_text 兜底解析分工。"""
        gen = _make_generator(
            monkeypatch, script=[], raw_text="<assignment>{}</assignment>"
        )
        persisted = {"calls": []}

        async def _spy(raw_text, role_id, peer_role_id):
            persisted["calls"].append(raw_text)

        gen._persist_negotiation_assignments = _spy
        result = await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            negotiation_reminders=[{"reminder_id": "r1"}],
        )

        assert result is False
        assert len(persisted["calls"]) == 1

    async def test_no_persist_without_raw_text(self, monkeypatch):
        """没有 raw_text 时不尝试解析（避免用空文本覆盖 registry）。"""
        gen = _make_generator(monkeypatch, script=[])
        persisted = {"calls": []}

        async def _spy(raw_text, role_id, peer_role_id):
            persisted["calls"].append(raw_text)

        gen._persist_negotiation_assignments = _spy
        await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            negotiation_reminders=[{"reminder_id": "r1"}],
        )

        assert persisted["calls"] == []

    async def test_state_is_reset_between_calls(self, monkeypatch):
        """每次调用开头清空上次的协商结果与 raw_text（防串场）。"""
        gen = _make_generator(monkeypatch)
        gen._last_negotiation_assignments = [{"stale": True}]
        gen.record_raw_text("上一轮的原文")

        await gen.generate_peer_script(role_id="aveline", peer_qq_id="222")

        assert gen._last_negotiation_assignments == []
        assert gen._last_raw_text == ""


class TestProactiveAssignmentMode:
    """主动关怀时段分工协商模式。"""

    async def test_role_states_forwarded_to_llm(self, monkeypatch):
        """各角色状态简述透传给 LLM 阶段。"""
        gen = _make_generator(monkeypatch)
        role_states = {"aveline": "精力充沛", "ling": "有点累"}

        await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            proactive_assignment_mode=True,
            role_states=role_states,
        )
        call = gen._script_llm.calls[0]

        assert call["proactive_assignment_mode"] is True
        assert call["role_states"] == role_states

    async def test_persists_assignment_after_dispatch(self, monkeypatch):
        """分发成功后写主动关怀 registry。"""
        gen = _make_generator(
            monkeypatch, raw_text="<proactive_assignment>{}</proactive_assignment>"
        )
        persisted = {"calls": []}

        async def _spy(raw_text, role_id, peer_role_id):
            persisted["calls"].append(raw_text)

        gen._persist_proactive_assignment = _spy
        await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            proactive_assignment_mode=True,
        )

        assert len(persisted["calls"]) == 1

    async def test_persists_from_raw_text_when_script_empty(self, monkeypatch):
        """剧本生成失败时仍从 raw_text 兜底解析时段分工（与协商模式对称）。"""
        gen = _make_generator(
            monkeypatch,
            script=[],
            raw_text="<proactive_assignment>{}</proactive_assignment>",
        )
        persisted = {"calls": []}

        async def _spy(raw_text, role_id, peer_role_id):
            persisted["calls"].append(raw_text)

        gen._persist_proactive_assignment = _spy
        result = await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            proactive_assignment_mode=True,
        )

        assert result is False
        assert persisted["calls"] == [
            "<proactive_assignment>{}</proactive_assignment>"
        ]

    async def test_legacy_state_kwargs_forwarded(self, monkeypatch):
        """向后兼容的 aveline_state / ling_state 也要透传。"""
        gen = _make_generator(monkeypatch)

        await gen.generate_peer_script(
            role_id="aveline",
            peer_qq_id="222",
            proactive_assignment_mode=True,
            aveline_state="精力充沛",
            ling_state="有点累",
        )
        call = gen._script_llm.calls[0]

        assert call["aveline_state"] == "精力充沛"
        assert call["ling_state"] == "有点累"


# ============================================================
# 分工落库的细节分支
# ============================================================

class _StubRegistry:
    """替身分工注册表。"""

    def __init__(self):
        self.assigned: List[Dict[str, Any]] = []
        self.status: List[Dict[str, Any]] = []
        self.assignments_set: List[Any] = []

    async def mark_assigned(self, reminder_id, title, persona, reason):
        self.assigned.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "persona": persona,
                "reason": reason,
            }
        )

    async def mark_negotiation_status(self, status, reason=""):
        self.status.append({"status": status, "reason": reason})

    async def set_assignments(self, assignments):
        self.assignments_set.append(assignments)


class TestPersistNegotiationAssignments:
    """_persist_negotiation_assignments 的分支。"""

    async def test_writes_assignments_and_marks_completed(self, monkeypatch):
        """解析出分工时逐条写入并标记 completed。"""
        gen = PeerScriptGenerator(_StubHost())
        registry = _StubRegistry()

        import core.services.active_care.storage.reminder_assignment_registry as reg_mod

        monkeypatch.setattr(
            reg_mod, "get_reminder_assignment_registry", lambda: registry
        )
        raw = (
            "<assignment>"
            '{"assignments": ['
            '{"reminder_id": "r1", "assigned_to": "aveline", "reason": "她更合适"},'
            '{"reminder_id": "r2", "assigned_to": "ling", "reason": "她跟进过"}'
            "]}"
            "</assignment>"
        )

        await gen._persist_negotiation_assignments(raw, "aveline", "ling")

        assert len(registry.assigned) == 2
        assert registry.assigned[0]["reminder_id"] == "r1"
        assert registry.assigned[0]["persona"] == "aveline"
        assert registry.status[-1]["status"] == "completed"
        assert len(gen._last_negotiation_assignments) == 2

    async def test_marks_failed_when_no_valid_block(self, monkeypatch):
        """解析不出分工时标记 failed，让调用方走先到先得兜底。"""
        gen = PeerScriptGenerator(_StubHost())
        registry = _StubRegistry()

        import core.services.active_care.storage.reminder_assignment_registry as reg_mod

        monkeypatch.setattr(
            reg_mod, "get_reminder_assignment_registry", lambda: registry
        )

        await gen._persist_negotiation_assignments("没有任何 JSON 块", "aveline", "ling")

        assert registry.assigned == []
        assert registry.status[-1]["status"] == "failed"

    async def test_registry_exception_is_swallowed(self, monkeypatch):
        """registry 获取异常时不抛出（协商失败不能拖垮主流程）。"""
        gen = PeerScriptGenerator(_StubHost())

        import core.services.active_care.storage.reminder_assignment_registry as reg_mod

        def _boom():
            raise RuntimeError("注册表不可用")

        monkeypatch.setattr(reg_mod, "get_reminder_assignment_registry", _boom)

        await gen._persist_negotiation_assignments(
            '<assignment>{"assignments": [{"reminder_id": "r1", "assigned_to": "aveline"}]}</assignment>',
            "aveline",
            "ling",
        )  # 不应抛异常


class TestPersistProactiveAssignment:
    """_persist_proactive_assignment 的分支。"""

    async def test_writes_assignments(self, monkeypatch):
        """解析出时段分工时写入 registry。"""
        gen = PeerScriptGenerator(_StubHost())
        registry = _StubRegistry()

        import core.services.active_care.storage.proactive_assignment_registry as reg_mod

        monkeypatch.setattr(
            reg_mod, "get_proactive_assignment_registry", lambda: registry
        )
        raw = (
            "<proactive_assignment>"
            '{"assignments": [{"time_slot": "morning", "lead": "aveline"}]}'
            "</proactive_assignment>"
        )

        await gen._persist_proactive_assignment(raw, "aveline", "ling")

        assert len(registry.assignments_set) == 1
        assert registry.assignments_set[0][0]["time_slot"] == "morning"

    async def test_marks_failed_when_no_valid_block(self, monkeypatch):
        """解析不出时标记 failed，让调用方走轮流制兜底。"""
        gen = PeerScriptGenerator(_StubHost())
        registry = _StubRegistry()

        import core.services.active_care.storage.proactive_assignment_registry as reg_mod

        monkeypatch.setattr(
            reg_mod, "get_proactive_assignment_registry", lambda: registry
        )

        await gen._persist_proactive_assignment("没有块", "aveline", "ling")

        assert registry.assignments_set == []
        assert registry.status[-1]["status"] == "failed"

    async def test_registry_exception_is_swallowed(self, monkeypatch):
        """registry 异常时不抛出。"""
        gen = PeerScriptGenerator(_StubHost())

        import core.services.active_care.storage.proactive_assignment_registry as reg_mod

        def _boom():
            raise RuntimeError("注册表不可用")

        monkeypatch.setattr(reg_mod, "get_proactive_assignment_registry", _boom)

        await gen._persist_proactive_assignment(
            '<proactive_assignment>{"assignments": [{"time_slot": "morning", "lead": "aveline"}]}</proactive_assignment>',
            "aveline",
            "ling",
        )  # 不应抛异常


# ============================================================
# 兼容入口与辅助方法
# ============================================================

class TestCompatibilityEntries:
    """拆分后保留的兼容入口应正确委托。"""

    def test_load_peer_config_delegates(self, monkeypatch):
        """_load_peer_config 委托给 config_loader。"""
        gen = _make_generator(monkeypatch)

        cfg = gen._load_peer_config("aveline", "ling")

        assert cfg["role_name"] == "Aveline"
        assert gen._config_loader.calls == [("aveline", "ling")]

    async def test_gather_peer_context_delegates(self, monkeypatch):
        """_gather_peer_context 委托给 context_gatherer。"""
        gen = _make_generator(monkeypatch)

        ctx = await gen._gather_peer_context("aveline", "ling", {})

        assert ctx["time_str"] == "2026-09-23 04:20"
        assert gen._context_gatherer.calls == [("aveline", "ling")]

    async def test_generate_script_llm_delegates(self, monkeypatch):
        """_generate_script_llm 委托给 script_llm。"""
        gen = _make_generator(monkeypatch)

        script = await gen._generate_script_llm(role_id="aveline")

        assert len(script) == 2
        assert len(gen._script_llm.calls) == 1

    def test_record_raw_text_stores_value(self):
        """record_raw_text 保存原文供协商解析使用。"""
        gen = PeerScriptGenerator(_StubHost())

        gen.record_raw_text("原文内容")

        assert gen._last_raw_text == "原文内容"

    def test_init_sets_clean_state(self):
        """初始化时协商状态为空。"""
        gen = PeerScriptGenerator(_StubHost())

        assert gen._last_negotiation_assignments == []
        assert gen._last_raw_text == ""
