"""
C++ 调度器模块
提供资源隔离调度和 LLM 推理功能
"""

# 主引擎
from .cpp_scheduler_engine import CPPSchedulerEngine, get_scheduler_engine

# 模型管理
from .model.llm_model_manager import LLMModelManager
from .model.gpu_resource_manager import GPUResourceManager

# 推理执行
from .inference.inference_executor import InferenceExecutor

# 生命周期管理
from .lifecycle.scheduler_lifecycle import SchedulerLifecycle
from .lifecycle.health_monitor import HealthMonitor

# 生物系统
from .bio.bio_state import build_biological_status
from .bio.bio_system_manager import BioSystemManager

# 工具函数
from .utils.error_utils import friendly_llm_error, is_oom_error, is_cuda_backend_error
from .utils.circuit_breaker import (
    breaker_is_open,
    breaker_on_failure,
    breaker_on_success,
    create_breaker_state,
    get_breaker_status,
    BreakerState,
    BreakerRegistry,
)
from .utils.resource_utils import (
    check_memory_pressure,
    offload_tts_services,
    read_kv_swap_config,
    set_llm_config_attr,
    get_cuda_free_mb,
    MemoryPressureResult,
)
from .utils.kv_cache_manager import save_llm_state_emergency, restore_llm_state_emergency
from .utils.nvidia_smi_monitor import nvidia_smi_total_used_mb
from .utils.startup_config import resolve_llm_backend, apply_biological_config

# 推理统计
from .inference.inference_stats import get_last_llm_stats

# 推理工具
from .inference.inference_utils import clamp_messages, clamp_text, messages_to_text

# C++ 绑定
from .scheduler_wrapper import (
    _get_scheduler_py,
    _get_scheduler_class,
    is_cpp_scheduler_available,
)

# 任务调度（向后兼容）
from .task.task_scheduler import (
    get_global_scheduler,
    get_current_task_id,
    TaskPriority,
    TaskStatus,
    TaskInfo,
    GlobalTaskScheduler,
)
from .task.task_scheduler_adapter import (
    TaskSchedulerAdapter,
    io_task,
    initialize_scheduler,
    shutdown_scheduler,
)

__all__ = [
    # 主引擎
    'CPPSchedulerEngine',
    'get_scheduler_engine',
    # 模型管理
    'LLMModelManager',
    'GPUResourceManager',
    # 推理执行
    'InferenceExecutor',
    # 生命周期管理
    'SchedulerLifecycle',
    'HealthMonitor',
    # 生物系统
    'build_biological_status',
    'BioSystemManager',
    # 工具函数
    'friendly_llm_error',
    'is_oom_error',
    'is_cuda_backend_error',
    'breaker_is_open',
    'breaker_on_failure',
    'breaker_on_success',
    'create_breaker_state',
    'get_breaker_status',
    'BreakerState',
    'BreakerRegistry',
    'save_llm_state_emergency',
    'restore_llm_state_emergency',
    'get_last_llm_stats',
    'nvidia_smi_total_used_mb',
    'resolve_llm_backend',
    'apply_biological_config',
    'check_memory_pressure',
    'offload_tts_services',
    'read_kv_swap_config',
    'set_llm_config_attr',
    'get_cuda_free_mb',
    'MemoryPressureResult',
    'clamp_messages',
    'clamp_text',
    'messages_to_text',
    # C++ 绑定
    '_get_scheduler_py',
    '_get_scheduler_class',
    'is_cpp_scheduler_available',
    # 任务调度
    'get_global_scheduler',
    'get_current_task_id',
    'TaskPriority',
    'TaskStatus',
    'TaskInfo',
    'GlobalTaskScheduler',
    'TaskSchedulerAdapter',
    'io_task',
    'initialize_scheduler',
    'shutdown_scheduler',
]
