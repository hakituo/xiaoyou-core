#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""core/llm/dashscope_client.py 的单元测试。

全部使用替身对象（假的 aiohttp session / 假的 HTTP 响应 / 假的 SSE 内容流），
不发起任何真实网络请求，也不依赖本机数据。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest

from core.llm.dashscope_client import DashScopeClient, get_dashscope_client
from core.utils.debug_markers import DEBUG_ERROR_PREFIX

BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"


# --------------------------------------------------------------------------- #
# 替身对象
# --------------------------------------------------------------------------- #
class _FakeContent:
    """模拟 aiohttp 响应体的 ``content``（只实现本模块用到的 ``iter_any``）。"""

    def __init__(self, chunks: List[bytes]):
        self._chunks = list(chunks)

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    """模拟 aiohttp 响应对象。"""

    def __init__(
        self,
        status: int = 200,
        json_data: Optional[Dict[str, Any]] = None,
        text_data: str = "",
        chunks: Optional[List[bytes]] = None,
    ):
        self.status = status
        self._json_data = json_data
        self._text_data = text_data
        self.content = _FakeContent(chunks or [])

    async def json(self) -> Dict[str, Any]:
        return self._json_data or {}

    async def text(self) -> str:
        return self._text_data


class _FakePostContext:
    """模拟 ``session.post(...)`` 返回的异步上下文管理器。"""

    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    """模拟 aiohttp.ClientSession，记录每次 post 的入参。"""

    def __init__(self, response: Optional[_FakeResponse] = None):
        self.closed = False
        self._response = response or _FakeResponse()
        self.post_calls: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs) -> _FakePostContext:
        self.post_calls.append({"url": url, **kwargs})
        return _FakePostContext(self._response)


class _FailingSession:
    """模拟 post 阶段就抛异常的 session。"""

    def __init__(self, exc: Exception):
        self.closed = False
        self._exc = exc

    def post(self, *args, **kwargs):
        raise self._exc


# --------------------------------------------------------------------------- #
# 构造 / 驱动辅助函数
# --------------------------------------------------------------------------- #
def _make_client(session, api_key: str = "fake-key", initialized: bool = True) -> DashScopeClient:
    """构造一个 session 被替换为替身、且已完成初始化的客户端。"""

    client = DashScopeClient(api_key=api_key)
    client.initialized = initialized
    client.session = session

    async def _get_session():
        return session

    # 直接覆盖实例属性：函数存在实例字典里不会被绑定，调用时无需 self
    client._get_session = _get_session
    return client


def _drain_stream(client: DashScopeClient, messages: list, **kwargs) -> List[Dict[str, Any]]:
    """同步驱动异步生成器，收集全部分片。"""

    async def _run():
        return [chunk async for chunk in client.stream_chat(messages, **kwargs)]

    return asyncio.run(_run())


def _drain_parser(client: DashScopeClient, chunks: List[bytes]) -> List[Dict[str, Any]]:
    """同步驱动 ``_parse_dashscope_sse``，收集全部分片。"""

    async def _run():
        return [chunk async for chunk in client._parse_dashscope_sse(_FakeContent(chunks))]

    return asyncio.run(_run())


def _sse(payload: Any) -> bytes:
    """把 JSON 载荷包成一条 ``data:`` SSE 行（带换行）。"""
    return f"data: {json.dumps(payload)}\n".encode("utf-8")


def _ok_payload(content: str = "hello", finish_reason: Any = "stop", usage=None) -> Dict[str, Any]:
    """构造 DashScope 原生（result_format=message）成功响应。"""
    payload: Dict[str, Any] = {
        "output": {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
            ]
        }
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


