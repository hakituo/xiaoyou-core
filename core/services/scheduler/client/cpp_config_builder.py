"""
C++调度器配置构建模块
负责构建C++ LLM配置对象
"""


from core.utils.logger import get_logger
import os
from typing import Dict, Any

try:
    from ..scheduler_wrapper import _get_scheduler_class
except ImportError:
    _get_scheduler_class = None

from ..utils.resource_utils import (
    read_kv_swap_config,
    resolve_cpp_cache_size,
    set_llm_config_attr,
)

logger = get_logger(__name__)


class CPPConfigBuilder:
    """C++配置构建器"""

    @staticmethod
    def build_llm_config(config: Dict[str, Any]) -> Any:
        """构建C++ LLM配置对象"""
        if _get_scheduler_class is None:
            raise RuntimeError("C++ scheduler bindings not available")

        LLMModelConfig = _get_scheduler_class("LLMModelConfig")
        if LLMModelConfig is None:
            raise RuntimeError("C++ scheduler bindings not available")

        llm_config = LLMModelConfig()

        set_llm_config_attr(llm_config, ["modelPath", "model_path"], config.get("model_path", ""))
        set_llm_config_attr(
            llm_config, ["modelType", "model_type"], config.get("model_type") or "llama"
        )
        set_llm_config_attr(
            llm_config,
            ["gpu_device_id", "gpuDeviceId"],
            int(config.get("gpu_device_id", 0) or 0),
        )

        try:
            n_gpu_layers = config.get("n_gpu_layers", -1)
            if n_gpu_layers is None:
                n_gpu_layers = -1
            set_llm_config_attr(llm_config, ["n_gpu_layers", "nGpuLayers"], int(n_gpu_layers))
        except Exception:
            set_llm_config_attr(llm_config, ["n_gpu_layers", "nGpuLayers"], -1)

        cfg_ctx = int(config.get("max_context_size", 0) or 0)
        if cfg_ctx <= 0:
            max_ctx = 4096
        else:
            max_ctx = cfg_ctx

        req_batch = int(config.get("max_batch_size", 512) or 512)

        safe_sessions = resolve_cpp_cache_size(
            max_ctx, config.get("cache_size")
        )

        set_llm_config_attr(llm_config, ["max_context_size", "maxContextSize"], max_ctx)
        set_llm_config_attr(llm_config, ["maxBatchSize", "max_batch_size"], min(req_batch, 2048))
        set_llm_config_attr(llm_config, ["cacheSize", "cache_size"], safe_sessions)
        set_llm_config_attr(llm_config, ["enableCache", "enable_cache"], True)
        set_llm_config_attr(
            llm_config, ["temperature"], float(config.get("temperature", 0.7) or 0.7)
        )
        set_llm_config_attr(llm_config, ["topK", "top_k"], int(config.get("top_k", 40) or 40))
        set_llm_config_attr(
            llm_config, ["topP", "top_p"], float(config.get("top_p", 0.95) or 0.95)
        )
        set_llm_config_attr(
            llm_config,
            ["repetitionPenalty", "repetition_penalty"],
            float(config.get("repetition_penalty", 1.1) or 1.1),
        )

        draft_path = str(config.get("draft_model_path", "") or "")
        if not draft_path or draft_path.strip() == "":
            set_llm_config_attr(llm_config, ["draftModelPath", "draft_model_path"], "")
        else:
            resolved_draft_path = draft_path
            if not os.path.isabs(draft_path):
                try:
                    from core.utils.common import get_project_root

                    resolved_draft_path = str(get_project_root() / draft_path)
                except Exception:
                    resolved_draft_path = os.path.abspath(draft_path)

            if os.path.exists(resolved_draft_path):
                set_llm_config_attr(
                    llm_config, ["draftModelPath", "draft_model_path"], draft_path
                )
                logger.info(f"Draft model configured: {draft_path}")
            else:
                logger.warning(
                    f"Draft model not found: {resolved_draft_path}, disabling speculative decoding"
                )
                set_llm_config_attr(llm_config, ["draftModelPath", "draft_model_path"], "")

        set_llm_config_attr(
            llm_config,
            ["draftGpuDeviceId", "draft_gpu_device_id"],
            int(config.get("draft_gpu_device_id", -1) or -1),
        )
        set_llm_config_attr(
            llm_config,
            ["draftContextSize", "draft_context_size"],
            int(config.get("draft_context_size", 512) or 512),
        )

        kv_cfg = read_kv_swap_config(config)

        try:
            llm_config.enableKvSwap = bool(kv_cfg["kv_enabled"])
            llm_config.kvSwapDir = str(kv_cfg["kv_dir"] or "")
            llm_config.kvSwapTriggerTokens = int(kv_cfg["kv_trigger_tokens"])
        except Exception:
            pass

        return llm_config
