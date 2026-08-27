"""
工具模块
提供各种工具函数和辅助功能
"""

from .error_utils import friendly_llm_error, is_oom_error, is_cuda_backend_error
from .circuit_breaker import (
    breaker_is_open,
    breaker_on_failure,
    breaker_on_success,
    create_breaker_state,
    get_breaker_status,
)
from .kv_cache_manager import save_llm_state_emergency, restore_llm_state_emergency
from .nvidia_smi_monitor import nvidia_smi_total_used_mb
from .startup_config import resolve_llm_backend, apply_biological_config

__all__ = [
    'friendly_llm_error',
    'is_oom_error',
    'is_cuda_backend_error',
    'breaker_is_open',
    'breaker_on_failure',
    'breaker_on_success',
    'create_breaker_state',
    'get_breaker_status',
    'save_llm_state_emergency',
    'restore_llm_state_emergency',
    'nvidia_smi_total_used_mb',
    'resolve_llm_backend',
    'apply_biological_config',
]
