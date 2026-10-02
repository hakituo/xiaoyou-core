"""multimodal/tts_manager.py 单元测试（五）：边界与异常分支。

补 `test_tts_manager_{core,cache,lifecycle,shutdown,async,sync}.py` 覆盖不到的路径：
真实后台事件循环的启动/收尾、`close()` 在「有运行中事件循环」时的分支、
缓存/关闭流程里的 `except` 兜底。

⚠️ 依赖前提同其它 tts 测试：`soundfile` 属 voice 可选 extra → 缺依赖时整体跳过。
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


def _audio(tmp_path, name="a.wav", size=16):
    p = tmp_path / "tts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return str(p)


class _AsyncioProxy:
    """只拦截指定方法，其余透传真实 asyncio。"""

    def __init__(self, real, overrides):
        self._real = real
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._real, name)


# --------------------------------------------------------------------------
# 1. 真实后台事件循环
# --------------------------------------------------------------------------


def test_background_loop_starts_real_thread_and_stops(monkeypatch, tmp_path):
    """真的起一次后台事件循环，验证线程体与收尾路径都能走通。

    用 shutdown() 正常收尾，避免线程泄漏。
    """
    mgr = _make(monkeypatch, tmp_path)

    mgr._ensure_background_loop()

    assert mgr._bg_loop is not None and mgr._bg_loop.is_running()
    assert mgr._bg_thread is not None and mgr._bg_thread.is_alive()

    asyncio.run(mgr.shutdown())

    assert mgr._bg_thread is not None
    assert not mgr._bg_thread.is_alive(), "shutdown 后后台线程应已退出"


def test_ensure_background_loop_reuses_running_loop(monkeypatch, tmp_path):
    """第二次调用应复用同一个循环，不重复起线程。"""
    mgr = _make(monkeypatch, tmp_path)

    mgr._ensure_background_loop()
    first_loop, first_thread = mgr._bg_loop, mgr._bg_thread

    mgr._ensure_background_loop()

    assert mgr._bg_loop is first_loop
    assert mgr._bg_thread is first_thread

    asyncio.run(mgr.shutdown())


# --------------------------------------------------------------------------
# 2. close() 在「有运行中事件循环」时的分支
# --------------------------------------------------------------------------


def test_close_schedules_shutdown_when_loop_running(monkeypatch, tmp_path):
    """在协程里调 close() → get_event_loop() 返回运行中的循环 → 走 create_task 分支。"""
    mgr = _make(monkeypatch, tmp_path)
    mgr._initialized = True
    scheduled = []

    def _fake_create_task(coro):  # noqa: ANN001
        scheduled.append(coro)
        coro.close()  # 不真的调度，避免留下未完成任务
        return types.SimpleNamespace()

    monkeypatch.setattr(tm.asyncio, "create_task", _fake_create_task)

    async def _run():
        mgr.close()

    asyncio.run(_run())

    assert scheduled, "有运行中循环时应把 shutdown 交给 create_task"


# --------------------------------------------------------------------------
# 3. 缓存流程里的 except 兜底
# --------------------------------------------------------------------------


def test_clean_cache_swallows_getsize_error(monkeypatch, tmp_path):
    """统计缓存大小时 getsize 抛错只跳过该条目。"""
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(cleanup_interval_sec=0, entry_ttl_sec=9999))
    mgr._cache_put("k", _audio(tmp_path))
    mgr.last_cache_clean = 0

    def _boom(path):
        raise OSError("取不到大小")

    monkeypatch.setattr(tm.os.path, "getsize", _boom)

    mgr._check_and_clean_cache()  # 不应抛异常

    assert "k" in mgr._tts_cache


def test_evict_by_size_swallows_getsize_error(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._cache_put("k", _audio(tmp_path))

    def _boom(path):
        raise OSError("取不到大小")

    monkeypatch.setattr(tm.os.path, "getsize", _boom)

    mgr._evict_by_size(100.0)  # 不应抛异常

    assert mgr._tts_cache == {}, "取不到大小也应把条目驱逐掉"


def test_cache_get_swallows_move_to_end_error(monkeypatch, tmp_path):
    """命中时 move_to_end 失败不影响返回路径。"""
    mgr = _make(monkeypatch, tmp_path)
    path = _audio(tmp_path)
    mgr._cache_put("k", path)

    def _boom(*a, **kw):
        raise RuntimeError("顺序维护失败")

    monkeypatch.setattr(mgr._tts_cache, "move_to_end", _boom)

    assert mgr._cache_get("k") == path


def test_cache_put_swallows_move_to_end_error(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    def _boom(*a, **kw):
        raise RuntimeError("顺序维护失败")

    monkeypatch.setattr(mgr._tts_cache, "move_to_end", _boom)

    mgr._cache_put("k", _audio(tmp_path))  # 不应抛异常

    assert "k" in mgr._tts_cache


def test_cache_put_swallows_evict_remove_error(monkeypatch, tmp_path):
    """驱逐时删文件失败只记 warning。"""
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(max_entries=1))
    mgr._cache_put("k0", _audio(tmp_path, "a.wav"))

    def _boom(path):
        raise OSError("删不掉")

    monkeypatch.setattr(tm.os, "remove", _boom)

    mgr._cache_put("k1", _audio(tmp_path, "b.wav"))  # 不应抛异常

    assert "k0" not in mgr._tts_cache


# --------------------------------------------------------------------------
# 4. shutdown 里的 except 兜底
# --------------------------------------------------------------------------


def test_shutdown_swallows_wait_error(monkeypatch, tmp_path):
    """asyncio.wait 抛错只记 warning，关闭流程继续。"""
    mgr = _make(monkeypatch, tmp_path)
    mgr.new_engine = None

    async def _boom(*a, **kw):
        raise RuntimeError("wait 炸了")

    monkeypatch.setattr(tm, "asyncio", _AsyncioProxy(asyncio, {"wait": _boom}))

    async def _run():
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        mgr._inflight_async["k"] = fut
        await mgr.shutdown()

    asyncio.run(_run())

    assert mgr._inflight_async == {}, "即使 wait 失败也要清掉 inflight"


def test_shutdown_swallows_thread_join_error(monkeypatch, tmp_path):
    """join 抛错只记 warning。"""
    mgr = _make(monkeypatch, tmp_path)

    class _BadThread:
        def is_alive(self):
            return True

        def join(self, timeout=None):  # noqa: ANN001
            raise RuntimeError("join 炸了")

    mgr._bg_thread = _BadThread()

    asyncio.run(mgr.shutdown())  # 不应抛异常

    assert mgr._initialized is False


# --------------------------------------------------------------------------
# 5. close() 的「空闲事件循环」分支
# --------------------------------------------------------------------------


def test_close_runs_shutdown_on_idle_loop(monkeypatch, tmp_path):
    """get_event_loop() 返回一个**未运行**的循环 → 走 run_until_complete 分支。"""
    mgr = _make(monkeypatch, tmp_path)
    mgr._initialized = True
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(tm.asyncio, "get_event_loop", lambda: loop)

    try:
        mgr.close()
    finally:
        loop.close()

    assert mgr._initialized is False


# --------------------------------------------------------------------------
# 6. 后台循环收尾时取消未完成任务
# --------------------------------------------------------------------------


async def _forever():
    await asyncio.sleep(3600)


def test_background_loop_cancels_pending_tasks_on_stop(monkeypatch, tmp_path):
    """停循环时若还有未完成任务，finally 里应把它们取消并收尾。"""
    mgr = _make(monkeypatch, tmp_path)
    mgr._ensure_background_loop()

    pending = asyncio.run_coroutine_threadsafe(_forever(), mgr._bg_loop)
    # 等它真的进到 sleep，确保它出现在 asyncio.all_tasks() 里
    for _ in range(50):
        if mgr._bg_loop.is_running():
            break

    asyncio.run(mgr.shutdown())

    assert mgr._bg_thread is not None
    assert not mgr._bg_thread.is_alive(), "后台线程应已退出"
    assert pending.done() or pending.cancelled(), "未完成任务应被取消或已结束"
