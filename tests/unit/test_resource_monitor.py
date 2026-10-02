"""``core/resource/monitor.py`` 单元测试。

设计原则：

- 绝不触发真实 GPU / CUDA / nvidia-smi / 真实采样等待；
  一律通过向 ``sys.modules`` 或 ``monitor`` 模块属性注入桩对象来控制外部依赖
  （``psutil`` / ``torch`` / ``pynvml`` / ``winreg`` / ``subprocess`` / ``shutil``）。
- 不使用 ``sleep``，不依赖真实当前时间（用固定 ``time.time`` 桩）。
- 只断言「注入的桩值被正确读出 / 计算」，不断言真实内存、显存、耗时等易变数值。
- 异步接口按仓库惯例用「同步测试函数 + ``asyncio.run``」。
"""
from __future__ import annotations

import asyncio
import builtins
import sys
import types

import pytest

from core.contracts import ResourceSeverity, ResourceType
from core.resource import monitor
from core.resource.monitor import (
    ResourceMonitor,
    ResourceThreshold,
    _get_torch,
)

MiB = 1024 * 1024


# ==================== 通用桩对象 ====================


class _FakeOS:
    """受控的 ``os`` 替身，支持 name / getcwd / splitdrive / path.exists。"""

    def __init__(self, name="nt", cwd="C:/work", drive="C:", existing=(), exists_raises=False):
        self.name = name
        self._cwd = cwd
        self._drive = drive
        self._existing = set(existing)
        self._exists_raises = exists_raises
        self.path = types.SimpleNamespace(splitdrive=self._splitdrive, exists=self._exists)

    def _splitdrive(self, p):
        if self._drive and p.startswith(self._drive):
            return (self._drive, p[len(self._drive):])
        return ("", p)

    def _exists(self, p):
        if self._exists_raises:
            raise OSError("exists boom")
        return p in self._existing

    def getcwd(self):
        return self._cwd


class _FakeProcess:
    """受控的 ``psutil.Process`` 替身。"""

    def __init__(self, pid=1234, rss=0, children=None, children_raises=False, pid_raises=False):
        self._pid = pid
        self._rss = rss
        self._children = children if children is not None else []
        self._children_raises = children_raises
        self._pid_raises = pid_raises

    @property
    def pid(self):
        if self._pid_raises:
            return object()  # int(object()) 会抛 TypeError
        return self._pid

    def memory_info(self):
        return types.SimpleNamespace(rss=self._rss)

    def children(self, recursive=False):
        if self._children_raises:
            raise RuntimeError("children boom")
        return self._children


class _FakeCompleted:
    """``subprocess.run`` 的返回替身。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_psutil(vm_percent=50.0, vm_available=8 * MiB, cpu=10.0, disk=None, disk_raises=False):
    """构造 psutil 替身；``disk`` 为可调用对象时优先使用。"""

    def virtual_memory():
        return types.SimpleNamespace(percent=vm_percent, available=vm_available)

    def disk_usage(path):
        if disk is not None:
            return disk(path)
        if disk_raises:
            raise OSError("disk boom")
        return types.SimpleNamespace(percent=42.0)

    return types.SimpleNamespace(
        virtual_memory=virtual_memory,
        cpu_percent=lambda interval=None: cpu,
        disk_usage=disk_usage,
        Process=lambda: _FakeProcess(),
    )


def _fake_subprocess(check_output=None, run=None):
    """构造 subprocess 替身，保留 DEVNULL 常量。"""

    def _default_check_output(*a, **k):
        raise RuntimeError("check_output boom")

    def _default_run(*a, **k):
        raise RuntimeError("run boom")

    import subprocess as _real

    return types.SimpleNamespace(
        check_output=check_output or _default_check_output,
        run=run or _default_run,
        DEVNULL=_real.DEVNULL,
    )


def _fake_time(now):
    """固定 time.time 返回值。"""
    return types.SimpleNamespace(time=lambda: now)


def _fake_nvml(memory_used=2 * MiB, memory_total=8 * MiB):
    """构造 nvml 替身：显存读取正常，进程列表返回空。"""
    return types.SimpleNamespace(
        nvmlDeviceGetMemoryInfo=lambda h: types.SimpleNamespace(
            used=memory_used, total=memory_total
        ),
        nvmlDeviceGetComputeRunningProcesses=lambda h: [],
        nvmlDeviceGetComputeRunningProcesses_v2=lambda h: [],
        nvmlDeviceGetGraphicsRunningProcesses=lambda h: [],
        nvmlDeviceGetGraphicsRunningProcesses_v2=lambda h: [],
    )


def _nvml_monitor(**kwargs):
    """构造一个「NVML 已就绪」的监控器。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = _fake_nvml(**kwargs)
    return mon


async def _boom_async(*a, **k):
    raise RuntimeError("subprocess boom")


# ==================== 阈值配置 ====================


def test_thresholds_property_and_set_threshold():
    """thresholds 属性返回内部字典，set_threshold 能覆盖阈值。"""
    mon = ResourceMonitor()
    assert mon.thresholds[ResourceType.MEMORY].warning == 70.0
    assert mon.thresholds[ResourceType.CPU].emergency == 95.0

    new_th = ResourceThreshold(1.0, 2.0, 3.0)
    mon.set_threshold(ResourceType.CPU, new_th)
    assert mon.thresholds[ResourceType.CPU] is new_th


