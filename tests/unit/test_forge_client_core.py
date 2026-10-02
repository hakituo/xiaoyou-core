#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``core/modules/forge_client.py`` 基础层（连接 / 配置 / 缓存）单元测试。

覆盖：``__init__`` / ``_is_connection_error`` / ``_log_unavailable`` /
``_get_current_model_filename`` / ``get_options`` / ``ping`` / ``unload_model`` /
``_looks_like_win_pipe_broken`` / ``wait_for_model_loaded`` / ``get_models`` /
``_get_models_cached``。

约束：
- ``requests`` 是模块级 import，必须 patch **被测模块自身**（``forge_client.requests``），
  绝不触发真实 HTTP；
- ``time`` 同样被替换成受控时钟 ``FakeClock``，不依赖真实时间流逝、不真 sleep；
- 不写任何磁盘（无文件 IO），不依赖跨用例全局状态。
"""

from __future__ import annotations

import pytest

import core.modules.forge_client as fc
from core.modules.forge_client import ForgeClient


# --------------------------------------------------------------------------- #
# 替身工具
# --------------------------------------------------------------------------- #


class FakeClock:
    """受控时钟：完整替代被测模块内的 ``time``。"""

    def __init__(self, now: float = 1000.0):
        self.now = float(now)
        self.sleeps = []

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds) -> None:
        self.sleeps.append(seconds)
        self.now += float(seconds)


class FakeResponse:
    """假 HTTP 响应。"""

    def __init__(self, status_code=200, json_data=None, text="", content=b""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    """``requests`` 模块替身：按调用顺序弹出预设结果并记录调用。"""

    def __init__(self, get_results=None, post_results=None):
        self._get_results = list(get_results or [])
        self._post_results = list(post_results or [])
        self.get_calls = []
        self.post_calls = []

    @staticmethod
    def _pop(results):
        if not results:
            return FakeResponse()
        item = results.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item()
        return item

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self._pop(self._get_results)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self._pop(self._post_results)


class BadStrError(Exception):
    """``str()`` 自身抛错的异常，用于覆盖 except 兜底分支。"""

    def __str__(self):
        raise RuntimeError("boom")


class BadStrObject:
    """真值但 ``str()`` 抛错的对象。"""

    def __bool__(self):
        return True

    def __str__(self):
        raise RuntimeError("boom")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(fc, "time", c)
    return c


@pytest.fixture()
def fake_requests(monkeypatch):
    def _install(get_results=None, post_results=None):
        fr = FakeRequests(get_results, post_results)
        monkeypatch.setattr(fc, "requests", fr)
        return fr

    return _install


@pytest.fixture()
def client(clock):
    return ForgeClient()


# --------------------------------------------------------------------------- #
# __init__
# --------------------------------------------------------------------------- #


def test_init_defaults(client):
    """默认构造：URL、映射表与缓存字段初始值。"""
    assert client.base_url == "http://127.0.0.1:7860"
    assert client.model_map["sd1.5"].endswith(".safetensors")
    assert client.model_map["sdxl"] == client.model_map["juggernaut"]
    assert client.vae_map["default"] == "Automatic"
    assert client.lora_map == {}
    assert client.current_model is None
    assert client._models_cache is None
    assert client._models_cache_ts == 0.0
    assert client._last_loaded_checkpoint is None
    assert client._last_unavailable_log_ts == 0.0
    assert client._unavailable_log_interval == 15.0


def test_init_custom_base_url():
    """自定义 base_url 生效。"""
    assert ForgeClient("http://host:9").base_url == "http://host:9"


# --------------------------------------------------------------------------- #
# _is_connection_error
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "Cannot connect to host",
        "Connection refused",
        "Failed to establish a new connection",
        "Max retries exceeded",
        "Connection error",
        "Operation timed out",
        "read timeout",
        "No connection could be made because the target machine actively refused it",
    ],
)
def test_is_connection_error_true(client, text):
    """各类连接类文案均判为连接错误。"""
    assert client._is_connection_error(Exception(text)) is True


@pytest.mark.parametrize("text", ["", "HTTP 500 internal", "some random failure"])
def test_is_connection_error_false(client, text):
    """无关文案判为非连接错误。"""
    assert client._is_connection_error(Exception(text)) is False


def test_is_connection_error_case_insensitive(client):
    """大小写不敏感。"""
    assert client._is_connection_error(Exception("CANNOT CONNECT")) is True


def test_is_connection_error_str_raises(client):
    """``str(err)`` 抛错时返回 False（兜底分支）。"""
    assert client._is_connection_error(BadStrError()) is False


# --------------------------------------------------------------------------- #
# _log_unavailable
# --------------------------------------------------------------------------- #


def test_log_unavailable_warning_branch(client, clock):
    """距上次日志超过间隔 → 记录 warning 并更新时间戳。"""
    client._last_unavailable_log_ts = 0.0
    client._log_unavailable("动作", Exception("e"))
    assert client._last_unavailable_log_ts == clock.now


def test_log_unavailable_debug_branch(client, clock):
    """间隔内 → 只记 debug，时间戳不变。"""
    client._last_unavailable_log_ts = clock.now
    before = client._last_unavailable_log_ts
    client._log_unavailable("动作", Exception("e"))
    assert client._last_unavailable_log_ts == before


def test_log_unavailable_none_ts(client, clock):
    """时间戳为 None 时按 0.0 处理（走 warning 分支）。"""
    client._last_unavailable_log_ts = None
    client._log_unavailable("动作", Exception("e"))
    assert client._last_unavailable_log_ts == clock.now


# --------------------------------------------------------------------------- #
# _get_current_model_filename
# --------------------------------------------------------------------------- #


def test_get_current_model_filename_ok(client, fake_requests):
    """200 且含 sd_model_checkpoint → 返回该值。"""
    fr = fake_requests(
        get_results=[FakeResponse(200, {"sd_model_checkpoint": "A.safetensors"})]
    )
    assert client._get_current_model_filename() == "A.safetensors"
    assert fr.get_calls[0][0].endswith("/sdapi/v1/options")
    assert fr.get_calls[0][1]["timeout"] == 5


def test_get_current_model_filename_missing_key(client, fake_requests):
    """200 但缺 key → None。"""
    fake_requests(get_results=[FakeResponse(200, {})])
    assert client._get_current_model_filename() is None


def test_get_current_model_filename_non_200(client, fake_requests):
    """非 200 → None。"""
    fake_requests(get_results=[FakeResponse(404, text="no")])
    assert client._get_current_model_filename() is None


def test_get_current_model_filename_connection_error(client, fake_requests):
    """连接错误 → 记录不可用并返回 None。"""
    fake_requests(get_results=[ConnectionError("Cannot connect to Forge")])
    assert client._get_current_model_filename() is None
    assert client._last_unavailable_log_ts == 1000.0


def test_get_current_model_filename_other_error(client, fake_requests):
    """非连接错误 → 记录 error 并返回 None。"""
    fake_requests(get_results=[ValueError("weird")])
    assert client._get_current_model_filename() is None


# --------------------------------------------------------------------------- #
# get_options
# --------------------------------------------------------------------------- #


def test_get_options_ok(client, fake_requests):
    """200 → 返回 json 字典。"""
    fr = fake_requests(get_results=[FakeResponse(200, {"sd_model_checkpoint": "m"})])
    assert client.get_options() == {"sd_model_checkpoint": "m"}
    assert fr.get_calls[0][1]["timeout"] == 5.0


def test_get_options_timeout_floor(client, fake_requests):
    """timeout 下限被夹到 0.1。"""
    fr = fake_requests(get_results=[FakeResponse(200, {})])
    assert client.get_options(timeout=0) == {}
    assert fr.get_calls[0][1]["timeout"] == 0.1


def test_get_options_non_200(client, fake_requests):
    """非 200 → None。"""
    fake_requests(get_results=[FakeResponse(500, text="x")])
    assert client.get_options() is None


def test_get_options_connection_error(client, fake_requests):
    """连接错误 → None 且记录不可用。"""
    fake_requests(get_results=[ConnectionError("Connection refused")])
    assert client.get_options() is None
    assert client._last_unavailable_log_ts == 1000.0


def test_get_options_other_error(client, fake_requests):
    """非连接错误 → None。"""
    fake_requests(get_results=[ValueError("bad")])
    assert client.get_options() is None


# --------------------------------------------------------------------------- #
# ping
# --------------------------------------------------------------------------- #


def test_ping_true(client, fake_requests):
    """200 → True。"""
    fake_requests(get_results=[FakeResponse(200, {})])
    assert client.ping() is True


def test_ping_false_non_200(client, fake_requests):
    """非 200 → False。"""
    fake_requests(get_results=[FakeResponse(503)])
    assert client.ping() is False


def test_ping_false_exception(client, fake_requests):
    """异常 → False。"""
    fake_requests(get_results=[ConnectionError("Cannot connect")])
    assert client.ping() is False


# --------------------------------------------------------------------------- #
# unload_model
# --------------------------------------------------------------------------- #


def test_unload_model_200(client, fake_requests):
    """200 → True 且清空 _last_loaded_checkpoint。"""
    fr = fake_requests(post_results=[FakeResponse(200)])
    client._last_loaded_checkpoint = "x.safetensors"
    assert client.unload_model() is True
    assert client._last_loaded_checkpoint is None
    assert fr.post_calls[0][0].endswith("/sdapi/v1/unload-checkpoint")
    assert fr.post_calls[0][1]["timeout"] == 10


def test_unload_model_204(client, fake_requests):
    """204 → True。"""
    fake_requests(post_results=[FakeResponse(204)])
    assert client.unload_model() is True


def test_unload_model_other_status(client, fake_requests):
    """其他状态码 → False。"""
    fake_requests(post_results=[FakeResponse(500, text="boom")])
    assert client.unload_model() is False


def test_unload_model_exception(client, fake_requests):
    """异常 → False。"""
    fake_requests(post_results=[ConnectionError("Cannot connect")])
    assert client.unload_model() is False


# --------------------------------------------------------------------------- #
# _looks_like_win_pipe_broken
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body,expected",
    [
        ("[WinError 233] The pipe is being closed", True),
        ("[winerror 233] lowercase", True),
        ("管道的另一端上无任何进程。", True),
        ("", False),
        (None, False),
        ("normal error text", False),
    ],
)
def test_looks_like_win_pipe_broken(client, body, expected):
    """WinError233 / 中文断管文案判定。"""
    assert client._looks_like_win_pipe_broken(body) is expected


def test_looks_like_win_pipe_broken_str_raises(client):
    """``str(body)`` 抛错时返回 False（兜底分支）。"""
    assert client._looks_like_win_pipe_broken(BadStrObject()) is False


# --------------------------------------------------------------------------- #
# wait_for_model_loaded
# --------------------------------------------------------------------------- #


def test_wait_for_model_loaded_empty_target(client, clock):
    """空目标 → 立即 False，不进入轮询、不 sleep。"""
    assert client.wait_for_model_loaded("   ") is False
    assert clock.sleeps == []


def test_wait_for_model_loaded_found(client, clock, monkeypatch):
    """首次命中（大小写不敏感）→ True，不 sleep。"""
    monkeypatch.setattr(
        client,
        "_get_current_model_filename",
        lambda: "SDXL\\juggernautXL_ragnarokBy.safetensors",
    )
    assert client.wait_for_model_loaded("Juggernaut", timeout=5) is True
    assert clock.sleeps == []


def test_wait_for_model_loaded_timeout(client, clock, monkeypatch):
    """始终不命中 → 轮询到 deadline 后 False（受控时钟推进）。"""
    monkeypatch.setattr(
        client, "_get_current_model_filename", lambda: "other.safetensors"
    )
    assert client.wait_for_model_loaded("target", timeout=3, poll_interval=1) is False
    assert clock.sleeps == [1, 1, 1]


# --------------------------------------------------------------------------- #
# get_models
# --------------------------------------------------------------------------- #


def test_get_models_ok(client, clock, fake_requests):
    """200 → 返回列表并写入缓存与时间戳。"""
    models = [{"title": "A"}]
    fr = fake_requests(get_results=[FakeResponse(200, models)])
    assert client.get_models() == models
    assert client._models_cache == models
    assert client._models_cache_ts == clock.now
    assert fr.get_calls[0][0].endswith("/sdapi/v1/sd-models")


def test_get_models_non_200(client, fake_requests):
    """非 200 → []。"""
    fake_requests(get_results=[FakeResponse(500, text="x")])
    assert client.get_models() == []


def test_get_models_connection_error(client, fake_requests):
    """连接错误 → [] 且记录不可用。"""
    fake_requests(get_results=[ConnectionError("Cannot connect")])
    assert client.get_models() == []
    assert client._last_unavailable_log_ts == 1000.0


def test_get_models_other_error(client, fake_requests):
    """非连接错误 → []。"""
    fake_requests(get_results=[ValueError("bad")])
    assert client.get_models() == []


# --------------------------------------------------------------------------- #
# _get_models_cached
# --------------------------------------------------------------------------- #


def test_get_models_cached_hit(client, clock, monkeypatch):
    """缓存未过期 → 直接返回缓存，不调 get_models。"""
    client._models_cache = [{"t": 1}]
    client._models_cache_ts = clock.now
    called = []
    monkeypatch.setattr(
        client, "get_models", lambda: called.append(1) or ["fresh"]
    )
    assert client._get_models_cached() == [{"t": 1}]
    assert called == []


def test_get_models_cached_stale(client, clock, monkeypatch):
    """缓存过期 → 重新拉取。"""
    client._models_cache = [{"t": 1}]
    client._models_cache_ts = clock.now - 100
    monkeypatch.setattr(client, "get_models", lambda: ["fresh"])
    assert client._get_models_cached(60.0) == ["fresh"]


def test_get_models_cached_no_cache(client, monkeypatch):
    """无缓存 → 重新拉取。"""
    monkeypatch.setattr(client, "get_models", lambda: ["fresh"])
    assert client._get_models_cached() == ["fresh"]