# --------------------------------------------------------------------------- #
# __init__
# --------------------------------------------------------------------------- #
def test_init_with_api_key_sets_fixed_config(monkeypatch):
    """传入 api_key 时字段就位，且模型固定为 qwen3.5-plus（model 参数被忽略）。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    client = DashScopeClient(api_key="explicit-key", model="qwen-max")

    assert client.api_key == "explicit-key"
    assert client.default_model == "qwen3.5-plus"
    assert client.base_url == BASE_URL
    assert client.timeout == 60
    assert client.session is None
    assert client.initialized is False


def test_init_without_api_key_warns_and_keeps_none(monkeypatch):
    """既无入参也无环境变量时 api_key 为 None（走 warning 分支）。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    client = DashScopeClient()

    assert client.api_key is None
    assert client.default_model == "qwen3.5-plus"


def test_init_falls_back_to_env_api_key(monkeypatch):
    """未传 api_key 时回退到环境变量 DASHSCOPE_API_KEY。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-key")

    assert DashScopeClient().api_key == "env-key"


# --------------------------------------------------------------------------- #
# initialize / get_status
# --------------------------------------------------------------------------- #
def test_initialize_creates_session_once_and_is_idempotent():
    """initialize 只取一次 session，重复调用不再取。"""
    session = _FakeSession()
    client = _make_client(session, initialized=False)
    calls: List[int] = []

    async def _get_session():
        calls.append(1)
        return session

    client._get_session = _get_session

    asyncio.run(client.initialize())
    assert client.initialized is True

    asyncio.run(client.initialize())
    assert calls == [1]


def test_get_status_before_init(monkeypatch):
    """未初始化时状态为 not_initialized 且 session 不活跃。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-key")
    client = DashScopeClient()

    status = client.get_status()

    assert status["provider"] == "DashScope"
    assert status["llm_status"] == {"instances_count": 1}
    assert status["init_state"] == "not_initialized"
    assert status["api_key_configured"] is True
    assert status["session_active"] is False
    assert status["model"] == "qwen3.5-plus"
    assert status["base_url"] == BASE_URL


