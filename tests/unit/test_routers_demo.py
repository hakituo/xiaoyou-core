# -*- coding: utf-8 -*-
"""``routers/demo.py`` 的单元测试。

裁决：该模块虽然是「演示」用途，但被 ``main.py`` 无条件挂载
（``main.py:97`` 导入 ``routers.demo``，``main.py:206`` ``app.include_router(demo_router)``），
因此会进入 CI 覆盖率口径，必须补测。

可测性：模块内所有外部依赖（调度器、配置、资源管理器、资源锁）都是
**函数体内的惰性 import**，可以在测试里直接替换模块属性，无需真实服务/模型/网络。
唯一需要处理的是源码里的 ``asyncio.sleep``（合计 4.3 秒的真实等待），
本文件用 ``routers.demo`` 模块级 asyncio 替身把 sleep 变成立即返回，
同时**记录**调用参数用于断言，从而既快又不断言真实流逝时间。
"""
from __future__ import annotations

import asyncio
import json
import os
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config.integrated_config as integrated_config
import core.resource_manager as resource_manager_mod
import core.utils.resource_lock as resource_lock_mod
from core.services.scheduler import cpp_scheduler_engine
from core.utils import demo_utils

import routers.demo as demo_mod

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(demo_mod.__file__)))
DEMO_INDEX = os.path.join(_PROJECT_ROOT, "static", "demo", "index.html")


# ==================== 通用替身 ====================


class _FastAsyncio:
    """``routers.demo`` 内部 asyncio 的替身：sleep 立即返回并记录延时。

    ``__getattr__`` 把 ``wait_for`` / ``get_event_loop`` 等原样透传，
    只拦截 ``sleep``，避免改动全局 asyncio 模块。
    """

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "sleeps", [])

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)

    async def sleep(self, delay):
        object.__getattribute__(self, "sleeps").append(delay)
        return None


class _FakeWebSocket:
    """WebSocket 替身，只实现 ``demo.py`` 用到的接口。"""

    def __init__(self, *, query_params=None, headers=None, send_limit=None, send_exc=None):
        self.query_params = query_params
        self.headers = headers or {}
        self.accepted = False
        self.closed = None
        self.sent = []
        self._send_limit = send_limit
        self._send_exc = send_exc

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)

    async def send_text(self, text):
        # send_limit 用于确定性地跳出源码里的 while True（否则用例会死循环）
        if self._send_limit is not None and len(self.sent) >= self._send_limit:
            raise self._send_exc
        self.sent.append(text)


class _FakeModel:
    """模型资源状态替身。"""

    def __init__(
        self,
        *,
        is_loaded=False,
        is_offloaded=False,
        memory_usage_mb=0,
        vram_usage_mb=0,
        priority=5,
        device="cuda:0",
    ):
        self.is_loaded = is_loaded
        self.is_offloaded = is_offloaded
        self.memory_usage_mb = memory_usage_mb
        self.vram_usage_mb = vram_usage_mb
        self.priority = priority
        self.device = device


class _FakeMonitor:
    """系统监控替身。"""

    def __init__(
        self,
        *,
        gpu_info=(1024, 8192),
        cpu_usage=12.5,
        cpu_model="FakeCPU",
        memory_usage=33.3,
        gpu_model="FakeGPU",
        cpu_usage_exc=None,
    ):
        self._gpu_info = gpu_info
        self._cpu_usage = cpu_usage
        self._cpu_model = cpu_model
        self._memory_usage = memory_usage
        self._gpu_model = gpu_model
        self._cpu_usage_exc = cpu_usage_exc

    def get_gpu_memory_usage(self):
        return self._gpu_info

    def get_cpu_usage(self):
        if self._cpu_usage_exc is not None:
            raise self._cpu_usage_exc
        return self._cpu_usage

    def get_cpu_model(self):
        return self._cpu_model

    def get_memory_usage(self):
        return self._memory_usage

    def get_gpu_model(self):
        return self._gpu_model