def test_resource_threshold_slots():
    """ResourceThreshold 三档阈值可读。"""
    th = ResourceThreshold(10.0, 20.0, 30.0)
    assert (th.warning, th.critical, th.emergency) == (10.0, 20.0, 30.0)


def test_invalidate_gpu_cache_resets_all():
    """invalidate_gpu_cache 清空显存与进程缓存及时间戳。"""
    mon = ResourceMonitor()
    mon._gpu_memory_cache = (1, 2)
    mon._gpu_memory_cache_time = 5.0
    mon._gpu_process_cache = {1: 2}
    mon._gpu_process_cache_time = 5.0

    mon.invalidate_gpu_cache()

    assert mon._gpu_memory_cache is None
    assert mon._gpu_memory_cache_time == 0.0
    assert mon._gpu_process_cache is None
    assert mon._gpu_process_cache_time == 0.0


# ==================== 内存 / CPU 基础指标 ====================


def test_memory_and_cpu_metrics_use_psutil(monkeypatch):
    """内存 / CPU 指标直接读取 psutil 返回值。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "psutil", _fake_psutil(vm_percent=42.5, vm_available=3 * MiB, cpu=33.3))

    assert mon.get_memory_usage() == 42.5
    assert mon.get_available_memory_mb() == 3
    assert mon.get_cpu_usage() == 33.3


def test_get_process_memory_usage_mb():
    """进程内存按 rss 字节换算成 MB。"""
    mon = ResourceMonitor()
    mon._process = _FakeProcess(rss=300 * MiB)
    assert mon.get_process_memory_usage() == 300


# ==================== CPU 型号 ====================


def test_get_cpu_model_returns_cache():
    """已缓存时直接返回，不触发探测。"""
    mon = ResourceMonitor()
    mon._cpu_model = "Cached CPU"
    assert mon.get_cpu_model() == "Cached CPU"


def test_get_cpu_model_probe_exception_falls_back(monkeypatch):
    """探测抛异常时降级为 Unknown CPU。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt"))

    def _boom():
        raise RuntimeError("probe boom")

    monkeypatch.setattr(mon, "_get_cpu_model_windows", _boom)
    assert mon.get_cpu_model() == "Unknown CPU"
    assert mon._cpu_model == "Unknown CPU"


def test_get_cpu_model_linux_branch(monkeypatch):
    """os.name != nt 时走 Linux 分支。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="posix"))
    monkeypatch.setattr(mon, "_get_cpu_model_linux", lambda: "Linux CPU")
    assert mon.get_cpu_model() == "Linux CPU"


def test_cpu_model_windows_via_winreg(monkeypatch):
    """Windows 注册表能取到型号时直接返回并 strip。"""
    mon = ResourceMonitor()
    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda *a: "key",
        QueryValueEx=lambda k, n: ("  Intel(R) Core(TM) i9  ", 1),
        CloseKey=lambda k: None,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert mon._get_cpu_model_windows() == "Intel(R) Core(TM) i9"


def test_cpu_model_windows_winreg_empty_then_powershell(monkeypatch):
    """注册表返回空串时回退到 PowerShell。"""
    mon = ResourceMonitor()
    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda *a: "key",
        QueryValueEx=lambda k, n: ("", 1),
        CloseKey=lambda k: None,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    def check_output(args, **kwargs):
        assert args[0] == "powershell"
        return "  AMD Ryzen 7  "

    monkeypatch.setattr(monitor, "subprocess", _fake_subprocess(check_output=check_output))
    assert mon._get_cpu_model_windows() == "AMD Ryzen 7"


def test_cpu_model_windows_winreg_raises_then_powershell(monkeypatch):
    """注册表异常时回退到 PowerShell。"""
    mon = ResourceMonitor()
    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda *a: (_ for _ in ()).throw(OSError("no key")),
        QueryValueEx=lambda k, n: ("", 1),
        CloseKey=lambda k: None,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(check_output=lambda args, **k: "PS CPU"),
    )
    assert mon._get_cpu_model_windows() == "PS CPU"


def test_cpu_model_windows_powershell_fails_then_wmic(monkeypatch):
    """PowerShell 失败时回退到 wmic。"""
    mon = ResourceMonitor()
    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda *a: (_ for _ in ()).throw(OSError("no key")),
        QueryValueEx=lambda k, n: ("", 1),
        CloseKey=lambda k: None,
    ))

    def check_output(args, **kwargs):
        if args[0] == "powershell":
            raise RuntimeError("no ps")
        assert args[0] == "wmic"
        return "Name\nIntel i7-9700\n"

    monkeypatch.setattr(monitor, "subprocess", _fake_subprocess(check_output=check_output))
    assert mon._get_cpu_model_windows() == "Intel i7-9700"


def test_cpu_model_windows_all_fail_returns_unknown(monkeypatch):
    """注册表 / PowerShell / wmic 全失败时返回 Unknown CPU。"""
    mon = ResourceMonitor()
    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda *a: (_ for _ in ()).throw(OSError("no key")),
        QueryValueEx=lambda k, n: ("", 1),
        CloseKey=lambda k: None,
    ))
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(check_output=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    assert mon._get_cpu_model_windows() == "Unknown CPU"


def test_cpu_model_linux_via_lscpu(monkeypatch):
    """Linux 优先解析 lscpu 输出。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(check_output=lambda *a, **k: "Model name  : AMD EPYC 7B12\n"),
    )
    assert mon._get_cpu_model_linux() == "AMD EPYC 7B12"


