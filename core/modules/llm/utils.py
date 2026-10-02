"""
LLM模块工具函数
"""

import os
from typing import Optional
from pathlib import Path
from core.utils.common import get_project_root

_LLAMA_CPP_INTERNALS_PATCHED = False


def patch_llama_cpp_internals():
    """修补 llama_cpp 内部实现，防止关闭时的错误"""
    global _LLAMA_CPP_INTERNALS_PATCHED
    if _LLAMA_CPP_INTERNALS_PATCHED:
        return
    try:
        import llama_cpp._internals as _internals

        llama_model_cls = getattr(_internals, "LlamaModel", None)
        if llama_model_cls is not None:
            if hasattr(llama_model_cls, "close"):
                original_close = llama_model_cls.close

                def _safe_close(self):
                    try:
                        if not hasattr(self, "sampler"):
                            setattr(self, "sampler", None)
                        return original_close(self)
                    except AttributeError:
                        return None

                llama_model_cls.close = _safe_close

            if hasattr(llama_model_cls, "__del__"):
                original_del = llama_model_cls.__del__

                def _safe_del(self):
                    try:
                        if not hasattr(self, "sampler"):
                            setattr(self, "sampler", None)
                        return original_del(self)
                    except Exception:
                        try:
                            return getattr(self, "close")()
                        except Exception:
                            return None

                llama_model_cls.__del__ = _safe_del
    except Exception:
        pass
    _LLAMA_CPP_INTERNALS_PATCHED = True


def get_torch():
    """获取 torch 模块，如果未安装则返回 None"""
    try:
        import torch

        return torch
    except Exception:
        return None


def resolve_use_mmap(
    use_mmap: bool, ram_mirror_offload: bool, n_gpu_layers: int
) -> bool:
    """
    根据配置决定是否启用 mmap。
    如果启用了 ram_mirror_offload，则强制禁用 mmap。
    镜像迁移逻辑通过禁用 mmap 来避免 OS Page Cache 与 VRAM 的双重占用。
    """
    if bool(ram_mirror_offload):
        return False

    return bool(use_mmap)


def normalize_local_path(path_value: Optional[str]) -> str:
    """规范化本地路径"""
    if not path_value:
        return ""
    raw = str(path_value).strip()
    if not raw:
        return ""

    try:
        p = Path(raw).expanduser()
    except Exception:
        p = Path(raw)

    try:
        if not p.is_absolute():
            p = (get_project_root() / p).resolve()
        else:
            p = p.resolve()
    except Exception:
        p = Path(os.path.abspath(str(p)))

    try:
        return os.path.normcase(os.path.abspath(str(p)))
    except Exception:
        return str(p)


def is_local_runtime_ready(module) -> bool:
    """检查本地模型运行时是否就绪

    Args:
        module: LLMModule 实例

    Returns:
        本地模型是否已加载就绪
    """
    if module.is_gguf:
        return module.llama_model is not None
    return module.model is not None and module.tokenizer is not None


def resolve_model_path(model_hint: Optional[str]) -> Optional[str]:
    """
    解析模型路径或模型名称，返回完整的规范化路径

    Args:
        model_hint: 可以是完整路径、相对路径或模型名称

    Returns:
        规范化的完整路径，如果无法解析则返回 None
    """
    if not model_hint:
        return None

    hint = str(model_hint).strip()
    if not hint:
        return None

    # 如果已经是完整路径（包含路径分隔符或以 .gguf 结尾）
    if "/" in hint or "\\" in hint or hint.lower().endswith(".gguf"):
        return normalize_local_path(hint)

    # 否则当作模型名称处理，尝试在 models/llm/ 目录下查找
    # 1. 尝试直接添加 .gguf 后缀
    model_name_with_ext = hint if hint.lower().endswith(".gguf") else f"{hint}.gguf"
    candidate_path = os.path.join("models", "llm", model_name_with_ext)
    full_path = normalize_local_path(candidate_path)

    if os.path.exists(full_path):
        return full_path

    # 2. 尝试不区分大小写匹配
    try:
        models_dir = get_project_root() / "models" / "llm"
        if models_dir.exists():
            hint_lower = hint.lower()
            for file in models_dir.iterdir():
                if file.is_file() and file.suffix.lower() == ".gguf":
                    # 移除 .gguf 后缀进行比较
                    file_name_without_ext = file.stem.lower()
                    if file_name_without_ext == hint_lower:
                        return normalize_local_path(str(file))
    except Exception as e:
        from core.utils.logger import get_logger

        logger = get_logger("LLM.UTILS")
        logger.warning(f"Failed to search for model file: {e}")

    # 3. 如果都找不到，返回原始规范化路径（可能不存在，但至少格式正确）
    return normalize_local_path(candidate_path)
