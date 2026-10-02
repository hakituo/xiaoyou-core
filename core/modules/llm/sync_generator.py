"""
LLM模块同步生成器
负责非流式聊天生成逻辑
"""

import gc
import time
from typing import Optional

try:
    from transformers.models.auto.modeling_auto import AutoModelForCausalLM
    from transformers.models.auto.tokenization_auto import AutoTokenizer
except ImportError:
    AutoModelForCausalLM = None
    AutoTokenizer = None

from core.utils.logger import get_logger
from .utils import get_torch, is_local_runtime_ready
from .inference_utils import (
    build_llama_cpp_chat_kwargs,
    strip_unexpected_llama_cpp_kwargs,
)
from .error_handler import (
    is_cuda_backend_error,
    is_index_out_of_bounds_error,
    get_error_message,
)

logger = get_logger("LLM.SYNC_GENERATOR")


class SyncGenerator:
    """同步生成器，负责处理非流式聊天请求"""

    # 定义停止token
    STOP_TOKENS = [
        "User:",
        "user:",
        "\nUser",
        " ",
        "<|end|>",
        "",
    ]

    def __init__(self, module):
        """
        初始化同步生成器

        Args:
            module: 所属的LLMModule实例
        """
        self.module = module

    def _is_local_runtime_ready(self) -> bool:
        return is_local_runtime_ready(self.module)

    async def generate(
        self,
        prompt,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model_path: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> dict:
        """
        生成文本回复（非流式）

        Args:
            prompt: 提示词或消息列表
            max_tokens: 最大生成token数
            temperature: 温度参数
            model_path: 模型路径
            conversation_id: 会话ID

        Returns:
            包含状态和回复的字典
        """
        async with self.module._lock:
            try:
                # 检查云模型路径
                if model_path and str(model_path).startswith("cloud:"):
                    return {
                        "status": "error",
                        "error": get_error_message("cloud_model_in_local", model_path),
                    }

                # 检查是否需要切换模型
                if model_path and model_path != self.module.text_model_path:
                    logger.info(
                        f"Model switch requested: {self.module.text_model_path} -> {model_path}"
                    )
                    await self.module._unload_model_unsafe()
                    self.module.text_model_path = model_path
                    self.module.is_loaded = False

                from core.services.scheduler.cpp_scheduler_engine import (
                    cpp_scheduler_engine,
                )

                # 检查是否使用C++调度器
                use_cpp_scheduler = (
                    cpp_scheduler_engine.enabled
                    and self.module._use_cpp_scheduler_for_llm
                    and self.module.text_model_path
                    and str(self.module.text_model_path).lower().endswith(".gguf")
                    and (
                        model_path is None or model_path == self.module.text_model_path
                    )
                )

                if use_cpp_scheduler:
                    return await self._generate_with_scheduler(
                        prompt, max_tokens, temperature, conversation_id
                    )

                if self.module.is_loaded and not self._is_local_runtime_ready():
                    logger.warning(
                        "检测到模型状态不一致（is_loaded=True 但本地推理对象缺失），将触发重新加载"
                    )
                    self.module.is_loaded = False

                # 确保模型已加载
                if not self.module.is_loaded:
                    from .model_loader import ModelLoader

                    loader = ModelLoader(self.module)
                    success = await self.module._load_model_wrapper(loader)
                    if not success:
                        return {"status": "error", "error": "模型加载失败"}

                # 获取生成参数
                max_tokens = (
                    max_tokens or self.module.settings.model.max_new_tokens or None
                )
                temperature = (
                    temperature or self.module.settings.model.temperature or 0.7
                )
                min_p = self.module.settings.model.min_p
                repetition_penalty = (
                    self.module.settings.model.repetition_penalty or 1.1
                )
                top_p = self.module.settings.model.top_p or 0.9

                # 执行生成
                return await self._do_generate(
                    prompt, max_tokens, temperature, min_p, repetition_penalty, top_p
                )

            except Exception as e:
                logger.error(f"生成文本时出错: {str(e)}")
                return {"status": "error", "error": str(e)}

    async def _generate_with_scheduler(
        self,
        prompt,
        max_tokens: Optional[int],
        temperature: Optional[float],
        conversation_id: Optional[str],
    ) -> dict:
        """使用C++调度器生成"""
        from core.services.scheduler.task.task_scheduler import get_global_scheduler

        try:
            reply_parts = []
            eff_max_tokens = (
                max_tokens or self.module.settings.model.max_new_tokens or None
            )
            eff_temperature = (
                temperature or self.module.settings.model.temperature or 0.7
            )
            eff_top_p = self.module.settings.model.top_p or 0.9
            eff_top_k = getattr(self.module.settings.model, "top_k", None)
            eff_repetition_penalty = (
                self.module.settings.model.repetition_penalty or 1.1
            )
            eff_min_p = getattr(self.module.settings.model, "min_p", None)

            async for token in get_global_scheduler().submit_llm_task(
                prompt=prompt,
                max_tokens=eff_max_tokens,
                temperature=eff_temperature,
                top_p=eff_top_p,
                top_k=eff_top_k,
                repetition_penalty=eff_repetition_penalty,
                min_p=eff_min_p,
                conversation_id=conversation_id,
            ):
                if isinstance(token, dict):
                    if "error" in token:
                        return {
                            "status": "error",
                            "error": str(token.get("error") or "生成失败"),
                        }
                    content = token.get("content")
                    if content:
                        reply_parts.append(str(content))
                    if token.get("done"):
                        break
                    continue
                if token is None:
                    continue
                reply_parts.append(str(token))

            return {"status": "success", "response": "".join(reply_parts)}

        except Exception as e:
            logger.warning(f"C++ Scheduler 推理失败，回退到 Python 推理: {e}")
            # 回退到本地推理
            if not self.module.is_loaded:
                from .model_loader import ModelLoader

                loader = ModelLoader(self.module)
                success = await self.module._load_model_wrapper(loader)
                if not success:
                    return {"status": "error", "error": "模型加载失败"}

            max_tokens = max_tokens or self.module.settings.model.max_new_tokens or None
            temperature = temperature or self.module.settings.model.temperature or 0.7
            min_p = self.module.settings.model.min_p
            repetition_penalty = self.module.settings.model.repetition_penalty or 1.1
            top_p = self.module.settings.model.top_p or 0.9

            return await self._do_generate(
                prompt, max_tokens, temperature, min_p, repetition_penalty, top_p
            )

    async def _do_generate(
        self,
        prompt,
        max_tokens: int,
        temperature: float,
        min_p,
        repetition_penalty: float,
        top_p: float,
    ) -> dict:
        """执行实际生成"""
        import asyncio

        return await asyncio.to_thread(
            self._generate_sync,
            prompt,
            max_tokens,
            temperature,
            min_p,
            repetition_penalty,
            top_p,
        )

    def _generate_sync(
        self,
        prompt,
        max_tokens: int,
        temperature: float,
        min_p,
        repetition_penalty: float,
        top_p: float,
    ) -> dict:
        """同步生成逻辑"""
        with self.module._thread_lock:
            if self.module.is_gguf:
                return self._generate_gguf_sync(
                    prompt, max_tokens, temperature, min_p, repetition_penalty, top_p
                )

            return self._generate_transformers_sync(
                prompt, max_tokens, temperature, min_p, repetition_penalty, top_p
            )

    def _generate_gguf_sync(
        self,
        prompt,
        max_tokens: int,
        temperature: float,
        min_p,
        repetition_penalty: float,
        top_p: float,
    ) -> dict:
        """GGUF同步生成逻辑"""
        try:
            # 限制max_tokens
            try:
                n_ctx = None
                if hasattr(self.module.llama_model, "n_ctx"):
                    try:
                        n_ctx = int(self.module.llama_model.n_ctx())
                    except Exception:
                        n_ctx = None
                if not n_ctx:
                    n_ctx = (
                        self.module.config.get("n_ctx")
                        or getattr(self.module.settings.model, "n_ctx", None)
                        or 2048
                    )
                max_allowed_tokens = max(128, int(n_ctx * 0.5))
                if max_tokens > max_allowed_tokens:
                    logger.warning(
                        f"[sync] Clamping max_tokens from {max_tokens} to {max_allowed_tokens} based on n_ctx={n_ctx}"
                    )
                    max_tokens = max_allowed_tokens
            except Exception as clamp_err:
                logger.error(
                    f"[sync] Failed to clamp max_tokens for GGUF model: {clamp_err}"
                )

            # 构建消息
            messages = []
            if isinstance(prompt, str):
                messages = [{"role": "user", "content": prompt}]
            elif isinstance(prompt, list):
                messages = prompt

            # 执行生成
            try:
                top_k = getattr(self.module.settings.model, "top_k", None)
                logger.info(
                    f"Starting GGUF sync generation with {len(messages)} messages. max_tokens={max_tokens}"
                )
                start_time = time.time()

                llama_kwargs = build_llama_cpp_chat_kwargs(
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                    min_p=min_p,
                    stop=self.STOP_TOKENS,
                    stream=False,
                )

                try:
                    response = self.module.llama_model.create_chat_completion(
                        messages=messages,
                        **llama_kwargs,
                    )
                except TypeError as e:
                    llama_kwargs = strip_unexpected_llama_cpp_kwargs(
                        llama_kwargs, str(e)
                    )
                    response = self.module.llama_model.create_chat_completion(
                        messages=messages,
                        **llama_kwargs,
                    )

                logger.info(
                    f"GGUF sync generation completed. Time: {time.time() - start_time:.4f}s"
                )

            except Exception as e:
                error_str = str(e)

                # CUDA错误时切换到CPU重试
                cfg_layers = self.module.config.get("n_gpu_layers", -1)
                if int(cfg_layers) != 0 and is_cuda_backend_error(error_str):
                    return self._retry_with_cpu(
                        messages,
                        max_tokens,
                        temperature,
                        top_p,
                        top_k,
                        repetition_penalty,
                        min_p,
                        e,
                    )

                # 索引越界错误时重置模型
                elif is_index_out_of_bounds_error(error_str):
                    return self._retry_with_reset(
                        messages,
                        max_tokens,
                        temperature,
                        top_p,
                        top_k,
                        repetition_penalty,
                        min_p,
                    )

                else:
                    raise e

            content = response["choices"][0]["message"]["content"]
            finish_reason = (
                response["choices"][0] or {}
            ).get("finish_reason", "stop")
            return {
                "status": "success",
                "response": content,
                "finish_reason": finish_reason,
            }

        except Exception as e:
            logger.error(f"GGUF推理失败: {e}")
            # 检查上下文窗口超限
            if "exceed context window" in str(e):
                n_ctx = 0
                if hasattr(self.module.llama_model, "n_ctx"):
                    try:
                        n_ctx = int(self.module.llama_model.n_ctx())
                    except Exception:
                        n_ctx = 0
                return {
                    "status": "error",
                    "error": get_error_message("context_window_exceeded", str(n_ctx)),
                }
            return {"status": "error", "error": str(e)}

    def _retry_with_cpu(
        self,
        messages,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k,
        repetition_penalty: float,
        min_p,
        original_error,
    ) -> dict:
        """切换到CPU模式重试"""
        logger.warning(
            f"GGUF推理触发CUDA后端错误，尝试切换到CPU并重试一次: {original_error}"
        )

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

        torch = get_torch()
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
            raise original_error

        # 重试生成
        llama_kwargs = build_llama_cpp_chat_kwargs(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            min_p=min_p,
            stop=self.STOP_TOKENS,
            stream=False,
        )

        try:
            response = self.module.llama_model.create_chat_completion(
                messages=messages,
                **llama_kwargs,
            )
        except TypeError as e2:
            llama_kwargs = strip_unexpected_llama_cpp_kwargs(llama_kwargs, str(e2))
            response = self.module.llama_model.create_chat_completion(
                messages=messages,
                **llama_kwargs,
            )

        content = response["choices"][0]["message"]["content"]
        finish_reason = (
            response["choices"][0] or {}
        ).get("finish_reason", "stop")
        return {
            "status": "success",
            "response": content,
            "finish_reason": finish_reason,
        }

    def _retry_with_reset(
        self,
        messages,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k,
        repetition_penalty: float,
        min_p,
    ) -> dict:
        """重置模型后重试"""
        logger.warning("GGUF推理遇到索引错误，尝试重置模型并重试")
        self.module.llama_model.reset()

        llama_kwargs = build_llama_cpp_chat_kwargs(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            min_p=min_p,
            stop=self.STOP_TOKENS,
            stream=False,
        )

        try:
            response = self.module.llama_model.create_chat_completion(
                messages=messages,
                **llama_kwargs,
            )
        except TypeError as e2:
            llama_kwargs = strip_unexpected_llama_cpp_kwargs(llama_kwargs, str(e2))
            response = self.module.llama_model.create_chat_completion(
                messages=messages,
                **llama_kwargs,
            )

        content = response["choices"][0]["message"]["content"]
        finish_reason = (
            response["choices"][0] or {}
        ).get("finish_reason", "stop")
        return {
            "status": "success",
            "response": content,
            "finish_reason": finish_reason,
        }

    def _generate_transformers_sync(
        self,
        prompt,
        max_tokens: int,
        temperature: float,
        min_p,
        repetition_penalty: float,
        top_p: float,
    ) -> dict:
        """Transformers同步生成逻辑"""
        torch = get_torch()
        if torch is None:
            raise RuntimeError(get_error_message("torch_not_installed"))
        if self.module.tokenizer is None or self.module.model is None:
            raise RuntimeError("本地模型未正确初始化，请稍后重试。")

        # 处理消息列表，应用Chat Template
        if isinstance(prompt, list):
            try:
                prompt_text = self.module.tokenizer.apply_chat_template(
                    prompt, tokenize=False, add_generation_prompt=True
                )
            except Exception as e:
                logger.warning(f"应用Chat Template失败，回退到原始文本: {e}")
                prompt_text = str(prompt)
        else:
            prompt_text = str(prompt)

        inputs = self.module.tokenizer(prompt_text, return_tensors="pt")
        if self.module.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            # 构建生成参数
            gen_kwargs = {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "do_sample": True,
                "repetition_penalty": repetition_penalty,
                "pad_token_id": self.module.tokenizer.eos_token_id,
            }

            if min_p is not None:
                gen_kwargs["min_p"] = min_p
            if top_p is not None:
                gen_kwargs["top_p"] = top_p

            output = self.module.model.generate(**inputs, **gen_kwargs)

        response = self.module.tokenizer.decode(
            output[0][len(inputs["input_ids"][0]) :], skip_special_tokens=True
        )

        return {"status": "success", "response": response}
