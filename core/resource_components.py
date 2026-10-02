#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源管理基础组件
"""

from __future__ import annotations
from core.utils.logger import get_logger


import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

import psutil
import sys

from core.contracts import DeviceType, ModelRuntimeState, ResourceSeverity, ResourceType
from core.utils.async_subprocess import run_subprocess_with_timeout

logger = get_logger(__name__)


def _get_torch():
    """延迟导入 torch，避免启动时加载 2~5 秒"""
    return sys.modules.get("torch")


class ResourcePriority(Enum):
    """资源优先级枚举"""

    HIGH = 100
    MEDIUM = 50
    LOW = 10
    IDLE = 1


ResourceState = ResourceSeverity


@dataclass
class ResourceThreshold:
    """资源阈值配置"""

    warning: float
    critical: float
    emergency: float


class ResourceMonitor:
    """资源监控器"""

    def __init__(self):
        self._thresholds = {
            ResourceType.MEMORY: ResourceThreshold(70.0, 85.0, 95.0),
            ResourceType.CPU: ResourceThreshold(70.0, 85.0, 95.0),
            ResourceType.GPU_MEMORY: ResourceThreshold(70.0, 85.0, 95.0),
            ResourceType.DISK: ResourceThreshold(70.0, 85.0, 95.0),
        }
        self._process = psutil.Process()
        self._last_check_time = 0
        self._check_interval = 1.0
        self.force_pressure = False
        self._nvidia_smi_path: Optional[str] = None
        self._nvml = None
        self._nvml_handle = None
        self._nvml_failed = False

    def set_threshold(self, resource_type: ResourceType, threshold: ResourceThreshold):
        self._thresholds[resource_type] = threshold

    def get_memory_usage(self) -> float:
        return psutil.virtual_memory().percent

    def get_process_memory_usage(self) -> int:
        return self._process.memory_info().rss // (1024 * 1024)

    def get_cpu_usage(self) -> float:
        return psutil.cpu_percent(interval=None)

    async def get_gpu_memory_usage_async(self) -> Optional[tuple[int, int]]:
        try:
            if self._ensure_nvml():
                info = self._nvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                used = int(int(info.used) // (1024 * 1024))
                total = int(int(info.total) // (1024 * 1024))
                if self.force_pressure:
                    used = int(total * 0.92)
                return (used, total)
        except Exception:
            pass

        if self._nvidia_smi_path is None:
            self._nvidia_smi_path = self._resolve_nvidia_smi_path()

        try:
            exe = self._nvidia_smi_path or "nvidia-smi"
            # P0-18: 用 run_subprocess_with_timeout 统一处理超时/异常时的子进程清理
            _, stdout, _ = await run_subprocess_with_timeout(
                [exe, "--query-gpu=memory.used,memory.total",
                 "--format=csv,nounits,noheader"],
                timeout=2.0,
            )
            output = stdout.decode().strip()
            first_line = output.splitlines()[0].strip() if output else ""
            if first_line and "," in first_line:
                used_str, total_str = [part.strip() for part in first_line.split(",", 1)]
                used = int(used_str)
                total = int(total_str)
                if self.force_pressure:
                    used = int(total * 0.92)
                return (used, total)
        except Exception as e:
            logger.debug(f"Async nvidia-smi failed: {e}")
        return None

    def get_gpu_memory_usage(self) -> Optional[tuple[int, int]]:
        try:
            if self._ensure_nvml():
                info = self._nvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                return (
                    int(info.used // (1024 * 1024)),
                    int(info.total // (1024 * 1024)),
                )
        except Exception:
            pass
        return None

    def get_gpu_compute_process_usage(self) -> Optional[Dict[int, int]]:
        try:
            if self._ensure_nvml():
                return self._get_nvml_process_usage_mb()
        except Exception:
            pass

        if self._nvidia_smi_path is None:
            self._nvidia_smi_path = self._resolve_nvidia_smi_path()

        try:
            exe = self._nvidia_smi_path or "nvidia-smi"
            result = subprocess.run(
                [
                    exe,
                    "--query-compute-apps=pid,used_memory",
                    "--format=csv,nounits,noheader",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=1.5,
            )
            lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            if not lines:
                return {}

            data: Dict[int, int] = {}
            for line in lines:
                if "," not in line:
                    continue
                pid_str, mem_str = [part.strip() for part in line.split(",", 1)]
                try:
                    pid = int(pid_str)
                    mem = int(mem_str)
                except Exception:
                    continue
                if pid <= 0 or mem < 0:
                    continue
                data[pid] = int(mem)
            return data
        except Exception:
            return None

    async def get_gpu_compute_process_usage_async(self) -> Optional[Dict[int, int]]:
        try:
            if self._ensure_nvml():
                return self._get_nvml_process_usage_mb()
        except Exception:
            pass

        if self._nvidia_smi_path is None:
            self._nvidia_smi_path = self._resolve_nvidia_smi_path()

        try:
            exe = self._nvidia_smi_path or "nvidia-smi"
            # P0-18: 用 run_subprocess_with_timeout 统一处理超时/异常时的子进程清理
            _, stdout, _ = await run_subprocess_with_timeout(
                [exe, "--query-compute-apps=pid,used_memory",
                 "--format=csv,nounits,noheader"],
                timeout=1.6,
            )
            text = (stdout or b"").decode(errors="ignore")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                return {}

            data: Dict[int, int] = {}
            for line in lines:
                if "," not in line:
                    continue
                pid_str, mem_str = [part.strip() for part in line.split(",", 1)]
                try:
                    pid = int(pid_str)
                    mem = int(mem_str)
                except Exception:
                    continue
                if pid <= 0 or mem < 0:
                    continue
                data[pid] = int(mem)
            return data
        except Exception:
            return None

    def _ensure_nvml(self) -> bool:
        if self._nvml_handle is not None:
            return True
        if bool(self._nvml_failed):
            return False
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return True
        except Exception:
            self._nvml_failed = True
            self._nvml = None
            self._nvml_handle = None
            return False

    def _get_nvml_process_usage_mb(self) -> Dict[int, int]:
        if self._nvml_handle is None:
            return {}
        nvml = self._nvml
        if nvml is None:
            return {}

        out: Dict[int, int] = {}

        def _read(fn_name: str):
            fn = getattr(nvml, fn_name, None)
            if not callable(fn):
                return
            try:
                procs = fn(self._nvml_handle)
            except Exception:
                return
            if not procs:
                return
            for proc in procs:
                pid = getattr(proc, "pid", None)
                used = getattr(proc, "usedGpuMemory", None)
                try:
                    pid_i = int(pid)
                except Exception:
                    continue
                if pid_i <= 0:
                    continue
                try:
                    used_bytes = int(used)
                except Exception:
                    used_bytes = 0
                if used_bytes < 0:
                    used_bytes = 0
                used_mb = int(used_bytes // (1024 * 1024))
                prev = int(out.get(pid_i, 0) or 0)
                if used_mb > prev:
                    out[pid_i] = used_mb

        _read("nvmlDeviceGetComputeRunningProcesses")
        _read("nvmlDeviceGetComputeRunningProcesses_v2")
        _read("nvmlDeviceGetGraphicsRunningProcesses")
        _read("nvmlDeviceGetGraphicsRunningProcesses_v2")
        return out

    def get_current_process_gpu_used_mb(
        self, pid_usage: Optional[Dict[int, int]] = None
    ) -> Optional[int]:
        try:
            pid = int(self._process.pid)
        except Exception:
            return None

        usage = pid_usage if pid_usage is not None else self.get_gpu_compute_process_usage()
        if usage is None:
            return None

        pids = {pid}
        try:
            for child in self._process.children(recursive=True):
                try:
                    pids.add(int(child.pid))
                except Exception:
                    continue
        except Exception:
            pass

        total = 0
        for proc_id in pids:
            try:
                total += int(usage.get(int(proc_id), 0) or 0)
            except Exception:
                continue
        return int(total)

    def _resolve_nvidia_smi_path(self) -> Optional[str]:
        try:
            path = shutil.which("nvidia-smi")
            if path:
                return str(path)
        except Exception:
            pass

        if os.name == "nt":
            candidates = [
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            ]
        else:
            candidates = [
                "/usr/bin/nvidia-smi",
                "/usr/local/nvidia/bin/nvidia-smi",
                "/usr/local/bin/nvidia-smi",
            ]
        for candidate in candidates:
            try:
                if os.path.exists(candidate):
                    return str(candidate)
            except Exception:
                continue
        return None

    def get_gpu_usage_percent(self) -> Optional[float]:
        info = self.get_gpu_memory_usage()
        if info:
            used, total = info
            return (used / total) * 100 if total > 0 else 0
        return None

    def get_disk_usage(self) -> float:
        try:
            return psutil.disk_usage(os.getcwd()).percent
        except Exception:
            try:
                cwd = os.getcwd()
                if os.name == "nt":
                    drive = os.path.splitdrive(cwd)[0]
                    if drive:
                        return psutil.disk_usage(drive + "\\").percent
                else:
                    return psutil.disk_usage("/").percent
            except Exception:
                pass
        return 0.0

    def get_cpu_model(self) -> str:
        try:
            if os.name == "nt":
                try:
                    import winreg

                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                    )
                    model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    winreg.CloseKey(key)
                    if model:
                        return str(model).strip()
                except Exception:
                    pass

                try:
                    # P0-19: PowerShell 启动较慢，设置 timeout 避免阻塞
                    output = subprocess.check_output(
                        [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name",
                        ],
                        text=True,
                        timeout=10,
                    ).strip()
                    if output:
                        return output
                except Exception:
                    pass

                try:
                    # P0-19: wmic 在新 Windows 上已弃用，可能很慢
                    output = subprocess.check_output(
                        ["wmic", "cpu", "get", "name"], text=True, timeout=5
                    )
                    lines = output.strip().split("\n")
                    if len(lines) > 1:
                        return lines[1].strip()
                except Exception:
                    pass
            else:
                try:
                    output = subprocess.check_output(
                        ["lscpu"], text=True, stderr=subprocess.DEVNULL, timeout=5
                    )
                    for line in output.split("\n"):
                        if "Model name" in line and ":" in line:
                            return line.split(":")[1].strip()
                except Exception:
                    pass

                try:
                    with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                        for line in f:
                            if "model name" in line:
                                return line.split(":")[1].strip()
                except Exception:
                    pass
        except Exception:
            pass
        return "Unknown CPU"

    def get_gpu_model(self) -> str:
        _torch = _get_torch()
        if _torch and _torch.cuda.is_available():
            try:
                return _torch.cuda.get_device_name(0)
            except Exception:
                pass

        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        if os.name == "nt":
            try:
                # P0-19: PowerShell 启动较慢，设置 timeout 避免阻塞
                output = subprocess.check_output(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                    ],
                    text=True,
                    timeout=10,
                ).strip()
                if output:
                    return output.split("\n")[0].strip()
            except Exception:
                pass

        return "Unknown GPU"

    def get_resource_state(self, resource_type: ResourceType) -> ResourceState:
        current_time = time.time()
        if current_time - self._last_check_time < self._check_interval:
            return ResourceState.NORMAL

        self._last_check_time = current_time
        threshold = self._thresholds[resource_type]

        if resource_type == ResourceType.MEMORY:
            usage = self.get_memory_usage()
        elif resource_type == ResourceType.CPU:
            usage = self.get_cpu_usage()
        elif resource_type == ResourceType.GPU_MEMORY:
            usage = self.get_gpu_usage_percent()
            if usage is None:
                return ResourceState.NORMAL
        elif resource_type == ResourceType.DISK:
            usage = self.get_disk_usage()
        else:
            return ResourceState.NORMAL

        if usage >= threshold.emergency:
            return ResourceState.EMERGENCY
        if usage >= threshold.critical:
            return ResourceState.CRITICAL
        if usage >= threshold.warning:
            return ResourceState.WARNING
        return ResourceState.NORMAL

    def is_resource_pressure(self, resource_type: ResourceType) -> bool:
        state = self.get_resource_state(resource_type)
        return state in [
            ResourceState.WARNING,
            ResourceState.CRITICAL,
            ResourceState.EMERGENCY,
        ]


@dataclass
class ModelResource:
    """模型资源类"""

    model_id: str
    model_type: str
    priority: ResourcePriority
    load_func: Callable
    unload_func: Callable
    memory_usage_mb: int = 0
    vram_usage_mb: int = 0
    device: str = "CPU"
    offload_func: Optional[Callable] = None
    instance: Any = None
    is_loaded: bool = False
    is_offloaded: bool = False
    last_used_time: float = field(default_factory=time.time)
    usage_count: int = 0

    def update_usage(self):
        self.last_used_time = time.time()
        self.usage_count += 1

    @property
    def runtime_state(self) -> ModelRuntimeState:
        if bool(self.is_loaded):
            if bool(self.is_offloaded):
                return ModelRuntimeState.OFFLOADED
            return ModelRuntimeState.LOADED
        return ModelRuntimeState.UNLOADED

    @property
    def device_type(self) -> DeviceType:
        device = str(self.device or "").strip().lower()
        if device in {"gpu", "cuda"}:
            return DeviceType.GPU
        if device in {"cpu"}:
            return DeviceType.CPU
        return DeviceType.UNKNOWN

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "priority": getattr(self.priority, "name", str(self.priority)),
            "state": self.runtime_state.value,
            "device": self.device_type.value,
            "memory_usage_mb": int(self.memory_usage_mb or 0),
            "vram_usage_mb": int(self.vram_usage_mb or 0),
            "is_loaded": bool(self.is_loaded),
            "is_offloaded": bool(self.is_offloaded),
            "last_used_time": float(self.last_used_time or 0.0),
            "usage_count": int(self.usage_count or 0),
        }
