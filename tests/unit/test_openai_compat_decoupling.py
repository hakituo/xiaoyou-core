"""openai_compat/client.py 拆分后的契约测试。

覆盖从 client.py 抽出去的三块：DSML 流式过滤、重试策略、非 200 判定，
以及拆分后必须保住的两条兼容契约（client 模块 re-export、动态 key 走临时 session）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.llm.openai_compat import OpenAIClient
from core.llm.openai_compat import client as client_module
from core.llm.openai_compat.dsml_parser import DSML_CLOSE_MARKERS, DSML_START_MARKERS
from core.llm.openai_compat.dsml_stream import DSMLStreamFilter
from core.llm.openai_compat.error_handling import classify_error_response
from core.llm.openai_compat.session_mixin import LLMSessionMixin
from core.llm.openai_compat.retry import DEFAULT_MAX_ATTEMPTS, RetryPolicy


START = DSML_START_MARKERS[0]
CLOSE = DSML_CLOSE_MARKERS[0]
PREFIX = START[1 : -len("tool_calls>")]


def _dsml_block() -> str:
    """一段完整的 V4 DSML 工具调用块"""
    return (
        f"{START}"
        f"<{PREFIX}invoke name=\"get_weather\">"
        f"<{PREFIX}parameter name=\"city\" string=\"true\">上海</{PREFIX}parameter>"
        f"</{PREFIX}invoke>"
        f"{CLOSE}"
    )


# ---------------------------------------------------------------- DSML 过滤


def test_filter_passthrough_when_no_dsml():
    """无 DSML 的 chunk 原样透传（含 content 以外的字段）"""
    dsml_filter = DSMLStreamFilter()
    chunk = {"content": "你好", "finish_reason": None}
    assert dsml_filter.filter_chunk(chunk) == [chunk]
    assert dsml_filter.active is False


def test_filter_passthrough_without_content():
    """usage / finish_reason 这类 chunk 不进 DSML 状态机"""
    dsml_filter = DSMLStreamFilter()
    chunk = {"usage": {"prompt_tokens": 1}}
    assert dsml_filter.filter_chunk(chunk) == [chunk]


def test_filter_parses_block_inside_one_chunk():
    """闭合标记与起始标记在同一个 chunk：前文本 + tool_calls + 剩余文本"""
    dsml_filter = DSMLStreamFilter()
    out = dsml_filter.filter_chunk({"content": f"查一下{_dsml_block()}好的"})

    assert out[0] == {"content": "查一下"}
    assert out[1]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert out[2] == {"finish_reason": "tool_calls"}
    assert out[3] == {"content": "好的"}
    assert dsml_filter.active is False


def test_filter_buffers_across_chunks():
    """DSML 块跨 chunk 到达时先缓冲，闭合后才吐，且中间不泄漏原始 token"""
    dsml_filter = DSMLStreamFilter()
    block = _dsml_block()
    head, tail = block[:40], block[40:]

    assert dsml_filter.filter_chunk({"content": f"开始{head}"}) == [{"content": "开始"}]
    assert dsml_filter.active is True

    out = dsml_filter.filter_chunk({"content": f"{tail}结束"})
    assert out[0]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert out[1] == {"finish_reason": "tool_calls"}
    assert out[2] == {"content": "结束"}


def test_filter_instances_do_not_share_buffer():
    """两个过滤器互不影响：这是把状态从 client 实例搬到调用内实例的目的"""
    f1 = DSMLStreamFilter()
    f2 = DSMLStreamFilter()
    block = _dsml_block()

    f1.filter_chunk({"content": block[:40]})
    out2 = f2.filter_chunk({"content": block})

    assert f1.active is True          # 还在等自己的闭合标记
    assert out2[0]["tool_calls"]      # f2 已经完整解析
    assert f2.active is False


# ---------------------------------------------------------------- 重试策略


def test_retry_policy_defaults():
    policy = RetryPolicy()
    assert policy.max_attempts == DEFAULT_MAX_ATTEMPTS == 3
    assert policy.has_next(0) is True
    assert policy.has_next(1) is True
    assert policy.has_next(2) is False
    assert policy.delay(0) == 0.25
    assert policy.delay(1) == 0.5


def test_retry_policy_only_retries_transient_errors():
    policy = RetryPolicy()
    assert policy.should_retry(ConnectionResetError("connection reset"), 0) is True
    assert policy.should_retry(ValueError("bad payload"), 0) is False
    # 用尽次数后不再重试
    assert policy.should_retry(ConnectionResetError("connection reset"), 2) is False
    # 调用方附加条件（流式已吐过内容就不再重试）
    assert policy.should_retry(ConnectionResetError("connection reset"), 0, False) is False


async def test_retry_policy_backoff_sleeps():
    policy = RetryPolicy()
    with patch("asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await policy.backoff(1)
    sleep_mock.assert_awaited_once_with(0.5)


# ------------------------------------------------------- 非 200 响应判定


def test_classify_system_order_400_asks_for_retry():
    payload = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "s1"},
            {"role": "system", "content": "s2"},
        ],
    }
    info = classify_error_response(
        400, "system message must be at the beginning", payload=payload, attempt=0
    )
    assert info.retry_payload is not None
    assert len(info.retry_payload["messages"]) == 3  # 第一次只重排，不合并

    second = classify_error_response(
        400, "system message must be at the beginning", payload=payload, attempt=1
    )
    assert len(second.retry_payload["messages"]) == 2  # 第二次合并成单条 system
    assert second.retry_payload is not None


def test_classify_system_order_400_gives_up_on_last_attempt():
    info = classify_error_response(
        400, "system message must be at the beginning", payload={}, attempt=2
    )
    assert info.retry_payload is None


def test_classify_marks_422_as_non_retryable():
    info = classify_error_response(422, "input new_sensitive (1026)")
    assert info.non_retryable is True
    assert info.retry_payload is None


def test_classify_leaves_5xx_retryable_to_upper_layer():
    """5xx 是否重试由调度层决定，客户端只判定「不是认证/内容策略类」"""
    assert classify_error_response(500, "boom").non_retryable is False
    assert classify_error_response(429, "rate limit").non_retryable is False


def test_classify_dumps_group_chat_payload(tmp_path: Path, monkeypatch):
    """MiniMax group chat 400 的调试落盘只写一次，且失败不影响主流程"""
    monkeypatch.chdir(tmp_path)
    classify_error_response(400, "invalid group chat params", payload={"model": "m"})
    dumped = tmp_path / "minimax_400_payload.json"
    assert dumped.exists()
    assert '"model": "m"' in dumped.read_text(encoding="utf-8")


# ------------------------------------------------------- 拆分后的兼容契约


def test_client_module_keeps_backward_compatible_exports():
    """siliconflow_client 与验证脚本仍从 client 导入这两个符号"""
    assert client_module.LLMSessionMixin is LLMSessionMixin
    assert client_module._is_sensitive_input_rejection(422, "new_sensitive") is True


@pytest.mark.asyncio
async def test_stream_chat_uses_temp_session_for_dynamic_key():
    base = {
        "initialized": True,
        "base_url": "http://example.invalid/v1/chat/completions",
        "api_key": "static",
        "timeout": 5,
        "proxy": None,
    }
    client = object.__new__(OpenAIClient)
    for key, value in base.items():
        setattr(client, key, value)
    client._route_vision_if_needed = AsyncMock(return_value=([{"role": "user", "content": "x"}], ""))
    client._build_payload = lambda *_a, **_kw: {"model": "m"}
    client._get_session = AsyncMock(return_value=_FakeSession())

    created: list[_FakeSession] = []
    with patch("aiohttp.ClientSession", side_effect=lambda **kw: _new_session(created, kw)):
        chunks = [c async for c in client.stream_chat([], api_key="dynamic")]

    assert chunks == [{"error": "API returned 599"}]
    assert len(created) == 1
    assert created[0].headers["Authorization"] == "Bearer dynamic"
    assert client._get_session.await_count == 0  # 没走常驻 session


@pytest.mark.asyncio
async def test_stream_chat_reuses_resident_session_without_dynamic_key():
    client = object.__new__(OpenAIClient)
    client.initialized = True
    client.base_url = "http://example.invalid/v1/chat/completions"
    client.api_key = "static"
    client.timeout = 5
    client.proxy = None
    client._route_vision_if_needed = AsyncMock(return_value=([{"role": "user", "content": "x"}], ""))
    client._build_payload = lambda *_a, **_kw: {"model": "m"}
    client._get_session = AsyncMock(return_value=_FakeSession())

    created: list[_FakeSession] = []
    with patch("aiohttp.ClientSession", side_effect=lambda **kw: _new_session(created, kw)):
        chunks = [c async for c in client.stream_chat([])]

    assert chunks == [{"error": "API returned 599"}]
    assert created == []
    assert client._get_session.await_count == 1


def test_build_payload_has_no_stats_side_effect():
    """调用统计已外移到编排层，_build_payload 保持纯构造"""
    client = OpenAIClient(api_key="k", base_url="http://example.invalid/v1")
    with patch.object(client_module, "log_llm_call_stats") as stats_mock:
        client._build_payload([{"role": "user", "content": "hi"}], stream=False)
    stats_mock.assert_not_called()


class _FakeResponse:
    def __init__(self, status: int, body: str = ""):
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeSession:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.closed = False

    def post(self, *_args, **_kwargs):
        return _FakeResponse(599, "boom")

    async def close(self):
        self.closed = True


def _new_session(sink: list, kwargs: dict) -> _FakeSession:
    session = _FakeSession(headers=kwargs.get("headers", {}))
    sink.append(session)
    return session
