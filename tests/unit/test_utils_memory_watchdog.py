"""core/utils/memory_watchdog.py 单元测试。

覆盖范围：
- 三个 dataclass 的默认值
- ``MemoryWatchdog`` 单例与 ``__init__`` 幂等、log_dir 两种来源
- ``start`` / ``stop``（含无事件循环、任务取消、报告保存失败）
- ``_async_monitor_loop`` 的正常退出 / 异常续跑 / 取消退出三条路径
- ``_take_snapshot_fast`` 成功与 psutil 失败兜底
- ``_check_memory_fast`` 的采样裁剪、增长判定、定期趋势日志、广播
- 按需深度分析：``take_detailed_snapshot`` / ``_analyze_objects`` / ``_get_loaded_models``
  / ``analyze_top_objects`` / ``sample_large_lists`` / ``analyze_leak_source``
- tracemalloc 的 ``get_tracemalloc_diff`` / ``get_tracemalloc_top``
- 状态与报告：``get_status`` / ``get_trend`` / ``report`` / ``_save_report``
- WebSocket 订阅与广播
- 模块级便捷函数：``get_memory_watchdog`` / ``stop_memory_watchdog`` / ``get_memory_status``

不依赖真实内存压力：快照与 psutil 结果按需替换，时间相关分支用桩 sleep。
"""

from __future__ import annotations

import asyncio
import gc
import json
import sys
import tracemalloc

import pytest

from core.utils import memory_watchdog as mw


# ============================================================
# 桩
# ============================================================

class _AsyncioProxy:
    """替换模块内 asyncio 引用：sleep 立即返回并记录时长，其余透传真实 asyncio。"""

    def __init__(self, raise_cancelled=False):
        self.sleeps = []
        self._raise_cancelled = raise_cancelled

    async def sleep(self, seconds, *args, **kwargs):
        self.sleeps.append(seconds)
        if self._raise_cancelled:
            raise asyncio.CancelledError()
        await asyncio.sleep(0)

    def __getattr__(self, name):
        return getattr(asyncio, name)


class _GcProxy:
    """替换模块内 gc 引用：可指定 get_objects / get_referrers 的返回值，其余透传真实 gc。

    **为什么必须收敛对象集合**：``analyze_leak_source`` / ``sample_large_lists`` 会对每个
    对象调 ``gc.get_referrers``（近似 O(n²)）。真实 pytest 进程堆里有几万到几十万对象，
    实测单次 ``analyze_leak_source`` 就要 1.5 秒且随堆增大而恶化，整包跑会把 CI 拖慢数分钟；
    同时结果会随进程状态漂移，断言不可靠。用受控的小集合既快又确定。
    """

    def __init__(self, objects=None, referrers=None, referrers_map=None,
                 get_objects_raises=False):
        self._objects = objects
        self._referrers = referrers
        self._referrers_map = referrers_map
        self._get_objects_raises = get_objects_raises

    def get_objects(self):
        if self._get_objects_raises:
            raise RuntimeError("gc 不可用")
        if self._objects is None:
            return gc.get_objects()
        return list(self._objects)

    def get_referrers(self, obj):
        if self._referrers_map is not None:
            return list(self._referrers_map.get(id(obj), []))
        if self._referrers is None:
            return gc.get_referrers(obj)
        return list(self._referrers)

    def __getattr__(self, name):
        return getattr(gc, name)


class _FakeTask:
    def __init__(self, done=False):
        self._done = done
        self.cancelled = False

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True


class _SysProxy:
    """替换模块内 sys 引用：``getsizeof`` 恒抛错，其余透传真实 sys。

    用于覆盖「大小统计失败但数量统计保留」的分支。用代理而不是 patch 真实
    ``sys.getsizeof``，避免影响同进程内其它代码。
    """

    def __init__(self):
        self.attempts = 0

    def getsizeof(self, *args, **kwargs):
        self.attempts += 1
        raise TypeError("不支持大小统计")

    def __getattr__(self, name):
        return getattr(sys, name)


def _capture_logger(monkeypatch, module):
    """替换模块 logger，返回收集到的 (level, text) 列表。"""
    records = []

    class _Logger:
        def __getattr__(self, name):
            def _record(*args, **kwargs):
                records.append((name, " ".join(str(a) for a in args)))

            return _record

    monkeypatch.setattr(module, "logger", _Logger())
    return records


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch):
    """重置类单例与模块级单例，避免用例互相污染。"""
    monkeypatch.setattr(mw.MemoryWatchdog, "_instance", None)
    monkeypatch.setattr(mw, "_watchdog", None)