class _FakeResourceManager:
    """资源管理器替身。"""

    def __init__(self, *, models=None, monitor=None, metrics_exc=None):
        self.models = {} if models is None else models
        self.monitor = monitor if monitor is not None else _FakeMonitor()
        self._metrics_exc = metrics_exc
        self.metrics_calls = 0

    async def _update_model_resource_metrics(self):
        self.metrics_calls += 1
        if self._metrics_exc is not None:
            raise self._metrics_exc


class _FakeEngine:
    """C++ 调度器替身。"""

    def __init__(self, enabled=True):
        self.enabled = enabled


def _make_settings(*, token="", kv_swap_enabled=False):
    """构造 ``get_settings()`` 的替身返回值。"""
    return types.SimpleNamespace(
        security=types.SimpleNamespace(web_access_token=token),
        model=types.SimpleNamespace(kv_swap_enabled=kv_swap_enabled),
    )


# ==================== fixture ====================


@pytest.fixture()
def fast_asyncio(monkeypatch):
    """把 routers.demo 的 asyncio 换成立即返回的替身，并返回它以便断言 sleep 参数。"""
    shim = _FastAsyncio(asyncio)
    monkeypatch.setattr(demo_mod, "asyncio", shim)
    return shim


@pytest.fixture()
def clean_demo_logs():
    """隔离 demo 日志全局缓存，避免跨用例污染。"""
    demo_utils.clear_demo_logs()
    yield
    demo_utils.clear_demo_logs()


@pytest.fixture()
def client():
    """只挂载 demo router 的最小应用，用于 HTTP 路由测试。"""
    app = FastAPI()
    app.include_router(demo_mod.router)
    with TestClient(app) as c:
        yield c


def _run_ws(ws):
    """直接调用 WebSocket 端点协程（不经过真实握手，便于精确控制分支）。"""
    return asyncio.run(demo_mod.websocket_status(ws))


def _patch_ws_deps(monkeypatch, *, rm, token="tok", scheduler=None, lock=None, metrics=None):
    """统一替换 WebSocket 端点的外部依赖。"""
    monkeypatch.setattr(cpp_scheduler_engine, "get_scheduler_status", lambda: scheduler)
    monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings(token=token))
    if lock is None:
        monkeypatch.setattr(
            resource_lock_mod,
            "get_resource_lock",
            lambda: types.SimpleNamespace(get_status=lambda: None),
        )
    else:
        monkeypatch.setattr(resource_lock_mod, "get_resource_lock", lock)
    if metrics is not None:
        # 源码里是 _demo_utils()[1]()，因此必须替换成「可调用对象」而不是元组
        monkeypatch.setattr(demo_mod, "_demo_utils", lambda: metrics)


# ==================== HTTP: GET /demo ====================


def test_demo_page_serves_static_html(client):
    """静态页面存在时，应原样返回 static/demo/index.html 的内容。"""
    resp = client.get("/demo")
    assert resp.status_code == 200
    with open(DEMO_INDEX, "r", encoding="utf-8") as f:
        expected = f.read()
    assert resp.text == expected


def test_demo_page_fallback_when_html_missing(monkeypatch, client):
    """静态页面缺失时，应返回内联的兜底 HTML 而不是抛异常。"""
    fake_os = types.SimpleNamespace(
        path=types.SimpleNamespace(
            dirname=os.path.dirname,
            abspath=os.path.abspath,
            join=os.path.join,
            exists=lambda _p: False,
        )
    )
    monkeypatch.setattr(demo_mod, "os", fake_os)

    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "Demo Dashboard HTML not found in static/demo/index.html" in resp.text


# ==================== HTTP: POST /demo/logs ====================


