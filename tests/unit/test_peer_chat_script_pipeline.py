# -*- coding: utf-8 -*-
"""peer_chat 剧本链路测试：决策 / 剧本 LLM 生成 / 分发 / 后处理 hooks。

覆盖 core/services/active_care/peer_chat/ 下的：
- peer_chat_decision.py   （LLM 决策，超时与异常降级）
- peer_script_llm.py      （剧本生成，超时/解析失败重试/轮数越界/知识防火墙）
- peer_script_dispatch.py （剧本逐条分发与路由）
- peer_script_hooks.py    （分发后副作用：日记、巡检、剧本记录、主人通知）

全部用替身隔离 LLM 与外部服务，不产生网络/模型开销。
"""

from __future__ import annotations

import asyncio

import pytest

from core.services.active_care.peer_chat import peer_script_dispatch
from core.services.active_care.peer_chat import peer_script_hooks
from core.services.active_care.peer_chat.peer_chat_decision import PeerChatDecider
from core.services.active_care.peer_chat.peer_script_llm import (
    PeerScriptLLMGenerator,
)


# ============================================================
# 通用替身
# ============================================================

class _StubLLM:
    """替身 LLM 模块：可编程返回脚本或抛异常。"""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._exc is not None:
            raise self._exc
        return self._response


class _ScriptHost:
    """替身 PeerScriptGenerator：提供 PeerScriptLLMGenerator 需要的宿主接口。"""

    def __init__(self):
        self.raw_texts = []
        self._host = _ScriptExecutor()


class _ScriptExecutor:
    """替身 ActiveCareExecutor：提供 settings 与响应文本提取。"""

    def __init__(self):
        self.settings = object()

    @staticmethod
    def _extract_text_from_llm_response(raw):
        """原实现的各种响应形态都归一成文本；这里只处理测试用到的两种。"""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return str(raw.get("response") or raw.get("text") or "")
        return str(raw or "")


def _record_raw_text(self, text):  # noqa: ANN001 - 绑定到替身用
    self.raw_texts.append(text)


def _patch_script_llm_deps(monkeypatch, llm, *, knowledge=None, script=None):
    """把 peer_script_llm 的所有外部依赖替换成替身。

    peer_script_llm 内部是"函数体内 import"，所以必须 patch 源模块上的符号。
    """
    import clients.bots.qq.peer_chat as peer_chat_module
    from core.services.active_care.peer_chat import peer_knowledge

    # LLM 模块入口
    monkeypatch.setattr(
        peer_script_llm_module(), "get_llm_module", lambda: llm
    )

    # 模型路径解析：直接给一个哨兵值，避免读真实配置
    import config.model_config as model_config

    monkeypatch.setattr(
        model_config,
        "resolve_active_care_model_path",
        lambda **kwargs: "stub/script/model",
    )

    # prompt 构造：返回固定结构，避免拼装真实 prompt（也避免读人设文件）
    class _Prompt:
        system_prompt = "SYSTEM"
        user_prompt = "USER"

    import core.agents.chat_agent_components.persona_system.prompt.qq_peer_context as qq_prompt

    monkeypatch.setattr(
        qq_prompt,
        "build_script_generation_prompt",
        lambda **kwargs: _Prompt(),
    )

    # 知识分桶与校验：默认放行（校验逻辑另有专门用例）
    monkeypatch.setattr(
        peer_knowledge,
        "build_knowledge_buckets",
        lambda **kwargs: knowledge if knowledge is not None else {"role_id": "aveline", "peer_role_id": "ling"},
    )
    if script is not None:
        # parse_script 走替身，直接给出目标剧本
        monkeypatch.setattr(
            peer_chat_module.PeerChatManager,
            "parse_script",
            staticmethod(lambda raw: list(script)),
        )
    # 双角色配置读取
    import core.utils.config_accessor as config_accessor

    monkeypatch.setattr(
        config_accessor,
        "get_dual_role_config",
        lambda key, default=None, settings=None: default,
    )


def peer_script_llm_module():
    from core.services.active_care.peer_chat import peer_script_llm

    return peer_script_llm


def _make_generator():
    """构造带替身宿主的生成器。"""
    host = _ScriptHost()
    host.record_raw_text = _record_raw_text.__get__(host)
    return PeerScriptLLMGenerator(host), host


CONTEXT = {
    "recent_master_history": "",
    "recent_peer_scripts": "",
    "time_str": "2026-09-22 10:00",
    "bio_state": None,
    "peer_bio_state": None,
    "master_history_by_role": {},
}

BASE_KWARGS = {
    "role_id": "aveline",
    "peer_role_id": "ling",
    "role_name": "七濑 Aveline",
    "peer_name": "Ling",
    "topic": "周末安排",
    "situation": "周六下午",
    "opening_idea": "",
    "context": CONTEXT,
}