@pytest.fixture
def watchdog(tmp_path):
    return mw.MemoryWatchdog(log_dir=str(tmp_path / "watchdog"))


# ============================================================
# 数据结构
# ============================================================

class TestDataclasses:
    def test_memory_snapshot_defaults(self):
        snap = mw.MemorySnapshot()

        assert (snap.timestamp, snap.process_rss_mb, snap.gc_objects) == (0.0, 0.0, 0)

    def test_detailed_snapshot_defaults_are_independent(self):
        first = mw.DetailedMemorySnapshot()
        second = mw.DetailedMemorySnapshot()
        first.loaded_models.append("m")
        first.object_counts["list"] = 1

        assert second.loaded_models == []
        assert second.object_counts == {}
        assert second.object_sizes == {}

    def test_growth_record_holds_details(self):
        record = mw.MemoryGrowthRecord(timestamp=1.0, delta_mb=2.0, delta_percent=3.0, source="s")

        assert record.details == {}
        assert record.source == "s"


# ============================================================
# 单例
# ============================================================

class TestSingleton:
    def test_repeated_construction_keeps_first_config(self, tmp_path):
        first = mw.MemoryWatchdog(check_interval=11.0, log_dir=str(tmp_path / "a"))
        second = mw.MemoryWatchdog(check_interval=99.0, log_dir=str(tmp_path / "b"))

        assert first is second
        # __init__ 幂等：第二次传入的参数不再生效
        assert second._check_interval == 11.0
        assert second._log_dir == tmp_path / "a"

    def test_get_memory_watchdog_returns_singleton(self, tmp_path):
        first = mw.get_memory_watchdog(log_dir=str(tmp_path / "wd"))
        second = mw.get_memory_watchdog(check_interval=123.0)

        assert first is second
        assert second._check_interval == 60.0

    def test_stop_memory_watchdog_stops_and_clears(self, monkeypatch):
        stopped = []
        monkeypatch.setattr(mw, "_watchdog", type("_W", (), {"stop": lambda self: stopped.append(1)})())

        mw.stop_memory_watchdog()

        assert stopped == [1]
        assert mw._watchdog is None

    def test_stop_memory_watchdog_without_instance(self):
        mw.stop_memory_watchdog()  # 不应抛异常

        assert mw._watchdog is None


# ============================================================
# 初始化
# ============================================================

class TestInit:
    def test_default_log_dir_is_under_project_logs(self):
        dog = mw.MemoryWatchdog()

        assert dog._log_dir.name == "memory_watchdog"
        assert dog._log_dir.parent.name == "logs"
        assert dog._log_dir.is_dir()

    def test_custom_log_dir_is_created(self, tmp_path):
        target = tmp_path / "nested" / "dir"

        dog = mw.MemoryWatchdog(log_dir=str(target))

        assert dog._log_dir == target
        assert target.is_dir()

    def test_defaults(self, watchdog):
        assert watchdog._growth_threshold_mb == 300.0
        assert watchdog._growth_threshold_percent == 10.0
        assert watchdog._max_snapshots == 500
        assert watchdog._is_running is False
        assert watchdog._snapshots == []
        assert watchdog._growth_records == []
        assert watchdog._baseline_snapshot is None
        assert watchdog._ws_subscribers == []
        assert watchdog._tm_enabled is False


# ============================================================
# start / stop
# ============================================================

