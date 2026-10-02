"""core/utils/concurrency 的单例工具与全局资源锁单测。

覆盖：
- `singleton.singleton` 装饰器：同实例、__init__ 只跑一次、clear_instance 可重置
- `singleton.SingletonFactory`：get/aget 缓存、reset/shutdown、instance 只读不触发创建
- `resource_lock.GlobalResourceLock`：开关、并发串行化、拒收阈值、超时、状态清理

「禁止 flaky」的做法：
- 需要超时分支时把模块内 `asyncio` 引用换成 `_AsyncioProxy`，由它确定性地抛超时，
  不依赖真实时间流逝，也不去污染全局 asyncio 模块；
- 需要「确认第二个请求在等」时用 `asyncio.Event` + 少量 `sleep(0)` 让步，
  不使用 `sleep(秒数)` 卡时间。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from core.utils.concurrency import resource_lock
from core.utils.concurrency.async_locks import LazyAsyncLock
from core.utils.concurrency.singleton import SingletonFactory, singleton

# ============================================================
# @singleton 装饰器
# ============================================================

_INIT_LOG: list = []


@singleton
class _Service:
    """每次真正执行 __init__ 就往 _INIT_LOG 记一笔，用来验证只初始化一次。"""

    def __init__(self, value=None):
        _INIT_LOG.append(value)
        self.value = value


@singleton
class _OtherService:
    pass


@pytest.fixture(autouse=True)
def _reset_singletons():
    _INIT_LOG.clear()
    _Service.clear_instance()
    _OtherService.clear_instance()
    yield
    _INIT_LOG.clear()
    _Service.clear_instance()
    _OtherService.clear_instance()


class TestSingletonDecorator:
    def test_returns_same_instance(self):
        assert _Service() is _Service()

    def test_init_runs_only_once_and_keeps_first_args(self):
        first = _Service("first")
        second = _Service("second")
        assert first is second
        assert _INIT_LOG == ["first"]
        assert first.value == "first"

    def test_clear_instance_allows_reinitialization(self):
        first = _Service("x")
        _Service.clear_instance()
        second = _Service("y")
        assert second is not first
        assert _INIT_LOG == ["x", "y"]
        assert second.value == "y"

    def test_each_decorated_class_has_its_own_instance(self):
        assert _Service() is not _OtherService()

    def test_keeps_class_name_and_exposes_clear_instance(self):
        assert _Service.__name__ == "_Service"
        assert callable(_Service.clear_instance)

    def test_repeated_clear_instance_is_safe(self):
        _Service.clear_instance()
        _Service.clear_instance()
        assert _Service("after") is _Service()


# ============================================================
# SingletonFactory
# ============================================================


class TestSingletonFactory:
    def test_get_caches_and_calls_factory_once_with_first_args(self):
        calls: list = []

        def factory(*args, **kwargs):
            calls.append((args, kwargs))
            return {"n": len(calls)}

        f = SingletonFactory(factory)
        first = f.get(1, x=2)
        second = f.get()

        assert first is second
        assert calls == [((1,), {"x": 2})]

    def test_instance_property_does_not_trigger_creation(self):
        f = SingletonFactory(lambda: object())
        assert f.instance is None
        created = f.get()
        assert f.instance is created

    def test_reset_clears_and_allows_recreation(self):
        f = SingletonFactory(lambda: object())
        first = f.get()
        f.reset()
        assert f.instance is None
        assert f.get() is not first

    def test_shutdown_calls_instance_shutdown_and_clears(self):
        class Resource:
            def __init__(self):
                self.shutdown_called = False

            def shutdown(self):
                self.shutdown_called = True

        f = SingletonFactory(Resource)
        instance = f.get()
        f.shutdown()

        assert instance.shutdown_called is True
        assert f.instance is None

    def test_shutdown_without_shutdown_method_only_clears(self):
        f = SingletonFactory(lambda: object())
        f.get()
        f.shutdown()
        assert f.instance is None

    def test_shutdown_without_instance_is_noop(self):
        f = SingletonFactory(lambda: object())
        f.shutdown()  # 不应抛
        assert f.instance is None

    @pytest.mark.asyncio
    async def test_aget_caches_and_calls_async_factory_once(self):
        calls: list = []

        async def factory(*args, **kwargs):
            calls.append((args, kwargs))
            return {"n": len(calls)}

        f = SingletonFactory(factory, is_async=True)
        first = await f.aget(1)
        second = await f.aget()

        assert first is second
        assert calls == [((1,), {})]

    @pytest.mark.asyncio
    async def test_aget_returns_existing_instance_created_by_get(self):
        f = SingletonFactory(lambda: "sync-made")
        existing = f.get()
        assert await f.aget() is existing

    @pytest.mark.asyncio
    async def test_concurrent_aget_creates_only_one_instance(self):
        calls: list = []

        async def factory():
            calls.append(1)
            await asyncio.sleep(0)
            return object()

        f = SingletonFactory(factory, is_async=True)
        results = await asyncio.gather(f.aget(), f.aget(), f.aget())

        assert len(calls) == 1
        assert results[0] is results[1] is results[2]


# ============================================================
# GlobalResourceLock
# ============================================================


class _AsyncioProxy:
    """只覆盖 `wait_for`，其余属性透传真实 asyncio。

    只替换被测模块的模块级引用，不动全局 asyncio 模块，避免影响 pytest 自身。
    """

    def __init__(self, real, *, raise_timeout=False):
        self._real = real
        self._raise_timeout = raise_timeout

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def wait_for(self, coro, timeout):
        if self._raise_timeout:
            coro.close()
            raise self._real.TimeoutError()
        return await self._real.wait_for(coro, timeout=timeout)


@pytest.fixture
def lock(monkeypatch):
    """构造状态可控的 GlobalResourceLock 实例；类级单例由 monkeypatch 自动还原。"""
    monkeypatch.setattr(resource_lock.GlobalResourceLock, "_instance", None)
    monkeypatch.setattr(
        resource_lock.GlobalResourceLock, "_load_settings", lambda self: None
    )
    instance = resource_lock.GlobalResourceLock()
    instance._enabled = True
    instance._max_concurrent = 1
    instance._max_waiting = 8
    instance._acquire_timeout_seconds = 600.0
    instance._semaphore = asyncio.Semaphore(1)
    instance._state_lock = LazyAsyncLock()
    instance._active = 0
    instance._waiting = 0
    instance._current_holders = []
    return instance


class TestResourceLockStatus:
    def test_get_status_shape_and_defaults(self, lock):
        status = lock.get_status()
        assert set(status) == {
            "enabled",
            "active",
            "waiting",
            "max_concurrent",
            "max_waiting",
            "holders",
        }
        assert status["enabled"] is True
        assert status["active"] == 0
        assert status["waiting"] == 0
        assert status["holders"] == []

    def test_get_status_holders_is_a_copy(self, lock):
        status = lock.get_status()
        status["holders"].append("mutated")
        assert lock._current_holders == []

    def test_new_returns_the_class_level_singleton(self, lock):
        assert resource_lock.GlobalResourceLock() is lock

    def test_get_resource_lock_returns_module_singleton(self):
        assert resource_lock.get_resource_lock() is resource_lock._global_lock

    def test_load_settings_falls_back_to_defaults_on_error(self, monkeypatch):
        monkeypatch.setattr(resource_lock.GlobalResourceLock, "_instance", None)
        monkeypatch.setattr(
            "config.integrated_config.get_settings",
            MagicMock(side_effect=RuntimeError("配置不可用")),
        )
        instance = resource_lock.GlobalResourceLock()

        assert instance._enabled is True
        assert instance._max_concurrent == 1
        assert instance._max_waiting == 8
        assert instance._acquire_timeout_seconds == 600.0


class TestAcquireDisabled:
    @pytest.mark.asyncio
    async def test_disabled_gate_yields_without_tracking(self, lock):
        lock._enabled = False
        async with lock.acquire("r"):
            assert lock.get_status()["active"] == 0
            assert lock.get_status()["holders"] == []
        assert lock.get_status()["active"] == 0


class TestAcquireEnabled:
    @pytest.mark.asyncio
    async def test_tracks_active_and_holders_then_cleans_up(self, lock):
        async with lock.acquire("req-1"):
            status = lock.get_status()
            assert status["active"] == 1
            assert status["holders"] == ["req-1"]

        status = lock.get_status()
        assert status["active"] == 0
        assert status["holders"] == []

    @pytest.mark.asyncio
    async def test_releases_on_exception_inside_block(self, lock):
        with pytest.raises(ValueError, match="boom"):
            async with lock.acquire("req-1"):
                raise ValueError("boom")

        assert lock.get_status()["active"] == 0
        assert lock.get_status()["holders"] == []

    @pytest.mark.asyncio
    async def test_semaphore_is_recreated_when_missing(self, lock):
        lock._semaphore = None
        async with lock.acquire("r"):
            assert lock._semaphore is not None
            assert lock.get_status()["active"] == 1

    @pytest.mark.asyncio
    async def test_holders_list_is_reinitialized_when_none(self, lock):
        lock._current_holders = None
        async with lock.acquire("r"):
            assert lock._current_holders == ["r"]

    @pytest.mark.asyncio
    async def test_holder_cleanup_is_safe_when_entry_vanished(self, lock):
        ctx = lock.acquire("r")
        await ctx.__aenter__()
        lock._current_holders = []  # 模拟外部把持有人列表清空
        await ctx.__aexit__(None, None, None)
        assert lock.get_status()["active"] == 0

    @pytest.mark.asyncio
    async def test_holder_removal_error_is_swallowed(self, lock):
        class _BadRemoveList(list):
            def remove(self, item):
                raise RuntimeError("remove 失败")

        lock._current_holders = _BadRemoveList(["r"])
        async with lock.acquire("r"):
            pass
        # 清理阶段抛错必须被吞掉，且不影响 active 的递减
        assert lock.get_status()["active"] == 0

    @pytest.mark.asyncio
    async def test_semaphore_release_error_is_swallowed(self, lock):
        class _BadReleaseSemaphore:
            def __init__(self, real):
                self._real = real

            async def acquire(self):
                return await self._real.acquire()

            def release(self):
                raise RuntimeError("release 失败")

        lock._semaphore = _BadReleaseSemaphore(asyncio.Semaphore(1))
        async with lock.acquire("r"):
            pass
        # release 抛错同样必须被吞掉，否则会盖掉业务异常
        assert lock.get_status()["active"] == 0


class TestAcquireSerialization:
    @pytest.mark.asyncio
    async def test_second_request_waits_until_first_releases(self, lock):
        order: list[str] = []
        first_holds = asyncio.Event()
        release_first = asyncio.Event()

        async def first():
            async with lock.acquire("a"):
                order.append("a")
                first_holds.set()
                await release_first.wait()

        async def second():
            async with lock.acquire("b"):
                order.append("b")

        t1 = asyncio.create_task(first())
        await first_holds.wait()

        t2 = asyncio.create_task(second())
        # 给 second 充分机会去抢信号量；信号量仍被 first 持有，它必须还在排队
        for _ in range(10):
            await asyncio.sleep(0)
        assert order == ["a"]
        assert lock.get_status()["waiting"] == 1

        release_first.set()
        await asyncio.gather(t1, t2)

        assert order == ["a", "b"]
        assert lock.get_status()["waiting"] == 0
        assert lock.get_status()["active"] == 0


class TestRejectIfFull:
    @pytest.mark.asyncio
    async def test_raises_when_waiting_reaches_max(self, lock):
        lock._max_waiting = 1
        lock._waiting = 1

        with pytest.raises(RuntimeError, match="队列已满"):
            async with lock.acquire("r", reject_if_full=True):
                pass

        # 被拒的请求不应改动 waiting 计数
        assert lock._waiting == 1

    @pytest.mark.asyncio
    async def test_allows_when_below_max(self, lock):
        lock._max_waiting = 8
        lock._waiting = 0
        async with lock.acquire("r", reject_if_full=True):
            assert lock.get_status()["active"] == 1

    @pytest.mark.asyncio
    async def test_zero_max_waiting_disables_rejection(self, lock):
        lock._max_waiting = 0
        lock._waiting = 100
        async with lock.acquire("r", reject_if_full=True):
            assert lock.get_status()["active"] == 1

    @pytest.mark.asyncio
    async def test_without_reject_flag_queue_limit_is_ignored(self, lock):
        lock._max_waiting = 1
        lock._waiting = 1
        async with lock.acquire("r"):
            assert lock.get_status()["active"] == 1


class TestAcquireTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_runtime_error_and_resets_counters(self, lock, monkeypatch):
        # 用代理让 wait_for 确定性地抛超时，不依赖真实时间流逝
        monkeypatch.setattr(
            resource_lock, "asyncio", _AsyncioProxy(asyncio, raise_timeout=True)
        )

        with pytest.raises(RuntimeError, match="等待 GPU 资源超时"):
            async with lock.acquire("r"):
                pass

        status = lock.get_status()
        assert status["waiting"] == 0
        assert status["active"] == 0

    @pytest.mark.asyncio
    async def test_zero_timeout_takes_plain_acquire_branch(self, lock):
        lock._acquire_timeout_seconds = 0
        async with lock.acquire("r"):
            assert lock.get_status()["active"] == 1
        assert lock.get_status()["active"] == 0
