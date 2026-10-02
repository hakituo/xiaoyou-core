"""core/async_monitor.py 单元测试。

覆盖范围：
- ``PerformanceMonitor``：配置默认值、GPU 惰性探测、start/stop、监控循环、
  ``_collect_metrics`` 的各路降级、``_save_history``、``_check_health_thresholds``、
  ``update_app_metrics`` / ``get_current_metrics`` / ``get_metrics_history`` / ``export_metrics``
- ``HealthChecker``：注册、单服务检查（协程/同步两种 checker 与状态归一化）、
  批量检查、整体摘要
- 模块级：``get_performance_monitor`` / ``get_health_checker`` / ``initialize_monitoring``
  / ``shutdown_monitoring``
- FastAPI 中间件 ``request_performance_middleware``
- 装饰器 ``enhanced_logger``（异步/同步 × 成功/异常）

不依赖真实资源：psutil / torch / pynvml / asyncio 循环 / 线程 / 时钟全部用桩或代理替换，
不启动真实监控线程、不真实等待、不读真实 GPU。
"""

from __future__ import annotations

import asyncio
import json
import psutil
import sys
import threading
import time
import types

import pytest

from core.async_monitor import HealthChecker, PerformanceMonitor
from core import async_monitor as am
from core.contracts import HealthStatus


# ============================================================
# 桩与代理
# ============================================================

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


class _TimeProxy:
    """替换模块内 time 引用：``time()`` 返回受控值，其余透传真实 time。

    用于把「指标是否过期」「请求是否算慢」这类判断变成确定值，不依赖真实时间流逝。
    """

    def __init__(self, now=1000.0):
        self._now = now

    def time(self):
        return self._now

    def advance(self, delta):
        self._now += delta

    def __getattr__(self, name):
        return getattr(time, name)


class _PsutilProxy:
    """替换模块内 psutil 引用：可让 cpu_percent / virtual_memory 抛错，其余透传真实 psutil。"""

    def __init__(self, cpu=12.5, memory_percent=34.5, cpu_exc=None, memory_exc=None):
        self._cpu = cpu
        self._memory_percent = memory_percent
        self._cpu_exc = cpu_exc
        self._memory_exc = memory_exc

    def cpu_percent(self, interval=None):
        if self._cpu_exc is not None:
            raise self._cpu_exc
        return self._cpu

    def virtual_memory(self):
        if self._memory_exc is not None:
            raise self._memory_exc
        return types.SimpleNamespace(percent=self._memory_percent)

    def __getattr__(self, name):
        return getattr(psutil, name)


class _ThreadStub:
    """替身线程：不真的跑 target，只记录 start/join 与存活状态。"""

    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.started = False
        self.joined = []
        self._alive = False

    def start(self):
        self.started = True
        self._alive = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.joined.append(timeout)
        self._alive = False


class _ThreadingProxy:
    """替换模块内 threading 引用：Thread 换成替身，Event/RLock 等透传真实 threading。"""

    def __init__(self, thread_cls=_ThreadStub):
        self.Thread = thread_cls

    def __getattr__(self, name):
        return getattr(threading, name)


class _LoopStub:
    def __init__(self, running=True):
        self._running = running

    def is_running(self):
        return self._running