class TestStartStop:
    def test_start_without_running_loop_degrades(self, watchdog):
        """同步调用（无事件循环）时应降级：不启动任务、is_running 回到 False。"""
        watchdog.start()

        assert watchdog._is_running is False
        assert watchdog._task is None
        # 基线快照仍然拍了
        assert len(watchdog._snapshots) == 1

    async def test_start_creates_task_and_records_baseline(self, watchdog):
        watchdog._check_interval = 0

        watchdog.start()
        await asyncio.sleep(0)

        assert watchdog._is_running is True
        assert watchdog._task is not None
        assert watchdog._baseline_snapshot is not None
        assert watchdog._last_snapshot is watchdog._baseline_snapshot
        assert watchdog._tm_enabled is False
        assert watchdog._tm_baseline is None

        watchdog._is_running = False
        await asyncio.wait([watchdog._task])

    async def test_start_twice_is_noop(self, watchdog):
        watchdog._check_interval = 0
        watchdog.start()
        task = watchdog._task

        watchdog.start()

        assert watchdog._task is task

        watchdog._is_running = False
        await asyncio.wait([task])

    def test_stop_cancels_pending_task(self, watchdog):
        task = _FakeTask(done=False)
        watchdog._task = task
        watchdog._is_running = True

        watchdog.stop()

        assert task.cancelled is True
        assert watchdog._is_running is False

    def test_stop_skips_finished_task(self, watchdog):
        task = _FakeTask(done=True)
        watchdog._task = task
        watchdog._is_running = True

        watchdog.stop()

        assert task.cancelled is False
        assert watchdog._is_running is False

    def test_stop_swallows_report_failure(self, watchdog, monkeypatch):
        def _boom():
            raise RuntimeError("磁盘满了")

        monkeypatch.setattr(watchdog, "_save_report", _boom)

        watchdog.stop()  # 不应抛异常

        assert watchdog._is_running is False


# ============================================================
# 监控循环
# ============================================================

class TestMonitorLoop:
    async def test_loop_exits_when_flag_cleared(self, watchdog, monkeypatch):
        proxy = _AsyncioProxy()
        monkeypatch.setattr(mw, "asyncio", proxy)
        watchdog._is_running = True

        def _stop():
            watchdog._is_running = False

        monkeypatch.setattr(watchdog, "_check_memory_fast", _stop)

        await watchdog._async_monitor_loop()

        assert proxy.sleeps == [watchdog._check_interval]

    async def test_loop_swallows_check_exception_and_backs_off(self, watchdog, monkeypatch):
        """检查抛异常时落 debug 日志并退避 5 秒，然后继续下一轮。"""
        proxy = _AsyncioProxy()
        monkeypatch.setattr(mw, "asyncio", proxy)
        records = _capture_logger(monkeypatch, mw)
        watchdog._check_interval = 0
        watchdog._is_running = True
        state = {"n": 0}

        def _flaky():
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("检查失败")
            watchdog._is_running = False

        monkeypatch.setattr(watchdog, "_check_memory_fast", _flaky)

        await watchdog._async_monitor_loop()

        assert proxy.sleeps == [0, 5, 0]
        assert any("MemoryWatchdog 检查异常" in text for _, text in records)

    async def test_loop_breaks_on_cancellation(self, watchdog, monkeypatch):
        """取消时 break 退出，不把 CancelledError 抛给调用方。"""
        monkeypatch.setattr(mw, "asyncio", _AsyncioProxy(raise_cancelled=True))
        watchdog._is_running = True

        await watchdog._async_monitor_loop()  # 不应抛异常

        assert watchdog._is_running is True


# ============================================================
# 快照与快速检查
# ============================================================

class TestSnapshot:
    def test_take_snapshot_fast_reads_psutil(self, watchdog):
        snap = watchdog._take_snapshot_fast()

        assert snap.timestamp > 0
        assert snap.system_total_mb > 0
        assert snap.process_rss_mb > 0

    def test_take_snapshot_fast_degrades_on_psutil_error(self, watchdog, monkeypatch):
        class _BadProcess:
            def memory_info(self):
                raise OSError("进程已退出")

        monkeypatch.setattr(watchdog, "_process", _BadProcess())

        snap = watchdog._take_snapshot_fast()

        assert snap.process_rss_mb == 0.0
        assert snap.timestamp > 0


