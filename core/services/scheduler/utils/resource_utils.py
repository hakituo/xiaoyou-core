"""
资源管理公共工具模块
提供内存压力检查、TTS卸载等跨模块复用的工具函数
"""

from core.utils.logger import get_logger
import asyncio

from dataclasses import dataclass
from typing import Optional

import psutil

logger = get_logger(__name__)


@dataclass
class MemoryPressureResult:
    """内存压力检查结果"""
    percent: float
    is_pressure: bool
    threshold: float
    has_gpu: bool


def check_memory_pressure(default_threshold: float = 97.0) -> MemoryPressureResult:
    """
    检查系统内存压力状态

    Args:
        default_threshold: 默认内存压力阈值百分比

    Returns:
        MemoryPressureResult 包含内存使用率、是否处于压力状态、阈值和GPU可用性
    """
    mem_percent = 0.0
    try:
        mem_percent = float(psutil.virtual_memory().percent)
    except Exception:
        mem_percent = 0.0

    mem_emergency = default_threshold
    try:
        from config.integrated_config import get_settings

        settings = get_settings()
        mem_block = getattr(
            settings.immune, "llm_load_memory_block_threshold", None
        )
        if mem_block is None:
            mem_block = getattr(
                settings.immune, "memory_emergency_threshold", default_threshold
            )
        mem_emergency = float(mem_block)
    except Exception:
        mem_emergency = default_threshold

    has_gpu = False
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and result.stdout.strip():
            has_gpu = True
    except Exception:
        try:
            import torch
            if torch.cuda.is_available():
                has_gpu = True
        except Exception:
            pass

    return MemoryPressureResult(
        percent=mem_percent,
        is_pressure=bool(mem_percent >= mem_emergency),
        threshold=mem_emergency,
        has_gpu=has_gpu,
    )


async def offload_tts_services(caller_name: str = "unknown") -> None:
    """
    主动卸载TTS/Voice服务的GPU资源，为LLM加载腾出显存

    Args:
        caller_name: 调用方名称，用于日志记录
    """
    try:
        from core.resource_manager import get_resource_manager

        rm = get_resource_manager()
        if rm:
            if hasattr(rm, "_offload_voice_services"):
                await rm._offload_voice_services()

            tts_model = rm.models.get("tts_engine")
            if (
                tts_model
                and tts_model.is_loaded
                and getattr(tts_model, "device", "") != "cpu"
            ):
                logger.info(
                    "%s: 正在将TTS迁移到CPU以为LLM腾出显存...", caller_name
                )
                if tts_model.offload_func:
                    if asyncio.iscoroutinefunction(tts_model.offload_func):
                        await tts_model.offload_func("release")
                    else:
                        tts_model.offload_func("release")
    except Exception as e:
        logger.warning(
            "%s: 卸载TTS服务失败（非致命）: %s", caller_name, e
        )


def read_kv_swap_config(config: dict, fallback_to_settings: bool = True) -> dict:
    """
    读取KV Swap配置，优先从config字典读取，其次从全局设置读取

    Args:
        config: GPU配置字典
        fallback_to_settings: 是否回退到全局设置

    Returns:
        包含 kv_enabled, kv_dir, kv_trigger_tokens 的字典
    """
    kv_enabled = False
    kv_dir = ""
    kv_trigger_tokens = 2048

    if fallback_to_settings:
        try:
            from config.integrated_config import get_settings
            from core.utils.common import get_project_root

            settings = get_settings()
            model_settings = getattr(settings, "model", None)
            kv_enabled = bool(getattr(model_settings, "kv_swap_enabled", False))
            kv_trigger_tokens = int(
                getattr(model_settings, "kv_swap_trigger_tokens", 2048) or 2048
            )
            kv_dir_cfg = getattr(model_settings, "kv_swap_dir", None)
            if kv_dir_cfg:
                kv_dir = str(kv_dir_cfg)
            else:
                cache_dir = str(
                    getattr(model_settings, "cache_dir", "cache") or "cache"
                )
                kv_dir = str((get_project_root() / cache_dir / "kvswap").resolve())
        except Exception:
            kv_enabled = False

    try:
        if "kv_swap_enabled" in config:
            kv_enabled = bool(config.get("kv_swap_enabled"))
    except Exception:
        pass
    try:
        if "kv_swap_dir" in config and config.get("kv_swap_dir"):
            kv_dir = str(config.get("kv_swap_dir") or "")
    except Exception:
        pass
    try:
        if (
            "kv_swap_trigger_tokens" in config
            and config.get("kv_swap_trigger_tokens") is not None
        ):
            kv_trigger_tokens = int(
                config.get("kv_swap_trigger_tokens") or kv_trigger_tokens
            )
    except Exception:
        pass

    return {
        "kv_enabled": kv_enabled,
        "kv_dir": kv_dir,
        "kv_trigger_tokens": kv_trigger_tokens,
    }


def set_llm_config_attr(obj, names: list[str], value) -> bool:
    """
    安全设置LLM配置对象属性，支持多种命名风格（camelCase/snake_case）

    Args:
        obj: 配置对象
        names: 可能的属性名列表
        value: 要设置的值

    Returns:
        是否成功设置
    """
    for name in names:
        if hasattr(obj, name):
            try:
                setattr(obj, name, value)
                return True
            except Exception:
                return False
    return False


def resolve_cpp_cache_size(
    max_context_size: int, configured_cache_size: Optional[int] = None
) -> int:
    """按 C++ 配置构建规则计算会话缓存数量。"""
    try:
        max_ctx = max(1, int(max_context_size))
    except (TypeError, ValueError):
        max_ctx = 4096

    if configured_cache_size is not None:
        try:
            return max(0, int(configured_cache_size))
        except (TypeError, ValueError):
            pass

    target_slot_size = max(1, min(2048, max_ctx // 2))
    n_seq_max = max(1, max_ctx // target_slot_size)
    return max(1, n_seq_max - 1)


def resolve_cpp_slot_context(
    max_context_size: int, configured_cache_size: Optional[int] = None
) -> int:
    """计算 C++ llama.cpp 每个序列真正可用的上下文 token 上限。"""
    try:
        max_ctx = max(1, int(max_context_size))
    except (TypeError, ValueError):
        max_ctx = 4096

    cache_size = resolve_cpp_cache_size(max_ctx, configured_cache_size)
    slot_size = max_ctx if cache_size <= 0 else max_ctx // (cache_size + 1)
    return max(1, slot_size - 4)


def get_cuda_free_mb() -> Optional[int]:
    """获取CUDA可用显存（MB）"""
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free_b, _total_b = torch.cuda.mem_get_info()
        return int(free_b // (1024 * 1024))
    except Exception:
        return None