class _WaitForRecorder:
    """替换 peer_script_llm 模块内的 asyncio 引用（不动全局 asyncio 模块）。

    - `timeouts`：按调用顺序记录收到的 timeout 实参，用于断言超时转发正确
    - `raise_timeout_on` / `raise_exc_on`：指定第几次调用（0 起）抛超时或指定异常，
      其余调用透传给真实 `asyncio.wait_for`；这样测超时分支不必依赖真实时间流逝。
    """

    # 被测模块用 `except asyncio.TimeoutError` 判断超时，代理必须暴露同一类型
    TimeoutError = asyncio.TimeoutError

    def __init__(self, raise_timeout_on=(), raise_exc_on=None):
        self.timeouts = []
        self._calls = 0
        self._raise_timeout_on = set(raise_timeout_on)
        self._raise_exc_on = dict(raise_exc_on or {})

    async def wait_for(self, coro, timeout=None):
        index = self._calls
        self._calls += 1
        self.timeouts.append(timeout)
        if index in self._raise_timeout_on:
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()
        if index in self._raise_exc_on:
            if hasattr(coro, "close"):
                coro.close()
            raise self._raise_exc_on[index]
        return await asyncio.wait_for(coro, timeout=timeout)

    def __getattr__(self, name):
        """未覆盖的属性透传真实 asyncio，避免代理缺方法。"""
        return getattr(asyncio, name)


# ============================================================
# peer_chat_decision.py
# ============================================================

class TestPeerChatDecider:
    """决策器：正常解析 / 超时降级 / 异常降级 / 社交事件失败不影响主流程。"""

    async def test_decide_parses_llm_json_output(self, monkeypatch):
        """正常返回 JSON 时应解析出 should_send 与 topic。"""
        decider = PeerChatDecider()
        llm = _StubLLM(
            response='{"thought":"聊两句","should_send":true,'
            '"conversation_seed":"周末去哪","trigger":"刚吃完饭"}'
        )
        _patch_decider_deps(monkeypatch, llm)

        result = await decider.decide({}, "aveline", "Ling")
        assert result["should_send"] is True
        assert result["topic"] == "周末去哪"
        assert result["situation"] == "刚吃完饭"
        assert result["intent"] == "peer_chat"

    async def test_decide_timeout_degrades_to_no_send(self, monkeypatch):
        """LLM 超时必须降级为"不发送"，不能让 scheduler 周期被卡死。"""
        decider = PeerChatDecider()
        llm = _StubLLM(exc=asyncio.TimeoutError())
        _patch_decider_deps(monkeypatch, llm)
        # wait_for 会把 TimeoutError 抛出来，走 asyncio.TimeoutError 分支
        monkeypatch.setattr(
            asyncio, "wait_for", _raise_timeout
        )

        result = await decider.decide({}, "aveline", "Ling")
        assert result["should_send"] is False
        assert result["reason_code"] == "llm_timeout"
        assert result["topic"] == ""
        assert result["avoid"] == []

    async def test_decide_timeout_records_metric(self, monkeypatch):
        """超时必须计入 decision_timeout 指标（调参依据）。"""
        from core.services.active_care.peer_chat.peer_chat_metrics import (
            get_peer_chat_metrics,
        )

        metrics = get_peer_chat_metrics()
        metrics.reset()
        decider = PeerChatDecider()
        llm = _StubLLM(exc=asyncio.TimeoutError())
        _patch_decider_deps(monkeypatch, llm)
        monkeypatch.setattr(asyncio, "wait_for", _raise_timeout)

        await decider.decide({}, "aveline", "Ling")
        assert metrics.get_snapshot()["decision_timeout"] >= 1
        metrics.reset()

    async def test_decide_timeout_config_falls_back_when_settings_read_fails(
        self, monkeypatch
    ):
        """读决策超时配置失败时必须回退 20 秒，而不是让异常冒泡。

        注意 get_settings 在 peer_chat_decision 里是**模块级导入**，必须 patch 该模块上的
        名字；patch config.integrated_config 上的同名函数不会影响已绑定的引用。
        另外 __init__ 也会读一次配置，所以要先构造 decider 再打桩。
        """
        from core.services.active_care.peer_chat import peer_chat_decision

        decider = PeerChatDecider()
        llm = _StubLLM(response="{}")
        _patch_decider_deps(monkeypatch, llm)

        calls = []

        def _boom():
            calls.append(1)
            raise RuntimeError("配置未初始化")

        monkeypatch.setattr(peer_chat_decision, "get_settings", _boom)

        proxy = _WaitForRecorder(raise_timeout_on={0})
        monkeypatch.setattr(peer_chat_decision, "asyncio", proxy)

        result = await decider.decide({}, "aveline", "Ling")
        # 证明真的走了"读配置失败"这条分支，而不是恰好读到同值的真实配置
        assert calls == [1]
        assert proxy.timeouts == [20.0]
        assert result["reason_code"] == "llm_timeout"

    async def test_decide_timeout_swallows_metrics_failure(self, monkeypatch):
        """超时路径里指标模块不可用时，仍应正常降级为不发送。"""
        from core.services.active_care.peer_chat import (
            peer_chat_decision,
            peer_chat_metrics,
        )

        decider = PeerChatDecider()
        llm = _StubLLM(response="{}")
        _patch_decider_deps(monkeypatch, llm)

        proxy = _WaitForRecorder(raise_timeout_on={0})
        monkeypatch.setattr(peer_chat_decision, "asyncio", proxy)

        def _boom():
            raise RuntimeError("指标模块不可用")

        monkeypatch.setattr(peer_chat_metrics, "get_peer_chat_metrics", _boom)

        result = await decider.decide({}, "aveline", "Ling")
        assert result["should_send"] is False
        assert result["reason_code"] == "llm_timeout"

    async def test_decide_exception_degrades_to_no_send(self, monkeypatch):
        """LLM 抛非超时异常时同样降级为不发送，并给出 decision_error。"""
        decider = PeerChatDecider()
        llm = _StubLLM(exc=RuntimeError("模型不可用"))
        _patch_decider_deps(monkeypatch, llm)

        result = await decider.decide({}, "aveline", "Ling")
        assert result["should_send"] is False
        assert result["reason_code"] == "decision_error"
        assert "模型不可用" in result["reason"]

    async def test_decide_handles_dict_response_shape(self, monkeypatch):
        """LLM 返回 dict（含 response 字段）时也要能解析。"""
        decider = PeerChatDecider()
        llm = _StubLLM(
            response={"response": '{"should_send":true,"conversation_seed":"天气"}'}
        )
        _patch_decider_deps(monkeypatch, llm)

        result = await decider.decide({}, "aveline", "Ling")
        assert result["should_send"] is True
        assert result["topic"] == "天气"

    async def test_decide_social_event_failure_is_swallowed(self, monkeypatch):
        """社交事件引擎挂掉不得影响决策主流程（降级为空 hint）。"""
        decider = PeerChatDecider()
        llm = _StubLLM(response='{"should_send":true}')
        _patch_decider_deps(monkeypatch, llm, social_events_boom=True)

        result = await decider.decide({}, "aveline", "Ling")
        assert result["should_send"] is True

    async def test_decide_reads_nested_life_energy_and_mood(self, monkeypatch):
        """bio_state 的 life 子字典优先于顶层（结构兼容性）。"""
        decider = PeerChatDecider()
        llm = _StubLLM(response='{"should_send":false}')
        captured = {}
        _patch_decider_deps(monkeypatch, llm, capture_prompt=captured)

        context = {
            "now": "2026-09-22 10:00:00",
            "bio_state": {"life": {"energy": 12.0, "mood": "低落"}},
            "elapsed_seconds": 3600,
        }
        await decider.decide(context, "aveline", "Ling")
        assert captured["energy"] == 12.0
        assert captured["mood"] == "低落"
        assert captured["elapsed_seconds"] == 3600