def test_get_status_after_init_reports_active_session():
    """初始化后状态为 initialized 且 session 活跃。"""
    client = _make_client(_FakeSession(), initialized=False)

    asyncio.run(client.initialize())
    status = client.get_status()

    assert status["init_state"] == "initialized"
    assert status["session_active"] is True


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #
def test_generate_without_api_key_returns_error(monkeypatch):
    """缺少 API Key 时直接返回错误字典，不发起请求。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    session = _FakeSession()
    client = _make_client(session, api_key=None)

    result = asyncio.run(client.generate("hi"))

    assert result == {"status": "error", "error": "DashScope API Key missing"}
    assert session.post_calls == []


def test_generate_success_returns_text_usage_and_finish_reason():
    """200 + output.choices 时返回 success 及文本、usage、finish_reason。"""
    response = _FakeResponse(
        status=200,
        json_data=_ok_payload("你好", "stop", {"total_tokens": 7}),
    )
    session = _FakeSession(response)
    client = _make_client(session)

    result = asyncio.run(client.generate("hi"))

    assert result["status"] == "success"
    assert result["text"] == "你好"
    assert result["usage"] == {"total_tokens": 7}
    assert result["finish_reason"] == "stop"
    # 请求发往原生 DashScope 地址，且 payload 结构固定
    call = session.post_calls[0]
    assert call["url"] == BASE_URL
    assert call["json"]["model"] == "qwen3.5-plus"
    assert call["json"]["parameters"]["result_format"] == "message"
    assert call["json"]["input"]["messages"] == [{"role": "user", "content": "hi"}]


def test_generate_success_without_usage_and_finish_reason():
    """响应缺少 usage / finish_reason 时使用空默认值。"""
    response = _FakeResponse(status=200, json_data=_ok_payload("ok", None))
    session = _FakeSession(response)
    client = _make_client(session)

    result = asyncio.run(client.generate("hi"))

    assert result["status"] == "success"
    assert result["text"] == "ok"
    assert result["usage"] == {}
    assert result["finish_reason"] is None


def test_generate_returns_dashscope_error_code():
    """响应带 code 字段时返回带 code 的错误字典。"""
    response = _FakeResponse(
        status=200,
        json_data={"code": "InvalidApiKey", "message": "Invalid API-key provided."},
    )
    client = _make_client(_FakeSession(response))

    result = asyncio.run(client.generate("hi"))

    assert result["status"] == "error"
    assert result["code"] == "InvalidApiKey"
    assert "Invalid API-key provided." in result["error"]


def test_generate_unknown_response_format():
    """既无 output.choices 也无 code 时归为未知格式。"""
    response = _FakeResponse(status=200, json_data={"output": {}})
    client = _make_client(_FakeSession(response))

    result = asyncio.run(client.generate("hi"))

    assert result["status"] == "error"
    assert result["error"] == "Unknown response format"
    assert result["raw"] == {"output": {}}


def test_generate_http_error_includes_status_and_body():
    """非 200 时返回带状态码与响应体的错误。"""
    response = _FakeResponse(status=429, text_data="rate limited")
    client = _make_client(_FakeSession(response))

    result = asyncio.run(client.generate("hi"))

    assert result == {"status": "error", "error": "HTTP 429: rate limited"}


def test_generate_network_exception_is_caught():
    """请求阶段抛异常时被捕获并转成错误字典。"""
    client = _make_client(_FailingSession(RuntimeError("conn reset")))

    result = asyncio.run(client.generate("hi"))

    assert result == {"status": "error", "error": "conn reset"}


def test_generate_builds_messages_from_history():
    """history 被转成 messages，且当前 prompt 追加为最后一条 user 消息。"""
    response = _FakeResponse(status=200, json_data=_ok_payload())
    session = _FakeSession(response)
    client = _make_client(session)
    history = [
        {"role": "system", "content": "你是小悠"},
        {"role": "user", "content": "早"},
        {"role": "assistant", "content": "早呀"},
    ]

    asyncio.run(client.generate("今天做什么", history=history))

    assert session.post_calls[0]["json"]["input"]["messages"] == [
        {"role": "system", "content": "你是小悠"},
        {"role": "user", "content": "早"},
        {"role": "assistant", "content": "早呀"},
        {"role": "user", "content": "今天做什么"},
    ]


def test_generate_history_message_missing_fields_uses_defaults():
    """history 中缺 role / content 的条目补默认值 user / 空串。"""
    response = _FakeResponse(status=200, json_data=_ok_payload())
    session = _FakeSession(response)
    client = _make_client(session)

    asyncio.run(client.generate("hi", history=[{}]))

    assert session.post_calls[0]["json"]["input"]["messages"] == [
        {"role": "user", "content": ""},
        {"role": "user", "content": "hi"},
    ]


def test_generate_does_not_duplicate_prompt_already_in_history():
    """history 末尾内容与 prompt 相同时不再重复追加。"""
    response = _FakeResponse(status=200, json_data=_ok_payload())
    session = _FakeSession(response)
    client = _make_client(session)

    asyncio.run(client.generate("hi", history=[{"role": "user", "content": "hi"}]))

    assert session.post_calls[0]["json"]["input"]["messages"] == [{"role": "user", "content": "hi"}]


def test_generate_respects_explicit_model_and_parameters():
    """显式 model 与采样参数覆盖默认值。"""
    response = _FakeResponse(status=200, json_data=_ok_payload())
    session = _FakeSession(response)
    client = _make_client(session)

    asyncio.run(
        client.generate(
            "hi",
            model="qwen3.5-plus-custom",
            max_tokens=128,
            temperature=0.1,
            top_p=0.2,
            repetition_penalty=1.3,
        )
    )

    payload = session.post_calls[0]["json"]
    assert payload["model"] == "qwen3.5-plus-custom"
    assert payload["parameters"] == {
        "max_tokens": 128,
        "temperature": 0.1,
        "top_p": 0.2,
        "repetition_penalty": 1.3,
        "result_format": "message",
    }


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
def test_chat_success_returns_response_and_finish_reason():
    """chat 成功时返回 response / finish_reason，并把最后一条当作 prompt。"""
    response = _FakeResponse(status=200, json_data=_ok_payload("答案", "stop"))
    session = _FakeSession(response)
    client = _make_client(session)

    result = asyncio.run(
        client.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "问题"}])
    )

    assert result == {"response": "答案", "finish_reason": "stop"}
    assert session.post_calls[0]["json"]["input"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "问题"},
    ]


def test_chat_single_message_has_empty_history():
    """只有一条消息时 history 为空（len(messages) > 1 的假分支）。"""
    response = _FakeResponse(status=200, json_data=_ok_payload("ok", "stop"))
    session = _FakeSession(response)
    client = _make_client(session)

    result = asyncio.run(client.chat([{"role": "user", "content": "唯一一条"}]))

    assert result["response"] == "ok"
    assert session.post_calls[0]["json"]["input"]["messages"] == [
        {"role": "user", "content": "唯一一条"}
    ]


def test_chat_empty_messages_uses_empty_prompt():
    """空消息列表时 prompt 取空串（messages 为假值的分支）。"""
    response = _FakeResponse(status=200, json_data=_ok_payload("ok", "stop"))
    session = _FakeSession(response)
    client = _make_client(session)

    asyncio.run(client.chat([]))

    assert session.post_calls[0]["json"]["input"]["messages"] == [{"role": "user", "content": ""}]


def test_chat_initializes_client_when_needed():
    """未初始化时 chat 会先自动初始化。"""
    response = _FakeResponse(status=200, json_data=_ok_payload("ok", "stop"))
    session = _FakeSession(response)
    client = _make_client(session, initialized=False)

    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

    assert client.initialized is True
    assert result["response"] == "ok"


def test_chat_forwards_kwargs_to_generate():
    """chat 把额外 kwargs 透传给 generate。"""
    client = _make_client(_FakeSession())
    seen: Dict[str, Any] = {}

    async def _fake_generate(prompt, history, **kwargs):
        seen["prompt"] = prompt
        seen["history"] = history
        seen["kwargs"] = kwargs
        return {"status": "success", "text": "t", "finish_reason": "stop"}

    client.generate = _fake_generate

    result = asyncio.run(
        client.chat([{"role": "user", "content": "hi"}], max_tokens=64, temperature=0.3)
    )

    assert result == {"response": "t", "finish_reason": "stop"}
    assert seen["prompt"] == "hi"
    assert seen["history"] == []
    assert seen["kwargs"] == {"max_tokens": 64, "temperature": 0.3}


def test_chat_failure_returns_debug_prefixed_error():
    """generate 失败时 chat 返回带 [DEBUG_ERROR] 前缀的错误字符串。"""
    client = _make_client(_FakeSession())

    async def _fake_generate(prompt, history, **kwargs):
        return {"status": "error", "error": "boom"}

    client.generate = _fake_generate

    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

    assert isinstance(result, str)
    assert result == f"{DEBUG_ERROR_PREFIX} Error: boom"


# --------------------------------------------------------------------------- #
# stream_chat
# --------------------------------------------------------------------------- #
def test_stream_chat_without_api_key_yields_error(monkeypatch):
    """缺少 API Key 时只产出一个错误分片。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    session = _FakeSession()
    client = _make_client(session, api_key=None)

    chunks = _drain_stream(client, [{"role": "user", "content": "hi"}])

    assert chunks == [{"error": "DashScope API Key missing"}]
    assert session.post_calls == []