def test_add_demo_log_default_level(client, clean_demo_logs):
    """省略 level 时应使用默认值 info，并真正写入共享日志缓存。"""
    resp = client.post("/demo/logs", json={"message": "hello-demo"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    logs = demo_utils.get_demo_logs()
    assert len(logs) == 1
    assert logs[0]["text"] == "hello-demo"
    assert logs[0]["level"] == "info"


def test_add_demo_log_custom_level(client, clean_demo_logs):
    """显式传入 level 时应原样落库。"""
    resp = client.post("/demo/logs", json={"message": "boom", "level": "error"})
    assert resp.status_code == 200

    logs = demo_utils.get_demo_logs()
    assert [entry["level"] for entry in logs] == ["error"]
    assert logs[0]["text"] == "boom"


def test_add_demo_log_rejects_missing_message(client, clean_demo_logs):
    """缺少必填字段 message 时应 422，且不产生任何日志。"""
    resp = client.post("/demo/logs", json={"level": "info"})
    assert resp.status_code == 422
    assert demo_utils.get_demo_logs() == []


# ==================== HTTP: POST /demo/trigger_kvswap ====================


def test_trigger_kvswap_engine_missing(monkeypatch, client):
    """调度器单例为 None 时，应返回错误提示且不写任何日志。"""
    logged = []
    monkeypatch.setattr(cpp_scheduler_engine, "get_scheduler_engine", lambda: None)
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings())
    monkeypatch.setattr(demo_utils, "add_demo_log", lambda *a, **k: logged.append(a))

    resp = client.post("/demo/trigger_kvswap")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "error",
        "message": "C++ 调度器未启用，无法演示 KVSwap",
    }
    assert logged == []


def test_trigger_kvswap_engine_disabled(monkeypatch, client):
    """调度器存在但 enabled=False 时，同样返回错误提示。"""
    monkeypatch.setattr(
        cpp_scheduler_engine, "get_scheduler_engine", lambda: _FakeEngine(enabled=False)
    )
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings())

    resp = client.post("/demo/trigger_kvswap")
    assert resp.json()["status"] == "error"


def test_trigger_kvswap_kv_disabled_warns_but_completes(monkeypatch, client, fast_asyncio):
    """KVSwap 在配置中被禁用时，应先补一条 warning 日志，流程仍走完。"""
    logged = []
    monkeypatch.setattr(cpp_scheduler_engine, "get_scheduler_engine", lambda: _FakeEngine())
    monkeypatch.setattr(
        integrated_config, "get_settings", lambda: _make_settings(kv_swap_enabled=False)
    )
    monkeypatch.setattr(
        demo_utils, "add_demo_log", lambda msg, level="info": logged.append((msg, level))
    )

    resp = client.post("/demo/trigger_kvswap")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "message": "KVSwap test sequence completed"}

    assert "已禁用" in logged[0][0]
    assert logged[0][1] == "warning"
    # 禁用分支额外多一条日志：8 条 vs 启用分支的 7 条
    assert len(logged) == 8
    assert fast_asyncio.sleeps == [0.8, 1.2, 1.5, 0.8]


def test_trigger_kvswap_full_sequence(monkeypatch, client, fast_asyncio):
    """KVSwap 已启用时，不应出现「已禁用」日志，日志顺序与内容应完整。"""
    logged = []
    monkeypatch.setattr(cpp_scheduler_engine, "get_scheduler_engine", lambda: _FakeEngine())
    monkeypatch.setattr(
        integrated_config, "get_settings", lambda: _make_settings(kv_swap_enabled=True)
    )
    monkeypatch.setattr(
        demo_utils, "add_demo_log", lambda msg, level="info": logged.append((msg, level))
    )

    resp = client.post("/demo/trigger_kvswap")
    assert resp.json()["status"] == "ok"

    messages = [msg for msg, _ in logged]
    assert len(messages) == 7
    assert not any("已禁用" in msg for msg in messages)
    assert "启动 KVSwap 压力测试" in messages[0]
    assert "已构建虚拟上下文负载" in messages[1]
    # 负载长度来自源码里固定字符串的 100 次重复，这里是精确值而非量级
    assert "3300 字符" in messages[1]
    assert "reconstructed" in messages[-1]
    assert [level for _, level in logged][-1] == "success"
    # 4 次等待的时长顺序，断言的是「参数」而不是真实流逝时间
    assert fast_asyncio.sleeps == [0.8, 1.2, 1.5, 0.8]


