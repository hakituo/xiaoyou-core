"""multimodal/tts_manager.py 单元测试（三）：初始化、后台循环、inflight 等待。

⚠️ 依赖前提同 `test_tts_manager_core.py`：`soundfile` 属 voice 可选 extra，
CI 未安装 → 用 `importorskip` 整体跳过而不是失败。

⚠️ 不启动真实 TTS 引擎、不联网；`TEMP_DIR` 一律重定向到 tmp_path。
"""

from __future__ import annotations

import asyncio
import types

import pytest


from multimodal import tts_manager as tm  # noqa: E402
from multimodal.tts_manager import TTSCacheConfig, TTSCacheManager  # noqa: E402


def _make(monkeypatch, tmp_path, config=None):
    temp_dir = tmp_path / "tts"
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)
    return TTSCacheManager(config)


class _AsyncioProxy:
    """只拦截 `run_coroutine_threadsafe`，其余属性透传真实 asyncio。

    ⚠️ 不能 patch 全局 asyncio —— 那会把 pytest 自己搞坏。
    """

    def __init__(self, real, factory):
        self._real = real
        self._factory = factory

    def __getattr__(self, name):
        return getattr(self._real, name)

    def run_coroutine_threadsafe(self, coro, loop):  # noqa: ANN001
        coro.close()  # 不真的执行，避免「协程从未被 await」告警
        return self._factory()


class _FakeThreadFuture:
    """`concurrent.futures.Future` 替身。"""

    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def result(self, timeout=None):  # noqa: ANN001
        if self.error is not None:
            raise self.error
        return self.value


class _FakeEngine:
    def __init__(self, *, init_ok=True, last_error=None):
        self.settings = object()
        self.init_ok = init_ok
        self.last_error = last_error
        self.shutdown_called = 0

    async def initialize(self):
        if not self.init_ok:
            raise RuntimeError("引擎起不来")

    async def shutdown(self):
        self.shutdown_called += 1


# --------------------------------------------------------------------------
# 1. _initialize
# --------------------------------------------------------------------------