class _AsyncioProxy:
    """替换模块内 asyncio 引用。

    - ``get_running_loop`` 可指定返回值或抛错，用于覆盖「无事件循环」等分支；
    - ``to_thread`` 默认改为就地执行（仍是协程），避免测试真的开线程；
    - 其余属性透传真实 asyncio。
    """

    def __init__(self, loop=None, get_running_loop_exc=None, inline_to_thread=True):
        self._loop = loop
        self._get_running_loop_exc = get_running_loop_exc
        self._inline_to_thread = inline_to_thread

    def get_running_loop(self):
        if self._get_running_loop_exc is not None:
            raise self._get_running_loop_exc
        if self._loop is None:
            return asyncio.get_running_loop()
        return self._loop

    async def to_thread(self, func, *args, **kwargs):
        if not self._inline_to_thread:
            return await asyncio.to_thread(func, *args, **kwargs)
        return func(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _fake_torch(cuda_available=True, total_memory=1000, allocated=250,
                props_exc=None, alloc_exc=None):
    """构造假的 torch 模块，供 _collect_metrics 的显存近似分支使用。"""
    module = types.ModuleType("torch")

    def _get_device_properties(index):
        if props_exc is not None:
            raise props_exc
        return types.SimpleNamespace(total_memory=total_memory)

    def _memory_allocated():
        if alloc_exc is not None:
            raise alloc_exc
        return allocated

    module.cuda = types.SimpleNamespace(
        is_available=lambda: cuda_available,
        get_device_properties=_get_device_properties,
        memory_allocated=_memory_allocated,
    )
    return module


def _fake_pynvml(gpu_percent=42.0, init_exc=None, util_exc=None):
    """构造假的 pynvml 模块，供 _collect_metrics 的 nvml 分支使用。"""
    module = types.ModuleType("pynvml")

    def _nvml_init():
        if init_exc is not None:
            raise init_exc

    def _get_handle_by_index(index):
        return "handle"

    def _get_utilization_rates(handle):
        if util_exc is not None:
            raise util_exc
        return types.SimpleNamespace(gpu=gpu_percent)

    module.nvmlInit = _nvml_init
    module.nvmlDeviceGetHandleByIndex = _get_handle_by_index
    module.nvmlDeviceGetUtilizationRates = _get_utilization_rates
    return module


class _MonitorStub:
    """替身监控器，只记录 start/stop 是否被调用。"""

    def __init__(self, thread=None):
        self.monitor_thread = thread
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def _block_import(monkeypatch, blocked_name):
    """让指定的模块名 import 失败，其余 import 正常。"""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _fake_import(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(f"模拟 {blocked_name} 缺失")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)


@pytest.fixture(autouse=True)
def _reset_module_globals(monkeypatch):
    """重置模块级单例，避免用例互相污染。"""
    monkeypatch.setattr(am, "_performance_monitor", None)
    monkeypatch.setattr(am, "_health_checker", None)


@pytest.fixture
def monitor():
    return PerformanceMonitor()


# ============================================================
# 构造与配置
# ============================================================

class TestInit:
    def test_defaults(self):
        mon = PerformanceMonitor()

        assert mon.enabled is True
        assert mon.interval == 1.0
        assert mon.history_size == 60
        assert mon.monitor_thread is None
        assert mon.app_metrics == {}
        assert set(mon.metrics_history) == {
            "cpu_usage", "memory_usage", "gpu_usage", "async_tasks", "active_connections",
        }
        assert all(len(v) == 0 for v in mon.metrics_history.values())
        assert mon.current_metrics["cpu_usage"] == 0.0
        assert mon.current_metrics["memory_usage"] == 0.0
        assert mon.current_metrics["gpu_usage"] == 0.0
        assert mon.current_metrics["async_tasks"] == 0
        assert mon.current_metrics["active_connections"] == 0
        assert isinstance(mon.current_metrics["timestamp"], float)

    def test_custom_config(self):
        mon = PerformanceMonitor({"enabled": False, "interval": 3.5, "history_size": 7})

        assert mon.enabled is False
        assert mon.interval == 3.5
        assert mon.history_size == 7
        # deque 的 maxlen 要跟着 history_size 走
        assert mon.metrics_history["cpu_usage"].maxlen == 7

    def test_empty_config_falls_back_to_defaults(self):
        mon = PerformanceMonitor({})

        assert mon.enabled is True
        assert mon.config == {}


# ============================================================
# GPU 惰性探测
# ============================================================

class TestLazyCheckGpu:
    def test_returns_early_when_already_checked(self, monitor, monkeypatch):
        monitor._gpu_checked = True
        monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=True))

        monitor._lazy_check_gpu()

        # 已检查过就不再探测，torch 可用也不会被记上
        assert monitor._torch_available is False

    def test_marks_torch_available_when_cuda_present(self, monitor, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=True))
        monkeypatch.setitem(sys.modules, "pynvml", _fake_pynvml(init_exc=RuntimeError("no nvml")))
        records = _capture_logger(monkeypatch, am)

        monitor._lazy_check_gpu()

        assert monitor._torch_available is True
        assert monitor._gpu_checked is True
        assert monitor._pynvml_available is False
        assert any(level == "warning" for level, _ in records)

    def test_leaves_torch_unavailable_when_cuda_absent(self, monitor, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=False))
        monkeypatch.setitem(sys.modules, "pynvml", _fake_pynvml(init_exc=RuntimeError("no nvml")))

        monitor._lazy_check_gpu()

        assert monitor._torch_available is False

    def test_torch_import_error_is_swallowed(self, monitor, monkeypatch):
        # sys.modules 里放 None 可稳定模拟 import 失败
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setitem(sys.modules, "pynvml", _fake_pynvml(init_exc=RuntimeError("no nvml")))

        monitor._lazy_check_gpu()

        assert monitor._torch_available is False

    def test_marks_pynvml_available_on_success(self, monitor, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setitem(sys.modules, "pynvml", _fake_pynvml(gpu_percent=10.0))
        records = _capture_logger(monkeypatch, am)

        monitor._lazy_check_gpu()

        assert monitor._pynvml_available is True
        assert any(level == "info" for level, _ in records)


# ============================================================
# 启停与监控循环
# ============================================================

class TestStartStop:
    def test_start_skipped_when_disabled(self, monkeypatch):
        mon = PerformanceMonitor({"enabled": False})
        records = _capture_logger(monkeypatch, am)

        mon.start()

        assert mon.monitor_thread is None
        assert any("性能监控已禁用" in text for _, text in records)

    def test_start_skipped_when_already_running(self, monitor, monkeypatch):
        running = _ThreadStub()
        running.start()
        monitor.monitor_thread = running
        records = _capture_logger(monkeypatch, am)

        monitor.start()

        assert monitor.monitor_thread is running
        assert any("性能监控已经在运行" in text for _, text in records)

    def test_start_spawns_daemon_thread(self, monitor, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        records = _capture_logger(monkeypatch, am)

        monitor.start()

        assert isinstance(monitor.monitor_thread, _ThreadStub)
        assert monitor.monitor_thread.daemon is True
        assert monitor.monitor_thread.started is True
        assert monitor.stop_event.is_set() is False
        assert any("性能监控已启动" in text for _, text in records)

    def test_stop_sets_event_and_joins(self, monitor, monkeypatch):
        running = _ThreadStub()
        running.start()
        monitor.monitor_thread = running
        records = _capture_logger(monkeypatch, am)

        monitor.stop()

        assert monitor.stop_event.is_set() is True
        assert running.joined == [5.0]
        assert any("性能监控已停止" in text for _, text in records)

    def test_stop_without_thread_is_noop(self, monitor, monkeypatch):
        records = _capture_logger(monkeypatch, am)

        monitor.stop()

        assert monitor.stop_event.is_set() is False
        assert records == []

    def test_stop_when_thread_not_alive_is_noop(self, monitor, monkeypatch):
        monitor.monitor_thread = _ThreadStub()  # 未 start → is_alive() False
        records = _capture_logger(monkeypatch, am)

        monitor.stop()

        assert monitor.stop_event.is_set() is False
        assert records == []


class TestMonitorLoop:
    def test_loop_runs_until_stop_event(self, monitor, monkeypatch):
        calls = {"collect": 0, "save": 0, "threshold": 0}
        rounds = {"n": 0}

        def _collect():
            calls["collect"] += 1
            rounds["n"] += 1
            if rounds["n"] >= 2:
                monitor.stop_event.set()

        monkeypatch.setattr(monitor, "_collect_metrics", _collect)
        monkeypatch.setattr(monitor, "_save_history", lambda: calls.__setitem__("save", calls["save"] + 1))
        monkeypatch.setattr(
            monitor, "_check_health_thresholds",
            lambda: calls.__setitem__("threshold", calls["threshold"] + 1),
        )
        records = _capture_logger(monkeypatch, am)

        monitor._monitor_loop()

        assert calls["collect"] == 2
        assert calls["save"] == 2
        assert calls["threshold"] == 2
        assert any("Monitor loop started" in text for _, text in records)
        assert any("Monitor loop stopped" in text for _, text in records)

    def test_loop_swallows_errors_and_continues(self, monitor, monkeypatch):
        state = {"n": 0}

        def _collect():
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("采集炸了")
            monitor.stop_event.set()

        monkeypatch.setattr(monitor, "_collect_metrics", _collect)
        monkeypatch.setattr(monitor, "_save_history", lambda: None)
        monkeypatch.setattr(monitor, "_check_health_thresholds", lambda: None)
        records = _capture_logger(monkeypatch, am)

        monitor._monitor_loop()

        assert state["n"] == 2
        assert any("性能监控出错" in text for _, text in records)

    def test_loop_waits_interval_between_rounds(self, monitor, monkeypatch):
        waits = []

        class _Event:
            def __init__(self):
                self._set = False

            def is_set(self):
                return self._set

            def set(self):
                self._set = True

            def wait(self, timeout=None):
                waits.append(timeout)
                self._set = True  # 等待后立刻退出，避免死循环

        monitor.stop_event = _Event()
        monkeypatch.setattr(monitor, "_collect_metrics", lambda: None)
        monkeypatch.setattr(monitor, "_save_history", lambda: None)
        monkeypatch.setattr(monitor, "_check_health_thresholds", lambda: None)
        monitor.interval = 2.5

        monitor._monitor_loop()

        assert waits == [2.5]


# ============================================================
# 指标采集
# ============================================================

class TestCollectMetrics:
    def _no_gpu(self, monitor, monkeypatch, **kwargs):
        """把 GPU 探测与事件循环都关掉，只测基础指标。"""
        monkeypatch.setattr(monitor, "_lazy_check_gpu", lambda: None)
        monkeypatch.setattr(
            am, "asyncio", _AsyncioProxy(get_running_loop_exc=RuntimeError("无事件循环"))
        )
        monkeypatch.setattr(am, "psutil", _PsutilProxy(**kwargs))
        monkeypatch.setattr(am, "time", _TimeProxy(now=1234.5))

    def test_collects_cpu_memory_without_gpu(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch, cpu=12.5, memory_percent=34.5)

        monitor._collect_metrics()

        assert monitor.current_metrics["cpu_usage"] == 12.5
        assert monitor.current_metrics["memory_usage"] == 34.5
        assert monitor.current_metrics["gpu_usage"] == 0.0
        assert monitor.current_metrics["async_tasks"] == 0
        assert monitor.current_metrics["timestamp"] == 1234.5

    def test_cpu_failure_falls_back_to_zero(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch, cpu_exc=RuntimeError("cpu 不可用"))

        monitor._collect_metrics()

        assert monitor.current_metrics["cpu_usage"] == 0.0

    def test_memory_failure_falls_back_to_zero(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch, memory_exc=RuntimeError("memory 不可用"))

        monitor._collect_metrics()

        assert monitor.current_metrics["memory_usage"] == 0.0

    def test_gpu_usage_from_pynvml(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch)
        monitor._pynvml_available = True
        monkeypatch.setitem(sys.modules, "pynvml", _fake_pynvml(gpu_percent=42.0))

        monitor._collect_metrics()

        assert monitor.current_metrics["gpu_usage"] == 42.0

    def test_gpu_usage_pynvml_failure_falls_back_to_zero(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch)
        monitor._pynvml_available = True
        monkeypatch.setitem(
            sys.modules, "pynvml", _fake_pynvml(util_exc=RuntimeError("查不到利用率"))
        )

        monitor._collect_metrics()

        assert monitor.current_metrics["gpu_usage"] == 0.0

    def test_gpu_usage_from_torch_memory_ratio(self, monitor, monkeypatch):
        """pynvml 不可用时退回 torch 显存占用近似：250 / 1000 * 100 = 25%。"""
        self._no_gpu(monitor, monkeypatch)
        monitor._torch_available = True
        monkeypatch.setitem(
            sys.modules, "torch", _fake_torch(total_memory=1000, allocated=250)
        )

        monitor._collect_metrics()

        assert monitor.current_metrics["gpu_usage"] == 25.0

    def test_gpu_usage_torch_failure_falls_back_to_zero(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch)
        monitor._torch_available = True
        monkeypatch.setitem(
            sys.modules, "torch", _fake_torch(props_exc=RuntimeError("取不到设备属性"))
        )

        monitor._collect_metrics()

        assert monitor.current_metrics["gpu_usage"] == 0.0

    def test_async_tasks_zero_when_loop_not_running(self, monitor, monkeypatch):
        monkeypatch.setattr(monitor, "_lazy_check_gpu", lambda: None)
        monkeypatch.setattr(am, "psutil", _PsutilProxy())
        monkeypatch.setattr(am, "asyncio", _AsyncioProxy(loop=_LoopStub(running=False)))

        monitor._collect_metrics()

        assert monitor.current_metrics["async_tasks"] == 0

    def test_async_tasks_zero_on_unexpected_error(self, monitor, monkeypatch):
        monkeypatch.setattr(monitor, "_lazy_check_gpu", lambda: None)
        monkeypatch.setattr(am, "psutil", _PsutilProxy())
        monkeypatch.setattr(
            am, "asyncio", _AsyncioProxy(get_running_loop_exc=ValueError("其它异常"))
        )

        monitor._collect_metrics()

        assert monitor.current_metrics["async_tasks"] == 0

    async def test_async_tasks_counted_inside_running_loop(self, monitor, monkeypatch):
        """在真实运行中的事件循环里调用，应数到至少当前这个任务。"""
        monkeypatch.setattr(monitor, "_lazy_check_gpu", lambda: None)
        monkeypatch.setattr(am, "psutil", _PsutilProxy())

        monitor._collect_metrics()

        assert monitor.current_metrics["async_tasks"] >= 1

    def test_app_metrics_are_merged_in(self, monitor, monkeypatch):
        self._no_gpu(monitor, monkeypatch)
        monitor.app_metrics = {"active_connections": 7, "custom_metric": 1.5}

        monitor._collect_metrics()

        assert monitor.current_metrics["active_connections"] == 7
        assert monitor.current_metrics["custom_metric"] == 1.5

    def test_outer_failure_is_logged_not_raised(self, monitor, monkeypatch):
        monkeypatch.setattr(
            monitor, "_lazy_check_gpu",
            lambda: (_ for _ in ()).throw(RuntimeError("探测就炸了")),
        )
        records = _capture_logger(monkeypatch, am)

        monitor._collect_metrics()  # 不应抛异常

        assert any("收集指标失败" in text for _, text in records)


# ============================================================
# 历史与阈值
# ============================================================

class TestSaveHistory:
    def test_appends_timestamped_points(self, monitor):
        monitor.current_metrics = {
            "timestamp": 5.0,
            "cpu_usage": 1.0,
            "memory_usage": 2.0,
            "gpu_usage": 3.0,
            "async_tasks": 4,
            "active_connections": 5,
        }

        monitor._save_history()

        assert list(monitor.metrics_history["cpu_usage"]) == [(5.0, 1.0)]
        assert list(monitor.metrics_history["memory_usage"]) == [(5.0, 2.0)]
        assert list(monitor.metrics_history["gpu_usage"]) == [(5.0, 3.0)]
        assert list(monitor.metrics_history["async_tasks"]) == [(5.0, 4)]
        assert list(monitor.metrics_history["active_connections"]) == [(5.0, 5)]

    def test_missing_metric_is_skipped(self, monitor):
        monitor.current_metrics = {"timestamp": 5.0, "cpu_usage": 1.0}

        monitor._save_history()

        assert list(monitor.metrics_history["cpu_usage"]) == [(5.0, 1.0)]
        assert list(monitor.metrics_history["memory_usage"]) == []

    def test_history_is_capped_by_maxlen(self, monkeypatch):
        mon = PerformanceMonitor({"history_size": 2})
        for value in (1.0, 2.0, 3.0):
            mon.current_metrics = {"timestamp": value, "cpu_usage": value}
            mon._save_history()

        assert list(mon.metrics_history["cpu_usage"]) == [(2.0, 2.0), (3.0, 3.0)]

    def test_failure_is_logged_not_raised(self, monitor, monkeypatch):
        monitor.current_metrics = None
        records = _capture_logger(monkeypatch, am)

        monitor._save_history()  # 不应抛异常

        assert any("保存历史指标失败" in text for _, text in records)


class TestCheckHealthThresholds:
    def test_no_warning_below_thresholds(self, monitor, monkeypatch):
        monitor.current_metrics = {"cpu_usage": 1.0, "memory_usage": 1.0, "async_tasks": 1}
        records = _capture_logger(monkeypatch, am)

        monitor._check_health_thresholds()

        assert records == []

    def test_cpu_over_threshold_warns(self, monitor, monkeypatch):
        monitor.current_metrics = {"cpu_usage": 95.0, "memory_usage": 1.0, "async_tasks": 1}
        records = _capture_logger(monkeypatch, am)

        monitor._check_health_thresholds()

        assert len(records) == 1
        assert "CPU使用率过高" in records[0][1]

    def test_memory_over_threshold_warns(self, monitor, monkeypatch):
        monitor.current_metrics = {"cpu_usage": 1.0, "memory_usage": 90.0, "async_tasks": 1}
        records = _capture_logger(monkeypatch, am)

        monitor._check_health_thresholds()

        assert len(records) == 1
        assert "内存使用率过高" in records[0][1]

    def test_async_tasks_over_threshold_warns(self, monitor, monkeypatch):
        monitor.current_metrics = {"cpu_usage": 1.0, "memory_usage": 1.0, "async_tasks": 5000}
        records = _capture_logger(monkeypatch, am)

        monitor._check_health_thresholds()

        assert len(records) == 1
        assert "异步任务数量过多" in records[0][1]

    def test_all_three_can_warn_together(self, monitor, monkeypatch):
        monitor.current_metrics = {"cpu_usage": 99.0, "memory_usage": 99.0, "async_tasks": 9999}
        records = _capture_logger(monkeypatch, am)

        monitor._check_health_thresholds()

        assert len(records) == 3

    def test_custom_thresholds_are_honoured(self, monkeypatch):
        mon = PerformanceMonitor({"thresholds": {"cpu_usage": 5.0, "memory_usage": 5.0,
                                                 "async_tasks": 1}})
        mon.current_metrics = {"cpu_usage": 6.0, "memory_usage": 6.0, "async_tasks": 2}
        records = _capture_logger(monkeypatch, am)

        mon._check_health_thresholds()

        assert len(records) == 3

    def test_non_dict_thresholds_falls_back_to_defaults(self, monkeypatch):
        """记录现状：直接构造时传入非 dict 的 thresholds，``_check_health_thresholds`` 会抛
        ``AttributeError``。正常入口（``initialize_monitoring``）已把非 dict 归一成 {}，
        所以这条只在绕开入口直接构造时才可能发生，此处按实际行为如实锁定。"""
        mon = PerformanceMonitor({"thresholds": "not-a-dict"})
        mon.current_metrics = {"cpu_usage": 99.0, "memory_usage": 99.0, "async_tasks": 9999}

        with pytest.raises(AttributeError):
            mon._check_health_thresholds()


class TestAppMetricsAndQuery:
    def test_update_app_metrics_merges(self, monitor):
        monitor.update_app_metrics({"a": 1})
        monitor.update_app_metrics({"b": 2})

        assert monitor.app_metrics == {"a": 1, "b": 2}

    def test_get_current_metrics_returns_copy(self, monitor, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        calls = []
        monkeypatch.setattr(monitor, "_collect_metrics", lambda: calls.append(1))

        result = monitor.get_current_metrics()
        result["cpu_usage"] = 999

        assert calls == []  # 时间戳是刚写的，不算过期
        assert monitor.current_metrics["cpu_usage"] != 999

    def test_get_current_metrics_collects_when_stale_and_no_thread(self, monitor, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        monitor.current_metrics = {"timestamp": 0.0}
        calls = []
        monkeypatch.setattr(monitor, "_collect_metrics", lambda: calls.append(1))

        monitor.get_current_metrics()

        assert calls == [1]

    def test_get_current_metrics_skips_collect_when_thread_alive(self, monitor, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        monitor.current_metrics = {"timestamp": 0.0}
        alive = _ThreadStub()
        alive.start()
        monitor.monitor_thread = alive
        calls = []
        monkeypatch.setattr(monitor, "_collect_metrics", lambda: calls.append(1))

        monitor.get_current_metrics()

        assert calls == []

    def test_get_current_metrics_swallows_collect_error(self, monitor, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        monitor.current_metrics = {"timestamp": 0.0}
        monkeypatch.setattr(
            monitor, "_collect_metrics",
            lambda: (_ for _ in ()).throw(RuntimeError("主动采集失败")),
        )

        result = monitor.get_current_metrics()

        assert result == {"timestamp": 0.0}

    def test_get_metrics_history_unknown_name(self, monitor):
        assert monitor.get_metrics_history("nope") == []

    def test_get_metrics_history_with_limit(self, monitor):
        monitor.metrics_history["cpu_usage"].extend([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)])

        assert monitor.get_metrics_history("cpu_usage", limit=2) == [(2.0, 2.0), (3.0, 3.0)]

    def test_get_metrics_history_without_limit(self, monitor):
        monitor.metrics_history["cpu_usage"].extend([(1.0, 1.0), (2.0, 2.0)])

        assert monitor.get_metrics_history("cpu_usage") == [(1.0, 1.0), (2.0, 2.0)]

    def test_get_metrics_history_zero_limit_returns_all(self, monitor):
        """limit 为 0 属假值，走「不加限制」分支。"""
        monitor.metrics_history["cpu_usage"].extend([(1.0, 1.0)])

        assert monitor.get_metrics_history("cpu_usage", limit=0) == [(1.0, 1.0)]


class TestExportMetrics:
    def test_export_without_path_returns_json(self, monitor, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        monitor.current_metrics["timestamp"] = 1000.0
        monitor.metrics_history["cpu_usage"].append((1.0, 5.0))

        raw = monitor.export_metrics()
        payload = json.loads(raw)

        assert set(payload) == {"current", "history", "export_time"}
        assert payload["history"]["cpu_usage"] == [[1.0, 5.0]]
        assert payload["current"]["timestamp"] == 1000.0
        assert isinstance(payload["export_time"], str)

    def test_export_to_file(self, monitor, tmp_path, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        records = _capture_logger(monkeypatch, am)
        target = tmp_path / "metrics.json"

        raw = monitor.export_metrics(str(target))

        assert json.loads(target.read_text(encoding="utf-8")) == json.loads(raw)
        assert any("性能指标已导出到" in text for _, text in records)

    def test_export_write_failure_is_logged(self, monitor, tmp_path, monkeypatch):
        monkeypatch.setattr(am, "time", _TimeProxy(now=1000.0))
        records = _capture_logger(monkeypatch, am)

        # 目标是一个目录，open(..., "w") 必失败
        raw = monitor.export_metrics(str(tmp_path))

        assert json.loads(raw)  # 仍然返回 JSON 文本
        assert any("导出性能指标失败" in text for _, text in records)


# ============================================================
# HealthChecker
# ============================================================

class TestRegisterHealthChecker:
    def test_registers_checker_and_status(self):
        checker = HealthChecker()
        func = lambda: {"status": "healthy"}  # noqa: E731

        checker.register_health_checker("svc", func, interval=12.5)

        assert checker.health_checkers["svc"]["checker"] is func
        assert checker.health_checkers["svc"]["interval"] == 12.5
        assert checker.health_checkers["svc"]["last_check"] == 0
        assert checker.health_status["svc"]["status"] == HealthStatus.UNKNOWN.value
        assert checker.health_status["svc"]["details"] is None

    def test_default_interval(self):
        checker = HealthChecker()

        checker.register_health_checker("svc", lambda: {"status": "healthy"})

        assert checker.health_checkers["svc"]["interval"] == 30.0


class TestCheckServiceHealth:
    async def test_unknown_service(self):
        checker = HealthChecker()

        result = await checker.check_service_health("nope")

        assert result == {"status": "unknown", "details": "未知服务: nope"}

    async def test_async_checker_healthy(self):
        checker = HealthChecker()

        async def _check():
            return {"status": "healthy", "details": "ok"}

        checker.register_health_checker("svc", _check)

        result = await checker.check_service_health("svc")

        assert result["status"] == HealthStatus.HEALTHY.value
        assert result["details"] == "ok"
        assert checker.health_status["svc"] == result

    async def test_sync_checker_runs_via_to_thread(self, monkeypatch):
        monkeypatch.setattr(am, "asyncio", _AsyncioProxy())
        checker = HealthChecker()
        seen = []

        def _check():
            seen.append(1)
            return {"status": "healthy"}

        checker.register_health_checker("svc", _check)

        result = await checker.check_service_health("svc")

        assert seen == [1]
        assert result["status"] == HealthStatus.HEALTHY.value

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("HEALTHY", HealthStatus.HEALTHY.value),
            ("healthy", HealthStatus.HEALTHY.value),
            ("degraded", HealthStatus.DEGRADED.value),
            ("unhealthy", HealthStatus.UNHEALTHY.value),
            ("error", HealthStatus.ERROR.value),
            ("unknown", HealthStatus.UNKNOWN.value),
            ("weird", HealthStatus.UNHEALTHY.value),
            ("", HealthStatus.UNKNOWN.value),
        ],
    )
    async def test_status_normalization(self, raw, expected):
        checker = HealthChecker()

        async def _check():
            return {"status": raw}

        checker.register_health_checker("svc", _check)

        result = await checker.check_service_health("svc")

        assert result["status"] == expected

    async def test_status_missing_key_is_unknown(self):
        checker = HealthChecker()

        async def _check():
            return {"details": "没有 status 字段"}

        checker.register_health_checker("svc", _check)

        result = await checker.check_service_health("svc")

        assert result["status"] == HealthStatus.UNKNOWN.value

    async def test_status_none_is_unknown(self):
        checker = HealthChecker()

        async def _check():
            return {"status": None}

        checker.register_health_checker("svc", _check)

        result = await checker.check_service_health("svc")

        assert result["status"] == HealthStatus.UNKNOWN.value

    async def test_checker_failure_is_reported_as_error(self, monkeypatch):
        checker = HealthChecker()

        async def _check():
            raise RuntimeError("检查器炸了")

        checker.register_health_checker("svc", _check)
        records = _capture_logger(monkeypatch, am)

        result = await checker.check_service_health("svc")

        assert result["status"] == HealthStatus.ERROR.value
        assert result["details"] == "检查器炸了"
        assert checker.health_status["svc"] == result
        assert any("服务健康检查失败 [svc]" in text for _, text in records)


class TestCheckAllServices:
    async def test_gathers_all_results(self):
        checker = HealthChecker()

        async def _healthy():
            return {"status": "healthy"}

        async def _broken():
            raise RuntimeError("坏了")

        checker.register_health_checker("a", _healthy)
        checker.register_health_checker("b", _broken)

        results = await checker.check_all_services()

        assert set(results) == {"a", "b"}
        assert results["a"]["status"] == HealthStatus.HEALTHY.value
        assert results["b"]["status"] == HealthStatus.ERROR.value

    async def test_empty_registry_returns_empty_dict(self):
        assert await HealthChecker().check_all_services() == {}


class TestHealthSummary:
    def test_all_healthy(self):
        checker = HealthChecker()
        checker.health_status = {
            "a": {"status": "healthy"},
            "b": {"status": "healthy"},
        }

        summary = checker.get_health_summary()

        assert summary["overall_status"] == HealthStatus.HEALTHY.value
        assert summary["services"] == checker.health_status
        assert isinstance(summary["timestamp"], float)

    def test_any_error_wins(self):
        checker = HealthChecker()
        checker.health_status = {"a": {"status": "healthy"}, "b": {"status": "error"}}

        assert checker.get_health_summary()["overall_status"] == HealthStatus.ERROR.value

    def test_degraded_when_not_all_healthy_and_no_error(self):
        checker = HealthChecker()
        checker.health_status = {"a": {"status": "healthy"}, "b": {"status": "degraded"}}

        assert checker.get_health_summary()["overall_status"] == HealthStatus.DEGRADED.value

    def test_empty_status_counts_as_healthy(self):
        """没有注册任何服务时 all([]) 为真，整体判为 healthy。"""
        assert HealthChecker().get_health_summary()["overall_status"] == HealthStatus.HEALTHY.value

    def test_missing_status_key_is_not_healthy(self):
        checker = HealthChecker()
        checker.health_status = {"a": {"details": "没有状态"}}

        assert checker.get_health_summary()["overall_status"] == HealthStatus.DEGRADED.value


# ============================================================
# 模块级单例与初始化
# ============================================================

class TestModuleSingletons:
    def test_get_performance_monitor_caches(self):
        first = am.get_performance_monitor()
        second = am.get_performance_monitor()

        assert isinstance(first, PerformanceMonitor)
        assert first is second
        assert am._performance_monitor is first

    def test_get_health_checker_caches(self):
        first = am.get_health_checker()
        second = am.get_health_checker()

        assert isinstance(first, HealthChecker)
        assert first is second
        assert am._health_checker is first


class TestInitializeMonitoring:
    async def test_existing_monitor_with_live_thread_is_kept(self, monkeypatch):
        alive = _ThreadStub()
        alive.start()
        stub = _MonitorStub(thread=alive)
        monkeypatch.setattr(am, "_performance_monitor", stub)
        records = _capture_logger(monkeypatch, am)

        await am.initialize_monitoring()

        assert stub.started == 0
        assert am._performance_monitor is stub
        assert any("already initialized" in text for _, text in records)

    async def test_existing_monitor_with_dead_thread_is_restarted(self, monkeypatch):
        stub = _MonitorStub(thread=None)
        monkeypatch.setattr(am, "_performance_monitor", stub)
        records = _capture_logger(monkeypatch, am)

        await am.initialize_monitoring()

        assert stub.started == 1
        assert any("restarting" in text for _, text in records)

    async def test_creates_monitor_with_explicit_config(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        records = _capture_logger(monkeypatch, am)

        await am.initialize_monitoring({"performance_monitor": {"interval": 4.0}})

        created = am._performance_monitor
        assert isinstance(created, PerformanceMonitor)
        assert created.interval == 4.0
        # 未在配置里给出的阈值补默认值
        assert created.config["thresholds"]["async_tasks"] == 1000
        assert created.monitor_thread.started is True
        assert any("异步监控系统初始化完成" in text for _, text in records)

    async def test_non_dict_monitor_config_is_ignored(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())

        await am.initialize_monitoring({"performance_monitor": "not-a-dict"})

        assert am._performance_monitor.interval == 1.0

    async def test_non_dict_thresholds_are_ignored(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())

        await am.initialize_monitoring(
            {"performance_monitor": {"thresholds": "not-a-dict"}}
        )

        assert am._performance_monitor.config["thresholds"]["async_tasks"] == 1000

    async def test_config_none_uses_config_manager_when_available(self, monkeypatch):
        """config 为 None 且 ConfigManager 可用时，走「从配置中心读取」这条正常路径。"""
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        fake_module = types.ModuleType("core.core_engine.config_manager")

        class _ConfigManager:
            def get_all_config(self):
                return {"performance_monitor": {"interval": 6.0}}

        fake_module.ConfigManager = _ConfigManager
        monkeypatch.setitem(sys.modules, "core.core_engine.config_manager", fake_module)

        await am.initialize_monitoring()

        assert am._performance_monitor.interval == 6.0

    async def test_config_none_falls_back_to_empty_when_load_fails(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        _block_import(monkeypatch, "core.core_engine.config_manager")
        records = _capture_logger(monkeypatch, am)

        await am.initialize_monitoring()

        assert isinstance(am._performance_monitor, PerformanceMonitor)
        assert any("无法加载配置，使用默认配置" in text for _, text in records)

    async def test_settings_thresholds_are_applied(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        settings = types.SimpleNamespace(
            monitor=types.SimpleNamespace(
                cpu_threshold_high=77.0, memory_threshold_high=88.0
            )
        )
        fake_config = types.ModuleType("config.integrated_config")
        fake_config.get_settings = lambda: settings
        monkeypatch.setitem(sys.modules, "config.integrated_config", fake_config)

        await am.initialize_monitoring({})

        thresholds = am._performance_monitor.config["thresholds"]
        assert thresholds["cpu_usage"] == 77.0
        assert thresholds["memory_usage"] == 88.0
        assert thresholds["async_tasks"] == 1000

    async def test_settings_failure_keeps_async_tasks_default_only(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        _block_import(monkeypatch, "config.integrated_config")

        await am.initialize_monitoring({})

        thresholds = am._performance_monitor.config["thresholds"]
        assert thresholds == {"async_tasks": 1000}

    async def test_existing_thresholds_are_not_overwritten(self, monkeypatch):
        monkeypatch.setattr(am, "threading", _ThreadingProxy())
        settings = types.SimpleNamespace(
            monitor=types.SimpleNamespace(
                cpu_threshold_high=77.0, memory_threshold_high=88.0
            )
        )
        fake_config = types.ModuleType("config.integrated_config")
        fake_config.get_settings = lambda: settings
        monkeypatch.setitem(sys.modules, "config.integrated_config", fake_config)

        await am.initialize_monitoring(
            {"performance_monitor": {"thresholds": {"cpu_usage": 11.0}}}
        )

        assert am._performance_monitor.config["thresholds"]["cpu_usage"] == 11.0

    async def test_outer_failure_is_logged(self, monkeypatch):
        class _Boom:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("构造就炸了")

        monkeypatch.setattr(am, "PerformanceMonitor", _Boom)
        records = _capture_logger(monkeypatch, am)

        await am.initialize_monitoring({})  # 不应抛异常

        assert am._performance_monitor is None
        assert any("初始化监控系统失败" in text for _, text in records)


class TestShutdownMonitoring:
    async def test_stops_and_clears_globals(self, monkeypatch):
        stub = _MonitorStub()
        monkeypatch.setattr(am, "_performance_monitor", stub)
        monkeypatch.setattr(am, "_health_checker", HealthChecker())
        records = _capture_logger(monkeypatch, am)

        await am.shutdown_monitoring()

        assert stub.stopped == 1
        assert am._performance_monitor is None
        assert am._health_checker is None
        assert any("异步监控系统已关闭" in text for _, text in records)

    async def test_noop_when_nothing_initialized(self, monkeypatch):
        records = _capture_logger(monkeypatch, am)

        await am.shutdown_monitoring()

        assert am._performance_monitor is None
        assert any("异步监控系统已关闭" in text for _, text in records)


# ============================================================
# 请求中间件
# ============================================================

class _RequestStub:
    def __init__(self, path="/api/demo"):
        self.url = types.SimpleNamespace(path=path)


class _ResponseStub:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}


class TestRequestPerformanceMiddleware:
    async def test_fast_request_records_metrics(self, monkeypatch):
        time_proxy = _TimeProxy(now=1000.0)
        monkeypatch.setattr(am, "time", time_proxy)
        monitor = PerformanceMonitor()
        monkeypatch.setattr(am, "_performance_monitor", monitor)
        records = _capture_logger(monkeypatch, am)
        response = _ResponseStub(status_code=201)

        async def _call_next(request):
            time_proxy.advance(0.25)
            return response

        result = await am.request_performance_middleware(_RequestStub(), _call_next)

        assert result is response
        assert response.headers["X-Process-Time"] == "0.25"
        assert monitor.app_metrics["last_request_process_time"] == 0.25
        assert monitor.app_metrics["last_request_path"] == "/api/demo"
        assert monitor.app_metrics["last_request_status"] == 201
        assert records == []  # 0.25 秒不算慢请求

    async def test_slow_request_warns(self, monkeypatch):
        time_proxy = _TimeProxy(now=1000.0)
        monkeypatch.setattr(am, "time", time_proxy)
        monkeypatch.setattr(am, "_performance_monitor", PerformanceMonitor())
        records = _capture_logger(monkeypatch, am)

        async def _call_next(request):
            time_proxy.advance(2.0)
            return _ResponseStub()

        await am.request_performance_middleware(_RequestStub("/api/slow"), _call_next)

        assert any("慢请求警告" in text and "/api/slow" in text for _, text in records)

    async def test_exception_is_logged_and_reraised(self, monkeypatch):
        time_proxy = _TimeProxy(now=1000.0)
        monkeypatch.setattr(am, "time", time_proxy)
        monkeypatch.setattr(am, "_performance_monitor", PerformanceMonitor())
        records = _capture_logger(monkeypatch, am)

        async def _call_next(request):
            time_proxy.advance(0.5)
            raise ValueError("下游炸了")

        with pytest.raises(ValueError, match="下游炸了"):
            await am.request_performance_middleware(_RequestStub("/api/boom"), _call_next)

        assert any("请求处理异常" in text and "/api/boom" in text for _, text in records)


# ============================================================
# 日志增强装饰器
# ============================================================

class TestEnhancedLogger:
    def test_async_function_uses_async_wrapper(self, monkeypatch):
        records = _capture_logger(monkeypatch, am)

        @am.enhanced_logger
        async def _work(value):
            return value * 2

        result = asyncio.run(_work(21))

        assert result == 42
        assert any("[调用]" in text and "_work" in text for _, text in records)
        assert any("[完成]" in text and "返回: int" in text for _, text in records)

    def test_sync_function_uses_sync_wrapper(self, monkeypatch):
        records = _capture_logger(monkeypatch, am)

        @am.enhanced_logger
        def _work(value):
            return str(value)

        result = _work(7)

        assert result == "7"
        assert any("[调用]" in text for _, text in records)
        assert any("[完成]" in text and "返回: str" in text for _, text in records)

    def test_async_exception_is_logged_and_reraised(self, monkeypatch):
        records = _capture_logger(monkeypatch, am)

        @am.enhanced_logger
        async def _boom():
            raise RuntimeError("异步炸了")

        with pytest.raises(RuntimeError, match="异步炸了"):
            asyncio.run(_boom())

        assert any("[异常]" in text and "异步炸了" in text for _, text in records)

    def test_sync_exception_is_logged_and_reraised(self, monkeypatch):
        records = _capture_logger(monkeypatch, am)

        @am.enhanced_logger
        def _boom():
            raise RuntimeError("同步炸了")

        with pytest.raises(RuntimeError, match="同步炸了"):
            _boom()

        assert any("[异常]" in text and "同步炸了" in text for _, text in records)

    def test_wrapper_preserves_args_and_kwargs(self, monkeypatch):
        _capture_logger(monkeypatch, am)
        seen = {}

        @am.enhanced_logger
        def _work(*args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return "done"

        result = _work(1, 2, key="v")

        assert result == "done"
        assert seen == {"args": (1, 2), "kwargs": {"key": "v"}}

    def test_returns_plain_callable_for_sync(self, monkeypatch):
        _capture_logger(monkeypatch, am)

        def _sync():
            return 1

        wrapped = am.enhanced_logger(_sync)

        assert not asyncio.iscoroutinefunction(wrapped)
        assert wrapped() == 1

    def test_returns_coroutine_callable_for_async(self, monkeypatch):
        _capture_logger(monkeypatch, am)

        async def _async():
            return 1

        wrapped = am.enhanced_logger(_async)

        assert asyncio.iscoroutinefunction(wrapped)