def test_cpu_model_linux_lscpu_fails_then_proc_cpuinfo(monkeypatch):
    """lscpu 失败时回退读 /proc/cpuinfo。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(check_output=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no lscpu"))),
    )

    class _FakeFile:
        def __enter__(self):
            return iter(["processor\t: 0\n", "model name\t: Intel Xeon Gold\n"])

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(builtins, "open", lambda *a, **k: _FakeFile())
    assert mon._get_cpu_model_linux() == "Intel Xeon Gold"


def test_cpu_model_linux_all_fail_returns_unknown(monkeypatch):
    """lscpu 与 /proc/cpuinfo 都不可用时返回 Unknown CPU。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(check_output=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no lscpu"))),
    )
    monkeypatch.setattr(
        builtins, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("no procfs"))
    )
    assert mon._get_cpu_model_linux() == "Unknown CPU"


# ==================== _get_torch ====================


def test_get_torch_reflects_sys_modules(monkeypatch):
    """_get_torch 直接读 sys.modules，不做真实 import。"""
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert _get_torch() is None

    fake_torch = types.SimpleNamespace(name="fake-torch")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _get_torch() is fake_torch


# ==================== GPU 显存（异步，带缓存） ====================


def test_gpu_memory_async_cache_hit(monkeypatch):
    """缓存未过期时直接返回缓存，不触发下游读取。"""
    mon = ResourceMonitor()
    mon._gpu_memory_cache = (11, 22)
    mon._gpu_memory_cache_time = 100.0
    monkeypatch.setattr(monitor, "time", _fake_time(100.2))  # 差值 0.2 < TTL 0.5

    called = []

    async def _should_not_call():
        called.append(1)
        return (99, 99)

    monkeypatch.setattr(mon, "_fetch_gpu_memory_async", _should_not_call)
    assert asyncio.run(mon.get_gpu_memory_usage_async()) == (11, 22)
    assert called == []


def test_gpu_memory_async_cache_miss_updates_cache(monkeypatch):
    """缓存过期时重新读取并刷新缓存。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "time", _fake_time(200.0))

    async def _fetch():
        return (33, 66)

    monkeypatch.setattr(mon, "_fetch_gpu_memory_async", _fetch)
    assert asyncio.run(mon.get_gpu_memory_usage_async()) == (33, 66)
    assert mon._gpu_memory_cache == (33, 66)
    assert mon._gpu_memory_cache_time == 200.0


def test_gpu_memory_async_fetch_none_keeps_cache_empty(monkeypatch):
    """下游返回 None 时不写缓存。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "time", _fake_time(300.0))

    async def _fetch():
        return None

    monkeypatch.setattr(mon, "_fetch_gpu_memory_async", _fetch)
    assert asyncio.run(mon.get_gpu_memory_usage_async()) is None
    assert mon._gpu_memory_cache is None


def test_fetch_gpu_memory_async_via_nvml():
    """NVML 可用时按字节换算成 MB。"""
    mon = _nvml_monitor(memory_used=3 * MiB, memory_total=12 * MiB)
    assert asyncio.run(mon._fetch_gpu_memory_async()) == (3, 12)


def test_fetch_gpu_memory_async_nvml_force_pressure():
    """force_pressure 时显存用量被改写为总量的 92%。"""
    mon = _nvml_monitor(memory_used=1 * MiB, memory_total=10 * MiB)
    mon.force_pressure = True
    assert asyncio.run(mon._fetch_gpu_memory_async()) == (9, 10)


def test_fetch_gpu_memory_async_nvml_error_falls_back_to_smi(monkeypatch):
    """NVML 抛错时降级到 nvidia-smi。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace(
        nvmlDeviceGetMemoryInfo=lambda h: (_ for _ in ()).throw(RuntimeError("nvml boom"))
    )
    mon._nvidia_smi_path = "nvidia-smi"

    async def fake_run(args, *, timeout, cwd=None, env=None):
        return (0, b"1024, 8192\n", b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_memory_async()) == (1024, 8192)


def test_fetch_gpu_memory_async_smi_force_pressure(monkeypatch):
    """nvidia-smi 路径同样支持 force_pressure。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    mon.force_pressure = True

    async def fake_run(args, *, timeout, cwd=None, env=None):
        return (0, b"100, 1000", b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_memory_async()) == (920, 1000)


