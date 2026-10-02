#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源监控模块
负责监控系统资源使用情况，包括内存、CPU、GPU等
"""


from core.utils.logger import get_logger
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple

import psutil

from core.contracts import ResourceType, ResourceSeverity
from core.utils.async_subprocess import run_subprocess_with_timeout

logger = get_logger(__name__)

# 类型别名
ResourceState = ResourceSeverity
GPUInfo = Tuple[int, int]  # (used_mb, total_mb)


def _get_torch():
    """延迟导入 torch，避免启动时加载 2~5 秒"""
    return sys.modules.get("torch")


class ResourceThreshold:
    """资源阈值配置"""
    
    __slots__ = ("warning", "critical", "emergency")
    
    def __init__(self, warning: float, critical: float, emergency: float):
        self.warning = warning
        self.critical = critical
        self.emergency = emergency


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
        self._last_check_time = 0.0
        self._check_interval = 1.0
        self.force_pressure = False
        
        # GPU相关缓存
        self._nvidia_smi_path: Optional[str] = None
        self._nvml = None
        self._nvml_handle = None
        self._nvml_failed = False
        
        # 缓存机制
        self._gpu_memory_cache: Optional[GPUInfo] = None
        self._gpu_memory_cache_time: float = 0.0
        self._gpu_cache_ttl: float = 0.5  # 缓存有效期（秒）
        
        self._gpu_process_cache: Optional[Dict[int, int]] = None
        self._gpu_process_cache_time: float = 0.0
        
        # 系统信息缓存
        self._cpu_model: Optional[str] = None
        self._gpu_model: Optional[str] = None
    
    @property
    def thresholds(self) -> Dict[ResourceType, ResourceThreshold]:
        """获取阈值配置"""
        return self._thresholds
    
    def set_threshold(self, resource_type: ResourceType, threshold: ResourceThreshold):
        """设置资源阈值"""
        self._thresholds[resource_type] = threshold
    
    def invalidate_gpu_cache(self):
        """使GPU缓存失效"""
        self._gpu_memory_cache = None
        self._gpu_memory_cache_time = 0.0
        self._gpu_process_cache = None
        self._gpu_process_cache_time = 0.0
    
    # ==================== 内存监控 ====================
    
    def get_memory_usage(self) -> float:
        """获取系统内存使用百分比"""
        return psutil.virtual_memory().percent
    
    def get_process_memory_usage(self) -> int:
        """获取当前进程内存使用（MB）"""
        return self._process.memory_info().rss // (1024 * 1024)
    
    def get_available_memory_mb(self) -> int:
        """获取可用内存（MB）"""
        return psutil.virtual_memory().available // (1024 * 1024)
    
    # ==================== CPU监控 ====================
    
    def get_cpu_usage(self) -> float:
        """获取CPU使用百分比"""
        return psutil.cpu_percent(interval=None)
    
    def get_cpu_model(self) -> str:
        """获取CPU型号"""
        if self._cpu_model is not None:
            return self._cpu_model
        
        try:
            if os.name == "nt":
                self._cpu_model = self._get_cpu_model_windows()
            else:
                self._cpu_model = self._get_cpu_model_linux()
        except Exception:
            logger.debug("获取CPU型号失败，使用默认值", exc_info=True)
            self._cpu_model = "Unknown CPU"
        
        return self._cpu_model
    
    def _get_cpu_model_windows(self) -> str:
        """Windows系统获取CPU型号"""
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
            logger.debug("通过Windows注册表获取CPU型号失败", exc_info=True)
            pass
        
        try:
            # P0-19: PowerShell 启动较慢，设置 timeout 避免阻塞
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name"],
                text=True,
                timeout=10,
            ).strip()
            if output:
                return output
        except Exception:
            logger.debug("通过PowerShell获取CPU型号失败", exc_info=True)
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
            logger.debug("通过WMIC获取CPU型号失败", exc_info=True)
            pass

        return "Unknown CPU"

    def _get_cpu_model_linux(self) -> str:
        """Linux系统获取CPU型号"""
        try:
            output = subprocess.check_output(
                ["lscpu"], text=True, stderr=subprocess.DEVNULL, timeout=5
            )
            for line in output.split("\n"):
                if "Model name" in line and ":" in line:
                    return line.split(":")[1].strip()
        except Exception:
            logger.debug("通过lscpu获取CPU型号失败", exc_info=True)
            pass
        
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
        except Exception:
            logger.debug("通过/proc/cpuinfo获取CPU型号失败", exc_info=True)
            pass
        
        return "Unknown CPU"
    
    # ==================== GPU监控 ====================
    
    async def get_gpu_memory_usage_async(self) -> Optional[GPUInfo]:
        """异步获取GPU内存使用情况（带缓存）"""
        current_time = time.time()
        
        # 检查缓存是否有效
        if (self._gpu_memory_cache is not None and 
            current_time - self._gpu_memory_cache_time < self._gpu_cache_ttl):
            return self._gpu_memory_cache
        
        result = await self._fetch_gpu_memory_async()
        
        # 更新缓存
        if result is not None:
            self._gpu_memory_cache = result
            self._gpu_memory_cache_time = current_time
        
        return result
    
    async def _fetch_gpu_memory_async(self) -> Optional[GPUInfo]:
        """异步获取GPU内存（实际实现）"""
        try:
            if self._ensure_nvml():
                info = self._nvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                used = int(info.used) // (1024 * 1024)
                total = int(info.total) // (1024 * 1024)
                if self.force_pressure:
                    used = int(total * 0.92)
                return (used, total)
        except Exception:
            logger.debug("通过NVML异步获取GPU内存失败", exc_info=True)
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
    
    def get_gpu_memory_usage(self) -> Optional[GPUInfo]:
        """同步获取GPU内存使用情况"""
        try:
            if self._ensure_nvml():
                info = self._nvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                return (
                    int(info.used // (1024 * 1024)),
                    int(info.total // (1024 * 1024)),
                )
        except Exception:
            logger.debug("通过NVML同步获取GPU内存失败", exc_info=True)
            pass
        return None
    
    def get_gpu_usage_percent(self) -> Optional[float]:
        """获取GPU使用百分比"""
        info = self.get_gpu_memory_usage()
        if info:
            used, total = info
            return (used / total) * 100 if total > 0 else 0
        return None
    
    async def get_gpu_compute_process_usage_async(self) -> Optional[Dict[int, int]]:
        """异步获取GPU进程使用情况（带缓存）"""
        current_time = time.time()
        
        # 检查缓存是否有效
        if (self._gpu_process_cache is not None and 
            current_time - self._gpu_process_cache_time < self._gpu_cache_ttl):
            return self._gpu_process_cache
        
        result = await self._fetch_gpu_process_usage_async()
        
        # 更新缓存
        if result is not None:
            self._gpu_process_cache = result
            self._gpu_process_cache_time = current_time
        
        return result
    
    async def _fetch_gpu_process_usage_async(self) -> Optional[Dict[int, int]]:
        """异步获取GPU进程使用（实际实现）"""
        try:
            if self._ensure_nvml():
                return self._get_nvml_process_usage_mb()
        except Exception:
            logger.debug("通过NVML异步获取GPU进程使用失败", exc_info=True)
        
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
            logger.debug("通过nvidia-smi异步获取GPU进程使用失败", exc_info=True)
            return None
    
    def get_gpu_compute_process_usage(self) -> Optional[Dict[int, int]]:
        """同步获取GPU进程使用情况"""
        try:
            if self._ensure_nvml():
                return self._get_nvml_process_usage_mb()
        except Exception:
            logger.debug("通过NVML同步获取GPU进程使用失败", exc_info=True)
        
        if self._nvidia_smi_path is None:
            self._nvidia_smi_path = self._resolve_nvidia_smi_path()
        
        try:
            exe = self._nvidia_smi_path or "nvidia-smi"
            result = subprocess.run(
                [exe, "--query-compute-apps=pid,used_memory", "--format=csv,nounits,noheader"],
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
            logger.debug("通过nvidia-smi同步获取GPU进程使用失败", exc_info=True)
            return None
    
    def get_current_process_gpu_used_mb(
        self, pid_usage: Optional[Dict[int, int]] = None
    ) -> Optional[int]:
        """获取当前进程GPU显存使用"""
        try:
            pid = int(self._process.pid)
        except Exception:
            logger.debug("获取当前进程PID失败", exc_info=True)
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
                    logger.debug("获取子进程PID失败", exc_info=True)
                    continue
        except Exception:
            logger.debug("获取子进程列表失败", exc_info=True)
            pass
        
        total = 0
        for proc_id in pids:
            try:
                total += int(usage.get(int(proc_id), 0) or 0)
            except Exception:
                logger.debug("计算进程GPU使用量失败", proc_id=proc_id, exc_info=True)
                continue
        return int(total)
    
    def get_gpu_model(self) -> str:
        """获取GPU型号"""
        if self._gpu_model is not None:
            return self._gpu_model
        
        _torch = _get_torch()
        if _torch and _torch.cuda.is_available():
            try:
                self._gpu_model = _torch.cuda.get_device_name(0)
                return self._gpu_model
            except Exception:
                logger.debug("通过torch获取GPU型号失败", exc_info=True)
                pass
        
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if result.returncode == 0 and result.stdout.strip():
                self._gpu_model = result.stdout.strip()
                return self._gpu_model
        except Exception:
            logger.debug("通过nvidia-smi获取GPU型号失败", exc_info=True)
            pass
        
        if os.name == "nt":
            try:
                # P0-19: PowerShell 启动较慢，设置 timeout 避免阻塞
                output = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                    text=True,
                    timeout=10,
                ).strip()
                if output:
                    self._gpu_model = output.split("\n")[0].strip()
                    return self._gpu_model
            except Exception:
                logger.debug("通过PowerShell获取GPU型号失败", exc_info=True)
                pass
        
        self._gpu_model = "Unknown GPU"
        return self._gpu_model
    
    # ==================== NVML辅助方法 ====================
    
    def _ensure_nvml(self) -> bool:
        """确保NVML已初始化"""
        if self._nvml_handle is not None:
            return True
        if self._nvml_failed:
            return False
        
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return True
        except Exception:
            logger.debug("NVML初始化失败", exc_info=True)
            self._nvml_failed = True
            self._nvml = None
            self._nvml_handle = None
            return False
    
    def _get_nvml_process_usage_mb(self) -> Dict[int, int]:
        """通过NVML获取进程GPU使用"""
        if self._nvml_handle is None or self._nvml is None:
            return {}
        
        nvml = self._nvml
        out: Dict[int, int] = {}
        
        def _read(fn_name: str):
            fn = getattr(nvml, fn_name, None)
            if not callable(fn):
                return
            try:
                procs = fn(self._nvml_handle)
            except Exception:
                logger.debug("NVML获取进程列表失败", fn_name=fn_name, exc_info=True)
                return
            if not procs:
                return
            for proc in procs:
                pid = getattr(proc, "pid", None)
                used = getattr(proc, "usedGpuMemory", None)
                try:
                    pid_i = int(pid)
                except Exception:
                    logger.debug("解析GPU进程PID失败", pid=pid, exc_info=True)
                    continue
                if pid_i <= 0:
                    continue
                try:
                    used_bytes = int(used)
                except Exception:
                    logger.debug("解析GPU进程内存使用失败", exc_info=True)
                    used_bytes = 0
                if used_bytes < 0:
                    used_bytes = 0
                used_mb = used_bytes // (1024 * 1024)
                prev = int(out.get(pid_i, 0) or 0)
                if used_mb > prev:
                    out[pid_i] = used_mb
        
        _read("nvmlDeviceGetComputeRunningProcesses")
        _read("nvmlDeviceGetComputeRunningProcesses_v2")
        _read("nvmlDeviceGetGraphicsRunningProcesses")
        _read("nvmlDeviceGetGraphicsRunningProcesses_v2")
        return out
    
    def _resolve_nvidia_smi_path(self) -> Optional[str]:
        """解析nvidia-smi路径"""
        try:
            path = shutil.which("nvidia-smi")
            if path:
                return str(path)
        except Exception:
            logger.debug("查找nvidia-smi路径失败", exc_info=True)
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
                logger.debug("检查nvidia-smi候选路径失败", candidate=candidate, exc_info=True)
                continue
        
        return None
    
    # ==================== 磁盘监控 ====================
    
    def get_disk_usage(self) -> float:
        """获取磁盘使用百分比"""
        try:
            return psutil.disk_usage(os.getcwd()).percent
        except Exception:
            logger.debug("获取磁盘使用率失败(主路径)", exc_info=True)
            try:
                cwd = os.getcwd()
                if os.name == "nt":
                    drive = os.path.splitdrive(cwd)[0]
                    if drive:
                        return psutil.disk_usage(drive + "\\").percent
                else:
                    return psutil.disk_usage("/").percent
            except Exception:
                logger.debug("获取磁盘使用率失败(备用路径)", exc_info=True)
                pass
        return 0.0
    
    # ==================== 资源状态判断 ====================
    
    def get_resource_state(self, resource_type: ResourceType) -> ResourceState:
        """获取资源状态"""
        current_time = time.time()
        if current_time - self._last_check_time < self._check_interval:
            return ResourceState.NORMAL
        
        self._last_check_time = current_time
        threshold = self._thresholds.get(resource_type)
        if threshold is None:
            return ResourceState.NORMAL
        
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
        """检查资源是否处于压力状态"""
        state = self.get_resource_state(resource_type)
        return state in [ResourceState.WARNING, ResourceState.CRITICAL, ResourceState.EMERGENCY]
