"""GGUF 流式生成与 CUDA 失败后的 CPU 重试（混入 StreamGenerator）。

从 ``core/modules/llm/stream_generator.py`` 拆出：
- ``_generate_gguf``：llama.cpp 的 create_chat_completion 流式调用（含上下文窗口重试）
- ``_cleanup_and_retry_cpu``：CUDA 后端错误后清显存、切 CPU 并重新加载

⚠️ 模块级 patch 语义：测试会 patch 门面模块的 ``time`` / ``get_torch``
（``monkeypatch.setattr(sg, "get_torch", ...)``），因此这两个名字必须在调用期从
门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

import gc

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.modules.llm import stream_generator as _facade
from core.services.scheduler.inference.inference_utils import (
    clamp_text,
    clamp_messages,
)
from core.utils.logger import get_logger

from .error_handler import (
    is_cuda_backend_error,
    is_context_window_error,
    get_error_message,
)
from .inference_utils import (
    build_llama_cpp_chat_kwargs,
    strip_unexpected_llama_cpp_kwargs,
)

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGeneratorGgufMixin:
    """llama.cpp（GGUF）流式生成与 CPU 兜底。"""

    def _generate_gguf(
        self,
        prompt_value,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k,
        repetition_penalty: float,
        min_p,
        _put_threadsafe,
    ):
        """GGUF流式生成"""
        # 应用长度限制
        n_ctx = 0
        if hasattr(self.module.llama_model, "n_ctx"):
            try:
                n_ctx = int(self.module.llama_model.n_ctx())
            except Exception:
                n_ctx = 0

        max_chars = 12000
        if n_ctx > 0:
            max_chars = max(1024, min(n_ctx * 3, 12000))

        if isinstance(prompt_value, list):
            prompt_value = clamp_messages(prompt_value, max_chars)
        elif isinstance(prompt_value, str):
            prompt_value = clamp_text(prompt_value, max_chars)

        # 构建消息
        messages = []
        if isinstance(prompt_value, str):
            messages = [{"role": "user", "content": prompt_value}]
        elif isinstance(prompt_value, list):
            messages = prompt_value

        logger.info(f"Calling create_chat_completion with {len(messages)} messages...")
        start_gen_time = _facade.time.time()

        # 检查GPU推理状态
        is_gpu_infer = False
        actual_n_gpu_layers = 0
        try:
            cfg_layers = self.module.config.get("n_gpu_layers", -1)
            if cfg_layers is None:
                cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
            actual_n_gpu_layers = int(cfg_layers)
            is_gpu_infer = actual_n_gpu_layers != 0

            if is_gpu_infer:
                try:
                    import torch

                    if torch.cuda.is_available():
                        gpu_name = torch.cuda.get_device_name(0)
                        gpu_memory = torch.cuda.get_device_properties(
                            0
                        ).total_memory / (1024**3)
                        logger.info(
                            f"GPU推理模式 - n_gpu_layers={actual_n_gpu_layers}, GPU={gpu_name}, 显存={gpu_memory:.1f}GB"
                        )
                    else:
                        logger.warning("配置了GPU推理但CUDA不可用，实际将使用CPU")
                except Exception as e:
                    logger.warning(f"无法检测CUDA状态: {e}")

            if is_gpu_infer and hasattr(self.module.llama_model, "n_gpu_layers"):
                try:
                    model_gpu_layers = int(self.module.llama_model.n_gpu_layers())
                    logger.info(
                        f"模型实际GPU层数: {model_gpu_layers} (配置: {actual_n_gpu_layers})"
                    )
                    if model_gpu_layers == 0 and actual_n_gpu_layers != 0:
                        logger.error(
                            "配置了GPU推理但模型实际未加载到GPU！这可能导致推理卡死"
                        )
                except Exception as e:
                    logger.warning(f"无法获取模型GPU层数: {e}")
        except Exception as e:
            logger.error(f"检查GPU推理状态失败: {e}")
            is_gpu_infer = False

        # 创建stream
        stream = None
        try:
            llama_kwargs = build_llama_cpp_chat_kwargs(
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                top_k=top_k,
                min_p=min_p,
                stop=self.STOP_TOKENS,
                stream=True,
            )
            try:
                stream = self.module.llama_model.create_chat_completion(
                    messages=messages,
                    **llama_kwargs,
                )
            except TypeError as e:
                llama_kwargs = strip_unexpected_llama_cpp_kwargs(llama_kwargs, str(e))
                stream = self.module.llama_model.create_chat_completion(
                    messages=messages,
                    **llama_kwargs,
                )
        except Exception as e:
            error_str = str(e)
            self.module._last_load_error = error_str
            cfg_layers = self.module.config.get("n_gpu_layers", -1)
            if int(cfg_layers) != 0 and is_cuda_backend_error(error_str):
                logger.warning(f"GGUF流式推理触发CUDA后端错误: {error_str}")
                # 清理并重试
                self._cleanup_and_retry_cpu()
                return
            if is_context_window_error(error_str):
                stream = self._retry_context_window_stream(
                    messages, llama_kwargs, max_tokens, error_str
                )
                if stream is not None:
                    pass
                else:
                    _put_threadsafe(
                        {
                            "error": get_error_message(
                                "context_window_exceeded", error_str
                            ),
                            "done": True,
                        }
                    )
                    return
            else:
                raise

        stream_create_time = _facade.time.time() - start_gen_time
        logger.info(
            f"create_chat_completion returned stream iterator. Time taken: {stream_create_time:.4f}s"
        )

        if is_gpu_infer and stream_create_time > 5.0:
            logger.warning(f"GPU推理Stream创建耗时较长({stream_create_time:.2f}秒)")

        # 迭代stream
        self._iterate_stream(
            stream, start_gen_time, is_gpu_infer, actual_n_gpu_layers, _put_threadsafe
        )

    def _cleanup_and_retry_cpu(self):
        """清理资源并切换到CPU重试"""
        try:
            if self.module.llama_model:
                del self.module.llama_model
        except Exception:
            pass
        self.module.llama_model = None
        self.module.is_loaded = False
        self.module.config["n_gpu_layers"] = 0
        try:
            self.module.config["n_ctx"] = min(
                int(self.module.config.get("n_ctx") or 2048), 2048
            )
        except Exception:
            self.module.config["n_ctx"] = 2048

        torch = _facade.get_torch()
        if torch and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            except Exception:
                pass
        gc.collect()

        # 重新加载
        from .model_loader import ModelLoader

        loader = ModelLoader(self.module)
        if not loader.load_sync() or not self.module.llama_model:
            raise RuntimeError("切换到CPU模式后重新加载失败")
