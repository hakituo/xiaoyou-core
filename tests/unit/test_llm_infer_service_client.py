#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""core/llm/infer_service_client.py 的单元测试。

全部使用替身对象（假的 aiohttp 会话 / 假的 HTTP 响应 / 假的 aiohttp 与 asyncio 模块），
不发起任何真实网络请求，也不依赖本机推理服务或模型。
"""

from __future__ import annotations

import asyncio
import runpy
from typing import Any, Dict, List, Optional

import aiohttp
import pytest

from core.llm import infer_service_client as mod

BASE_URL = "http://127.0.0.1:8000"


# --------------------------------------------------------------------------- #
# 替身对象
# --------------------------------------------------------------------------- #
class _FakeResponse:
    """模拟 aiohttp 响应对象（只实现本模块用到的属性与协程方法）。"""

    def __init__(
        self,
        status: int = 200,
        json_data: Optional[Dict[str, Any]] = None,
        text_data: str = "",
        content_type: str = "application/json",
    ):
        self.status = status
        self.content_type = content_type
        self._json_data = json_data
        self._text_data = text_data

    async def json(self) -> Dict[str, Any]:
        return self._json_data if self._json_data is not None else {}

    async def text(self) -> str:
        return self._text_data


class _FakeRequestContext:
    """模拟 ``session.request(...)`` 返回的异步上下文管理器。"""

    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    """模拟 aiohttp.ClientSession，记录每次 request 的入参。"""

    def __init__(
        self,
        response: Optional[_FakeResponse] = None,
        exc: Optional[BaseException] = None,
    ):
        self.closed = False
        self._response = response or _FakeResponse()
        self._exc = exc
        self.calls: List[Dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs) -> _FakeRequestContext:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._exc is not None:
            raise self._exc
        return _FakeRequestContext(self._response)


class _ClosableSession:
    """可记录 ``close()`` 次数的会话替身。"""

    def __init__(self, closed: bool = False):
        self.closed = closed
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _FakeAiohttp:
    """aiohttp 模块替身：仅替换 ClientSession，其余属性转发真实模块。"""

    def __init__(self, real: Any, session_cls: Any):
        self._real = real
        self.ClientSession = session_cls

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _FakeAsyncio:
    """asyncio 模块替身：记录 sleep 时长并立即返回，其余属性转发真实模块。"""

    def __init__(self, real: Any):
        self._real = real
        self.sleep_delays: List[float] = []

    async def sleep(self, delay: float) -> None:
        self.sleep_delays.append(delay)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _FakeServerSettings:
    """假的 server 配置节。"""

    host = "127.0.0.1"
    port = 9000


class _FakeSettings:
    """假的全局配置对象（只提供 __init__ 用到的 server 字段）。"""

    server = _FakeServerSettings()


class _FakeExampleClient:
    """example_usage 用的假客户端（异步上下文管理器）。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.closed = False

    async def __aenter__(self) -> "_FakeExampleClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.closed = True
        return False

    async def health_check(self) -> Dict[str, Any]:
        return {"status": "ok"}

    async def get_model_status(self) -> Dict[str, Any]:
        return {"model": "fake"}

    async def generate(self, **kwargs) -> Dict[str, Any]:
        if self.fail:
            raise RuntimeError("生成失败")
        return {"text": "hi"}


# --------------------------------------------------------------------------- #
# 构造 / 打桩辅助
# --------------------------------------------------------------------------- #
def _make_client(
    session: Optional[Any] = None,
    retry_count: int = 3,
    retry_delay: float = 0.0,
) -> mod.InferServiceClient:
    """构造 base_url 固定、session 被替换为替身的客户端（测试内默认零退避）。"""
    client = mod.InferServiceClient(base_url=BASE_URL, timeout=7)
    client.session = session
    client.retry_count = retry_count
    client.retry_delay = retry_delay
    return client


def _patch_asyncio(monkeypatch) -> _FakeAsyncio:
    """把模块内的 asyncio 换成记录 sleep 的替身，避免真实等待。"""
    shim = _FakeAsyncio(asyncio)
    monkeypatch.setattr(mod, "asyncio", shim)
    return shim


def _patch_client_session(monkeypatch) -> List[Any]:
    """把模块内的 aiohttp.ClientSession 换成替身，返回被创建实例的列表。"""
    created: List[Any] = []

    class _CreatedSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            created.append(self)

    monkeypatch.setattr(mod, "aiohttp", _FakeAiohttp(aiohttp, _CreatedSession))
    return created


# --------------------------------------------------------------------------- #
# __init__
# --------------------------------------------------------------------------- #
def test_init_with_explicit_base_url():
    """显式传入 base_url 时不读配置，其余字段取默认值。"""
    client = mod.InferServiceClient(base_url="http://1.2.3.4:9999", timeout=15)

    assert client.base_url == "http://1.2.3.4:9999"
    assert client.timeout == 15
    assert client.session is None
    assert client.retry_count == 3
    assert client.retry_delay == 1.0