async def _raise_timeout(coro, timeout=None):  # noqa: ANN001
    """替身 asyncio.wait_for：总是抛超时（用于确定性验证超时分支）。"""
    if hasattr(coro, "close"):
        coro.close()
    raise asyncio.TimeoutError()


def _patch_decider_deps(
    monkeypatch, llm, *, social_events_boom=False, capture_prompt=None
):
    """替换 PeerChatDecider 的全部外部依赖。"""
    from core.services.active_care.peer_chat import peer_chat_decision as decider_module

    monkeypatch.setattr(decider_module, "get_llm_module", lambda: llm)

    import config.model_config as model_config

    monkeypatch.setattr(
        model_config,
        "resolve_active_care_model_path",
        lambda **kwargs: "stub/decision/model",
    )

    class _Prompt:
        system_prompt = "SYS"
        user_prompt = "USR"

    import core.agents.chat_agent_components.persona_system.prompt.qq_peer_context as qq_prompt

    def _build_prompt(**kwargs):
        if capture_prompt is not None:
            capture_prompt.update(kwargs)
        return _Prompt()

    monkeypatch.setattr(
        qq_prompt, "build_peer_chat_decision_prompt", _build_prompt
    )

    if social_events_boom:
        import core.services.dual_role.social_events as social_module

        def _boom():
            raise RuntimeError("社交事件引擎不可用")

        monkeypatch.setattr(
            social_module, "get_social_event_engine", _boom
        )


# ============================================================
# peer_script_llm.py
# ============================================================

SIMPLE_SCRIPT = [
    {"role": "aveline", "content": "周末去哪"},
    {"role": "ling", "content": "还没想好"},
]


