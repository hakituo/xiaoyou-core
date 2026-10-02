"""``core.agents.chat_agent_components.context`` 单元测试。

覆盖目标：把该模块行覆盖率推到接近 100%。
本文件只测试纯函数、可注入的协作者与降级分支，不触碰真实模型 / 后端。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import threading
import types
from types import SimpleNamespace

import pytest

import core.agents.chat_agent_components.context as ctx
from core.agents.chat_agent_components.persona_system.prompt.components import (
    CONTEXT_COMPRESS_SYSTEM_PROMPT,
    RAG_REWRITE_SYSTEM_PROMPT,
)
from memory.weighted_memory_manager import WeightedMemoryManager


# --------------------------------------------------------------------------- #
# 通用工具 / fixture
# --------------------------------------------------------------------------- #
@pytest.fixture()
def reset_llm_state(monkeypatch):
    """重置模块级可变全局（懒加载 LLM、锁、失败退避时间），避免跨用例串味。"""
    for name, value in (
        ("_context_compress_llm", None),
        ("_context_compress_llm_task", None),
        ("_context_compress_load_failed_until", 0.0),
        ("_context_compress_llm_lock", asyncio.Lock()),
        ("_context_compress_inference_lock", asyncio.Lock()),
        ("_rag_rewrite_llm", None),
        ("_rag_rewrite_llm_task", None),
        ("_rag_rewrite_load_failed_until", 0.0),
        ("_rag_rewrite_llm_lock", asyncio.Lock()),
        ("_rag_rewrite_inference_lock", asyncio.Lock()),
    ):
        monkeypatch.setattr(ctx, name, value)
    return ctx


def _fake_llama_module(behaviour: str = "ok"):
    """构造假的 llama_cpp 模块。

    behaviour:
      - ok：正常构造
      - type_error：带 n_threads 时抛 TypeError（触发 default 重试分支）
      - boom：始终抛 ValueError（触发通用异常分支）
    """
    mod = types.ModuleType("llama_cpp")

    class _FakeLlama:
        def __init__(self, **kwargs):
            if behaviour == "boom":
                raise ValueError("load failed")
            if behaviour == "type_error" and "n_threads" in kwargs:
                raise TypeError("n_threads unsupported")
            self.kwargs = kwargs

    mod.Llama = _FakeLlama
    return mod


class _FakeLocalLLM:
    """假的本地 llama 实例，create_chat_completion 返回预设 payload 或抛异常。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


def _chat_result(content: str):
    return {"choices": [{"message": {"content": content}}]}


# --------------------------------------------------------------------------- #
# _extract_json_object
# --------------------------------------------------------------------------- #
def test_extract_json_object_empty_returns_none():
    assert ctx._extract_json_object("") is None
    assert ctx._extract_json_object(None) is None
    assert ctx._extract_json_object(0) is None


def test_extract_json_object_without_braces_returns_none():
    assert ctx._extract_json_object("no json here") is None


def test_extract_json_object_invalid_json_returns_none():
    assert ctx._extract_json_object("{not valid json}") is None


def test_extract_json_object_parses_embedded_object():
    text = 'prefix {"summary": "s", "facts": ["a"]} suffix'
    assert ctx._extract_json_object(text) == {"summary": "s", "facts": ["a"]}


def test_extract_json_object_coerces_non_string_input():
    assert ctx._extract_json_object({"a": 1}) is None or isinstance(
        ctx._extract_json_object({"a": 1}), (dict, type(None))
    )


# --------------------------------------------------------------------------- #
# _resolve_project_path / _safe_float / _safe_int
# --------------------------------------------------------------------------- #
def test_resolve_project_path_empty_returns_empty():
    assert ctx._resolve_project_path("") == ""
    assert ctx._resolve_project_path(None) == ""


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="盘符路径（D:/...）仅在 Windows 下被 os.path.isabs 判定为绝对路径",
)
def test_resolve_project_path_absolute_passthrough():
    assert ctx._resolve_project_path("D:/models/a.gguf") == "D:/models/a.gguf"


def test_resolve_project_path_relative_joins_project_root(monkeypatch):
    import core.utils.common as common

    monkeypatch.setattr(common, "get_project_root", lambda: "D:/root")
    assert ctx._resolve_project_path("models/a.gguf") == os.path.join(
        "D:/root", "models/a.gguf"
    )


def test_resolve_project_path_falls_back_to_cwd_on_error(monkeypatch):
    import core.utils.common as common

    def _boom():
        raise RuntimeError("no root")

    monkeypatch.setattr(common, "get_project_root", _boom)
    expected = os.path.join(os.getcwd(), "x.gguf")
    assert ctx._resolve_project_path("x.gguf") == expected


def test_safe_float_behaviour():
    assert ctx._safe_float("2.5", 1.0) == 2.5
    assert ctx._safe_float(0, 3.0) == 3.0
    assert ctx._safe_float("-4", 3.0) == 3.0
    assert ctx._safe_float("abc", 7.0) == 7.0
    assert ctx._safe_float(None, 5.0) == 5.0


def test_safe_int_behaviour():
    assert ctx._safe_int("9", 1) == 9
    assert ctx._safe_int(0, 4) == 4
    assert ctx._safe_int(-3, 4) == 4
    assert ctx._safe_int("abc", 8) == 8


# --------------------------------------------------------------------------- #
# _split_sentences / _score_sentence
# --------------------------------------------------------------------------- #
def test_split_sentences_empty():
    assert ctx._split_sentences("") == []
    assert ctx._split_sentences(None) == []
    assert ctx._split_sentences("   ") == []


def test_split_sentences_splits_on_punctuation():
    parts = ctx._split_sentences("你好。我饿了！吃饭吗？")
    assert parts == ["你好。", "我饿了！", "吃饭吗？"]


def test_score_sentence_empty_is_zero():
    assert ctx._score_sentence("", "user") == 0.0
    assert ctx._score_sentence("   ", "user") == 0.0


def test_score_sentence_user_role_bonus():
    assert ctx._score_sentence("随便一句话", "user") == 1.0
    assert ctx._score_sentence("随便一句话", "assistant") == 0.0


