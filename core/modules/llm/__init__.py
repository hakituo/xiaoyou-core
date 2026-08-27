"""
LLM模块

重构后的模块结构：
- module.py: 主类 LLMModule，负责协调各个子模块
- model_loader.py: ModelLoader 类，负责模型加载
- stream_generator.py: StreamGenerator 类，负责流式生成
- sync_generator.py: SyncGenerator 类，负责同步生成
- gpu_manager.py: GPUManager 类，负责GPU资源管理
- error_handler.py: 错误处理工具函数
- utils.py: 通用工具函数
- text_utils.py: 文本处理工具
- inference_utils.py: 推理相关工具
"""

from .module import LLMModule
from .model_loader import ModelLoader
from .stream_generator import StreamGenerator
from .sync_generator import SyncGenerator
from .gpu_manager import GPUManager
from .error_handler import (
    is_oom_error,
    is_cuda_backend_error,
    is_invalid_vector_subscript_error,
    is_index_out_of_bounds_error,
    is_context_window_error,
    is_model_load_error,
    expand_gpu_layer_candidates,
    get_error_message,
)
from .utils import (
    get_torch,
    normalize_local_path,
    patch_llama_cpp_internals,
)
from core.services.scheduler.inference.inference_utils import (
    clamp_text,
    clamp_messages,
)
from .inference_utils import (
    build_llama_cpp_chat_kwargs,
    strip_unexpected_llama_cpp_kwargs,
    apply_default_template,
)

__all__ = [
    # 主类
    "LLMModule",
    # 子模块
    "ModelLoader",
    "StreamGenerator",
    "SyncGenerator",
    "GPUManager",
    # 错误处理
    "is_oom_error",
    "is_cuda_backend_error",
    "is_invalid_vector_subscript_error",
    "is_index_out_of_bounds_error",
    "is_context_window_error",
    "is_model_load_error",
    "expand_gpu_layer_candidates",
    "get_error_message",
    # 工具函数
    "get_torch",
    "normalize_local_path",
    "patch_llama_cpp_internals",
    "clamp_text",
    "clamp_messages",
    "build_llama_cpp_chat_kwargs",
    "strip_unexpected_llama_cpp_kwargs",
    "apply_default_template",
]