class TestCheckMemoryFast:
    def _stub_snapshot(self, watchdog, monkeypatch, rss):
        monkeypatch.setattr(
            watchdog, "_take_snapshot_fast",
            lambda: mw.MemorySnapshot(timestamp=1.0, process_rss_mb=rss, system_percent=50.0),
        )

    def test_first_check_records_no_growth(self, watchdog, monkeypatch):
        self._stub_snapshot(watchdog, monkeypatch, 100.0)

        watchdog._check_memory_fast()

        assert watchdog._growth_records == []
        assert watchdog._last_snapshot.process_rss_mb == 100.0

    def test_growth_above_threshold_is_recorded(self, watchdog, monkeypatch):
        watchdog._last_snapshot = mw.MemorySnapshot(process_rss_mb=100.0)
        self._stub_snapshot(watchdog, monkeypatch, 500.0)

        watchdog._check_memory_fast()

        assert len(watchdog._growth_records) == 1
        record = watchdog._growth_records[0]
        assert record.delta_mb == 400.0
        assert record.delta_percent == 400.0
        assert record.source == "fast_check"

    def test_growth_with_zero_baseline_reports_zero_percent(self, watchdog, monkeypatch):
        """基线 RSS 为 0 时不能除零，百分比直接记 0。"""
        watchdog._last_snapshot = mw.MemorySnapshot(process_rss_mb=0.0)
        self._stub_snapshot(watchdog, monkeypatch, 500.0)

        watchdog._check_memory_fast()

        assert watchdog._growth_records[0].delta_percent == 0

    def test_growth_below_threshold_is_ignored(self, watchdog, monkeypatch):
        watchdog._last_snapshot = mw.MemorySnapshot(process_rss_mb=100.0)
        self._stub_snapshot(watchdog, monkeypatch, 120.0)

        watchdog._check_memory_fast()

        assert watchdog._growth_records == []

    def test_snapshots_are_trimmed_to_max(self, watchdog, monkeypatch):
        watchdog._max_snapshots = 3
        self._stub_snapshot(watchdog, monkeypatch, 100.0)

        for _ in range(5):
            watchdog._check_memory_fast()

        assert len(watchdog._snapshots) == 3

    def test_periodic_trend_log_emitted_every_ten_samples(self, watchdog, monkeypatch):
        records = _capture_logger(monkeypatch, mw)
        self._stub_snapshot(watchdog, monkeypatch, 100.0)

        for _ in range(10):
            watchdog._check_memory_fast()

        assert any("📊 内存" in text for _, text in records)

    def test_broadcast_receives_snapshot(self, watchdog, monkeypatch):
        self._stub_snapshot(watchdog, monkeypatch, 100.0)
        seen = []
        monkeypatch.setattr(watchdog, "_broadcast_snapshot", lambda snap: seen.append(snap))

        watchdog._check_memory_fast()

        assert seen[0].process_rss_mb == 100.0


# ============================================================
# 按需深度分析
# ============================================================

class TestDetailedSnapshot:
    def test_take_detailed_snapshot_collects_object_stats(self, watchdog, monkeypatch):
        monkeypatch.setattr(watchdog, "_analyze_objects", lambda: ({"list": 2}, {"list": 128}))
        monkeypatch.setattr(watchdog, "_get_loaded_models", lambda: ["m1"])
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[1, 2, 3]))

        snap = watchdog.take_detailed_snapshot()

        assert snap.gc_objects == 3
        assert snap.object_counts == {"list": 2}
        assert snap.object_sizes == {"list": 128}
        assert snap.loaded_models == ["m1"]
        assert snap.process_rss_mb > 0


class TestAnalyzeObjects:
    def test_counts_tracked_types(self, watchdog, monkeypatch):
        payload = [1, 2, 3]
        mapping = {"a": 1}
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[payload, mapping, "skip-me"]))

        counts, sizes = watchdog._analyze_objects()

        # str 也在 tracked_types 里，所以三种类型各计 1
        assert counts == {"list": 1, "dict": 1, "str": 1}
        assert sizes["list"] > 0
        assert sizes["dict"] > 0

    def test_size_failure_keeps_counts(self, watchdog, monkeypatch):
        """``getsizeof`` 抛错时只丢大小统计，数量统计仍保留。

        注意 ``sizes[t] += getsizeof(o)`` 的求值顺序：先取下标（defaultdict 会
        先把键插进去并给 0），再算 getsizeof 并抛错。所以失败后键还在、值恒为 0，
        不能断言 ``sizes == {}``。
        """
        proxy = _SysProxy()
        monkeypatch.setattr(mw, "sys", proxy)
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[[1, 2, 3]]))

        counts, sizes = watchdog._analyze_objects()

        assert counts == {"list": 1}
        assert sizes == {"list": 0}
        assert proxy.attempts > 0

    def test_get_objects_failure_returns_empty(self, watchdog, monkeypatch):
        monkeypatch.setattr(mw, "gc", _GcProxy(get_objects_raises=True))

        counts, sizes = watchdog._analyze_objects()

        assert counts == {}
        assert sizes == {}