def test_init_default_timeout_is_300():
    """timeout 默认 300 秒。"""
    assert mod.InferServiceClient(base_url="http://x").timeout == 300


def test_init_derives_base_url_from_settings(monkeypatch):
    """base_url 为 None 时由 settings.server 的 host/port 拼出地址。"""
    monkeypatch.delenv("INFER_SERVICE_HOST", raising=False)
    monkeypatch.delenv("INFER_SERVICE_PORT", raising=False)
    monkeypatch.setattr(mod, "get_settings", lambda: _FakeSettings())

    assert mod.InferServiceClient().base_url == "http://127.0.0.1:9000"


def test_init_env_vars_override_settings(monkeypatch):
    """INFER_SERVICE_HOST / INFER_SERVICE_PORT 环境变量优先于配置。"""
    monkeypatch.setattr(mod, "get_settings", lambda: _FakeSettings())
    monkeypatch.setenv("INFER_SERVICE_HOST", "10.0.0.5")
    monkeypatch.setenv("INFER_SERVICE_PORT", "12345")

    assert mod.InferServiceClient().base_url == "http://10.0.0.5:12345"


# --------------------------------------------------------------------------- #
# _get_session / _close_session / shutdown / 上下文管理器
# --------------------------------------------------------------------------- #
def test_get_session_creates_once_and_reuses(monkeypatch):
    """session 为空时创建（带 total 超时），再次获取复用同一对象。"""
    created = _patch_client_session(monkeypatch)
    client = mod.InferServiceClient(base_url="http://x", timeout=42)

    async def _run():
        return await client._get_session(), await client._get_session()

    first, second = asyncio.run(_run())

    assert first is second
    assert first is client.session
    assert len(created) == 1
    assert created[0] is first
    assert first.kwargs["timeout"].total == 42


def test_get_session_returns_existing_open_session(monkeypatch):
    """已有未关闭的 session 时直接复用，不新建。"""
    created = _patch_client_session(monkeypatch)
    client = mod.InferServiceClient(base_url="http://x")
    existing = _ClosableSession()
    client.session = existing

    assert asyncio.run(client._get_session()) is existing
    assert created == []


def test_get_session_recreates_when_closed(monkeypatch):
    """已关闭的 session 会被替换为新会话。"""
    created = _patch_client_session(monkeypatch)
    client = mod.InferServiceClient(base_url="http://x")
    stale = _ClosableSession(closed=True)
    client.session = stale

    got = asyncio.run(client._get_session())

    assert got is not stale
    assert got is client.session
    assert len(created) == 1


def test_close_session_closes_and_resets():
    """关闭会话后引用被清空。"""
    client = mod.InferServiceClient(base_url="http://x")
    session = _ClosableSession()
    client.session = session

    asyncio.run(client._close_session())

    assert session.close_calls == 1
    assert client.session is None


def test_close_session_noop_when_none():
    """无会话时 _close_session 是空操作。"""
    client = mod.InferServiceClient(base_url="http://x")

    asyncio.run(client._close_session())

    assert client.session is None


def test_close_session_keeps_reference_when_already_closed():
    """已关闭的会话不再调用 close()，也不清空引用。"""
    client = mod.InferServiceClient(base_url="http://x")
    session = _ClosableSession(closed=True)
    client.session = session

    asyncio.run(client._close_session())

    assert session.close_calls == 0
    assert client.session is session


def test_shutdown_delegates_to_close_session():
    """shutdown 等价于关闭并清空会话。"""
    client = mod.InferServiceClient(base_url="http://x")
    session = _ClosableSession()
    client.session = session

    asyncio.run(client.shutdown())

    assert session.close_calls == 1
    assert client.session is None


def test_async_context_manager_enters_and_closes():
    """async with 返回自身，退出时关闭会话。"""
    client = mod.InferServiceClient(base_url="http://x")
    session = _ClosableSession()
    client.session = session

    async def _run():
        async with client as entered:
            assert entered is client
        return client.session

    assert asyncio.run(_run()) is None
    assert session.close_calls == 1


# --------------------------------------------------------------------------- #
# _request_with_retry
# --------------------------------------------------------------------------- #
def test_request_with_retry_returns_json_on_200():
    """200 时直接返回解析后的 JSON，且只请求一次。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={"ok": True}))
    client = _make_client(session)

    result = asyncio.run(client._request_with_retry("GET", "/health"))

    assert result == {"ok": True}
    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "http://127.0.0.1:8000/health"


def test_request_with_retry_urljoin_semantics():
    """endpoint 不带前导斜杠时按 urljoin 规则替换 base_url 的最后一段。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={}))
    client = _make_client(session)
    client.base_url = "http://127.0.0.1:8000/api"

    asyncio.run(client._request_with_retry("GET", "generate"))

    assert session.calls[0]["url"] == "http://127.0.0.1:8000/generate"