def test_fetch_gpu_memory_async_smi_resolves_path(monkeypatch):
    """nvidia-smi 路径未缓存时会先解析。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = None
    monkeypatch.setattr(mon, "_resolve_nvidia_smi_path", lambda: "/fake/nvidia-smi")

    async def fake_run(args, *, timeout, cwd=None, env=None):
        assert args[0] == "/fake/nvidia-smi"
        return (0, b"5, 10", b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_memory_async()) == (5, 10)
    assert mon._nvidia_smi_path == "/fake/nvidia-smi"


@pytest.mark.parametrize("payload", [b"", b"garbage-no-comma", b"notint, also-not"])
def test_fetch_gpu_memory_async_smi_malformed(monkeypatch, payload):
    """nvidia-smi 输出畸形（空 / 无逗号 / 非整数）时返回 None。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"

    async def fake_run(args, *, timeout, cwd=None, env=None):
        return (0, payload, b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_memory_async()) is None


def test_fetch_gpu_memory_async_smi_raises(monkeypatch):
    """nvidia-smi 子进程异常时返回 None。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", _boom_async)
    assert asyncio.run(mon._fetch_gpu_memory_async()) is None


# ==================== GPU 显存（同步） ====================


def test_get_gpu_memory_usage_via_nvml():
    """同步接口走 NVML 返回 (used_mb, total_mb)。"""
    mon = _nvml_monitor(memory_used=5 * MiB, memory_total=20 * MiB)
    assert mon.get_gpu_memory_usage() == (5, 20)


def test_get_gpu_memory_usage_nvml_error_returns_none():
    """同步接口 NVML 异常时返回 None（不做 nvidia-smi 降级）。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace(
        nvmlDeviceGetMemoryInfo=lambda h: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert mon.get_gpu_memory_usage() is None


def test_get_gpu_memory_usage_no_nvml_returns_none():
    """NVML 不可用且已标记失败时返回 None。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    assert mon.get_gpu_memory_usage() is None


def test_get_gpu_usage_percent_normal():
    """显存占比 = used / total * 100。"""
    mon = _nvml_monitor(memory_used=25 * MiB, memory_total=100 * MiB)
    assert mon.get_gpu_usage_percent() == 25.0


def test_get_gpu_usage_percent_zero_total():
    """总量为 0 时返回 0，避免除零。"""
    mon = _nvml_monitor(memory_used=0, memory_total=0)
    assert mon.get_gpu_usage_percent() == 0


def test_get_gpu_usage_percent_no_info():
    """拿不到显存信息时返回 None。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    assert mon.get_gpu_usage_percent() is None


# ==================== GPU 进程使用（异步，带缓存） ====================


def test_gpu_process_async_cache_hit(monkeypatch):
    """进程缓存未过期时直接返回缓存。"""
    mon = ResourceMonitor()
    mon._gpu_process_cache = {1: 2}
    mon._gpu_process_cache_time = 100.0
    monkeypatch.setattr(monitor, "time", _fake_time(100.1))

    called = []

    async def _should_not_call():
        called.append(1)
        return {9: 9}

    monkeypatch.setattr(mon, "_fetch_gpu_process_usage_async", _should_not_call)
    assert asyncio.run(mon.get_gpu_compute_process_usage_async()) == {1: 2}
    assert called == []


def test_gpu_process_async_cache_miss_updates_cache(monkeypatch):
    """进程缓存过期时重新读取并刷新。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "time", _fake_time(500.0))

    async def _fetch():
        return {7: 8}

    monkeypatch.setattr(mon, "_fetch_gpu_process_usage_async", _fetch)
    assert asyncio.run(mon.get_gpu_compute_process_usage_async()) == {7: 8}
    assert mon._gpu_process_cache == {7: 8}
    assert mon._gpu_process_cache_time == 500.0


def test_gpu_process_async_fetch_none_keeps_cache_empty(monkeypatch):
    """下游返回 None 时不写进程缓存。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "time", _fake_time(600.0))

    async def _fetch():
        return None

    monkeypatch.setattr(mon, "_fetch_gpu_process_usage_async", _fetch)
    assert asyncio.run(mon.get_gpu_compute_process_usage_async()) is None
    assert mon._gpu_process_cache is None


def test_fetch_gpu_process_async_via_nvml():
    """NVML 可用时返回其进程占用字典。"""
    mon = _nvml_monitor()
    assert asyncio.run(mon._fetch_gpu_process_usage_async()) == {}


def test_fetch_gpu_process_async_nvml_error_falls_back(monkeypatch):
    """NVML 辅助函数抛错时被捕获并降级到 nvidia-smi。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    # 返回真值但不可迭代 -> 触发 TypeError，被外层 except 捕获
    mon._nvml = types.SimpleNamespace(
        nvmlDeviceGetComputeRunningProcesses=lambda h: 1
    )
    mon._nvidia_smi_path = "nvidia-smi"

    async def fake_run(args, *, timeout, cwd=None, env=None):
        return (0, b"111, 222\n", b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_process_usage_async()) == {111: 222}


def test_fetch_gpu_process_async_smi_resolves_path(monkeypatch):
    """异步路径下 smi 路径未缓存时先解析。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = None
    monkeypatch.setattr(mon, "_resolve_nvidia_smi_path", lambda: "/fake/nvidia-smi")

    async def fake_run(args, *, timeout, cwd=None, env=None):
        assert args[0] == "/fake/nvidia-smi"
        return (0, b"11, 22\n", b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_process_usage_async()) == {11: 22}
    assert mon._nvidia_smi_path == "/fake/nvidia-smi"