# ==================== WebSocket 握手 / 鉴权 ====================


def test_ws_route_is_mounted_and_rejects_when_token_unconfigured(monkeypatch):
    """路由确实挂在 /demo/ws/status；未配置访问令牌时应 1008 关闭。"""
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings(token=""))

    app = FastAPI()
    app.include_router(demo_mod.router)
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with c.websocket_connect("/demo/ws/status") as ws:
                ws.receive_text()

    assert excinfo.value.code == 1008
    assert "未配置访问令牌" in excinfo.value.reason


def test_ws_rejects_when_settings_raises(monkeypatch):
    """读取配置抛异常时，应降级为「未配置令牌」并关闭，而不是 500。"""

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(integrated_config, "get_settings", _boom)

    app = FastAPI()
    app.include_router(demo_mod.router)
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with c.websocket_connect("/demo/ws/status") as ws:
                ws.receive_text()

    assert excinfo.value.code == 1008
    assert "未配置访问令牌" in excinfo.value.reason


def test_ws_rejects_without_any_token(monkeypatch, fast_asyncio):
    """配置了令牌但请求未携带任何凭据时，应 1008 关闭且不接受连接。"""
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings(token="tok"))
    ws = _FakeWebSocket()

    _run_ws(ws)

    assert ws.accepted is False
    assert ws.closed == (1008, "未授权的 WebSocket 访问")
    assert ws.sent == []


def test_ws_rejects_wrong_query_token(monkeypatch, fast_asyncio):
    """query 携带错误令牌时应被拒绝。"""
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings(token="tok"))
    ws = _FakeWebSocket(query_params={"token": "bad"})

    _run_ws(ws)

    assert ws.accepted is False
    assert ws.closed == (1008, "未授权的 WebSocket 访问")


def test_ws_accepts_query_token(monkeypatch, fast_asyncio):
    """query 携带正确令牌时应接受连接并推送状态帧。"""
    rm = _FakeResourceManager(
        models={"m1": _FakeModel(is_loaded=True, vram_usage_mb=100)},
        monitor=_FakeMonitor(gpu_info=(2048, 8192)),
    )
    _patch_ws_deps(monkeypatch, rm=rm, token="tok", scheduler={"running": True})

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=1,
        send_exc=WebSocketDisconnect(1000),
    )
    _run_ws(ws)

    assert ws.accepted is True
    assert ws.closed is None
    payload = json.loads(ws.sent[0])
    assert payload["models"]["m1"]["vram_usage"] == 100
    assert payload["system"]["gpu_memory_used"] == 2048
    assert payload["scheduler"] == {"running": True}


def test_ws_accepts_bearer_header(monkeypatch, fast_asyncio):
    """没有 query 令牌时，应从 Authorization: Bearer 头取令牌。"""
    rm = _FakeResourceManager(models={})
    _patch_ws_deps(monkeypatch, rm=rm, token="tok")
    # query_params 为空 dict（falsy）→ 走 else 分支；随后命中 bearer 分支
    ws = _FakeWebSocket(
        query_params={},
        headers={"authorization": "  Bearer tok  "},
        send_limit=0,
        send_exc=WebSocketDisconnect(1000),
    )

    _run_ws(ws)

    assert ws.accepted is True
    assert ws.closed is None


def test_ws_accepts_internal_token_header(monkeypatch, fast_asyncio):
    """既无 query 令牌也无 bearer 时，应回落到 X-Internal-Token 头。"""
    rm = _FakeResourceManager(models={})
    _patch_ws_deps(monkeypatch, rm=rm, token="tok")
    # token 显式为 None → 命中「query_params 存在但 token 为 None」分支
    ws = _FakeWebSocket(
        query_params={"token": None},
        headers={"x-internal-token": "tok"},
        send_limit=0,
        send_exc=WebSocketDisconnect(1000),
    )

    _run_ws(ws)

    assert ws.accepted is True


