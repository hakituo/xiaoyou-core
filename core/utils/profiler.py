import time
import psutil
import torch
import gc
from dataclasses import dataclass
from typing import Dict, Any, Optional
from .logger import get_logger

logger = get_logger("Profiler")


@dataclass
class ResourceStats:
    """资源使用统计数据"""

    timestamp: float
    cpu_percent: float
    memory_used_mb: float
    memory_percent: float
    gpu_memory_used_mb: Optional[int] = None
    gpu_utilization: Optional[int] = None
    gpu_temperature: Optional[int] = None


class ResourceProfiler:
    """资源监控器"""

    def __init__(self, enable_gpu: bool = True):
        self.enable_gpu = enable_gpu
        self.has_gpu = torch.cuda.is_available() and enable_gpu
        self.stats_history: Dict[str, list[ResourceStats]] = {}
        self.current_session: Optional[str] = None
        self.session_start_time: Optional[float] = None

        # 初始化psutil
        psutil.cpu_percent(interval=0.1)

        logger.info(f"资源监控器初始化: GPU支持={self.has_gpu}")
# 全局资源监控器实例
global_profiler = ResourceProfiler()