class TestLoadedModels:
    def test_returns_only_loaded_models(self, watchdog, monkeypatch):
        class _Model:
            def __init__(self, loaded):
                self.is_loaded = loaded

        class _Rm:
            models = {"a": _Model(True), "b": _Model(False), "c": object()}

        monkeypatch.setattr(
            "core.resource_manager.get_resource_manager", lambda: _Rm()
        )

        assert watchdog._get_loaded_models() == ["a"]

    def test_returns_empty_when_manager_missing(self, watchdog, monkeypatch):
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: None)

        assert watchdog._get_loaded_models() == []

    def test_returns_empty_when_manager_has_no_models(self, watchdog, monkeypatch):
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: object())

        assert watchdog._get_loaded_models() == []

    def test_returns_empty_when_lookup_raises(self, watchdog, monkeypatch):
        def _boom():
            raise RuntimeError("资源管理器未就绪")

        monkeypatch.setattr("core.resource_manager.get_resource_manager", _boom)

        assert watchdog._get_loaded_models() == []


class TestAnalyzeTopObjects:
    def test_returns_sorted_top_n(self, watchdog, monkeypatch):
        payload = [1, 2, 3]
        mapping = {i: i for i in range(10)}
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[payload, mapping]))

        result = watchdog.analyze_top_objects(top_n=5)

        assert [name for name, _, _ in result] == ["dict", "list"]
        sizes = [size for _, _, size in result]
        assert sizes == sorted(sizes, reverse=True)
        assert all(count == 1 for _, count, _ in result)

    def test_top_n_truncates(self, watchdog, monkeypatch):
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[[1], {"a": 1}, (1,), {1}]))

        result = watchdog.analyze_top_objects(top_n=2)

        assert len(result) == 2

    def test_size_failure_does_not_break_analysis(self, watchdog, monkeypatch):
        monkeypatch.setattr(mw, "sys", _SysProxy())
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[[1, 2, 3], {"a": 1}]))

        result = watchdog.analyze_top_objects(top_n=5)

        # 大小统计全部失败 → 所有条目的 size 都是 0，但不抛异常
        assert result
        assert all(size == 0 for _, _, size in result)


class TestTracemalloc:
    def test_diff_without_tracing_returns_error(self, watchdog):
        watchdog._tm_enabled = False

        assert watchdog.get_tracemalloc_diff() == [{"error": "tracemalloc 未开启"}]

    def test_diff_without_baseline_returns_error(self, watchdog):
        already = tracemalloc.is_tracing()
        if not already:
            tracemalloc.start()
        try:
            watchdog._tm_enabled = True
            watchdog._tm_baseline = None

            assert watchdog.get_tracemalloc_diff() == [{"error": "无基线快照"}]
        finally:
            if not already:
                tracemalloc.stop()

    def test_diff_returns_allocation_rows(self, watchdog):
        already = tracemalloc.is_tracing()
        if not already:
            tracemalloc.start()
        try:
            watchdog._tm_enabled = True
            watchdog._tm_baseline = tracemalloc.take_snapshot()
            junk = [bytearray(1000) for _ in range(50)]

            result = watchdog.get_tracemalloc_diff(top_n=5)

            assert isinstance(result, list)
            assert result
            assert set(result[0]) == {
                "file", "line", "size_diff_mb", "size_mb", "count_diff", "count",
            }
            assert junk is not None
        finally:
            if not already:
                tracemalloc.stop()

    def test_top_without_tracing_returns_error(self, watchdog):
        watchdog._tm_enabled = False

        assert watchdog.get_tracemalloc_top() == [{"error": "tracemalloc 未开启"}]

    def test_top_returns_allocation_rows(self, watchdog):
        already = tracemalloc.is_tracing()
        if not already:
            tracemalloc.start()
        try:
            watchdog._tm_enabled = True
            junk = [bytearray(1000) for _ in range(50)]

            result = watchdog.get_tracemalloc_top(top_n=5)

            assert isinstance(result, list)
            assert result
            assert set(result[0]) == {"file", "line", "size_mb", "count"}
            assert junk is not None
        finally:
            if not already:
                tracemalloc.stop()