class TestPeerScriptLLMGenerator:
    """剧本生成：成功路径、超时、轮数越界、解析失败重试。"""

    async def test_generate_returns_script_on_success(self, monkeypatch):
        """正常返回可解析剧本时，直接返回该剧本并计数 scripts_generated。"""
        from core.services.active_care.peer_chat.peer_chat_metrics import (
            get_peer_chat_metrics,
        )

        metrics = get_peer_chat_metrics()
        metrics.reset()
        generator, host = _make_generator()
        llm = _StubLLM(response='{"script":[{"role":"aveline","content":"周末去哪"}]}')
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)

        result = await generator.generate(**BASE_KWARGS)
        assert result == SIMPLE_SCRIPT
        assert metrics.get_snapshot()["scripts_generated"] >= 1
        metrics.reset()

    async def test_generate_records_raw_text_for_negotiation(self, monkeypatch):
        """生成成功后必须把原文写回宿主，供协商模式主入口解析分工结果。"""
        generator, host = _make_generator()
        llm = _StubLLM(response="RAW_SCRIPT_TEXT")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)

        await generator.generate(**BASE_KWARGS)
        assert host.raw_texts == ["RAW_SCRIPT_TEXT"]

    async def test_generate_timeout_returns_empty_and_records_metric(
        self, monkeypatch
    ):
        """LLM 超时返回空列表，并计入 script_llm_timeout 指标。"""
        from core.services.active_care.peer_chat.peer_chat_metrics import (
            get_peer_chat_metrics,
        )

        metrics = get_peer_chat_metrics()
        metrics.reset()
        generator, _ = _make_generator()
        llm = _StubLLM(exc=asyncio.TimeoutError())
        _patch_script_llm_deps(monkeypatch, llm)
        monkeypatch.setattr(asyncio, "wait_for", _raise_timeout)

        result = await generator.generate(**BASE_KWARGS)
        assert result == []
        assert metrics.get_snapshot()["script_llm_timeout"] >= 1
        metrics.reset()

    async def test_generate_empty_response_returns_empty(self, monkeypatch):
        """LLM 返回空文本时返回空列表，不发空剧本给客户端。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="   ")
        _patch_script_llm_deps(monkeypatch, llm)

        result = await generator.generate(**BASE_KWARGS)
        assert result == []

    async def test_generate_enforce_round_limit_drops_overlong_script(
        self, monkeypatch
    ):
        """轮数超过 6 时按解析失败丢弃（enforce_round_limit 默认 True）。"""
        from core.services.active_care.peer_chat.peer_chat_metrics import (
            get_peer_chat_metrics,
        )

        metrics = get_peer_chat_metrics()
        metrics.reset()
        generator, _ = _make_generator()
        overlong = [
            {"role": "aveline" if i % 2 == 0 else "ling", "content": f"第{i}句"}
            for i in range(8)
        ]
        llm = _StubLLM(response="x")
        # parse_script 持续返回越界剧本 → 重试后仍越界 → 最终空列表
        _patch_script_llm_deps(monkeypatch, llm, script=overlong)

        result = await generator.generate(**BASE_KWARGS)
        assert result == []
        assert metrics.get_snapshot()["parse_retries"] >= 1
        metrics.reset()

    async def test_generate_allows_overlong_when_round_limit_disabled(
        self, monkeypatch
    ):
        """enforce_round_limit=False 时不限制轮数（供评估脚本观察模型真实轮数）。"""
        generator, _ = _make_generator()
        overlong = [
            {"role": "aveline" if i % 2 == 0 else "ling", "content": f"第{i}句"}
            for i in range(8)
        ]
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=overlong)

        result = await generator.generate(
            **BASE_KWARGS, enforce_round_limit=False
        )
        assert result == overlong

    async def test_generate_drops_script_with_knowledge_violation(
        self, monkeypatch
    ):
        """知识防火墙判定越权时丢弃剧本（触发重试，重试仍越权则空列表）。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)

        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge,
            "validate_peer_script",
            lambda *a, **k: ["第1条越权：提到对方私有状态"],
        )

        result = await generator.generate(**BASE_KWARGS)
        assert result == []

    async def test_generate_retry_path_succeeds_after_parse_failure(
        self, monkeypatch
    ):
        """首次解析失败但重试成功时返回重试得到的剧本。

        实现方式：让 parse_script 第一次返回空、第二次返回可用剧本。
        """
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm)

        import clients.bots.qq.peer_chat as peer_chat_module

        calls = {"n": 0}

        def _flaky_parse(raw):
            calls["n"] += 1
            return [] if calls["n"] == 1 else list(SIMPLE_SCRIPT)

        monkeypatch.setattr(
            peer_chat_module.PeerChatManager,
            "parse_script",
            staticmethod(_flaky_parse),
        )
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        result = await generator.generate(**BASE_KWARGS)
        assert result == SIMPLE_SCRIPT
        assert calls["n"] >= 2

    async def test_generate_negotiation_mode_appends_assignment_suffix(
        self, monkeypatch
    ):
        """协商模式下 user_prompt 必须追加分工输出格式要求，否则解析不到分工。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        reminders = [{"reminder_id": "r1", "title": "吃药提醒"}]
        await generator.generate(**BASE_KWARGS, negotiation_reminders=reminders)

        sent_user_prompt = llm.calls[-1]["messages"][1]["content"]
        assert "<assignment>" in sent_user_prompt
        assert "吃药提醒" in sent_user_prompt

    async def test_generate_without_negotiation_has_no_assignment_block(
        self, monkeypatch
    ):
        """普通模式不得混入协商输出格式（会让模型输出多余 JSON 块）。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        await generator.generate(**BASE_KWARGS)
        sent_user_prompt = llm.calls[-1]["messages"][1]["content"]
        assert "<assignment>" not in sent_user_prompt

    async def test_generate_uses_system_user_message_split(self, monkeypatch):
        """messages 必须是 system + user 两条（static/dynamic 分离命中 prompt 缓存）。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        await generator.generate(**BASE_KWARGS)
        messages = llm.calls[-1]["messages"]
        assert [m["role"] for m in messages] == ["system", "user"]
        assert messages[0]["content"] == "SYSTEM"

    async def test_generate_proactive_assignment_mode_appends_suffix(
        self, monkeypatch
    ):
        """主动关怀时段分工模式：必须追加时段划分后缀，并把双方状态原样透传。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        import core.services.active_care.prompt.proactive_assignment_prompts as prompts

        captured = {}

        def _build_suffix(**kwargs):
            captured.update(kwargs)
            return "\n\nPROACTIVE_SUFFIX\n"

        monkeypatch.setattr(
            prompts, "build_proactive_assignment_negotiation_suffix", _build_suffix
        )

        await generator.generate(
            **BASE_KWARGS,
            proactive_assignment_mode=True,
            aveline_state="工作中",
            ling_state="休息中",
            role_states={"aveline": "工作中"},
        )

        sent_user_prompt = llm.calls[-1]["messages"][1]["content"]
        assert "PROACTIVE_SUFFIX" in sent_user_prompt
        # 三个状态参数必须原样传到后缀构造函数，不能被吞掉
        assert captured == {
            "aveline_state": "工作中",
            "ling_state": "休息中",
            "role_states": {"aveline": "工作中"},
        }

    async def test_generate_timeout_config_falls_back_when_settings_read_fails(
        self, monkeypatch
    ):
        """读超时配置抛异常时必须回退到 45 秒，而不是让异常冒泡。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        import config.integrated_config as integrated_config

        def _boom():
            raise RuntimeError("配置未初始化")

        monkeypatch.setattr(integrated_config, "get_settings", _boom)

        proxy = _WaitForRecorder()
        monkeypatch.setattr(peer_script_llm_module(), "asyncio", proxy)

        result = await generator.generate(**BASE_KWARGS)
        assert result == SIMPLE_SCRIPT
        assert proxy.timeouts == [45.0]

    async def test_generate_llm_failure_falls_back_to_deepseek(
        self, monkeypatch
    ):
        """主 LLM 抛非超时异常时回退到 DeepSeekClient，回退成功仍返回剧本。"""
        generator, _ = _make_generator()
        llm = _StubLLM(exc=RuntimeError("主 LLM 挂了"))
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )
        monkeypatch.setenv("DEEPSEEK_API_KEY_QQBOT1", "sk-test")

        import core.llm.openai_compat.deepseek_client as deepseek_client

        created = {}
        chat_kwargs = []

        class _FallbackLLM:
            """替身回退客户端：记录构造参数与调用参数。"""

            def __init__(self, **kwargs):
                created.update(kwargs)

            async def chat(self, messages, **kwargs):
                chat_kwargs.append(kwargs)
                return "FALLBACK_TEXT"

        monkeypatch.setattr(deepseek_client, "DeepSeekClient", _FallbackLLM)

        result = await generator.generate(**BASE_KWARGS)
        assert result == SIMPLE_SCRIPT
        assert created["model"] == "deepseek-v4-flash"
        assert created["api_key"] == "sk-test"
        assert chat_kwargs == [{"temperature": 0.9, "max_tokens": 800}]

    async def test_generate_llm_failure_without_fallback_key_raises(
        self, monkeypatch
    ):
        """无回退 API Key 时必须显式报错，而不是静默返回空剧本。"""
        generator, _ = _make_generator()
        llm = _StubLLM(exc=RuntimeError("主 LLM 挂了"))
        _patch_script_llm_deps(monkeypatch, llm)
        monkeypatch.delenv("DEEPSEEK_API_KEY_QQBOT1", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        with pytest.raises(RuntimeError, match="无回退 API Key"):
            await generator.generate(**BASE_KWARGS)

    async def test_generate_logs_raw_preview_when_debug_enabled(
        self, monkeypatch
    ):
        """debug.peer_chat 打开时应输出原文预览（默认不落盘）。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="RAW")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        module = peer_script_llm_module()
        monkeypatch.setattr(module, "is_debug_enabled", lambda key: True)

        logged = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    logged.append((name, args))

                return _record

        monkeypatch.setattr(module, "logger", _Logger())

        await generator.generate(**BASE_KWARGS)
        assert any("raw_preview" in str(args) for _, args in logged)

    async def test_generate_swallows_metrics_failure_on_timeout(
        self, monkeypatch
    ):
        """超时路径里指标模块不可用时，仍应返回空剧本。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm)

        proxy = _WaitForRecorder(raise_timeout_on={0})
        monkeypatch.setattr(peer_script_llm_module(), "asyncio", proxy)

        from core.services.active_care.peer_chat import peer_chat_metrics

        def _boom():
            raise RuntimeError("指标模块不可用")

        monkeypatch.setattr(peer_chat_metrics, "get_peer_chat_metrics", _boom)

        result = await generator.generate(**BASE_KWARGS)
        assert result == []
        assert len(proxy.timeouts) == 1

    async def test_generate_swallows_metrics_failure_on_parse_retry(
        self, monkeypatch
    ):
        """解析失败重试路径里指标模块不可用时，仍应走完重试并返回空剧本。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        # parse 恒返回空 → 必然进入重试分支
        _patch_script_llm_deps(monkeypatch, llm, script=[])

        from core.services.active_care.peer_chat import peer_chat_metrics

        def _boom():
            raise RuntimeError("指标模块不可用")

        monkeypatch.setattr(peer_chat_metrics, "get_peer_chat_metrics", _boom)

        result = await generator.generate(**BASE_KWARGS)
        assert result == []

    async def test_generate_swallows_metrics_failure_on_success(
        self, monkeypatch
    ):
        """成功路径里指标模块不可用时，仍应正常返回剧本。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=SIMPLE_SCRIPT)
        from core.services.active_care.peer_chat import peer_knowledge

        monkeypatch.setattr(
            peer_knowledge, "validate_peer_script", lambda *a, **k: []
        )

        from core.services.active_care.peer_chat import peer_chat_metrics

        def _boom():
            raise RuntimeError("指标模块不可用")

        monkeypatch.setattr(peer_chat_metrics, "get_peer_chat_metrics", _boom)

        result = await generator.generate(**BASE_KWARGS)
        assert result == SIMPLE_SCRIPT

    async def test_generate_retry_exception_is_logged_and_returns_empty(
        self, monkeypatch
    ):
        """重试阶段抛异常时应记日志并返回空剧本，不让异常冒泡。"""
        generator, _ = _make_generator()
        llm = _StubLLM(response="x")
        _patch_script_llm_deps(monkeypatch, llm, script=[])

        module = peer_script_llm_module()
        # 第 0 次 wait_for 是主调用（正常返回），第 1 次是重试（抛异常）
        proxy = _WaitForRecorder(raise_exc_on={1: RuntimeError("重试失败")})
        monkeypatch.setattr(module, "asyncio", proxy)

        result = await generator.generate(**BASE_KWARGS)
        assert result == []
        assert len(proxy.timeouts) == 2


# ============================================================
# peer_script_dispatch.py
# ============================================================

class _StubAvelineService:
    """替身 AvelineService：记录 dispatch 调用，可编程 delivered。"""

    def __init__(self, delivered=True):
        self.calls = []
        self._delivered = delivered

    async def dispatch_proactive_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"delivered": self._delivered}


def _patch_dispatch_deps(monkeypatch, service):
    """替换 dispatch 依赖的 AvelineService 与 cid 构造函数。"""
    import core.core_engine.service_singletons as singletons

    monkeypatch.setattr(
        singletons, "get_aveline_service", lambda: service
    )
    import clients.bots.qq.utils as qq_utils

    monkeypatch.setattr(
        qq_utils,
        "build_persona_conversation_id",
        lambda base, persona_fn: f"{base}__{persona_fn}",
    )


DISPATCH_CFG = {
    "master_qq_id": "10001",
    "role_persona_fn": "core_aveline.json",
    "peer_persona_fn": "core_ling.json",
    "role_name": "七濑 Aveline",
    "peer_name": "Ling",
    "role_qq_id": "111",
    "peer_role_qq_id": "222",
}


class TestDispatchScript:
    """剧本分发：路由、目标 QQ、mention_user、AvelineService 缺失。"""

    async def test_dispatch_returns_false_when_service_missing(self, monkeypatch):
        """AvelineService 不可用时返回 (False, False, "")，不抛异常。"""
        import core.core_engine.service_singletons as singletons

        monkeypatch.setattr(singletons, "get_aveline_service", lambda: None)

        sent, notify, content = await peer_script_dispatch.dispatch_script(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert (sent, notify, content) == (False, False, "")

    async def test_dispatch_logs_routing_and_delay_when_debug_enabled(
        self, monkeypatch
    ):
        """debug.peer_script 打开时，两条路由分支与消息间延迟都要落日志。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        monkeypatch.setattr(
            peer_script_dispatch, "is_debug_enabled", lambda key: True
        )
        logged = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    logged.append((name, args))

                return _record

        monkeypatch.setattr(peer_script_dispatch, "logger", _Logger())

        # 冻结消息间延迟，避免用例真等若干秒
        import clients.bots.qq.peer_chat as peer_chat_module

        monkeypatch.setattr(
            peer_chat_module.PeerChatManager,
            "calc_message_delay",
            staticmethod(lambda content: 0.0),
        )

        sent, _notify, _content = await peer_script_dispatch.dispatch_script(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )

        assert sent is True
        texts = [str(args) for _, args in logged]
        # SIMPLE_SCRIPT 两条（aveline / ling）各命中一条分支日志
        assert sum(1 for t in texts if "剧本分发" in t) == 2
        # 只有非末句才需要延迟日志（2 条 → 1 次）
        assert sum(1 for t in texts if "剧本延迟" in t) == 1

    async def test_dispatch_routes_each_line_to_correct_conversation(
        self, monkeypatch
    ):
        """每一行按 line_role 路由到对应角色的 conversation 与目标 QQ。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        sent, _, _ = await peer_script_dispatch.dispatch_script(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert sent is True
        assert len(service.calls) == 2

        first = service.calls[0]
        assert first["target_conversation_id"] == "private_10001__core_aveline.json"
        assert first["extra_payload"]["target_qq_id"] == "222"  # 发给对方
        assert first["extra_payload"]["role_id"] == "aveline"

        second = service.calls[1]
        assert second["target_conversation_id"] == "private_10001__core_ling.json"
        assert second["extra_payload"]["target_qq_id"] == "111"  # 发回发起方
        assert second["extra_payload"]["role_id"] == "ling"

    async def test_dispatch_marks_peer_speaker_in_payload(self, monkeypatch):
        """说话者信息走 extra_payload.peer_speaker，不塞进 content（省 token）。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        await peer_script_dispatch.dispatch_script(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        # content 保持纯台词
        assert service.calls[0]["content"] == "周末去哪"
        assert service.calls[0]["extra_payload"]["peer_speaker"] == "七濑 Aveline"
        assert service.calls[1]["extra_payload"]["peer_speaker"] == "Ling"

    async def test_dispatch_skips_lines_with_unknown_role(self, monkeypatch):
        """role 不在双方之间的行被跳过（不广播给无关角色）。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        script = [
            {"role": "aveline", "content": "正常"},
            {"role": "ye", "content": "不该出现"},
        ]
        await peer_script_dispatch.dispatch_script(
            script=script, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert len(service.calls) == 1
        assert service.calls[0]["content"] == "正常"

    async def test_dispatch_skips_empty_content_lines(self, monkeypatch):
        """空 content 行直接跳过，不产生空消息。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        script = [
            {"role": "aveline", "content": "   "},
            {"role": "ling", "content": "有内容"},
        ]
        await peer_script_dispatch.dispatch_script(
            script=script, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert len(service.calls) == 1

    async def test_dispatch_sets_notify_only_for_last_line_mention(
        self, monkeypatch
    ):
        """仅当最后一行 mention_user 时才通知主人（避免中途刷屏）。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        script = [
            {"role": "aveline", "content": "第一句", "mention_user": True},
            {"role": "ling", "content": "最后一句", "mention_user": True},
        ]
        _, notify, content = await peer_script_dispatch.dispatch_script(
            script=script, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert notify is True
        assert content == "最后一句"

    async def test_dispatch_no_notify_when_mention_not_last(self, monkeypatch):
        """mention 出现在非末句时不触发通知。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        script = [
            {"role": "aveline", "content": "第一句", "mention_user": True},
            {"role": "ling", "content": "最后一句", "mention_user": False},
        ]
        _, notify, content = await peer_script_dispatch.dispatch_script(
            script=script, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert notify is False
        assert content == ""

    async def test_dispatch_not_delivered_reports_false(self, monkeypatch):
        """全部投递失败时 sent_any 为 False（调度器据此不记成功）。"""
        service = _StubAvelineService(delivered=False)
        _patch_dispatch_deps(monkeypatch, service)

        sent, _, _ = await peer_script_dispatch.dispatch_script(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert sent is False

    async def test_dispatch_broadcasts_original_primary_cid(self, monkeypatch):
        """广播目标是主人原始 cid，保证消息发到主人所有角色连接。"""
        service = _StubAvelineService()
        _patch_dispatch_deps(monkeypatch, service)

        await peer_script_dispatch.dispatch_script(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=DISPATCH_CFG,
        )
        assert service.calls[0]["original_primary_conversation_id"] == "private_10001"
        assert service.calls[0]["client_type"] == "qq"


# ============================================================
# peer_script_hooks.py
# ============================================================

class _StubHookHost:
    """替身 ActiveCareExecutor：记录 write_diary_entry / trigger_message 调用。"""

    def __init__(self):
        self.diary_calls = []
        self.trigger_calls = []

    async def write_diary_entry(self, kind, summary, thought=""):
        self.diary_calls.append({"kind": kind, "summary": summary, "thought": thought})

    async def trigger_message(self, **kwargs):
        self.trigger_calls.append(kwargs)


def _patch_hook_deps(monkeypatch, *, append_calls=None, heal_service=None):
    """替换 hooks 依赖的 AvelineService 与巡检服务。"""
    import core.core_engine.service_singletons as singletons

    class _Service:
        async def append_proactive_message(self, **kwargs):
            if append_calls is not None:
                append_calls.append(kwargs)

    monkeypatch.setattr(singletons, "get_aveline_service", lambda: _Service())

    import core.services.auto_heal.heal_service as heal_module

    monkeypatch.setattr(
        heal_module, "get_auto_heal_service", lambda: heal_service
    )


HOOK_CFG = {
    "role_name": "七濑 Aveline",
    "peer_name": "Ling",
    "role_persona_fn": "core_aveline.json",
}


class TestRunPeerPostHooks:
    """分发后副作用：日记、剧本记录、主人通知。"""

    async def test_hooks_write_diary_entry(self, monkeypatch):
        """必须写一条 peer_chat 日记，含轮数与对方名字。"""
        host = _StubHookHost()
        _patch_hook_deps(monkeypatch)

        await peer_script_hooks.run_peer_post_hooks(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=HOOK_CFG, should_notify_user=False, notify_content="", host=host,
        )
        assert len(host.diary_calls) == 1
        entry = host.diary_calls[0]
        assert entry["kind"] == "peer_chat"
        assert "Ling" in entry["summary"]
        assert "2" in entry["summary"]  # 2 轮

    async def test_hooks_save_script_to_peer_conversation(self, monkeypatch):
        """剧本逐条落到 peer_{role_id} 会话，带说话者标签。"""
        host = _StubHookHost()
        appends = []
        _patch_hook_deps(monkeypatch, append_calls=appends)

        await peer_script_hooks.run_peer_post_hooks(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=HOOK_CFG, should_notify_user=False, notify_content="", host=host,
        )
        assert len(appends) == 2
        assert all(c["conversation_id"] == "peer_aveline" for c in appends)
        assert appends[0]["content"] == "七濑 Aveline: 周末去哪"
        assert appends[1]["content"] == "Ling: 还没想好"

    async def test_hooks_skip_empty_content_lines_when_saving(self, monkeypatch):
        """保存剧本记录时跳过空 content 行。"""
        host = _StubHookHost()
        appends = []
        _patch_hook_deps(monkeypatch, append_calls=appends)

        script = [
            {"role": "aveline", "content": "有内容"},
            {"role": "ling", "content": ""},
        ]
        await peer_script_hooks.run_peer_post_hooks(
            script=script, role_id="aveline", peer_role_id="ling",
            cfg=HOOK_CFG, should_notify_user=False, notify_content="", host=host,
        )
        assert len(appends) == 1

    async def test_hooks_trigger_message_when_notify_required(self, monkeypatch):
        """should_notify_user=True 时必须触发主动关怀，并带上对方名字与内容。"""
        host = _StubHookHost()
        _patch_hook_deps(monkeypatch)

        await peer_script_hooks.run_peer_post_hooks(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=HOOK_CFG, should_notify_user=True,
            notify_content="问主人周末有没有空", host=host,
        )
        assert len(host.trigger_calls) == 1
        call = host.trigger_calls[0]
        assert call["sys_prompt_type"] == "share_peer_chat"
        assert "Ling" in call["user_input_mock"]
        assert "问主人周末有没有空" in call["user_input_mock"]
        assert call["persona_filename"] == "core_aveline.json"

    async def test_hooks_no_trigger_when_notify_not_required(self, monkeypatch):
        """不需要通知主人时绝不触发主动关怀（避免无意义打扰）。"""
        host = _StubHookHost()
        _patch_hook_deps(monkeypatch)

        await peer_script_hooks.run_peer_post_hooks(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=HOOK_CFG, should_notify_user=False, notify_content="", host=host,
        )
        assert host.trigger_calls == []

    async def test_hooks_survive_script_record_failure(self, monkeypatch):
        """保存剧本记录失败不得中断 hooks（日记已写、通知仍应尝试）。"""
        host = _StubHookHost()

        import core.core_engine.service_singletons as singletons

        class _BadService:
            async def append_proactive_message(self, **kwargs):
                raise RuntimeError("存储不可用")

        monkeypatch.setattr(singletons, "get_aveline_service", lambda: _BadService())
        import core.services.auto_heal.heal_service as heal_module

        monkeypatch.setattr(
            heal_module, "get_auto_heal_service", lambda: None
        )

        # 不抛异常即为通过
        await peer_script_hooks.run_peer_post_hooks(
            script=SIMPLE_SCRIPT, role_id="aveline", peer_role_id="ling",
            cfg=HOOK_CFG, should_notify_user=True, notify_content="x", host=host,
        )
        assert len(host.diary_calls) == 1
        assert len(host.trigger_calls) == 1


class TestBuildPatrolPersona:
    """巡检角色上下文构建。"""

    def test_patrol_persona_falls_back_on_error(self, monkeypatch):
        """人设管理器不可用时返回兜底文案，绝不抛异常。"""
        import core.character.managers.persona_manager as pm_module

        def _boom():
            raise RuntimeError("人设系统未就绪")

        monkeypatch.setattr(pm_module, "get_persona_manager", _boom)
        result = peer_script_hooks.build_patrol_persona("aveline", "七濑 Aveline")
        assert "七濑 Aveline" in result
        assert "巡检" in result

    def test_patrol_persona_uses_role_name_fallback(self):
        """兜底文案里必须出现传入的角色名（不能残留硬编码的名字）。"""
        result = peer_script_hooks.build_patrol_persona("ling", "Ling")
        assert "Ling" in result