def test_stream_chat_initializes_client_when_needed():
    """未初始化时 stream_chat 先初始化再请求。"""
    response = _FakeResponse(status=200, chunks=[_sse(_ok_payload("你好", "stop"))])
    client = _make_client(_FakeSession(response), initialized=False)

    chunks = _drain_stream(client, [{"role": "user", "content": "hi"}])

    assert client.initialized is True
    assert chunks == [
        {"content": "你好"},
        {"finish_reason": "stop", "usage": {}},
    ]


def test_stream_chat_sends_sse_payload_and_headers():
    """流式请求使用 SSE 头、incremental_output，并消费 kwargs。"""
    response = _FakeResponse(status=200, chunks=[b"data: [DONE]\n"])
    session = _FakeSession(response)
    client = _make_client(session)

    _drain_stream(
        client,
        [{"role": "user", "content": "hi"}],
        model="qwen3.5-plus-x",
        max_tokens=64,
        temperature=0.5,
        top_p=0.6,
        repetition_penalty=1.2,
    )

    call = session.post_calls[0]
    assert call["url"] == BASE_URL
    assert call["headers"] == {"X-DashScope-SSE": "enable"}
    assert call["json"]["model"] == "qwen3.5-plus-x"
    assert call["json"]["input"]["messages"] == [{"role": "user", "content": "hi"}]
    assert call["json"]["parameters"] == {
        "max_tokens": 64,
        "temperature": 0.5,
        "top_p": 0.6,
        "repetition_penalty": 1.2,
        "result_format": "message",
        "incremental_output": True,
    }