def test_fetch_gpu_process_async_smi_empty(monkeypatch):
    """nvidia-smi 无输出时返回空字典。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"

    async def fake_run(args, *, timeout, cwd=None, env=None):
        return (0, b"\n  \n", b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_process_usage_async()) == {}


def test_fetch_gpu_process_async_smi_parses_and_skips_invalid(monkeypatch):
    """解析有效行，跳过无逗号 / 非整数 / 非法数值行。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    payload = b"no-comma-line\nabc, 100\n200, xyz\n-1, 50\n0, 50\n300, -5\n400, 600\n"

    async def fake_run(args, *, timeout, cwd=None, env=None):
        return (0, payload, b"")

    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", fake_run)
    assert asyncio.run(mon._fetch_gpu_process_usage_async()) == {400: 600}


def test_fetch_gpu_process_async_smi_raises(monkeypatch):
    """nvidia-smi 异常时返回 None。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    monkeypatch.setattr(monitor, "run_subprocess_with_timeout", _boom_async)
    assert asyncio.run(mon._fetch_gpu_process_usage_async()) is None


# ==================== GPU 进程使用（同步） ====================


def test_get_gpu_process_usage_via_nvml():
    """同步接口 NVML 可用时返回进程占用字典。"""
    mon = _nvml_monitor()
    assert mon.get_gpu_compute_process_usage() == {}


def test_get_gpu_process_usage_nvml_error_falls_back(monkeypatch):
    """NVML 辅助抛错时降级到 subprocess.run 解析。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace(nvmlDeviceGetComputeRunningProcesses=lambda h: 1)
    mon._nvidia_smi_path = "nvidia-smi"

    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(run=lambda *a, **k: _FakeCompleted(0, "555, 666\n")),
    )
    assert mon.get_gpu_compute_process_usage() == {555: 666}


def test_get_gpu_process_usage_smi_empty(monkeypatch):
    """同步 nvidia-smi 无输出时返回空字典。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    monkeypatch.setattr(
        monitor, "subprocess", _fake_subprocess(run=lambda *a, **k: _FakeCompleted(0, "  \n"))
    )
    assert mon.get_gpu_compute_process_usage() == {}


def test_get_gpu_process_usage_smi_parses_and_skips_invalid(monkeypatch):
    """同步路径同样跳过无逗号 / 非整数 / 非法数值行。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    out = "no-comma\nabc, 1\n2, xyz\n-3, 4\n5, -6\n7, 8\n"
    monkeypatch.setattr(
        monitor, "subprocess", _fake_subprocess(run=lambda *a, **k: _FakeCompleted(0, out))
    )
    assert mon.get_gpu_compute_process_usage() == {7: 8}


def test_get_gpu_process_usage_smi_raises(monkeypatch):
    """同步 nvidia-smi 异常时返回 None。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = "nvidia-smi"
    monkeypatch.setattr(
        monitor, "subprocess", _fake_subprocess(run=lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    )
    assert mon.get_gpu_compute_process_usage() is None


def test_get_gpu_process_usage_resolves_smi_path(monkeypatch):
    """未缓存 smi 路径时先解析，解析结果为 None 时回退到裸命令名。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    mon._nvidia_smi_path = None
    monkeypatch.setattr(mon, "_resolve_nvidia_smi_path", lambda: None)

    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        return _FakeCompleted(0, "")

    monkeypatch.setattr(monitor, "subprocess", _fake_subprocess(run=fake_run))
    assert mon.get_gpu_compute_process_usage() == {}
    assert seen["args"][0] == "nvidia-smi"


# ==================== 当前进程 GPU 占用 ====================


def test_current_process_gpu_used_mb_pid_parse_fails():
    """当前进程 pid 无法转 int 时返回 None。"""
    mon = ResourceMonitor()
    mon._process = _FakeProcess(pid_raises=True)
    assert mon.get_current_process_gpu_used_mb({1: 1}) is None


def test_current_process_gpu_used_mb_usage_none(monkeypatch):
    """拿不到 GPU 进程使用信息时返回 None。"""
    mon = ResourceMonitor()
    mon._process = _FakeProcess(pid=10)
    monkeypatch.setattr(mon, "get_gpu_compute_process_usage", lambda: None)
    assert mon.get_current_process_gpu_used_mb() is None


def test_current_process_gpu_used_mb_sums_self_and_children():
    """累加自身与全部子进程的显存占用。"""
    children = [_FakeProcess(pid=101), _FakeProcess(pid=102)]
    mon = ResourceMonitor()
    mon._process = _FakeProcess(pid=100, children=children)
    assert mon.get_current_process_gpu_used_mb({100: 10, 101: 20, 102: 30}) == 60


def test_current_process_gpu_used_mb_child_pid_unparseable():
    """子进程 pid 无法解析时跳过该子进程。"""
    children = [_FakeProcess(pid_raises=True), _FakeProcess(pid=202)]
    mon = ResourceMonitor()
    mon._process = _FakeProcess(pid=200, children=children)
    assert mon.get_current_process_gpu_used_mb({200: 5, 202: 7}) == 12


def test_current_process_gpu_used_mb_children_raises():
    """枚举子进程失败时仅统计自身。"""
    mon = ResourceMonitor()
    mon._process = _FakeProcess(pid=300, children_raises=True)
    assert mon.get_current_process_gpu_used_mb({300: 9}) == 9