def test_request_with_retry_http_error_json_body(monkeypatch):
    """非 200 且 content_type 为 JSON 时错误信息带响应体，按指数退避重试后抛错。"""
    shim = _patch_asyncio(monkeypatch)
    session = _FakeSession(
        _FakeResponse(status=500, json_data={"detail": "boom"}, content_type="application/json")
    )
    client = _make_client(session, retry_count=2, retry_delay=1.0)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(client._request_with_retry("POST", "/generate"))

    message = str(excinfo.value)
    assert "HTTP 500" in message
    assert "boom" in message
    assert len(session.calls) == 3
    assert shim.sleep_delays == [1.0, 2.0]


@pytest.mark.parametrize(
    "status, content_type, json_data, text_data, expected",
    [
        # JSON 体为空字典（falsy）→ 回退到 text()
        (404, "application/json", {}, "json-empty-body", "json-empty-body"),
        # 非 JSON content_type → 直接使用 text()
        (503, "text/plain", {"ignored": True}, "plain-body", "plain-body"),
    ],
)
def test_request_with_retry_http_error_falls_back_to_text(
    status, content_type, json_data, text_data, expected
):
    """非 200 时错误信息在 JSON 体缺失/为空时回退到 text()。"""
    session = _FakeSession(
        _FakeResponse(
            status=status, json_data=json_data, text_data=text_data, content_type=content_type
        )
    )
    client = _make_client(session, retry_count=0)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(client._request_with_retry("GET", "/health"))

    message = str(excinfo.value)
    assert f"HTTP {status}" in message
    assert expected in message
    assert len(session.calls) == 1


def test_request_with_retry_client_error_retries_then_raises(monkeypatch):
    """aiohttp.ClientError 走重试分支，耗尽后抛出统一错误信息。"""
    shim = _patch_asyncio(monkeypatch)
    session = _FakeSession(exc=aiohttp.ClientConnectionError("conn refused"))
    client = _make_client(session, retry_count=2, retry_delay=1.0)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(client._request_with_retry("GET", "/health"))

    message = str(excinfo.value)
    assert "请求失败" in message
    assert "conn refused" in message
    assert len(session.calls) == 3
    assert shim.sleep_delays == [1.0, 2.0]


def test_request_with_retry_timeout_error_retries_then_raises(monkeypatch):
    """asyncio.TimeoutError 走同一个重试分支。"""
    shim = _patch_asyncio(monkeypatch)
    session = _FakeSession(exc=asyncio.TimeoutError("连接超时"))
    client = _make_client(session, retry_count=1, retry_delay=1.0)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(client._request_with_retry("GET", "/health"))

    message = str(excinfo.value)
    assert "请求失败" in message
    assert "连接超时" in message
    assert len(session.calls) == 2
    assert shim.sleep_delays == [1.0]


def test_request_with_retry_unexpected_error_reraises_original(monkeypatch):
    """非网络类异常同样重试，但耗尽后原样抛出（不包装）。"""
    shim = _patch_asyncio(monkeypatch)
    session = _FakeSession(exc=ValueError("bad value"))
    client = _make_client(session, retry_count=1, retry_delay=1.0)

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(client._request_with_retry("POST", "/generate"))

    assert str(excinfo.value) == "bad value"
    assert len(session.calls) == 2
    assert shim.sleep_delays == [1.0]


def test_request_with_retry_zero_retry_no_sleep(monkeypatch):
    """retry_count=0 时只尝试一次，不进入退避等待。"""
    shim = _patch_asyncio(monkeypatch)
    session = _FakeSession(exc=aiohttp.ClientConnectionError("once"))
    client = _make_client(session, retry_count=0, retry_delay=1.0)

    with pytest.raises(Exception):
        asyncio.run(client._request_with_retry("GET", "/health"))

    assert len(session.calls) == 1
    assert shim.sleep_delays == []


def test_request_with_retry_negative_retry_count_never_requests():
    """retry_count 为负数时循环体一次都不执行，落到末尾兜底抛错。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={"ok": True}))
    client = _make_client(session, retry_count=-1)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(client._request_with_retry("GET", "/health"))

    assert "所有重试都失败了" in str(excinfo.value)
    assert session.calls == []


# --------------------------------------------------------------------------- #
# health_check / get_model_status
# --------------------------------------------------------------------------- #
def test_health_check_success():
    """健康检查命中 GET /health 并返回结果。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={"status": "healthy"}))
    client = _make_client(session)

    assert asyncio.run(client.health_check()) == {"status": "healthy"}
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "http://127.0.0.1:8000/health"


