import shutil
import subprocess
import time
from typing import Optional

_cached_total_used_mb: Optional[int] = None
_cache_ts: float = 0.0
_CACHE_TTL: float = 2.0

_pynvml_available: Optional[bool] = None


def _try_pynvml_total_used_mb() -> Optional[int]:
    """尝试使用pynvml获取显存使用量（无进程创建开销）"""
    global _pynvml_available
    if _pynvml_available is False:
        return None

    try:
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        total = 0
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total += int(info.used // (1024 * 1024))
        pynvml.nvmlShutdown()
        if _pynvml_available is None:
            _pynvml_available = True
        return total
    except Exception:
        if _pynvml_available is None:
            _pynvml_available = False
        return None


def _subprocess_total_used_mb() -> Optional[int]:
    """通过nvidia-smi子进程获取显存使用量（回退方案）"""
    try:
        if not shutil.which("nvidia-smi"):
            return None
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode != 0:
            return None
        total = 0
        for line in (proc.stdout or "").splitlines():
            line = (line or "").strip()
            if not line:
                continue
            try:
                total += int(float(line))
            except Exception:
                continue
        return total
    except Exception:
        return None


def nvidia_smi_total_used_mb() -> Optional[int]:
    """获取nvidia-smi显存使用量（带2秒缓存，优先使用pynvml）"""
    global _cached_total_used_mb, _cache_ts

    now = time.time()
    if _cached_total_used_mb is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cached_total_used_mb

    result = _try_pynvml_total_used_mb()
    if result is None:
        result = _subprocess_total_used_mb()

    _cached_total_used_mb = result
    _cache_ts = now
    return result