def test_current_process_gpu_used_mb_usage_get_raises():
    """usage 取值抛错时被捕获，结果为 0。"""

    class _BadUsage:
        def get(self, *a):
            raise RuntimeError("get boom")

    mon = ResourceMonitor()
    mon._process = _FakeProcess(pid=400, children=[])
    assert mon.get_current_process_gpu_used_mb(_BadUsage()) == 0


# ==================== GPU 型号 ====================


def test_get_gpu_model_returns_cache():
    """已缓存时直接返回。"""
    mon = ResourceMonitor()
    mon._gpu_model = "Cached GPU"
    assert mon.get_gpu_model() == "Cached GPU"


def test_get_gpu_model_via_torch(monkeypatch):
    """torch.cuda 可用时优先用 torch 取型号。"""
    mon = ResourceMonitor()
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True, get_device_name=lambda i: "Fake GPU 0")
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert mon.get_gpu_model() == "Fake GPU 0"


def test_get_gpu_model_torch_raises_falls_to_smi(monkeypatch):
    """torch 取型号抛错时回退到 nvidia-smi。"""
    mon = ResourceMonitor()
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            get_device_name=lambda i: (_ for _ in ()).throw(RuntimeError("torch boom")),
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(run=lambda *a, **k: _FakeCompleted(0, "SMI GPU\n")),
    )
    assert mon.get_gpu_model() == "SMI GPU"


def test_get_gpu_model_torch_unavailable_then_smi(monkeypatch):
    """torch 不可用时跳过 torch 分支，走 nvidia-smi。"""
    mon = ResourceMonitor()
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(run=lambda *a, **k: _FakeCompleted(0, "SMI GPU\n")),
    )
    assert mon.get_gpu_model() == "SMI GPU"


def test_get_gpu_model_smi_fails_then_powershell(monkeypatch):
    """nvidia-smi 非零退出时回退到 Windows PowerShell。"""
    mon = ResourceMonitor()
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt"))

    def fake_run(args, **kwargs):
        return _FakeCompleted(1, "")

    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(run=fake_run, check_output=lambda *a, **k: "  PS GPU  \nsecond\n"),
    )
    assert mon.get_gpu_model() == "PS GPU"


def test_get_gpu_model_all_fail_returns_unknown(monkeypatch):
    """torch / nvidia-smi / PowerShell 全失败时返回 Unknown GPU。"""
    mon = ResourceMonitor()
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt"))
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(
            run=lambda *a, **k: (_ for _ in ()).throw(OSError("no smi")),
            check_output=lambda *a, **k: (_ for _ in ()).throw(OSError("no ps")),
        ),
    )
    assert mon.get_gpu_model() == "Unknown GPU"


def test_get_gpu_model_non_nt_returns_unknown(monkeypatch):
    """非 Windows 且前序全部失败时直接返回 Unknown GPU。"""
    mon = ResourceMonitor()
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(monitor, "os", _FakeOS(name="posix"))
    monkeypatch.setattr(
        monitor,
        "subprocess",
        _fake_subprocess(run=lambda *a, **k: (_ for _ in ()).throw(OSError("no smi"))),
    )
    assert mon.get_gpu_model() == "Unknown GPU"


# ==================== NVML 初始化 ====================


def test_ensure_nvml_handle_present_returns_true():
    """已有 handle 时直接返回 True。"""
    mon = _nvml_monitor()
    assert mon._ensure_nvml() is True


def test_ensure_nvml_failed_flag_returns_false():
    """已标记失败时直接返回 False，不再尝试导入。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    assert mon._ensure_nvml() is False


def test_ensure_nvml_import_success(monkeypatch):
    """pynvml 可导入时完成初始化并缓存 handle。"""
    mon = ResourceMonitor()
    handle = object()
    fake_pynvml = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlDeviceGetHandleByIndex=lambda i: handle,
    )
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)

    assert mon._ensure_nvml() is True
    assert mon._nvml is fake_pynvml
    assert mon._nvml_handle is handle


def test_ensure_nvml_import_failure(monkeypatch):
    """pynvml 初始化抛错时标记失败并清理状态。"""
    mon = ResourceMonitor()
    fake_pynvml = types.SimpleNamespace(
        nvmlInit=lambda: (_ for _ in ()).throw(RuntimeError("no driver")),
    )
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)

    assert mon._ensure_nvml() is False
    assert mon._nvml_failed is True
    assert mon._nvml is None
    assert mon._nvml_handle is None


# ==================== NVML 进程解析 ====================


def test_nvml_process_usage_no_handle_returns_empty():
    """handle 为空时返回空字典。"""
    mon = ResourceMonitor()
    assert mon._get_nvml_process_usage_mb() == {}


def test_nvml_process_usage_no_methods_returns_empty():
    """nvml 对象无任何读取方法时返回空字典。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace()
    assert mon._get_nvml_process_usage_mb() == {}