def test_health_check_propagates_error():
    """健康检查失败时原样向上抛出（不吞异常）。"""
    client = _make_client(_FakeSession())
    error = RuntimeError("health boom")

    async def _boom(*args, **kwargs):
        raise error

    client._request_with_retry = _boom

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(client.health_check())

    assert excinfo.value is error


def test_get_model_status_success():
    """模型状态查询命中 GET /model/status 并返回结果。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={"loaded": True}))
    client = _make_client(session)

    assert asyncio.run(client.get_model_status()) == {"loaded": True}
    assert session.calls[0]["url"] == "http://127.0.0.1:8000/model/status"


def test_get_model_status_propagates_error():
    """模型状态查询失败时原样向上抛出。"""
    client = _make_client(_FakeSession())
    error = RuntimeError("status boom")

    async def _boom(*args, **kwargs):
        raise error

    client._request_with_retry = _boom

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(client.get_model_status())

    assert excinfo.value is error


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #
def test_generate_success_sends_expected_payload():
    """generate 组装默认参数并以 POST /generate 发出。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={"text": "你好"}))
    client = _make_client(session)

    result = asyncio.run(client.generate("hi"))

    assert result == {"text": "你好"}
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://127.0.0.1:8000/generate"
    assert call["headers"] == {"Content-Type": "application/json"}
    assert call["json"] == {
        "prompt": "hi",
        "history": [],
        "max_tokens": None,
        "temperature": 0.7,
        "top_p": 0.9,
        "repetition_penalty": 1.0,
    }


def test_generate_forwards_history_and_overrides():
    """显式传入的 history 与采样参数被原样透传。"""
    session = _FakeSession(_FakeResponse(status=200, json_data={"text": "ok"}))
    client = _make_client(session)
    history = [{"role": "user", "content": "上一句"}]

    asyncio.run(
        client.generate(
            "p",
            history=history,
            max_tokens=10,
            temperature=0.1,
            top_p=0.5,
            repetition_penalty=1.2,
        )
    )

    payload = session.calls[0]["json"]
    assert payload["history"] is history
    assert payload["max_tokens"] == 10
    assert payload["temperature"] == 0.1
    assert payload["top_p"] == 0.5
    assert payload["repetition_penalty"] == 1.2


def test_generate_propagates_error():
    """生成失败时向上抛出，且确实发出过请求。"""
    session = _FakeSession(exc=ValueError("bad prompt"))
    client = _make_client(session, retry_count=0)

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(client.generate("p"))

    assert str(excinfo.value) == "bad prompt"
    assert len(session.calls) == 1


# --------------------------------------------------------------------------- #
# get_infer_client
# --------------------------------------------------------------------------- #
def test_get_infer_client_returns_singleton(monkeypatch):
    """首次调用创建实例，后续调用返回同一实例。"""
    monkeypatch.setattr(mod, "_global_client", None)
    monkeypatch.setattr(mod, "get_settings", lambda: _FakeSettings())

    first = mod.get_infer_client()
    second = mod.get_infer_client()

    assert isinstance(first, mod.InferServiceClient)
    assert first.base_url == "http://127.0.0.1:9000"
    assert first is second


def test_get_infer_client_reuses_existing_instance(monkeypatch):
    """已有全局实例时不再新建。"""
    existing = mod.InferServiceClient(base_url="http://cached:1")
    monkeypatch.setattr(mod, "_global_client", existing)

    assert mod.get_infer_client() is existing


# --------------------------------------------------------------------------- #
# example_usage / __main__ 入口
# --------------------------------------------------------------------------- #
def test_example_usage_prints_all_results(monkeypatch, capsys):
    """example_usage 正常路径打印健康检查、模型状态与生成结果。"""
    monkeypatch.setattr(mod, "InferServiceClient", lambda: _FakeExampleClient())

    asyncio.run(mod.example_usage())

    out = capsys.readouterr().out
    assert "健康检查" in out
    assert "模型状态" in out
    assert "生成结果: hi" in out


def test_example_usage_prints_error_on_failure(monkeypatch, capsys):
    """example_usage 捕获异常并打印错误，不向外抛出。"""
    monkeypatch.setattr(mod, "InferServiceClient", lambda: _FakeExampleClient(fail=True))

    asyncio.run(mod.example_usage())

    assert "错误: 生成失败" in capsys.readouterr().out


def test_main_block_runs_example_usage(monkeypatch):
    """以 __main__ 执行模块时调用 asyncio.run(example_usage())（打桩避免真实网络）。"""
    captured: Dict[str, Any] = {}

    def _fake_run(coro):
        captured["name"] = coro.cr_code.co_name
        coro.close()  # 关闭未运行的协程，避免 "never awaited" 告警

    monkeypatch.setattr(asyncio, "run", _fake_run)

    runpy.run_path(mod.__file__, run_name="__main__")

    assert captured["name"] == "example_usage"
