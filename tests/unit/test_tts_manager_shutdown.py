"""multimodal/tts_manager.py 单元测试（四）：健康检查、优雅关闭与单例。

⚠️ 依赖前提同 `test_tts_manager_core.py`：`soundfile` 属 voice 可选 extra，
CI 未安装 → 用 `importorskip` 整体跳过而不是失败。

⚠️ 不启动真实引擎/后台循环；`TEMP_DIR` 一律重定向到 tmp_path。
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


class _FakeEngine:
    def __init__(self):
        self.settings = object()
        self.shutdown_called = 0

    async def shutdown(self):
        self.shutdown_called += 1


class _FakeLoop:
    """后台循环替身：记录 stop / call_soon_threadsafe。"""

    def __init__(self, running=True):
        self._running = running
        self.soon = []
        self.stopped = 0

    def is_running(self):
        return self._running

    def stop(self):
        self.stopped += 1

    def call_soon_threadsafe(self, fn):  # noqa: ANN001
        self.soon.append(fn)


# --------------------------------------------------------------------------
# 1. health_check / _get_provider_name
# --------------------------------------------------------------------------


def test_health_check_reports_metrics(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._cache_hits, mgr._cache_misses, mgr._synthesis_count = 3, 1, 4

    health = mgr.health_check()

    assert health["cache_hit_rate"] == pytest.approx(0.75)
    assert health["cache_hits"] == 3
    assert health["synthesis_count"] == 4
    assert health["initialized"] is False
    assert health["provider"] == "unknown"


def test_health_check_zero_requests_has_zero_rate(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    assert mgr.health_check()["cache_hit_rate"] == 0.0


def test_health_check_reports_background_loop_state(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._bg_loop = _FakeLoop(running=True)

    assert mgr.health_check()["background_loop_running"] is True


def test_get_provider_name_from_engine_settings(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr.new_engine = _FakeEngine()
    monkeypatch.setattr(
        tm, "get_config", lambda *a, **kw: types.SimpleNamespace(provider="volcano")
    )

    assert mgr._get_provider_name() == "volcano"


def test_get_provider_name_unknown_without_engine(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    assert mgr._get_provider_name() == "unknown"


def test_get_provider_name_swallows_error(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr.new_engine = _FakeEngine()

    def _boom(*a, **kw):
        raise RuntimeError("配置炸了")

    monkeypatch.setattr(tm, "get_config", _boom)

    assert mgr._get_provider_name() == "unknown"


# --------------------------------------------------------------------------
# 2. shutdown
# --------------------------------------------------------------------------


def test_shutdown_waits_inflight_and_cleans_up(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    engine = _FakeEngine()
    mgr.new_engine = engine
    mgr._initialized = True
    path = tmp_path / "tts" / "a.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    mgr._cache_put("k", str(path))
    loop = _FakeLoop()
    mgr._bg_loop = loop

    async def _run():
        # 让 inflight 立刻完成：否则 asyncio.wait(timeout=30) 会真等 30 秒
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        mgr._inflight_async["k"] = fut
        await mgr.shutdown()

    asyncio.run(_run())

    assert mgr._shutting_down is True
    assert mgr._inflight_async == {}
    assert mgr._tts_cache == {}
    assert engine.shutdown_called == 1
    assert mgr._initialized is False
    assert loop.soon, "应请求停掉后台循环"


def test_shutdown_swallows_engine_error(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    class _BadEngine:
        async def shutdown(self):
            raise RuntimeError("关不掉")

    mgr.new_engine = _BadEngine()

    asyncio.run(mgr.shutdown())  # 不应抛异常


def test_shutdown_swallows_loop_stop_error(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    class _BadLoop(_FakeLoop):
        def call_soon_threadsafe(self, fn):  # noqa: ANN001
            raise RuntimeError("循环已死")

    mgr._bg_loop = _BadLoop()

    asyncio.run(mgr.shutdown())  # 不应抛异常


def test_shutdown_joins_background_thread(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    joined = []

    class _FakeThread:
        def is_alive(self):
            return True

        def join(self, timeout=None):  # noqa: ANN001
            joined.append(timeout)

    mgr._bg_thread = _FakeThread()

    asyncio.run(mgr.shutdown())

    assert joined == [5.0], "应带 5 秒超时地 join 后台线程"


def test_shutdown_without_engine_or_loop_is_safe(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    asyncio.run(mgr.shutdown())  # 不应抛异常

    assert mgr._initialized is False


# --------------------------------------------------------------------------
# 3. close（同步兼容层）
# --------------------------------------------------------------------------


def test_close_falls_back_when_no_running_loop(monkeypatch, tmp_path):
    """close() 在拿不到事件循环时走兜底分支：清缓存 + 停后台循环。"""
    mgr = _make(monkeypatch, tmp_path)
    mgr._initialized = True
    loop = _FakeLoop()
    mgr._bg_loop = loop

    def _boom():
        raise RuntimeError("没有事件循环")

    monkeypatch.setattr(tm.asyncio, "get_event_loop", _boom)

    mgr.close()

    assert mgr._initialized is False
    assert loop.soon, "兜底分支应停掉后台循环"


def test_close_swallows_stop_error(monkeypatch, tmp_path):
    """兜底分支里停循环失败也不能抛出去。"""
    mgr = _make(monkeypatch, tmp_path)

    class _BadLoop(_FakeLoop):
        def call_soon_threadsafe(self, fn):  # noqa: ANN001
            raise RuntimeError("停不掉")

    mgr._bg_loop = _BadLoop()

    def _boom():
        raise RuntimeError("没有事件循环")

    monkeypatch.setattr(tm.asyncio, "get_event_loop", _boom)

    mgr.close()  # 不应抛异常


# --------------------------------------------------------------------------
# 4. 单例
# --------------------------------------------------------------------------


def test_get_tts_manager_is_singleton(monkeypatch, tmp_path):
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(tmp_path / "tts"))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)

    assert tm.get_tts_manager() is tm.get_tts_manager()


def test_custom_config_flows_into_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(tmp_path / "tts"))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)
    cfg = TTSCacheConfig(synthesis_timeout_sec=7)

    assert tm.get_tts_manager(cfg).config is cfg


def test_cleanup_tts_sync_closes_and_clears(monkeypatch):
    closed = []

    class _Fake:
        def close(self):
            closed.append(1)

    monkeypatch.setattr(tm, "_tts_manager_instance", _Fake())

    tm.cleanup_tts_sync()

    assert closed == [1]
    assert tm._tts_manager_instance is None


def test_cleanup_tts_async_closes_and_clears(monkeypatch):
    closed = []

    class _Fake:
        async def shutdown(self):
            closed.append(1)

    monkeypatch.setattr(tm, "_tts_manager_instance", _Fake())

    asyncio.run(tm.cleanup_tts())

    assert closed == [1]
    assert tm._tts_manager_instance is None


def test_cleanup_functions_noop_when_absent(monkeypatch):
    monkeypatch.setattr(tm, "_tts_manager_instance", None)

    tm.cleanup_tts_sync()
    asyncio.run(tm.cleanup_tts())

    assert tm._tts_manager_instance is None