def test_ws_rejects_non_bearer_authorization(monkeypatch, fast_asyncio):
    """Authorization 头不是 Bearer 前缀时不应被当作令牌使用。"""
    monkeypatch.setattr(integrated_config, "get_settings", lambda: _make_settings(token="tok"))
    ws = _FakeWebSocket(headers={"authorization": "Basic dG9r"})

    _run_ws(ws)

    assert ws.accepted is False
    assert ws.closed == (1008, "未授权的 WebSocket 访问")


# ==================== WebSocket 主循环 ====================


def test_ws_status_payload_fields(monkeypatch, fast_asyncio):
    """校验状态帧的模型字段、显存显示规则与增量日志。"""
    models = {
        "loaded": _FakeModel(
            is_loaded=True,
            is_offloaded=False,
            vram_usage_mb=100,
            memory_usage_mb=200,
            priority=1,
            device="cuda:0",
        ),
        "offloaded": _FakeModel(
            is_loaded=True,
            is_offloaded=True,
            vram_usage_mb=300,
            memory_usage_mb=400,
            priority=2,
            device="cuda:1",
        ),
        "idle": _FakeModel(
            is_loaded=False,
            is_offloaded=False,
            vram_usage_mb=500,
            memory_usage_mb=600,
            priority=3,
            device="cuda:2",
        ),
    }
    rm = _FakeResourceManager(models=models, monitor=_FakeMonitor(gpu_info=(4096, 16384)))
    cleared = []
    fake_logs = [{"text": "L1", "level": "info"}, {"text": "L2", "level": "warning"}]
    metrics = (
        lambda *_a: None,
        lambda: list(fake_logs),
    )
    _patch_ws_deps(monkeypatch, rm=rm, token="tok", scheduler=None, metrics=metrics)
    monkeypatch.setattr(demo_utils, "clear_demo_logs", lambda: cleared.append(True))

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=1,
        send_exc=WebSocketDisconnect(1000),
    )
    _run_ws(ws)

    assert cleared == [True]  # 连接建立时应清空历史日志
    payload = json.loads(ws.sent[0])

    assert payload["models"]["loaded"]["vram_usage"] == 100
    assert payload["models"]["loaded"]["device"] == "cuda:0"
    # offload 到内存时显存显示为 0
    assert payload["models"]["offloaded"]["vram_usage"] == 0
    assert payload["models"]["offloaded"]["is_offloaded"] is True
    # 未加载的模型显存为 0 且设备回落 CPU
    assert payload["models"]["idle"]["vram_usage"] == 0
    assert payload["models"]["idle"]["device"] == "CPU"
    assert payload["models"]["idle"]["priority"] == "3"

    assert payload["system"]["cpu_percent"] == 12.5
    assert payload["system"]["cpu_model"] == "FakeCPU"
    assert payload["system"]["memory_percent"] == 33.3
    assert payload["system"]["gpu_memory_used"] == 4096
    assert payload["system"]["gpu_memory_total"] == 16384
    assert payload["system"]["gpu_model"] == "FakeGPU"
    assert payload["logs"] == fake_logs
    assert isinstance(payload["timestamp"], float)


def test_ws_status_gpu_info_missing_uses_defaults(monkeypatch, fast_asyncio):
    """监控拿不到 GPU 数据时，显存应回落 0 / 8192 默认值。"""
    rm = _FakeResourceManager(models={}, monitor=_FakeMonitor(gpu_info=None))
    _patch_ws_deps(monkeypatch, rm=rm, token="tok")

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=1,
        send_exc=WebSocketDisconnect(1000),
    )
    _run_ws(ws)

    payload = json.loads(ws.sent[0])
    assert payload["system"]["gpu_memory_used"] == 0
    assert payload["system"]["gpu_memory_total"] == 8192