class TestSampleLargeLists:
    """``sample_large_lists`` 只遍历 ``gc.get_objects()``，这里统一喂受控对象集合。

    该函数会对每个达标 list 调 ``gc.get_referrers``（近似 O(n²)）：真实 pytest 进程堆里
    有数万对象，实测单次调用就要秒级，整包跑会把 CI 从 86 秒拖到 4 分钟以上，且结果随
    进程状态漂移。受控集合同时解决「耗时」与「断言确定性」两个问题。
    """

    #: ``est_bytes = len * 8 + 56``，达标门槛 10000 字节 → 长度需 >= 1243
    def test_finds_large_list_and_sorts_desc(self, watchdog, monkeypatch):
        big = list(range(2000))      # 16056 字节
        mid = list(range(1300))      # 10456 字节
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[big, mid], referrers=[]))

        samples = watchdog.sample_large_lists(sample_size=50)

        assert [sample["len"] for sample in samples] == [2000, 1300]
        est = [sample["est_kb"] for sample in samples]
        assert est == sorted(est, reverse=True)

    def test_skips_lists_below_size_floor(self, watchdog, monkeypatch):
        """长度不足 100、或估算字节数不足 10KB 的 list 一律跳过。"""
        too_short = list(range(50))     # len < 100
        too_small = list(range(137))    # 100 <= len，但 137*8+56 < 10000
        keeper = list(range(1300))
        monkeypatch.setattr(
            mw, "gc", _GcProxy(objects=[too_short, too_small, keeper], referrers=[])
        )

        samples = watchdog.sample_large_lists(sample_size=100)

        assert [sample["len"] for sample in samples] == [1300]
        assert too_short and too_small

    def test_skips_non_list_objects(self, watchdog, monkeypatch):
        """``gc.get_objects()`` 里绝大多数不是 list，非 list 必须直接跳过。"""
        big = list(range(2000))
        monkeypatch.setattr(
            mw, "gc", _GcProxy(objects=["text", 42, {"a": 1}, big], referrers=[])
        )

        samples = watchdog.sample_large_lists(sample_size=50)

        assert [sample["len"] for sample in samples] == [2000]
        assert big

    def test_repr_failure_is_rendered_placeholder(self, watchdog, monkeypatch):
        class _Evil:
            def __repr__(self):
                raise RuntimeError("repr 挂了")

        payload = [_Evil()] * 2000
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[payload], referrers=[]))

        samples = watchdog.sample_large_lists(sample_size=50)

        assert [sample["repr"] for sample in samples] == ["<repr failed>"]
        assert payload

    def test_referrer_module_is_reported_with_file(self, watchdog, monkeypatch):
        """引用者是模块时带上 __file__。真实 list 的引用者通常是 dict，
        所以这里用 gc 代理喂一个模块引用者，专测该分支。"""
        payload = list(range(2000))
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[payload], referrers=[mw]))

        samples = watchdog.sample_large_lists(sample_size=50)

        assert samples[0]["referrer"] == f"module:{mw.__file__}"
        assert payload

    def test_referrer_class_is_reported_with_qualname(self, watchdog, monkeypatch):
        """引用者没有 __file__ 但有 __qualname__ 时（类/函数）退回 qualname。"""
        payload = list(range(2000))
        monkeypatch.setattr(
            mw, "gc", _GcProxy(objects=[payload], referrers=[mw.MemoryWatchdog])
        )

        samples = watchdog.sample_large_lists(sample_size=50)

        assert samples[0]["referrer"] == "type:MemoryWatchdog"
        assert payload

    def test_referrer_without_file_or_qualname_keeps_type_only(self, watchdog, monkeypatch):
        """引用者既无 __file__ 也无 __qualname__ 时只留类型名。"""
        payload = list(range(2000))
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[payload], referrers=[object()]))

        samples = watchdog.sample_large_lists(sample_size=50)

        assert samples[0]["referrer"] == "object"
        assert payload

    def test_no_referrer_leaves_ref_info_empty(self, watchdog, monkeypatch):
        """拿不到引用者时 referrer 为空串（``if referrers:`` 的假分支）。"""
        payload = list(range(2000))
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[payload], referrers=[]))

        samples = watchdog.sample_large_lists(sample_size=50)

        assert samples[0]["referrer"] == ""
        assert payload

    def test_sample_size_caps_results(self, watchdog, monkeypatch):
        payloads = [list(range(1300 + i)) for i in range(5)]
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=payloads, referrers=[]))

        samples = watchdog.sample_large_lists(sample_size=1)

        assert len(samples) == 1
        assert payloads