def test_stream_chat_uses_defaults_when_kwargs_absent():
    """未传 kwargs 时使用默认模型与默认采样参数。"""
    response = _FakeResponse(status=200, chunks=[b"data: [DONE]\n"])
    session = _FakeSession(response)
    client = _make_client(session)

    _drain_stream(client, [{"role": "user", "content": "hi"}])

    payload = session.post_calls[0]["json"]
    assert payload["model"] == "qwen3.5-plus"
    assert payload["parameters"]["max_tokens"] == 4096
    assert payload["parameters"]["temperature"] == 0.8
    assert payload["parameters"]["top_p"] == 0.8
    assert payload["parameters"]["repetition_penalty"] == 1.1


def test_stream_chat_reports_http_error():
    """非 200 时产出错误分片且不继续解析。"""
    response = _FakeResponse(status=401, text_data="unauthorized")
    client = _make_client(_FakeSession(response))

    chunks = _drain_stream(client, [{"role": "user", "content": "hi"}])

    assert chunks == [{"error": "HTTP 401: unauthorized"}]


def test_stream_chat_catches_request_exception():
    """请求抛异常时产出错误分片而不是抛出。"""
    client = _make_client(_FailingSession(RuntimeError("boom")))

    chunks = _drain_stream(client, [{"role": "user", "content": "hi"}])

    assert chunks == [{"error": "boom"}]


# --------------------------------------------------------------------------- #
# _parse_dashscope_sse
# --------------------------------------------------------------------------- #
def test_parse_sse_emits_content_then_finish_reason():
    """标准增量流：先若干 content，最后一条 finish_reason 结束。"""
    client = _make_client(_FakeSession())
    chunks = [
        _sse(_ok_payload("你", "null")),
        _sse(_ok_payload("好", "null")),
        _sse(_ok_payload("", "stop", {"total_tokens": 5})),
        b"data: [DONE]\n",
    ]

    assert _drain_parser(client, chunks) == [
        {"content": "你"},
        {"content": "好"},
        {"finish_reason": "stop", "usage": {"total_tokens": 5}},
    ]


def test_parse_sse_ignores_blank_and_non_data_lines():
    """空行、注释行等非 data: 行被跳过，且不产出任何分片。"""
    client = _make_client(_FakeSession())
    chunks = [b"\n", b": ping\n", b"\n", b"event: message\n", b"\n"]

    assert _drain_parser(client, chunks) == []


def test_parse_sse_skips_empty_chunks():
    """空 bytes 分片被跳过，不影响后续解析。"""
    client = _make_client(_FakeSession())
    chunks = [b"", _sse(_ok_payload("hi", "null")), b""]

    assert _drain_parser(client, chunks) == [{"content": "hi"}]