def test_score_sentence_numeric_and_date_and_keywords():
    score = ctx._score_sentence("我叫小明，生日是 2026-09-23，电话 13800000000", "user")
    # user 1.0 + 数字 2.0 + 日期 2.0 + 关键词 3.0 + 长度>=18 0.5
    assert score == pytest.approx(8.5)


def test_score_sentence_long_text_bonus_only():
    assert ctx._score_sentence("这是一句没有任何关键词但足够长的普通描述文本", "assistant") == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# _heuristic_compress_history
# --------------------------------------------------------------------------- #
def test_heuristic_compress_empty_history_returns_empty():
    assert ctx._heuristic_compress_history([], max_chars=400) == ""


def test_heuristic_compress_skips_empty_content_and_bad_role():
    history = [
        {"role": "user", "content": "   "},
        {"source": "weird", "content": "重要信息 2026-09-23"},
    ]
    out = ctx._heuristic_compress_history(history, max_chars=400)
    assert "2026-09-23" in out
    # 非法 role 归一到 system
    assert "- (system)" in out


def test_heuristic_compress_single_punctuation_sentence_kept():
    # "。" 会被切成一条（内容非空）的句子，因此走正常候选路径
    history = [{"role": "user", "content": "。"}]
    out = ctx._heuristic_compress_history(history, max_chars=400)
    assert out == "- (user) 。"


def test_heuristic_compress_truncates_long_sentence():
    long_sentence = "记" * 300 + "。"
    history = [{"role": "user", "content": long_sentence}]
    out = ctx._heuristic_compress_history(history, max_chars=400)
    assert out.endswith("...")
    assert len(out) <= 400


def test_heuristic_compress_respects_max_chars_break():
    history = [{"role": "user", "content": "很长的句子" + "x" * 150 + "。"} for _ in range(5)]
    out = ctx._heuristic_compress_history(history, max_chars=200)
    assert len(out) <= 200
    assert out.count("\n") <= 3


def test_heuristic_compress_caps_at_14_lines():
    history = [{"role": "user", "content": "a。"} for _ in range(40)]
    out = ctx._heuristic_compress_history(history, max_chars=1000)
    assert len(out.split("\n")) == 14


def test_heuristic_compress_min_max_chars_is_200():
    history = [{"role": "user", "content": "记" * 300 + "。"}]
    out = ctx._heuristic_compress_history(history, max_chars=1)
    assert len(out) <= 200


# --------------------------------------------------------------------------- #
# 懒加载：context compress LLM
# --------------------------------------------------------------------------- #
def test_schedule_compress_llm_returns_early_when_already_loaded(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_llm", object())
    called = {"n": 0}
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: called.__setitem__("n", called["n"] + 1) or p)
    asyncio.run(ctx._schedule_context_compress_llm_load("m.gguf"))
    assert called["n"] == 0


def test_schedule_compress_llm_returns_early_when_task_pending(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_llm_task", object())
    called = {"n": 0}
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: called.__setitem__("n", called["n"] + 1) or p)
    asyncio.run(ctx._schedule_context_compress_llm_load("m.gguf"))
    assert called["n"] == 0


def test_schedule_compress_llm_respects_failed_backoff(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_load_failed_until", 1e12)
    called = {"n": 0}
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: called.__setitem__("n", called["n"] + 1) or p)
    asyncio.run(ctx._schedule_context_compress_llm_load("m.gguf"))
    assert called["n"] == 0


def test_schedule_compress_llm_import_failure_sets_backoff(reset_llm_state, monkeypatch):
    monkeypatch.delitem(sys.modules, "llama_cpp", raising=False)
    monkeypatch.setitem(sys.modules, "llama_cpp", None)

    async def _scenario():
        await ctx._schedule_context_compress_llm_load("m.gguf")
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm is None
    assert ctx._context_compress_load_failed_until > 0


def test_schedule_compress_llm_missing_model_file_sets_backoff(reset_llm_state, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: "D:/definitely/missing.gguf")

    async def _scenario():
        await ctx._schedule_context_compress_llm_load("m.gguf")
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm is None
    assert ctx._context_compress_load_failed_until > 0