def test_initialize_short_circuits_when_already_done(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._initialized = True

    assert mgr._initialize() is True


def test_initialize_success(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    engine = _FakeEngine()
    monkeypatch.setattr("core.voice.tts_engine.TTSManager", lambda: engine)
    monkeypatch.setattr(TTSCacheManager, "_ensure_background_loop", lambda self: None)
    monkeypatch.setattr(
        tm, "asyncio", _AsyncioProxy(asyncio, lambda: _FakeThreadFuture(value=None))
    )

    assert mgr._initialize() is True
    assert mgr.new_engine is engine
    assert mgr._initialized is True


def test_initialize_wraps_failure(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    monkeypatch.setattr("core.voice.tts_engine.TTSManager", lambda: _FakeEngine(init_ok=False))
    monkeypatch.setattr(TTSCacheManager, "_ensure_background_loop", lambda self: None)
    monkeypatch.setattr(
        tm, "asyncio", _AsyncioProxy(asyncio, lambda: _FakeThreadFuture(error=RuntimeError("x")))
    )

    with pytest.raises(tm.TTSInitializationError, match="引擎初始化失败"):
        mgr._initialize()

    assert mgr._initialized is False


def test_initialize_wraps_import_error(monkeypatch, tmp_path):
    """引擎模块导入失败也要包成 TTSInitializationError。"""
    mgr = _make(monkeypatch, tmp_path)

    class _Boom:
        def __init__(self, *a, **kw):
            raise ImportError("没有 tts_engine")

    monkeypatch.setattr("core.voice.tts_engine.TTSManager", _Boom)

    with pytest.raises(tm.TTSInitializationError):
        mgr._initialize()


# --------------------------------------------------------------------------
# 2. _ensure_background_loop
# --------------------------------------------------------------------------


def test_ensure_background_loop_is_idempotent(monkeypatch, tmp_path):
    """循环已在跑时直接返回，不重复起线程。"""
    mgr = _make(monkeypatch, tmp_path)
    started = []

    class _FakeLoop:
        def is_running(self):
            return True

    mgr._bg_loop = _FakeLoop()
    monkeypatch.setattr(
        tm.threading, "Thread", lambda **kw: types.SimpleNamespace(start=lambda: started.append(1))
    )

    mgr._ensure_background_loop()

    assert started == [], "已有在跑的循环就不该再起线程"


def test_ensure_background_loop_raises_on_ready_timeout(monkeypatch, tmp_path):
    """后台循环 5 秒内没就绪 → TTSInitializationError。

    用「Thread.start 空实现 + Event.wait 返回 False」避免真的起线程。
    """
    mgr = _make(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tm.threading, "Thread", lambda **kw: types.SimpleNamespace(start=lambda: None)
    )
    monkeypatch.setattr(mgr._bg_loop_ready, "wait", lambda timeout=None: False)

    with pytest.raises(tm.TTSInitializationError, match="5秒内未能启动"):
        mgr._ensure_background_loop()


# --------------------------------------------------------------------------
# 双重检查锁的「竞争窗口」分支
# --------------------------------------------------------------------------


def test_ensure_background_loop_inner_double_check(monkeypatch, tmp_path):
    """等锁期间别的线程已把循环起好 → 内层检查直接返回，不再起线程。

    用「锁的 __enter__ 里改状态」精确复现那个竞争窗口，避免真的并发。
    """
    mgr = _make(monkeypatch, tmp_path)
    started = []

    class _RunningLoop:
        def is_running(self):
            return True

    class _Lock:
        def __enter__(self):
            mgr._bg_loop = _RunningLoop()  # 模拟竞争窗口：别人刚起好
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(mgr, "_init_lock", _Lock())
    monkeypatch.setattr(
        tm.threading,
        "Thread",
        lambda **kw: types.SimpleNamespace(start=lambda: started.append(1)),
    )

    mgr._ensure_background_loop()

    assert started == [], "内层双重检查命中时不该再起线程"


def test_initialize_inner_double_check(monkeypatch, tmp_path):
    """等锁期间别的线程已完成初始化 → 内层检查直接返回 True。

    若内层检查失效，会继续去 import 引擎并失败，所以这条用例有牙。
    """
    mgr = _make(monkeypatch, tmp_path)

    class _Lock:
        def __enter__(self):
            mgr._initialized = True  # 模拟竞争窗口：别人刚初始化完
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(mgr, "_init_lock", _Lock())

    assert mgr._initialize() is True


# --------------------------------------------------------------------------
# 3. _wait_for_inflight_async
# --------------------------------------------------------------------------


def test_wait_for_inflight_raises_without_future(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    with pytest.raises(tm.TTSSynthesisError, match="未找到进行中的 Future"):
        asyncio.run(mgr._wait_for_inflight_async("nope"))


def test_wait_for_inflight_returns_existing_file(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    path = tmp_path / "tts" / "a.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")

    async def _run():
        fut = asyncio.get_running_loop().create_future()
        mgr._inflight_async["k"] = fut
        asyncio.get_running_loop().call_soon(fut.set_result, str(path))
        return await mgr._wait_for_inflight_async("k", timeout=1)

    assert asyncio.run(_run()) == str(path)


def test_wait_for_inflight_rejects_invalid_result(monkeypatch, tmp_path):
    """Future 返回的文件不存在 → TTSSynthesisError。"""
    mgr = _make(monkeypatch, tmp_path)

    async def _run():
        fut = asyncio.get_running_loop().create_future()
        mgr._inflight_async["k"] = fut
        asyncio.get_running_loop().call_soon(fut.set_result, str(tmp_path / "gone.wav"))
        return await mgr._wait_for_inflight_async("k", timeout=1)

    with pytest.raises(tm.TTSSynthesisError, match="无效结果"):
        asyncio.run(_run())


def test_wait_for_inflight_timeout_pops_entry(monkeypatch, tmp_path):
    """永不 resolve 的 Future + 小超时 → TTSTimeoutError，且条目被清掉。"""
    mgr = _make(monkeypatch, tmp_path)

    async def _run():
        mgr._inflight_async["k"] = asyncio.get_running_loop().create_future()
        with pytest.raises(tm.TTSTimeoutError, match="合成超时"):
            await mgr._wait_for_inflight_async("k", timeout=0.05)

    asyncio.run(_run())

    assert "k" not in mgr._inflight_async