class TestAnalyzeLeakSource:
    """``analyze_leak_source`` 同样是全堆遍历 + 逐大对象 ``get_referrers``。

    与 ``TestSampleLargeLists`` 同理，统一用受控对象集合，既把耗时压到毫秒级，
    也让每条断言都是精确值而不是 ``>= 1`` 这种模糊下界。
    """

    @staticmethod
    def _fixture_objects():
        """返回 (大 list, 大 dict, 引用者 dict)。"""
        big_list = list(range(600))                 # > 500 → 计入大 list
        big_dict = {i: i for i in range(1100)}      # > 1000 → 计入大 dict
        holder = {"holds": big_list}                # big_list 的第一个引用者
        return big_list, big_dict, holder

    def test_reports_structure_and_large_containers(self, watchdog, monkeypatch):
        big_list, big_dict, holder = self._fixture_objects()
        monkeypatch.setattr(mw, "gc", _GcProxy(
            objects=[big_list, big_dict, holder, "text", 42],
            referrers_map={id(big_list): [holder], id(big_dict): [holder]},
        ))

        result = watchdog.analyze_leak_source()

        assert result["total_objects"] == 5
        assert result["object_counts"] == {"dict": 2, "list": 1, "str": 1, "int": 1}
        assert result["total_list_count"] == 1
        assert result["total_dict_count"] == 2
        assert result["large_lists_count"] == 1
        assert result["large_lists_top5"][0]["size"] == 600
        assert result["large_lists_top5"][0]["referrers"][0]["type"] == "dict"
        assert result["large_dicts_count"] == 1
        assert result["large_dicts_top5"][0]["size"] == 1100
        assert result["object_sizes_mb"]
        assert big_list and big_dict

    def test_list_holders_respect_top_n(self, watchdog, monkeypatch):
        """持有者按累计元素数降序，``top_n`` 截断生效。"""
        big_list, _, holder = self._fixture_objects()
        another = list(range(700))
        monkeypatch.setattr(mw, "gc", _GcProxy(
            objects=[big_list, another],
            referrers_map={id(big_list): [holder], id(another): [mw]},
        ))

        result = watchdog.analyze_leak_source(top_n=1)

        # module 持有 700 个元素 > dict 持有 600 个 → 只保留前者
        assert result["list_holders"] == [{"type": "module", "total_elements": 700}]
        assert big_list and another

    def test_size_failure_does_not_break_analysis(self, watchdog, monkeypatch):
        """``getsizeof`` 抛错时跳过大小统计，结构与数量统计仍完整。"""
        big_list, _, _ = self._fixture_objects()
        monkeypatch.setattr(mw, "gc", _GcProxy(objects=[big_list], referrers=[]))
        monkeypatch.setattr(mw, "sys", _SysProxy())

        result = watchdog.analyze_leak_source()

        assert result["total_objects"] == 1
        assert result["large_lists_count"] == 1
        # defaultdict 在取值时先插入键、再求值右操作数，故键保留、值停在 0
        assert result["object_sizes_mb"] == {"list": 0.0}
        assert big_list


# ============================================================
# 状态与报告
# ============================================================