def test_nvml_process_usage_fn_raises_and_falsy_procs():
    """读取函数抛错或返回空时被忽略。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace(
        nvmlDeviceGetComputeRunningProcesses=lambda h: (_ for _ in ()).throw(RuntimeError("boom")),
        nvmlDeviceGetComputeRunningProcesses_v2=lambda h: None,
        nvmlDeviceGetGraphicsRunningProcesses=lambda h: [],
        nvmlDeviceGetGraphicsRunningProcesses_v2=lambda h: [],
    )
    assert mon._get_nvml_process_usage_mb() == {}


def test_nvml_process_usage_skips_invalid_entries():
    """非法 pid / 负内存 / 非整数内存都被规整或跳过。"""
    procs = [
        types.SimpleNamespace(pid="abc", usedGpuMemory=1),        # pid 非整数 -> 跳过
        types.SimpleNamespace(pid=0, usedGpuMemory=1),            # pid <= 0 -> 跳过
        types.SimpleNamespace(pid=None, usedGpuMemory=1),         # pid None -> 跳过
        types.SimpleNamespace(pid=501, usedGpuMemory="xyz"),      # 内存非整数 -> 0 -> 不写
        types.SimpleNamespace(pid=502, usedGpuMemory=-100),       # 负内存 -> 0 -> 不写
        types.SimpleNamespace(pid=503, usedGpuMemory=2 * MiB),    # 正常 -> 2
    ]
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace(
        nvmlDeviceGetComputeRunningProcesses=lambda h: procs,
        nvmlDeviceGetComputeRunningProcesses_v2=lambda h: [],
        nvmlDeviceGetGraphicsRunningProcesses=lambda h: [],
        nvmlDeviceGetGraphicsRunningProcesses_v2=lambda h: [],
    )
    assert mon._get_nvml_process_usage_mb() == {503: 2}


def test_nvml_process_usage_keeps_max_across_sources():
    """同一 pid 出现在多个来源时保留最大值。"""
    mon = ResourceMonitor()
    mon._nvml_handle = object()
    mon._nvml = types.SimpleNamespace(
        nvmlDeviceGetComputeRunningProcesses=lambda h: [
            types.SimpleNamespace(pid=600, usedGpuMemory=1 * MiB)
        ],
        nvmlDeviceGetComputeRunningProcesses_v2=lambda h: [],
        nvmlDeviceGetGraphicsRunningProcesses=lambda h: [
            types.SimpleNamespace(pid=600, usedGpuMemory=4 * MiB)
        ],
        nvmlDeviceGetGraphicsRunningProcesses_v2=lambda h: [
            types.SimpleNamespace(pid=600, usedGpuMemory=2 * MiB)
        ],
    )
    assert mon._get_nvml_process_usage_mb() == {600: 4}


# ==================== nvidia-smi 路径解析 ====================


def test_resolve_nvidia_smi_path_from_which(monkeypatch):
    """shutil.which 命中时直接返回。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(
        monitor, "shutil", types.SimpleNamespace(which=lambda name: "/usr/bin/nvidia-smi")
    )
    assert mon._resolve_nvidia_smi_path() == "/usr/bin/nvidia-smi"


def test_resolve_nvidia_smi_path_which_raises(monkeypatch):
    """which 抛错时继续走候选路径。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(
        monitor,
        "shutil",
        types.SimpleNamespace(which=lambda name: (_ for _ in ()).throw(OSError("boom"))),
    )
    monkeypatch.setattr(
        monitor, "os", _FakeOS(name="posix", existing={"/usr/local/bin/nvidia-smi"})
    )
    assert mon._resolve_nvidia_smi_path() == "/usr/local/bin/nvidia-smi"


def test_resolve_nvidia_smi_path_windows_candidate(monkeypatch):
    """Windows 下命中候选路径。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "shutil", types.SimpleNamespace(which=lambda name: None))
    target = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", existing={target}))
    assert mon._resolve_nvidia_smi_path() == target


def test_resolve_nvidia_smi_path_none_found(monkeypatch):
    """所有候选都不存在时返回 None。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "shutil", types.SimpleNamespace(which=lambda name: None))
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", existing=set()))
    assert mon._resolve_nvidia_smi_path() is None


def test_resolve_nvidia_smi_path_exists_raises(monkeypatch):
    """检查候选路径抛错时被捕获并返回 None。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "shutil", types.SimpleNamespace(which=lambda name: None))
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", exists_raises=True))
    assert mon._resolve_nvidia_smi_path() is None


# ==================== 磁盘 ====================


def test_get_disk_usage_primary(monkeypatch):
    """主路径可用时返回 cwd 所在盘的使用率。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", cwd="C:/work", drive="C:"))
    monkeypatch.setattr(
        monitor, "psutil", _fake_psutil(disk=lambda path: types.SimpleNamespace(percent=42.0))
    )
    assert mon.get_disk_usage() == 42.0


def test_get_disk_usage_fallback_windows_drive(monkeypatch):
    """主路径失败时，Windows 下按盘符重试。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", cwd="C:/work", drive="C:"))

    def disk(path):
        if path == "C:/work":
            raise OSError("primary boom")
        assert path == "C:\\"
        return types.SimpleNamespace(percent=55.0)

    monkeypatch.setattr(monitor, "psutil", _fake_psutil(disk=disk))
    assert mon.get_disk_usage() == 55.0