def test_ws_status_resource_lock_failure_yields_none(monkeypatch, fast_asyncio):
    """资源锁不可用时 gpu_gate 应为 None，而不是让整个推送失败。"""
    rm = _FakeResourceManager(models={})

    def _boom():
        raise RuntimeError("lock unavailable")

    _patch_ws_deps(monkeypatch, rm=rm, token="tok", lock=_boom)

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=1,
        send_exc=WebSocketDisconnect(1000),
    )
    _run_ws(ws)

    assert json.loads(ws.sent[0])["system"]["gpu_gate"] is None


def test_ws_status_resource_lock_success_is_forwarded(monkeypatch, fast_asyncio):
    """资源锁可用时，应把其状态原样放进 gpu_gate。"""
    rm = _FakeResourceManager(models={})
    lock_status = {"holder": "chat", "waiting": 0}
    lock = lambda: types.SimpleNamespace(get_status=lambda: lock_status)  # noqa: E731
    _patch_ws_deps(monkeypatch, rm=rm, token="tok", lock=lock)

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=1,
        send_exc=WebSocketDisconnect(1000),
    )
    _run_ws(ws)

    assert json.loads(ws.sent[0])["system"]["gpu_gate"] == lock_status


def test_ws_metrics_update_failure_is_swallowed(monkeypatch, fast_asyncio):
    """资源指标刷新失败应被吞掉，循环继续推送状态帧。"""
    rm = _FakeResourceManager(models={}, metrics_exc=RuntimeError("metrics down"))
    _patch_ws_deps(monkeypatch, rm=rm, token="tok")

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=1,
        send_exc=WebSocketDisconnect(1000),
    )
    _run_ws(ws)

    assert rm.metrics_calls >= 1
    assert len(ws.sent) == 1  # 刷新失败没有中断推送


def test_ws_loop_exits_on_websocket_disconnect(monkeypatch, fast_asyncio):
    """客户端断开（send_text 抛 WebSocketDisconnect）时应静默收尾。"""
    rm = _FakeResourceManager(models={})
    _patch_ws_deps(monkeypatch, rm=rm, token="tok")

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=0,
        send_exc=WebSocketDisconnect(1006),
    )

    _run_ws(ws)  # 不应向外抛异常

    assert ws.accepted is True
    assert ws.sent == []


def test_ws_loop_exits_on_unexpected_error(monkeypatch, fast_asyncio):
    """主循环里出现非断开类异常时，应被兜底捕获而不是泄漏到 ASGI 层。"""
    rm = _FakeResourceManager(
        models={},
        monitor=_FakeMonitor(cpu_usage_exc=ValueError("no cpu data")),
    )
    _patch_ws_deps(monkeypatch, rm=rm, token="tok")

    ws = _FakeWebSocket(
        query_params={"token": "tok"},
        send_limit=0,
        send_exc=WebSocketDisconnect(1000),
    )

    _run_ws(ws)  # 不应向外抛 ValueError

    assert ws.accepted is True
    assert ws.sent == []


def test_ws_streams_over_real_testclient(monkeypatch, fast_asyncio):
    """端到端（真实 ASGI 握手）验证一次状态帧推送。"""
    rm = _FakeResourceManager(
        models={"m1": _FakeModel(is_loaded=True, vram_usage_mb=64, priority=7)},
        monitor=_FakeMonitor(gpu_info=(512, 8192)),
    )
    monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
    monkeypatch.setattr(
        integrated_config, "get_settings", lambda: _make_settings(token="secret")
    )
    monkeypatch.setattr(cpp_scheduler_engine, "get_scheduler_status", lambda: {"ok": True})
    monkeypatch.setattr(
        resource_lock_mod,
        "get_resource_lock",
        lambda: types.SimpleNamespace(get_status=lambda: {"open": True}),
    )

    app = FastAPI()
    app.include_router(demo_mod.router)
    with TestClient(app) as c:
        with c.websocket_connect("/demo/ws/status?token=secret") as ws:
            payload = json.loads(ws.receive_text())

    assert payload["models"]["m1"]["priority"] == "7"
    assert payload["system"]["gpu_memory_total"] == 8192
    assert payload["scheduler"] == {"ok": True}
    assert rm.metrics_calls >= 1