class TestStatusAndReport:
    def test_get_status_reports_growth(self, watchdog):
        watchdog._baseline_snapshot = mw.MemorySnapshot(process_rss_mb=10.0)
        watchdog._growth_records.append(
            mw.MemoryGrowthRecord(timestamp=1.0, delta_mb=1.0, delta_percent=1.0, source="s")
        )

        status = watchdog.get_status()

        assert status["growth_incidents"] == 1
        assert status["watchdog_running"] is False
        assert status["snapshot_count"] == 0
        assert status["growth_mb"] == round(status["process_rss_mb"] - 10.0, 2)

    def test_get_status_without_baseline_uses_zero(self, watchdog):
        status = watchdog.get_status()

        assert status["baseline_rss_mb"] == 0.0

    def test_get_trend_without_data(self, watchdog):
        assert watchdog.get_trend() == {"error": "无数据"}

    def test_get_trend_computes_min_max_avg(self, watchdog):
        watchdog._snapshots = [
            mw.MemorySnapshot(process_rss_mb=10.0),
            mw.MemorySnapshot(process_rss_mb=30.0),
            mw.MemorySnapshot(process_rss_mb=20.0),
        ]

        trend = watchdog.get_trend()

        assert trend["current_mb"] == 20.0
        assert trend["min_mb"] == 10.0
        assert trend["max_mb"] == 30.0
        assert trend["avg_mb"] == 20.0
        assert trend["points"] == 3

    def test_report_without_data(self, watchdog):
        assert watchdog.report() == {"error": "无数据"}

    def test_report_summarizes_history(self, watchdog):
        watchdog._snapshots = [
            mw.MemorySnapshot(process_rss_mb=100.0, process_vms_mb=200.0, system_percent=10.0),
            mw.MemorySnapshot(process_rss_mb=150.0, process_vms_mb=250.0, system_percent=20.0),
        ]
        watchdog._growth_records.append(
            mw.MemoryGrowthRecord(timestamp=1.0, delta_mb=50.0, delta_percent=50.0, source="fast_check")
        )

        report = watchdog.report()

        assert report["summary"]["current_rss_mb"] == 150.0
        assert report["summary"]["baseline_rss_mb"] == 100.0
        assert report["summary"]["total_growth_mb"] == 50.0
        assert report["summary"]["growth_incident_count"] == 1
        assert report["current_state"]["system_percent"] == 20.0
        assert report["recent_growth"][0]["source"] == "fast_check"
        assert report["trend"]["points"] == 2

    def test_save_report_writes_json_file(self, watchdog):
        watchdog._snapshots.append(
            mw.MemorySnapshot(process_rss_mb=100.0, process_vms_mb=200.0, system_percent=30.0)
        )

        watchdog._save_report()

        files = list(watchdog._log_dir.glob("memory_report_*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["summary"]["current_rss_mb"] == 100.0


# ============================================================
# WebSocket
# ============================================================

class TestWebSocket:
    def test_subscribe_is_deduplicated(self, watchdog):
        ws = object()

        watchdog.subscribe_ws(ws)
        watchdog.subscribe_ws(ws)

        assert watchdog._ws_subscribers == [ws]

    def test_unsubscribe_removes_only_present(self, watchdog):
        ws, other = object(), object()
        watchdog.subscribe_ws(ws)

        watchdog.unsubscribe_ws(other)
        assert watchdog._ws_subscribers == [ws]

        watchdog.unsubscribe_ws(ws)
        assert watchdog._ws_subscribers == []

    def test_broadcast_without_subscribers_is_noop(self, watchdog):
        watchdog._broadcast_snapshot(mw.MemorySnapshot())  # 不应抛异常

        assert watchdog._ws_subscribers == []

    async def test_broadcast_sends_and_drops_broken_subscriber(self, watchdog):
        sent = []

        class _GoodWs:
            async def send_json(self, data):
                sent.append(data)

        class _BadWs:
            def send_json(self, data):
                raise RuntimeError("连接已断开")

        good, bad = _GoodWs(), _BadWs()
        watchdog.subscribe_ws(good)
        watchdog.subscribe_ws(bad)

        watchdog._broadcast_snapshot(
            mw.MemorySnapshot(timestamp=1.0, process_rss_mb=10.0, system_percent=5.0)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert sent == [{
            "type": "memory_snapshot",
            "timestamp": 1.0,
            "process_rss_mb": 10.0,
            "system_percent": 5.0,
        }]
        assert watchdog._ws_subscribers == [good]


# ============================================================
# 模块级便捷函数
# ============================================================

class TestModuleHelpers:
    def test_get_memory_status_uses_watchdog(self, watchdog, monkeypatch):
        monkeypatch.setattr(mw, "_watchdog", watchdog)

        status = mw.get_memory_status()

        assert status["watchdog_running"] is False
        assert "process_rss_mb" in status

    def test_get_memory_status_without_watchdog_reads_psutil(self):
        status = mw.get_memory_status()

        assert status["watchdog_running"] is False
        assert status["process_rss_mb"] > 0
        assert status["system_percent"] > 0

    def test_get_memory_status_degrades_when_psutil_unavailable(self, monkeypatch):
        class _BadPsutil:
            def __getattr__(self, name):
                raise RuntimeError("psutil 不可用")

        monkeypatch.setattr(mw, "psutil", _BadPsutil())

        assert mw.get_memory_status() == {"error": "psutil 不可用"}