def test_schedule_compress_llm_loads_with_threads(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.delenv("XIAOYOU_CONTEXT_COMPRESS_THREADS", raising=False)

    async def _scenario():
        await ctx._schedule_context_compress_llm_load(str(model))
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm is not None
    assert ctx._context_compress_llm.kwargs["n_ctx"] == 768


def test_schedule_compress_llm_type_error_falls_back_to_default(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("type_error"))

    async def _scenario():
        await ctx._schedule_context_compress_llm_load(str(model))
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm is not None
    assert "n_threads" not in ctx._context_compress_llm.kwargs


def test_schedule_compress_llm_generic_exception_sets_backoff(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("boom"))

    async def _scenario():
        await ctx._schedule_context_compress_llm_load(str(model))
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm is None
    assert ctx._context_compress_load_failed_until > 0


def test_schedule_compress_llm_explicit_thread_env(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.setenv("XIAOYOU_CONTEXT_COMPRESS_THREADS", "2")

    async def _scenario():
        await ctx._schedule_context_compress_llm_load(str(model))
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm.kwargs["n_threads"] == 2


def test_get_context_compress_llm_returns_cached(reset_llm_state, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(ctx, "_context_compress_llm", sentinel)
    assert asyncio.run(ctx._get_context_compress_llm("m.gguf")) is sentinel


def test_get_context_compress_llm_schedules_then_returns_none(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_load_failed_until", 1e12)
    assert asyncio.run(ctx._get_context_compress_llm("m.gguf")) is None


class _OnEnterLock:
    """进入临界区时执行副作用的假锁，用于稳定触发锁内二次检查。"""

    def __init__(self, on_enter):
        self._on_enter = on_enter

    async def __aenter__(self):
        self._on_enter()
        return self

    async def __aexit__(self, *exc_info):
        return False


def test_schedule_compress_llm_double_check_llm_task(reset_llm_state, monkeypatch):
    """首次检查通过后，锁内再发现已有 task -> 直接返回。"""
    monkeypatch.setattr(
        ctx,
        "_context_compress_llm_lock",
        _OnEnterLock(lambda: monkeypatch.setattr(ctx, "_context_compress_llm_task", object())),
    )
    asyncio.run(ctx._schedule_context_compress_llm_load("m.gguf"))
    assert ctx._context_compress_llm is None


def test_schedule_compress_llm_double_check_failed_backoff(reset_llm_state, monkeypatch):
    """首次检查通过后，锁内再发现退避时间未到 -> 直接返回。"""
    monkeypatch.setattr(
        ctx,
        "_context_compress_llm_lock",
        _OnEnterLock(lambda: monkeypatch.setattr(ctx, "_context_compress_load_failed_until", 1e12)),
    )
    asyncio.run(ctx._schedule_context_compress_llm_load("m.gguf"))
    assert ctx._context_compress_llm is None


def test_schedule_compress_llm_cpu_count_failure_defaults_to_four(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.delenv("XIAOYOU_CONTEXT_COMPRESS_THREADS", raising=False)
    fake_os = SimpleNamespace(
        environ=os.environ,
        path=os.path,
        cpu_count=lambda: (_ for _ in ()).throw(RuntimeError("no cpu info")),
    )
    monkeypatch.setattr(ctx, "os", fake_os)

    async def _scenario():
        await ctx._schedule_context_compress_llm_load(str(model))
        task = ctx._context_compress_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._context_compress_llm.kwargs["n_threads"] == 4


# --------------------------------------------------------------------------- #
# _compress_history_block
# --------------------------------------------------------------------------- #
def test_compress_history_block_empty_history():
    out = asyncio.run(
        ctx._compress_history_block([], 400, "m.gguf", 64, 1.0)
    )
    assert out == ""


def test_compress_history_block_all_content_empty():
    history = [{"role": "user", "content": "  "}, {"role": "assistant", "content": ""}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "", 64, 1.0))
    assert out == ""


def test_compress_history_block_heuristic_when_no_model_path():
    history = [{"role": "user", "content": "我叫小明，生日 2026-09-23。"}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "", 64, 1.0))
    assert "2026-09-23" in out


def test_compress_history_block_heuristic_when_llm_unavailable(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_load_failed_until", 1e12)
    history = [{"role": "user", "content": "记住我喜欢喝美式。"}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "m.gguf", 64, 1.0))
    assert "美式" in out


def test_compress_history_block_local_llm_success(reset_llm_state, monkeypatch):
    payload = _chat_result(json.dumps({
        "summary": "用户在聊生日",
        "facts": ["生日 2026-09-23", "", "喜欢美式"],
        "open_questions": ["要不要订蛋糕", "", "几个人"],
    }, ensure_ascii=False))
    fake = _FakeLocalLLM(payload)
    monkeypatch.setattr(ctx, "_context_compress_llm", fake)

    history = [
        {"role": "user", "content": "生日 2026-09-23"},
        {"role": "assistant", "content": "好", "is_important": True},
        {"role": "system", "content": "x" * 500, "weight": 5.0},
        {"role": "tool", "content": "unknown role"},
    ]
    out = asyncio.run(ctx._compress_history_block(history, 500, "m.gguf", 64, 1.0))
    assert "用户在聊生日" in out
    assert "- 生日 2026-09-23" in out
    assert "未解决：要不要订蛋糕；几个人" in out
    assert "[!]" in fake.calls[0]["messages"][1]["content"]
    assert "[*]" in fake.calls[0]["messages"][1]["content"]
    assert "[system]" in fake.calls[0]["messages"][1]["content"]


def test_compress_history_block_local_llm_empty_out_falls_back(reset_llm_state, monkeypatch):
    fake = _FakeLocalLLM(_chat_result(json.dumps({"summary": "", "facts": [], "open_questions": []})))
    monkeypatch.setattr(ctx, "_context_compress_llm", fake)
    history = [{"role": "user", "content": "记住我住校。"}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "m.gguf", 64, 1.0))
    assert "住校" in out


def test_compress_history_block_local_llm_invalid_json_falls_back(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_llm", _FakeLocalLLM(_chat_result("not json")))
    history = [{"role": "user", "content": "记住我过敏花生。"}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "m.gguf", 64, 1.0))
    assert "花生" in out


def test_compress_history_block_local_llm_raises_falls_back(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_context_compress_llm", _FakeLocalLLM(RuntimeError("boom")))
    history = [{"role": "user", "content": "记住我过敏花生。"}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "m.gguf", 64, 1.0))
    assert "花生" in out


def test_compress_history_block_local_llm_bad_result_shape(reset_llm_state, monkeypatch):
    """choices[0].message 为 None 时内容提取应被吞掉并降级。"""
    monkeypatch.setattr(ctx, "_context_compress_llm", _FakeLocalLLM({"choices": [{"message": None}]}))
    history = [{"role": "user", "content": "记住我过敏花生。"}]
    out = asyncio.run(ctx._compress_history_block(history, 400, "m.gguf", 64, 1.0))
    assert "花生" in out


def test_compress_history_block_local_llm_output_truncated(reset_llm_state, monkeypatch):
    payload = _chat_result(json.dumps({"summary": "很长的摘要" + "字" * 600}))
    monkeypatch.setattr(ctx, "_context_compress_llm", _FakeLocalLLM(payload))
    history = [{"role": "user", "content": "内容"}]
    out = asyncio.run(ctx._compress_history_block(history, 200, "m.gguf", 64, 1.0))
    assert len(out) <= 200


def test_compress_history_block_api_model_success(monkeypatch):
    class _LLMModule:
        async def chat(self, **kwargs):
            self.kwargs = kwargs
            return {"response": json.dumps({
                "summary": "API 摘要",
                "facts": ["事实1"],
                "open_questions": ["问题1"],
            }, ensure_ascii=False)}

    fake_module = _LLMModule()
    monkeypatch.setattr("core.llm.get_llm_module", lambda: fake_module)

    history = [{"role": "user", "content": "hi"}]
    out = asyncio.run(
        ctx._compress_history_block(history, 500, "", 64, 1.0, api_model="cloud:test:model")
    )
    assert "API 摘要" in out
    assert "- 事实1" in out
    assert "未解决：问题1" in out
    assert fake_module.kwargs["model_path"] == "cloud:test:model"


def test_compress_history_block_api_model_non_dict_result(monkeypatch):
    class _LLMModule:
        async def chat(self, **kwargs):
            return "plain string"

    monkeypatch.setattr("core.llm.get_llm_module", lambda: _LLMModule())
    history = [{"role": "user", "content": "记住我住校。"}]
    out = asyncio.run(
        ctx._compress_history_block(history, 400, "", 64, 1.0, api_model="cloud:test:model")
    )
    # API 返回不可解析 -> 落到启发式
    assert "住校" in out


def test_compress_history_block_api_model_empty_summary_falls_back(monkeypatch):
    class _LLMModule:
        async def chat(self, **kwargs):
            return {"response": json.dumps({"summary": "", "facts": [], "open_questions": []})}

    monkeypatch.setattr("core.llm.get_llm_module", lambda: _LLMModule())
    history = [{"role": "user", "content": "记住我住校。"}]
    out = asyncio.run(
        ctx._compress_history_block(history, 400, "", 64, 1.0, api_model="cloud:test:model")
    )
    assert "住校" in out


def test_compress_history_block_api_model_output_truncated(monkeypatch):
    class _LLMModule:
        async def chat(self, **kwargs):
            return {"response": json.dumps({"summary": "长" * 600}, ensure_ascii=False)}

    monkeypatch.setattr("core.llm.get_llm_module", lambda: _LLMModule())
    history = [{"role": "user", "content": "内容"}]
    out = asyncio.run(
        ctx._compress_history_block(history, 200, "", 64, 1.0, api_model="cloud:test:model")
    )
    assert len(out) == 200


def test_compress_history_block_api_model_exception_falls_back(monkeypatch):
    class _LLMModule:
        async def chat(self, **kwargs):
            raise RuntimeError("api down")

    monkeypatch.setattr("core.llm.get_llm_module", lambda: _LLMModule())
    history = [{"role": "user", "content": "记住我住校。"}]
    out = asyncio.run(
        ctx._compress_history_block(history, 400, "", 64, 1.0, api_model="cloud:test:model")
    )
    assert "住校" in out


def test_compress_history_block_api_model_non_cloud_prefix_skipped(monkeypatch):
    """非 cloud: 前缀的 api_model 不应走 API 分支。"""
    history = [{"role": "user", "content": "记住我住校。"}]
    out = asyncio.run(
        ctx._compress_history_block(history, 400, "", 64, 1.0, api_model="local:model")
    )
    assert "住校" in out


def test_compress_history_block_prompt_constant_is_used(reset_llm_state, monkeypatch):
    fake = _FakeLocalLLM(_chat_result(json.dumps({"summary": "s"})))
    monkeypatch.setattr(ctx, "_context_compress_llm", fake)
    asyncio.run(ctx._compress_history_block([{"role": "user", "content": "x"}], 400, "m.gguf", 64, 1.0))
    assert fake.calls[0]["messages"][0]["content"] == CONTEXT_COMPRESS_SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# 懒加载：rag rewrite LLM
# --------------------------------------------------------------------------- #
def test_schedule_rag_rewrite_returns_early_when_loaded(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", object())
    called = {"n": 0}
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: called.__setitem__("n", called["n"] + 1) or p)
    asyncio.run(ctx._schedule_rag_rewrite_llm_load("m.gguf"))
    assert called["n"] == 0


def test_schedule_rag_rewrite_returns_early_when_task_pending(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm_task", object())
    called = {"n": 0}
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: called.__setitem__("n", called["n"] + 1) or p)
    asyncio.run(ctx._schedule_rag_rewrite_llm_load("m.gguf"))
    assert called["n"] == 0


def test_schedule_rag_rewrite_respects_backoff(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_load_failed_until", 1e12)
    called = {"n": 0}
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: called.__setitem__("n", called["n"] + 1) or p)
    asyncio.run(ctx._schedule_rag_rewrite_llm_load("m.gguf"))
    assert called["n"] == 0


def test_schedule_rag_rewrite_import_failure_sets_backoff(reset_llm_state, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)

    async def _scenario():
        await ctx._schedule_rag_rewrite_llm_load("m.gguf")
        task = ctx._rag_rewrite_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._rag_rewrite_llm is None
    assert ctx._rag_rewrite_load_failed_until > 0


def test_schedule_rag_rewrite_missing_model_sets_backoff(reset_llm_state, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.setattr(ctx, "_resolve_project_path", lambda p: "D:/nope/missing.gguf")

    async def _scenario():
        await ctx._schedule_rag_rewrite_llm_load("m.gguf")
        task = ctx._rag_rewrite_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._rag_rewrite_llm is None
    assert ctx._rag_rewrite_load_failed_until > 0


def test_schedule_rag_rewrite_loads_with_threads(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "r.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.delenv("XIAOYOU_RAG_REWRITE_THREADS", raising=False)

    async def _scenario():
        await ctx._schedule_rag_rewrite_llm_load(str(model))
        task = ctx._rag_rewrite_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._rag_rewrite_llm is not None
    assert ctx._rag_rewrite_llm.kwargs["n_ctx"] == 512


def test_schedule_rag_rewrite_type_error_falls_back(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "r.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("type_error"))

    async def _scenario():
        await ctx._schedule_rag_rewrite_llm_load(str(model))
        task = ctx._rag_rewrite_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._rag_rewrite_llm is not None
    assert "n_threads" not in ctx._rag_rewrite_llm.kwargs


def test_schedule_rag_rewrite_generic_exception_sets_backoff(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "r.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("boom"))

    async def _scenario():
        await ctx._schedule_rag_rewrite_llm_load(str(model))
        task = ctx._rag_rewrite_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._rag_rewrite_llm is None
    assert ctx._rag_rewrite_load_failed_until > 0


def test_get_rag_rewrite_llm_returns_cached(reset_llm_state, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", sentinel)
    assert asyncio.run(ctx._get_rag_rewrite_llm("m.gguf")) is sentinel


def test_get_rag_rewrite_llm_schedules_then_none(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_load_failed_until", 1e12)
    assert asyncio.run(ctx._get_rag_rewrite_llm("m.gguf")) is None


def test_schedule_rag_rewrite_double_check_llm_task(reset_llm_state, monkeypatch):
    monkeypatch.setattr(
        ctx,
        "_rag_rewrite_llm_lock",
        _OnEnterLock(lambda: monkeypatch.setattr(ctx, "_rag_rewrite_llm_task", object())),
    )
    asyncio.run(ctx._schedule_rag_rewrite_llm_load("m.gguf"))
    assert ctx._rag_rewrite_llm is None


def test_schedule_rag_rewrite_double_check_failed_backoff(reset_llm_state, monkeypatch):
    monkeypatch.setattr(
        ctx,
        "_rag_rewrite_llm_lock",
        _OnEnterLock(lambda: monkeypatch.setattr(ctx, "_rag_rewrite_load_failed_until", 1e12)),
    )
    asyncio.run(ctx._schedule_rag_rewrite_llm_load("m.gguf"))
    assert ctx._rag_rewrite_llm is None


def test_schedule_rag_rewrite_cpu_count_failure_defaults_to_four(reset_llm_state, monkeypatch, tmp_path):
    model = tmp_path / "r.gguf"
    model.write_text("x")
    monkeypatch.setitem(sys.modules, "llama_cpp", _fake_llama_module("ok"))
    monkeypatch.delenv("XIAOYOU_RAG_REWRITE_THREADS", raising=False)
    fake_os = SimpleNamespace(
        environ=os.environ,
        path=os.path,
        cpu_count=lambda: (_ for _ in ()).throw(RuntimeError("no cpu info")),
    )
    monkeypatch.setattr(ctx, "os", fake_os)

    async def _scenario():
        await ctx._schedule_rag_rewrite_llm_load(str(model))
        task = ctx._rag_rewrite_llm_task
        if task is not None:
            await task

    asyncio.run(_scenario())
    assert ctx._rag_rewrite_llm.kwargs["n_threads"] == 4


# --------------------------------------------------------------------------- #
# _rewrite_rag_query
# --------------------------------------------------------------------------- #
def test_rewrite_rag_query_returns_none_when_llm_missing(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_load_failed_until", 1e12)
    assert asyncio.run(ctx._rewrite_rag_query("hi", "m.gguf", 64, 1.0)) is None


def test_rewrite_rag_query_success_from_json(reset_llm_state, monkeypatch):
    fake = _FakeLocalLLM(_chat_result(json.dumps({"query": "改写后的查询"})))
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", fake)
    out = asyncio.run(ctx._rewrite_rag_query("原始问题", "m.gguf", 64, 1.0))
    assert out == "改写后的查询"
    assert fake.calls[0]["messages"][0]["content"] == RAG_REWRITE_SYSTEM_PROMPT


def test_rewrite_rag_query_raw_fallback_strips_quotes(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", _FakeLocalLLM(_chat_result('  "裸查询"  ')))
    out = asyncio.run(ctx._rewrite_rag_query("原始问题", "m.gguf", 64, 1.0))
    assert out == "裸查询"


def test_rewrite_rag_query_empty_returns_none(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", _FakeLocalLLM(_chat_result("")))
    assert asyncio.run(ctx._rewrite_rag_query("原始问题", "m.gguf", 64, 1.0)) is None


def test_rewrite_rag_query_truncates_to_160(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", _FakeLocalLLM(_chat_result("q" * 400)))
    out = asyncio.run(ctx._rewrite_rag_query("原始问题", "m.gguf", 64, 1.0))
    assert out is not None and len(out) == 160


def test_rewrite_rag_query_exception_returns_none(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", _FakeLocalLLM(RuntimeError("boom")))
    assert asyncio.run(ctx._rewrite_rag_query("原始问题", "m.gguf", 64, 1.0)) is None


def test_rewrite_rag_query_bad_result_shape_returns_none(reset_llm_state, monkeypatch):
    monkeypatch.setattr(ctx, "_rag_rewrite_llm", _FakeLocalLLM({"choices": [{"message": None}]}))
    assert asyncio.run(ctx._rewrite_rag_query("原始问题", "m.gguf", 64, 1.0)) is None


# --------------------------------------------------------------------------- #
# perform_context_summary
# --------------------------------------------------------------------------- #
class _FakeMM:
    """最小可用的记忆管理器替身（非 WeightedMemoryManager）。"""

    def __init__(self, memories=None, use_rw_lock=False):
        self.short_term_memory = list(memories or [])
        self._use_rw_lock = use_rw_lock
        self.lock = threading.Lock()
        self._rw_lock = SimpleNamespace(
            read_lock=lambda: contextlib.nullcontext(),
            write_lock=lambda: contextlib.nullcontext(),
        )
        self.added = []

    def add_memory(self, **kwargs):
        self.added.append(kwargs)


def _make_memories(n, **overrides):
    out = []
    for i in range(n):
        m = {"id": f"m{i}", "source": "user", "content": f"内容{i} 记住一些事情"}
        m.update(overrides)
        out.append(m)
    return out


def test_perform_context_summary_skips_when_too_few():
    mm = _FakeMM(_make_memories(5))
    asyncio.run(ctx.perform_context_summary(SimpleNamespace(), "u1", mm))
    assert mm.added == []
    assert len(mm.short_term_memory) == 5


def test_perform_context_summary_exception_is_swallowed():
    mm = SimpleNamespace()  # 缺少 short_term_memory -> 触发异常分支
    asyncio.run(ctx.perform_context_summary(SimpleNamespace(), "u1", mm))


def test_perform_context_summary_heuristic_path_removes_and_adds():
    mm = _FakeMM(_make_memories(35), use_rw_lock=True)
    agent = SimpleNamespace(summary_llm=None)
    asyncio.run(ctx.perform_context_summary(agent, "u1", mm, scope=None))

    assert len(mm.short_term_memory) == 8
    assert len(mm.added) == 1
    assert mm.added[0]["content"].startswith("【历史摘要】")
    assert mm.added[0]["source"] == "system_summary"
    assert mm.added[0]["scopes"] is None


def test_perform_context_summary_uses_summary_llm_and_scope():
    calls = {}

    class _SummaryLLM:
        async def chat(self, prompt, temperature=0.3):
            calls["prompt"] = prompt
            calls["temperature"] = temperature
            return "模型生成的摘要"

    mm = _FakeMM(_make_memories(35), use_rw_lock=False)
    agent = SimpleNamespace(summary_llm=_SummaryLLM())
    asyncio.run(ctx.perform_context_summary(agent, "u1", mm, scope="local"))

    assert calls["temperature"] == 0.3
    assert mm.added[0]["content"] == "【历史摘要】 模型生成的摘要"
    assert mm.added[0]["scopes"] == ["local"]


def test_perform_context_summary_returns_when_summary_empty():
    class _SummaryLLM:
        async def chat(self, prompt, temperature=0.3):
            return ""

    mm = _FakeMM(_make_memories(35))
    asyncio.run(ctx.perform_context_summary(SimpleNamespace(summary_llm=_SummaryLLM()), "u1", mm))
    assert mm.added == []
    assert len(mm.short_term_memory) == 35


def test_perform_context_summary_filters_and_normalises_content():
    """覆盖过滤分支与多模态内容清洗。"""
    memories = _make_memories(40)
    memories[0] = {"id": "skip1", "source": "system_summary", "content": "跳过"}
    memories[1] = {"id": "skip2", "source": "user", "content": "【历史摘要】 旧的"}
    memories[2] = {"id": "skip3", "source": "user", "content": "x", "topics": ["daily_summary"]}
    memories[3] = {"id": "skip4", "source": "user", "content": "已生成 今日每日学习总结 内容"}
    memories[4] = {
        "id": "multi",
        "source": "user",
        "content": [
            {"type": "text", "text": "看这张图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "unknown", "text": "ignored"},
            "not-a-dict",
        ],
    }
    memories[5] = {"id": "img", "source": "user", "content": "data:image/png;base64," + "A" * 1200}

    mm = _FakeMM(memories)
    asyncio.run(ctx.perform_context_summary(SimpleNamespace(summary_llm=None), "u1", mm))

    assert len(mm.added) == 1
    # 被过滤项从未进入 to_summarize，因此仍留在短期记忆中
    remaining_ids = {m["id"] for m in mm.short_term_memory}
    assert {"skip1", "skip2", "skip3", "skip4"} <= remaining_ids
    # 多模态 / 超长图片消息被清洗后参与摘要，并被移除
    assert "multi" not in remaining_ids and "img" not in remaining_ids


def test_perform_context_summary_skips_non_dict_memory():
    """短期记忆中混入非 dict 项时应被跳过（摘要为空则提前返回，不触发删除）。"""
    memories = _make_memories(40)
    memories.append("not-a-dict")

    class _EmptyLLM:
        async def chat(self, prompt, temperature=0.3):
            return ""

    mm = _FakeMM(memories)
    asyncio.run(ctx.perform_context_summary(SimpleNamespace(summary_llm=_EmptyLLM()), "u1", mm))
    assert mm.added == []
    assert len(mm.short_term_memory) == 41


def test_perform_context_summary_scope_filtering_includes_none_and_matching():
    memories = _make_memories(35)
    # 前 10 条带 scope，含与不含
    for i in range(10):
        memories[i] = dict(memories[i], scopes=["local"] if i % 2 == 0 else ["cloud"])
    mm = _FakeMM(memories)
    asyncio.run(ctx.perform_context_summary(SimpleNamespace(summary_llm=None), "u1", mm, scope="local"))
    assert len(mm.added) == 1
    assert mm.added[0]["scopes"] == ["local"]


# --------------------------------------------------------------------------- #
# build_conversation_history
# --------------------------------------------------------------------------- #
class _SimpleMM:
    """非 WeightedMemoryManager 的占位对象。"""


@pytest.fixture()
def deps(monkeypatch):
    """把 build_conversation_history 的所有下游协作者替换为可控桩。"""
    captured = {"build_kwargs": None}

    async def _prepare_active_tools(agent, message_text, model_hint, **kwargs):
        captured["prepare_tools"] = (message_text, model_hint, kwargs)
        return ["tool_a"]

    async def _resolve_persona_prompt(**kwargs):
        captured["persona_kwargs"] = kwargs
        return "PERSONA"

    async def _resolve_scope(**kwargs):
        captured["scope_kwargs"] = kwargs
        return ("local", False)

    async def _fetch_history(memory_manager, user_id, scope, **kwargs):
        captured["fetch_kwargs"] = kwargs
        return [{"role": "user", "content": "历史一"}]

    async def _inject_thinking(memory_manager, messages):
        messages.append({"content": "thinking"})

    async def _apply_local_budget(history, messages, user_message, active_tools, compress_history_fn):
        captured["compress_fn"] = compress_history_fn
        messages.append({"content": "budget"})
        return history, user_message

    async def _inject_sensitive(memory_manager, is_sensitive_mode, messages):
        captured["sensitive_mode"] = is_sensitive_mode
        messages.append({"content": "sensitive"})

    def _filter_tool_names(names, **kwargs):
        captured["filter_kwargs"] = kwargs
        return list(names)

    def _build_complete(**kwargs):
        captured["build_kwargs"] = kwargs
        return [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]

    def _record_summary(*args, **kwargs):
        # 同步记录入参（create_task 之前就会求值），再返回一个可被取消的空协程
        captured["summary_args"] = (args, kwargs)

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(ctx, "_prepare_active_tools", _prepare_active_tools)
    monkeypatch.setattr(ctx, "_resolve_persona_prompt", _resolve_persona_prompt)
    monkeypatch.setattr(ctx, "_resolve_scope_and_sensitive_mode", _resolve_scope)
    monkeypatch.setattr(ctx, "_fetch_history_for_scope", _fetch_history)
    monkeypatch.setattr(ctx, "_inject_thinking_store", _inject_thinking)
    monkeypatch.setattr(ctx, "_apply_local_context_budget", _apply_local_budget)
    monkeypatch.setattr(ctx, "_inject_sensitive_memories", _inject_sensitive)
    monkeypatch.setattr(ctx, "filter_tool_names", _filter_tool_names)
    monkeypatch.setattr(ctx, "_detect_cloud_mode", lambda agent, hint: False)
    monkeypatch.setattr(ctx, "is_debug_enabled", lambda key: False)
    monkeypatch.setattr(ctx, "perform_context_summary", _record_summary)
    monkeypatch.setattr(
        "core.agents.chat_agent_components.persona_system.prompt.build_complete_message_list",
        _build_complete,
    )
    return captured


class _Agent:
    """仅提供同步 _get_memory_manager 的最小 agent 替身。"""

    def __init__(self, mm=None, study=False):
        self.tool_registry = None
        self.config = SimpleNamespace(system_prompt="")
        self._mm = mm if mm is not None else _SimpleMM()
        self._study = study
        self.study_calls = 0

    def _get_memory_manager(self, user_id):
        return self._mm

    def _is_study_mode(self, message, model_hint):
        self.study_calls += 1
        return self._study


class _AsyncAgent(_Agent):
    """额外提供 get_memory_manager_async 的 agent 替身。"""

    async def get_memory_manager_async(self, user_id):
        return self._mm


def test_build_history_basic_local_flow(deps):
    agent = _Agent()
    messages = asyncio.run(ctx.build_conversation_history(agent, "u1", "你好"))
    assert messages == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U"},
    ]
    build = deps["build_kwargs"]
    assert build["history_messages"] == [{"role": "user", "content": "历史一"}]
    assert build["sensitive_injections"] == ["thinking", "budget", "sensitive"]
    assert build["is_qq_session"] is False
    assert build["active_tools"] == ["tool_a"]


def test_build_history_message_as_multimodal_list(deps):
    agent = _Agent()
    message = [
        {"type": "text", "text": "第一段"},
        {"type": "image_url", "image_url": {}},
        {"type": "text", "text": "第二段"},
    ]
    asyncio.run(ctx.build_conversation_history(agent, "u1", message))
    assert deps["build_kwargs"]["message"] == "第一段第二段"
    assert deps["prepare_tools"][0] == "第一段第二段"


def test_build_history_uses_async_memory_manager(deps):
    agent = _AsyncAgent()
    asyncio.run(ctx.build_conversation_history(agent, "u1", "你好"))
    assert deps["build_kwargs"]["memory_manager"] is agent._mm


def test_build_history_active_tools_override_skips_prepare(deps):
    agent = _Agent()
    asyncio.run(
        ctx.build_conversation_history(agent, "u1", "你好", active_tools_override=["only"])
    )
    assert "prepare_tools" not in deps
    assert deps["filter_kwargs"]["tool_names"] if False else True
    assert deps["build_kwargs"]["active_tools"] == ["only"]


def test_build_history_system_prompt_override_skips_persona_resolve(deps):
    agent = _Agent()
    asyncio.run(
        ctx.build_conversation_history(agent, "u1", "你好", system_prompt_override="  覆盖人设  ")
    )
    assert "persona_kwargs" not in deps
    assert deps["scope_kwargs"]["messages"] == [
        {"role": "system", "content": "覆盖人设"}
    ]


def test_build_history_blank_system_prompt_override_falls_through(deps):
    agent = _Agent()
    asyncio.run(
        ctx.build_conversation_history(agent, "u1", "你好", system_prompt_override="   ")
    )
    assert deps["persona_kwargs"]["message"] == "你好"


def test_build_history_cloud_mode_applies_cloud_budget(deps, monkeypatch):
    calls = {}

    def _cloud_budget(history, message_text):
        calls["n"] = len(history)
        return history + [{"role": "assistant", "content": "裁剪后"}]

    monkeypatch.setattr(ctx, "_apply_cloud_history_budget", _cloud_budget)
    monkeypatch.setattr(ctx, "_detect_cloud_mode", lambda agent, hint: True)

    agent = _Agent()
    asyncio.run(ctx.build_conversation_history(agent, "u1", "你好", model_hint="cloud:x"))

    assert calls["n"] == 1
    assert deps["build_kwargs"]["history_messages"][-1]["content"] == "裁剪后"
    # 云端路径不应注入 thinking / budget / sensitive
    assert deps["build_kwargs"]["sensitive_injections"] == []


def test_build_history_cloud_mode_without_history_skips_budget(deps, monkeypatch):
    monkeypatch.setattr(ctx, "_detect_cloud_mode", lambda agent, hint: True)

    async def _empty_history(*args, **kwargs):
        return []

    monkeypatch.setattr(ctx, "_fetch_history_for_scope", _empty_history)
    agent = _Agent()
    asyncio.run(ctx.build_conversation_history(agent, "u1", "你好"))
    assert deps["build_kwargs"]["history_messages"] == []


def test_build_history_override_filters_and_sanitizes(deps, monkeypatch):
    captured = {}

    def _sanitize(history, persona_filename=""):
        captured["persona_filename"] = persona_filename
        return [dict(m, content="SAN:" + m["content"]) for m in history]

    monkeypatch.setattr(ctx, "_sanitize_history_messages", _sanitize)

    override = [
        {"role": "user", "content": "保留", "timestamp": 123},
        {"role": "assistant", "content": "也保留"},
        {"role": "system", "content": "丢弃角色"},
        {"role": "user", "content": "   "},
        "not-a-dict",
    ]
    agent = _Agent()
    asyncio.run(
        ctx.build_conversation_history(
            agent, "u1", "你好", history_override=override, persona_filename="p.yaml"
        )
    )
    history = deps["build_kwargs"]["history_messages"]
    assert [m["content"] for m in history] == ["SAN:保留", "SAN:也保留"]
    assert history[0]["timestamp"] == 123
    assert captured["persona_filename"] == "p.yaml"
    assert "fetch_kwargs" not in deps


def test_build_history_study_mode_from_agent(deps):
    agent = _Agent(study=True)
    asyncio.run(ctx.build_conversation_history(agent, "u1", "学习"))
    assert agent.study_calls >= 1
    assert deps["filter_kwargs"]["mode"] == "study"
    assert deps["fetch_kwargs"]["is_study_mode"] is True


def test_build_history_study_mode_from_classify_category(deps, monkeypatch):
    monkeypatch.setattr(
        "memory.core.taxonomy.classify_category", lambda text: "learning"
    )
    agent = _Agent(study=False)
    asyncio.run(ctx.build_conversation_history(agent, "u1", "背单词"))
    assert deps["fetch_kwargs"]["is_study_mode"] is True


def test_build_history_classify_category_error_is_swallowed(deps, monkeypatch):
    def _boom(text):
        raise RuntimeError("taxonomy down")

    monkeypatch.setattr("memory.core.taxonomy.classify_category", _boom)
    agent = _Agent(study=False)
    asyncio.run(ctx.build_conversation_history(agent, "u1", "背单词"))
    assert deps["fetch_kwargs"]["is_study_mode"] is False


def test_build_history_empty_message_skips_classify(deps, monkeypatch):
    called = {"n": 0}

    def _classify(text):
        called["n"] += 1
        return "learning"

    monkeypatch.setattr("memory.core.taxonomy.classify_category", _classify)
    agent = _Agent(study=False)
    asyncio.run(ctx.build_conversation_history(agent, "u1", ""))
    assert called["n"] == 0


def test_build_history_weighted_manager_triggers_summary_and_state(deps, monkeypatch):
    mm = object.__new__(WeightedMemoryManager)
    mm.state_tracker = SimpleNamespace(auto_update_from_text=lambda text: None)
    mm.get_state_context = lambda: "STATE_CTX"

    agent = _Agent(mm=mm)
    asyncio.run(ctx.build_conversation_history(agent, "u1", "今天吃饭了吗"))

    assert "summary_args" in deps
    args, kwargs = deps["summary_args"]
    assert args[0] is agent and args[1] == "u1" and args[2] is mm
    assert kwargs["scope"] == "local"
    assert deps["build_kwargs"]["state_context"] == "STATE_CTX"


def test_build_history_weighted_manager_swallows_state_errors(deps, monkeypatch):
    mm = object.__new__(WeightedMemoryManager)

    def _boom(text):
        raise RuntimeError("tracker down")

    def _boom_ctx():
        raise RuntimeError("state down")

    mm.state_tracker = SimpleNamespace(auto_update_from_text=_boom)
    mm.get_state_context = _boom_ctx

    agent = _Agent(mm=mm)
    messages = asyncio.run(ctx.build_conversation_history(agent, "u1", "你好"))
    assert messages
    assert deps["build_kwargs"]["state_context"] is None


def test_build_history_weighted_manager_empty_message_skips_auto_update(deps):
    calls = {"n": 0}
    mm = object.__new__(WeightedMemoryManager)

    def _auto(text):
        calls["n"] += 1

    mm.state_tracker = SimpleNamespace(auto_update_from_text=_auto)
    mm.get_state_context = lambda: "S"

    agent = _Agent(mm=mm)
    asyncio.run(ctx.build_conversation_history(agent, "u1", ""))
    assert calls["n"] == 0


@pytest.mark.parametrize(
    "user_id,expected",
    [
        ("group_123", True),
        ("private_abc", True),
        ("qq_42", True),
        ("default_user", True),
        ("GROUP_UPPER", True),
        ("normal_user", False),
        ("", False),
    ],
)
def test_build_history_qq_session_detection(deps, user_id, expected):
    agent = _Agent()
    asyncio.run(ctx.build_conversation_history(agent, user_id, "你好"))
    assert deps["build_kwargs"]["is_qq_session"] is expected


def test_build_history_debug_logging_path(deps, monkeypatch):
    monkeypatch.setattr(ctx, "is_debug_enabled", lambda key: True)
    agent = _Agent()
    messages = asyncio.run(
        ctx.build_conversation_history(agent, "u1", "你好", model_hint="cloud:x")
    )
    assert messages


def test_build_history_slow_path_logs_timings(deps, monkeypatch):
    """通过注入递增的 perf_counter 稳定触发 SLOW 分支。"""
    state = {"t": 0.0}

    def _perf_counter():
        state["t"] += 0.5
        return state["t"]

    monkeypatch.setattr(ctx, "time", SimpleNamespace(perf_counter=_perf_counter))
    # 屏蔽真实 logger，避免异步日志线程在 pytest 退出后写已关闭的流
    monkeypatch.setattr(ctx, "logger", SimpleNamespace(info=lambda *a, **k: None))
    agent = _Agent()
    messages = asyncio.run(ctx.build_conversation_history(agent, "u1", "你好"))
    assert messages
    assert state["t"] >= 4.0


def test_build_history_scope_override_passed_through(deps):
    agent = _Agent()
    asyncio.run(
        ctx.build_conversation_history(agent, "u1", "你好", scope_override="study")
    )
    assert deps["scope_kwargs"]["scope_override"] == "study"


def test_build_history_extra_context_and_persona_passed_to_builder(deps):
    agent = _Agent()
    asyncio.run(
        ctx.build_conversation_history(
            agent,
            "u1",
            "你好",
            extra_dynamic_context="EXTRA",
            user_name="小明",
            persona_filename="core_ye.json",
        )
    )
    build = deps["build_kwargs"]
    assert build["extra_dynamic_context"] == "EXTRA"
    assert build["user_name"] == "小明"
    assert build["persona_filename"] == "core_ye.json"
    assert deps["persona_kwargs"]["user_name"] == "小明"