def test_get_disk_usage_fallback_posix_root(monkeypatch):
    """主路径失败时，非 Windows 下回退到根目录。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="posix", cwd="/work", drive=""))

    def disk(path):
        if path == "/work":
            raise OSError("primary boom")
        assert path == "/"
        return types.SimpleNamespace(percent=66.0)

    monkeypatch.setattr(monitor, "psutil", _fake_psutil(disk=disk))
    assert mon.get_disk_usage() == 66.0


def test_get_disk_usage_fallback_no_drive_returns_zero(monkeypatch):
    """主路径失败且无法解析盘符时返回 0.0。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", cwd="/work", drive=""))
    monkeypatch.setattr(monitor, "psutil", _fake_psutil(disk_raises=True))
    assert mon.get_disk_usage() == 0.0


def test_get_disk_usage_all_paths_fail_returns_zero(monkeypatch):
    """主路径与备用路径都失败时返回 0.0。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", cwd="C:/work", drive="C:"))
    monkeypatch.setattr(monitor, "psutil", _fake_psutil(disk_raises=True))
    assert mon.get_disk_usage() == 0.0


# ==================== 资源状态 ====================


def _arm_check(mon, monkeypatch, now=1000.0):
    """让 get_resource_state 通过节流闸门。"""
    mon._last_check_time = 0.0
    monkeypatch.setattr(monitor, "time", _fake_time(now))


def test_get_resource_state_throttled_returns_normal(monkeypatch):
    """距上次检查不足间隔时直接返回 NORMAL。"""
    mon = ResourceMonitor()
    mon._last_check_time = 100.0
    monkeypatch.setattr(monitor, "time", _fake_time(100.2))
    assert mon.get_resource_state(ResourceType.MEMORY) is ResourceSeverity.NORMAL
    assert mon._last_check_time == 100.0  # 未刷新


def test_get_resource_state_missing_threshold_returns_normal(monkeypatch):
    """阈值缺失时返回 NORMAL。"""
    mon = ResourceMonitor()
    mon._thresholds.pop(ResourceType.DISK)
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(ResourceType.DISK) is ResourceSeverity.NORMAL


def test_get_resource_state_unknown_type_returns_normal(monkeypatch):
    """非四类资源的自定义键走最终兜底分支，返回 NORMAL。"""
    mon = ResourceMonitor()
    sentinel = "future-resource"
    mon._thresholds[sentinel] = ResourceThreshold(1.0, 2.0, 3.0)
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(sentinel) is ResourceSeverity.NORMAL


@pytest.mark.parametrize(
    "percent, expected",
    [
        (10.0, ResourceSeverity.NORMAL),
        (70.0, ResourceSeverity.WARNING),
        (85.0, ResourceSeverity.CRITICAL),
        (95.0, ResourceSeverity.EMERGENCY),
    ],
)
def test_get_resource_state_memory_tiers(monkeypatch, percent, expected):
    """内存阈值各档位边界（70/85/95 取 >=）。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "psutil", _fake_psutil(vm_percent=percent))
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(ResourceType.MEMORY) is expected


@pytest.mark.parametrize(
    "cpu, expected",
    [
        (69.9, ResourceSeverity.NORMAL),
        (75.0, ResourceSeverity.WARNING),
        (90.0, ResourceSeverity.CRITICAL),
        (99.0, ResourceSeverity.EMERGENCY),
    ],
)
def test_get_resource_state_cpu_tiers(monkeypatch, cpu, expected):
    """CPU 阈值各档位。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "psutil", _fake_psutil(cpu=cpu))
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(ResourceType.CPU) is expected


def test_get_resource_state_disk(monkeypatch):
    """磁盘类型走 get_disk_usage。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "os", _FakeOS(name="nt", cwd="C:/work", drive="C:"))
    monkeypatch.setattr(
        monitor, "psutil", _fake_psutil(disk=lambda path: types.SimpleNamespace(percent=88.0))
    )
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(ResourceType.DISK) is ResourceSeverity.CRITICAL


def test_get_resource_state_gpu_memory_no_info(monkeypatch):
    """GPU 显存不可用时返回 NORMAL。"""
    mon = ResourceMonitor()
    mon._nvml_failed = True
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(ResourceType.GPU_MEMORY) is ResourceSeverity.NORMAL


def test_get_resource_state_gpu_memory_ok(monkeypatch):
    """GPU 显存可用时按占比判定档位。"""
    mon = _nvml_monitor(memory_used=80 * MiB, memory_total=100 * MiB)
    _arm_check(mon, monkeypatch)
    assert mon.get_resource_state(ResourceType.GPU_MEMORY) is ResourceSeverity.WARNING


def test_is_resource_pressure_true_and_false(monkeypatch):
    """WARNING 及以上视为压力；NORMAL 不算压力。"""
    mon = ResourceMonitor()
    monkeypatch.setattr(monitor, "psutil", _fake_psutil(vm_percent=90.0))
    _arm_check(mon, monkeypatch)
    assert mon.is_resource_pressure(ResourceType.MEMORY) is True

    monkeypatch.setattr(monitor, "psutil", _fake_psutil(vm_percent=10.0))
    _arm_check(mon, monkeypatch)
    assert mon.is_resource_pressure(ResourceType.MEMORY) is False