def test_parse_sse_skips_invalid_json_and_continues():
    """坏 JSON 行只记录告警，后续正常分片仍然解析。"""
    client = _make_client(_FakeSession())
    chunks = [b"data: {not json}\n", b"data:\n", _sse(_ok_payload("hi", "null"))]

    assert _drain_parser(client, chunks) == [{"content": "hi"}]


def test_parse_sse_error_payload_yields_error_and_stops():
    """DashScope 错误响应（有 code 无 output）产出错误分片并立即终止。"""
    client = _make_client(_FakeSession())
    chunks = [
        _sse({"code": "DataInspectionFailed", "message": "inspection failed"}),
        _sse(_ok_payload("不应出现", "null")),
    ]

    assert _drain_parser(client, chunks) == [
        {"error": "DashScope Error: inspection failed"}
    ]


def test_parse_sse_skips_payloads_without_choices():
    """无 choices 的载荷（如 usage-only 心跳）被跳过。"""
    client = _make_client(_FakeSession())
    chunks = [_sse({"output": {"choices": []}}), _sse({"output": {}}), _sse(_ok_payload("hi", "null"))]

    assert _drain_parser(client, chunks) == [{"content": "hi"}]


def test_parse_sse_handles_null_choice_and_empty_content():
    """choices[0] 为 null、content 为空串时不产出分片。"""
    client = _make_client(_FakeSession())
    chunks = [
        _sse({"output": {"choices": [None]}}),
        _sse({"output": {"choices": [{"message": None, "finish_reason": "null"}]}}),
        _sse({"output": {"choices": [{"message": {"content": ""}, "finish_reason": "null"}]}}),
    ]

    assert _drain_parser(client, chunks) == []


def test_parse_sse_finish_reason_null_string_is_not_reported():
    """finish_reason 为字符串 "null"（或缺失）时不算结束。"""
    client = _make_client(_FakeSession())
    chunks = [
        _sse({"output": {"choices": [{"message": {"content": "a"}, "finish_reason": "null"}]}}),
        _sse({"output": {"choices": [{"message": {"content": "b"}}]}}),
        _sse({"output": {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}}),
    ]

    assert _drain_parser(client, chunks) == [
        {"content": "a"},
        {"content": "b"},
        {"finish_reason": "length", "usage": {}},
    ]


def test_parse_sse_stops_at_done_marker():
    """遇到 data:[DONE] 立即结束，忽略其后的数据。"""
    client = _make_client(_FakeSession())
    chunks = [_sse(_ok_payload("a", "null")), b"data: [DONE]\n", _sse(_ok_payload("b", "null"))]

    assert _drain_parser(client, chunks) == [{"content": "a"}]


def test_parse_sse_reassembles_line_split_across_chunks():
    """同一条 data: 行被切成多个 chunk 时先拼接再解析。"""
    client = _make_client(_FakeSession())
    raw = _sse(_ok_payload("拼好的", "stop"))
    head, tail = raw[:12], raw[12:]

    assert _drain_parser(client, [head, tail]) == [
        {"content": "拼好的"},
        {"finish_reason": "stop", "usage": {}},
    ]


def test_parse_sse_drops_incomplete_trailing_line():
    """未以换行结尾的残留数据不会被解析（记录当前实现行为）。"""
    client = _make_client(_FakeSession())
    raw = _sse(_ok_payload("没有换行结尾", "stop")).rstrip(b"\n")

    assert _drain_parser(client, [raw]) == []


# --------------------------------------------------------------------------- #
# 模块级单例
# --------------------------------------------------------------------------- #
def test_get_dashscope_client_returns_singleton(monkeypatch):
    """get_dashscope_client 首次构造后复用同一实例。"""
    import core.llm.dashscope_client as module

    monkeypatch.setattr(module, "_dashscope_client", None)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-key")

    first = get_dashscope_client()
    second = get_dashscope_client()

    assert isinstance(first, DashScopeClient)
    assert first is second
    assert first.api_key == "env-key"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", "-n", "0"]))
