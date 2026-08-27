"""
LLM模块流式生成器
负责流式聊天生成逻辑
"""

import time
import asyncio
import threading
import gc
import re
from contextlib import AsyncExitStack
from typing import Optional

try:
    from transformers import TextIteratorStreamer
except ImportError:
    TextIteratorStreamer = None

from core.utils.logger import get_logger
from core.utils.resource_lock import get_resource_lock
from .utils import get_torch, normalize_local_path, is_local_runtime_ready
from core.services.scheduler.inference.inference_utils import (
    clamp_text,
    clamp_messages,
    rough_estimate_tokens_from_text,
)
from .inference_utils import (
    build_llama_cpp_chat_kwargs,
    strip_unexpected_llama_cpp_kwargs,
)
from .error_handler import (
    is_cuda_backend_error,
    is_context_window_error,
    get_error_message,
)

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGenerator:
    """流式生成器，负责处理流式聊天请求"""

    # 定义停止token
    STOP_TOKENS = [
        "User:",
        "user:",
        "\nUser",
        "<|user|>",
        "<|end|>",
        "<|endoftext|>",
        "\n\n\n",
    ]

    def __init__(self, module):
        """
        初始化流式生成器

        Args:
            module: 所属的LLMModule实例
        """
        self.module = module

    def _is_local_runtime_ready(self) -> bool:
        return is_local_runtime_ready(self.module)

    def _prompt_to_text(self, prompt) -> str:
        """将prompt转换为文本用于超时估计"""
        if isinstance(prompt, list):
            parts = []
            for m in prompt:
                if isinstance(m, dict):
                    role = m.get("role")
                    content = m.get("content")
                    if role is None and content is None:
                        parts.append(str(m))
                        continue
                    if role is None:
                        parts.append(str(content))
                        continue
                    if content is None:
                        parts.append(f"{role}:")
                        continue
                    parts.append(f"{role}: {content}")
                else:
                    parts.append(str(m))
            return "\n".join(parts)
        if not isinstance(prompt, str):
            try:
                return str(prompt)
            except Exception:
                return ""
        return prompt

    def _calculate_first_token_timeout(
        self, prompt_text: str, base_timeout: float, is_cpu_infer: bool
    ) -> float:
        """计算首token超时时间"""
        est_tokens = rough_estimate_tokens_from_text(prompt_text)
        if est_tokens > 0:
            scaled = 10.0 + (float(est_tokens) / 15.0)
            if is_cpu_infer:
                scaled = max(scaled, 30.0 + (float(est_tokens) / 10.0))
            return max(float(base_timeout), min(120.0, float(scaled)))
        return base_timeout

    def _parse_context_window_error(self, error_text: str):
        text = str(error_text or "")
        matched = re.search(
            r"requested tokens\s*\((\d+)\)\s*exceed context window of\s*(\d+)",
            text,
            flags=re.IGNORECASE,
        )
        if not matched:
            return None
        try:
            requested = int(matched.group(1))
            window = int(matched.group(2))
            return requested, window
        except Exception:
            return None

    def _retry_context_window_stream(
        self, messages, llama_kwargs: dict, max_tokens: int, error_text: str
    ):
        parsed = self._parse_context_window_error(error_text)
        if not parsed:
            return None
        requested, window = parsed
        overflow = max(1, int(requested) - int(window))
        retry_max_tokens = max(16, int(max_tokens) - overflow - 32)
        if retry_max_tokens >= int(max_tokens):
            retry_max_tokens = max(16, int(max_tokens) // 2)
        retry_kwargs = dict(llama_kwargs)
        retry_kwargs["max_tokens"] = int(retry_max_tokens)
        retry_text_budget = max(512, int(window) * 2)
        retry_messages = clamp_messages(messages, retry_text_budget)
        logger.warning(
            "请求超过上下文窗口，自动收缩并重试: requested=%s, window=%s, max_tokens %s -> %s",
            requested,
            window,
            max_tokens,
            retry_max_tokens,
        )
        try:
            return self.module.llama_model.create_chat_completion(
                messages=retry_messages,
                **retry_kwargs,
            )
        except TypeError as te:
            retry_kwargs = strip_unexpected_llama_cpp_kwargs(retry_kwargs, str(te))
            return self.module.llama_model.create_chat_completion(
                messages=retry_messages,
                **retry_kwargs,
            )

    async def generate(
        self,
        prompt,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model_path: Optional[str] = None,
        first_token_timeout: float = 30.0,
        conversation_id: Optional[str] = None,
    ):
        """
        流式生成文本回复

        Args:
            prompt: 提示词或消息列表
            max_tokens: 最大生成token数
            temperature: 温度参数
            model_path: 模型路径
            first_token_timeout: 首token超时时间
            conversation_id: 会话ID

        Yields:
            生成的内容片段
        """
        logger.info(
            f"StreamGenerator.generate called. prompt_len={len(str(prompt))}, model_path={model_path}"
        )
        self.module.last_used = time.time()

        # 检查云模型路径
        if model_path and str(model_path).startswith("cloud:"):
            logger.error(f"LocalLLMModule received cloud model path: {model_path}")
            yield {
                "error": get_error_message("cloud_model_in_local", model_path),
                "done": True,
            }
            return

        # 解析模型路径（支持模型名称自动补全）
        from .utils import resolve_model_path

        effective_model_path = (
            resolve_model_path(model_path)
            if model_path
            else self.module.text_model_path
        )
        fallback_model_path = None

        from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine

        # 检查是否使用C++调度器
        use_cpp_scheduler = (
            cpp_scheduler_engine.enabled
            and self.module._use_cpp_scheduler_for_llm
            and effective_model_path
            and str(effective_model_path).lower().endswith(".gguf")
        )

        # 确定是否需要GPU资源锁
        need_gpu_gate = False
        try:
            if self.module.is_gguf:
                cfg_layers = self.module.config.get("n_gpu_layers")
                if cfg_layers is None:
                    cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
                need_gpu_gate = int(cfg_layers) != 0
            else:
                need_gpu_gate = (
                    str(getattr(self.module, "device", "") or "").lower() == "cuda"
                )
        except Exception:
            need_gpu_gate = True

        async with AsyncExitStack() as stack:
            if bool(need_gpu_gate):
                await stack.enter_async_context(
                    get_resource_lock().acquire("LLM", reject_if_full=True)
                )

            # 使用C++调度器
            if use_cpp_scheduler:
                async for item in self._generate_with_scheduler(
                    prompt,
                    max_tokens,
                    temperature,
                    effective_model_path,
                    first_token_timeout,
                    conversation_id,
                ):
                    yield item
                return

            # 准备GPU资源
            await self._prepare_gpu_resources()

            # 检查是否需要切换模型
            if model_path:
                from .utils import resolve_model_path

                requested_path = resolve_model_path(model_path) or str(model_path)
                current_path = normalize_local_path(self.module.text_model_path) or str(
                    self.module.text_model_path
                )
                if requested_path != current_path:
                    logger.info(
                        f"Model switch requested: {self.module.text_model_path} -> {model_path}"
                    )
                    fallback_model_path = current_path
                    async with self.module._lock:
                        if requested_path != current_path:
                            await self.module._unload_model_unsafe()
                            self.module.text_model_path = requested_path
                            self.module.is_loaded = False

        if self.module.is_loaded and not self._is_local_runtime_ready():
            logger.warning(
                "检测到模型状态不一致（is_loaded=True 但本地推理对象缺失），将触发重新加载"
            )
            self.module.is_loaded = False

        # 确保模型已加载
        if not self.module.is_loaded:
            logger.info("Model not loaded, loading...")
            async with self.module._lock:
                if not self.module.is_loaded:
                    from .model_loader import ModelLoader

                    loader = ModelLoader(self.module)
                    success = await self.module._load_model_wrapper(loader)
                    if not success:
                        if fallback_model_path:
                            success = await self._try_fallback_model(
                                fallback_model_path
                            )
                        if not success:
                            logger.error("Model load failed.")
                            yield {
                                "status": "error",
                                "error": self.module._last_load_error or "模型加载失败",
                                "done": True,
                            }
                            return

        # 获取生成参数
        max_tokens = max_tokens or self.module.settings.model.max_new_tokens or None
        temperature = temperature or self.module.settings.model.temperature or 0.7
        min_p = self.module.settings.model.min_p
        repetition_penalty = self.module.settings.model.repetition_penalty or 1.1
        top_p = self.module.settings.model.top_p or 0.9
        top_k = getattr(self.module.settings.model, "top_k", None)

        # 对GGUF模型限制max_tokens
        if self.module.is_gguf:
            max_tokens = self._clamp_max_tokens_for_gguf(max_tokens)

        # 调整首token超时时间
        first_token_timeout = self._adjust_timeout(prompt, first_token_timeout)

        # 执行生成
        async for item in self._do_generate(
            prompt,
            max_tokens,
            temperature,
            min_p,
            repetition_penalty,
            top_p,
            top_k,
            first_token_timeout,
        ):
            yield item

    async def _generate_with_scheduler(
        self,
        prompt,
        max_tokens: Optional[int],
        temperature: Optional[float],
        model_path: str,
        first_token_timeout: float,
        conversation_id: Optional[str],
    ):
        """使用C++调度器生成"""
        from core.services.scheduler.task.task_scheduler import get_global_scheduler

        scheduler = get_global_scheduler()
        try:
            if not getattr(scheduler, "_running", False):
                worker_count = 4
                try:
                    worker_count = int(
                        getattr(
                            getattr(self.module.settings, "scheduler", None),
                            "worker_count",
                            4,
                        )
                        or 4
                    )
                except Exception:
                    worker_count = 4
                await scheduler.start(
                    worker_count=worker_count, llm_model_path=model_path
                )
        except Exception as e:
            logger.error(f"全局调度器启动失败: {e}")
            yield {"error": f"全局调度器启动失败: {e}", "done": True}
            return

        logger.info("Delegating inference to C++ Scheduler...")
        try:
            if self.module.is_loaded:
                async with self.module._lock:
                    await self.module._unload_model_unsafe()

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

            try:
                async for token in get_global_scheduler().submit_llm_task(
                    prompt=prompt,
                    model_path=model_path,
                    max_tokens=eff_max_tokens,
                    temperature=eff_temperature,
                    top_p=eff_top_p,
                    top_k=eff_top_k,
                    repetition_penalty=eff_repetition_penalty,
                    min_p=eff_min_p,
                    first_token_timeout=first_token_timeout,
                    conversation_id=conversation_id,
                ):
                    if isinstance(token, dict):
                        yield token
                        if token.get("done"):
                            return
                        if "error" in token:
                            return
                        continue
                    yield {"content": token}
            except asyncio.CancelledError:
                logger.warning(
                    "Stream chat cancelled. Requesting C++ scheduler to stop inference."
                )
                if hasattr(get_global_scheduler(), "request_stop_current_inference"):
                    await get_global_scheduler().request_stop_current_inference()
                else:
                    from core.services.scheduler.cpp_scheduler_engine import (
                        cpp_scheduler_engine,
                    )

                    if hasattr(cpp_scheduler_engine, "request_stop_current_inference"):
                        await cpp_scheduler_engine.request_stop_current_inference()
                raise
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            error_msg = f"C++ Scheduler inference failed: {e}"
            logger.error(error_msg)
            yield {
                "error": "本地模型调度服务暂时不可用，请稍后再试或检查后台日志。",
                "done": True,
            }

    async def _prepare_gpu_resources(self):
        """准备GPU资源"""
        should_prepare_gpu = True
        try:
            if self.module.text_model_path and str(
                self.module.text_model_path
            ).lower().endswith(".gguf"):
                cfg_layers = self.module.config.get("n_gpu_layers")
                if cfg_layers is None:
                    cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
                try:
                    should_prepare_gpu = int(cfg_layers) != 0
                except Exception:
                    should_prepare_gpu = True
            else:
                should_prepare_gpu = str(self.module.device).lower() == "cuda"
        except Exception:
            should_prepare_gpu = True

        if should_prepare_gpu:
            try:
                from core.resource_manager import get_global_resource_manager

                rm = await get_global_resource_manager()
                await rm.prepare_for_heavy_task("llm")
            except Exception as e:
                logger.error(f"Failed to prepare resources: {e}")

    async def _try_fallback_model(self, fallback_path: str) -> bool:
        """尝试回退到旧模型"""
        try:
            logger.warning(
                "模型切换失败，回退到旧模型: %s (错误: %s)",
                fallback_path,
                self.module._last_load_error or "未知",
            )
            await self.module._unload_model_unsafe()
            self.module.text_model_path = fallback_path
            self.module.is_loaded = False

            # 回退时强制禁用 scheduler 模式，确保本地加载
            original_scheduler_flag = self.module._use_cpp_scheduler_for_llm
            self.module._use_cpp_scheduler_for_llm = False

            try:
                from .model_loader import ModelLoader

                loader = ModelLoader(self.module)
                restored = await self.module._load_model_wrapper(loader)
                if restored:
                    logger.info("旧模型回退加载成功")
                return restored
            finally:
                # 恢复原始 scheduler 标志
                self.module._use_cpp_scheduler_for_llm = original_scheduler_flag
        except Exception as e:
            logger.error("旧模型回退失败: %s", e)
            return False

    def _clamp_max_tokens_for_gguf(self, max_tokens: int) -> int:
        """根据n_ctx限制max_tokens"""
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
            max_allowed_tokens = max(512, int(n_ctx * 0.8))
            if max_tokens > max_allowed_tokens:
                logger.warning(
                    f"Clamping max_tokens from {max_tokens} to {max_allowed_tokens} based on n_ctx={n_ctx}"
                )
                return max_allowed_tokens
        except Exception as e:
            logger.error(f"Failed to clamp max_tokens for GGUF model: {e}")
        return max_tokens

    def _adjust_timeout(self, prompt, base_timeout: float) -> float:
        """调整首token超时时间"""
        try:
            if not isinstance(base_timeout, (int, float)) or base_timeout <= 0:
                base_timeout = (
                    self.module.config.get("first_token_timeout")
                    or getattr(self.module.settings.model, "first_token_timeout", None)
                    or 10.0
                )
        except Exception:
            base_timeout = 10.0

        prompt_text = self._prompt_to_text(prompt)
        max_chars = 0
        if self.module.is_gguf and hasattr(self.module.llama_model, "n_ctx"):
            try:
                n_ctx = int(self.module.llama_model.n_ctx())
            except Exception:
                n_ctx = 0
            if n_ctx > 0:
                max_chars = max(1024, n_ctx * 3)
        if max_chars > 0:
            prompt_text = clamp_text(prompt_text, max_chars)

        # 判断是否为CPU推理
        is_cpu_infer = False
        if self.module.is_gguf:
            try:
                cfg_layers = self.module.config.get("n_gpu_layers")
                if cfg_layers is None:
                    cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
                is_cpu_infer = int(cfg_layers) == 0
            except Exception:
                is_cpu_infer = False
        else:
            is_cpu_infer = str(self.module.device).lower() != "cuda"

        return self._calculate_first_token_timeout(
            prompt_text, base_timeout, is_cpu_infer
        )

    async def _do_generate(
        self,
        prompt,
        max_tokens: int,
        temperature: float,
        min_p,
        repetition_penalty: float,
        top_p: float,
        top_k,
        first_token_timeout: float,
    ):
        """执行实际生成"""
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _producer():
            logger.info(f"Producer thread started. Timestamp: {time.time()}")

            def _put_threadsafe(payload):
                try:
                    if loop.is_closed():
                        return
                    asyncio.run_coroutine_threadsafe(queue.put(payload), loop)
                except Exception:
                    return

            acquired = False
            try:
                try:
                    timeout_sec = float(first_token_timeout)
                except Exception:
                    timeout_sec = 10.0

                # 获取线程锁
                if self.module._thread_lock.locked():
                    logger.warning(
                        f"检测到线程锁已被占用，尝试等待 {timeout_sec}s 后强制获取..."
                    )
                    lock_wait_start = time.time()
                    acquired = self.module._thread_lock.acquire(timeout=timeout_sec)
                    if not acquired:
                        logger.error(
                            f"锁获取超时（{time.time() - lock_wait_start:.1f}s），可能存在死锁"
                        )
                        try:
                            self.module._thread_lock.release()
                            logger.warning("已强制释放线程锁")
                        except Exception:
                            pass
                        acquired = self.module._thread_lock.acquire(timeout=5.0)
                else:
                    acquired = self.module._thread_lock.acquire(
                        timeout=max(0.1, timeout_sec)
                    )

                if not acquired:
                    _put_threadsafe(
                        {
                            "error": get_error_message("thread_lock_timeout"),
                            "done": True,
                        }
                    )
                    return

                logger.info("Acquired thread lock. Starting generation...")
                prompt_value = prompt
                if isinstance(prompt_value, list):
                    prompt_value = list(prompt_value)

                if self.module.is_gguf:
                    self._generate_gguf(
                        prompt_value,
                        max_tokens,
                        temperature,
                        top_p,
                        top_k,
                        repetition_penalty,
                        min_p,
                        _put_threadsafe,
                    )
                else:
                    self._generate_transformers(
                        prompt_value,
                        max_tokens,
                        temperature,
                        top_p,
                        top_k,
                        repetition_penalty,
                        min_p,
                        _put_threadsafe,
                    )

            except Exception as e:
                logger.error(f"Stream generation error: {e}")
                import traceback

                logger.error(traceback.format_exc())
                _put_threadsafe({"error": str(e), "done": True})
            finally:
                if acquired:
                    try:
                        self.module._thread_lock.release()
                    except Exception:
                        pass
                logger.info("Producer thread finishing. Sending sentinel.")
                _put_threadsafe(None)

        threading.Thread(
            target=_producer, daemon=True, name="llm_stream_producer"
        ).start()

        # 消费队列
        async for item in self._consume_queue(queue, first_token_timeout):
            yield item

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
        start_gen_time = time.time()

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

        stream_create_time = time.time() - start_gen_time
        logger.info(
            f"create_chat_completion returned stream iterator. Time taken: {stream_create_time:.4f}s"
        )

        if is_gpu_infer and stream_create_time > 5.0:
            logger.warning(f"GPU推理Stream创建耗时较长({stream_create_time:.2f}秒)")

        # 迭代stream
        self._iterate_stream(
            stream, start_gen_time, is_gpu_infer, actual_n_gpu_layers, _put_threadsafe
        )

    def _iterate_stream(
        self, stream, start_gen_time, is_gpu_infer, actual_n_gpu_layers, _put_threadsafe
    ):
        """迭代stream并产出内容"""
        if stream is None:
            logger.error("create_chat_completion返回的stream为None！")
            _put_threadsafe(
                {
                    "error": get_error_message("stream_init_failed"),
                    "done": True,
                }
            )
            return

        count = 0
        last_chunk_time = time.time()
        chunk_timeout = 30.0
        stream_iter_start = time.time()

        logger.info(
            f"开始迭代stream，is_gpu_infer={is_gpu_infer}, n_gpu_layers={actual_n_gpu_layers}"
        )

        try:
            for chunk in stream:
                current_time = time.time()
                elapsed_since_iter = current_time - stream_iter_start

                # 检测长时间无chunk
                if count == 0 and elapsed_since_iter > 10.0:
                    logger.error(
                        f"GPU推理严重问题：stream迭代开始后{elapsed_since_iter:.1f}秒仍无chunk！"
                    )
                    # 检查GPU状态
                    try:
                        import torch

                        if torch.cuda.is_available():
                            gpu_mem_used = torch.cuda.memory_allocated(0) / (1024**3)
                            gpu_mem_reserved = torch.cuda.memory_reserved(0) / (1024**3)
                            logger.error(
                                f"GPU显存状态 - 已分配: {gpu_mem_used:.2f}GB, 已保留: {gpu_mem_reserved:.2f}GB"
                            )
                    except Exception:
                        pass

                elapsed_since_last_chunk = current_time - last_chunk_time
                if count > 0 and elapsed_since_last_chunk > chunk_timeout:
                    logger.error(
                        f"推理可能卡住：已{elapsed_since_last_chunk:.1f}秒没有新token"
                    )

                if count == 0:
                    first_token_time = time.time() - start_gen_time
                    logger.info(
                        f"Received first chunk. Time to first token: {first_token_time:.4f}s"
                    )

                count += 1
                last_chunk_time = current_time

                # 检查chunk格式
                if not isinstance(chunk, dict):
                    logger.warning(f"收到非字典格式的chunk: {type(chunk)}")
                    continue

                if "choices" not in chunk or len(chunk["choices"]) == 0:
                    logger.warning(f"chunk缺少choices字段: {chunk.keys()}")
                    continue

                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta and delta["content"]:
                    content = delta["content"]
                    _put_threadsafe({"content": content})

        except StopIteration:
            logger.info("Stream正常结束（StopIteration）")
        except Exception as stream_error:
            logger.error(f"Stream迭代异常: {stream_error}", exc_info=True)
            _put_threadsafe(
                {
                    "error": f"GPU推理stream异常: {str(stream_error)}",
                    "done": True,
                }
            )
            return

        total_time = time.time() - start_gen_time
        logger.info(
            f"Stream finished. Total chunks: {count}. Total time: {total_time:.4f}s"
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
            raise RuntimeError("切换到CPU模式后重新加载失败")

    def _generate_transformers(
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
        """Transformers流式生成"""
        logger.info("Using Transformers generation.")
        if self.module.tokenizer is None or self.module.model is None:
            _put_threadsafe(
                {
                    "error": "本地模型未正确初始化，请稍后重试。",
                    "done": True,
                }
            )
            return

        if not TextIteratorStreamer:
            logger.error("TextIteratorStreamer not found.")
            _put_threadsafe(
                {"error": "Transformers library or TextIteratorStreamer not available"}
            )
            return

        streamer = TextIteratorStreamer(
            self.module.tokenizer, skip_prompt=True, skip_special_tokens=True
        )

        # 准备输入
        if isinstance(prompt_value, list):
            try:
                prompt_text = self.module.tokenizer.apply_chat_template(
                    prompt_value, tokenize=False, add_generation_prompt=True
                )
            except Exception:
                prompt_text = str(prompt_value)
        else:
            prompt_text = str(prompt_value)

        inputs = self.module.tokenizer(prompt_text, return_tensors="pt")
        if self.module.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}

        gen_kwargs = {
            "max_new_tokens": max_tokens,
            "temperature": temperature,
            "do_sample": True,
            "repetition_penalty": repetition_penalty,
            "pad_token_id": self.module.tokenizer.eos_token_id,
            "streamer": streamer,
        }
        if min_p is not None:
            gen_kwargs["min_p"] = min_p
        if top_p is not None:
            gen_kwargs["top_p"] = top_p
        if top_k is not None:
            try:
                gen_kwargs["top_k"] = int(top_k)
            except Exception:
                pass

        # 启动生成线程
        generation_thread = threading.Thread(
            target=self.module.model.generate, kwargs=dict(inputs, **gen_kwargs)
        )
        generation_thread.start()

        for new_text in streamer:
            _put_threadsafe({"content": new_text})

        generation_thread.join()
        logger.info("Generation thread joined.")

    async def _consume_queue(self, queue: asyncio.Queue, first_token_timeout: float):
        """消费生成队列"""
        logger.info("Consuming queue...")

        first_item = True
        received_token = False

        while True:
            if first_item:
                start_wait_time = time.time()
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=1.0)
                        break
                    except asyncio.TimeoutError:
                        elapsed = time.time() - start_wait_time
                        if elapsed >= first_token_timeout:
                            logger.error(
                                f"LLM stream first token timeout after {first_token_timeout}s"
                            )
                            self.module._last_timeout_at = time.time()

                            # 触发恢复
                            await self._trigger_recovery()

                            yield {
                                "error": get_error_message(
                                    "first_token_timeout", str(first_token_timeout)
                                ),
                                "done": True,
                            }
                            return
                        else:
                            if int(elapsed) % 2 == 0:
                                logger.info(
                                    f"Still waiting for model generation... ({elapsed:.1f}/{first_token_timeout}s)"
                                )
                first_item = False
            else:
                item = await queue.get()

            if item is None:
                logger.info("Received sentinel. Stream finished.")
                break

            if isinstance(item, dict) and "error" in item:
                logger.error(f"Stream error in queue: {item['error']}")
            if isinstance(item, dict) and item.get("content"):
                received_token = True
            yield item

        if received_token:
            self.module._force_cpu_after_timeout = False
            self.module._last_timeout_at = None

    async def _trigger_recovery(self):
        """触发超时后的恢复"""

        async def _recover():
            try:
                for _ in range(3):
                    acquired = False
                    try:
                        acquired = self.module._thread_lock.acquire(timeout=1.0)
                        if not acquired:
                            await asyncio.sleep(1.0)
                            continue
                        async with self.module._lock:
                            await self.module._unload_model_unsafe()
                            self.module.is_loaded = False
                        return
                    finally:
                        if acquired:
                            try:
                                self.module._thread_lock.release()
                            except Exception:
                                pass
            finally:
                self.module._recovery_task = None

        if self.module._recovery_task and not self.module._recovery_task.done():
            return

        try:
            self.module._recovery_task = asyncio.create_task(_recover())
        except Exception:
            self.module._recovery_task = None

        # 等待恢复完成
        recovery_wait_start = time.time()
        max_recovery_wait = 30.0
        while self.module._recovery_task and not self.module._recovery_task.done():
            await asyncio.sleep(0.5)
            if time.time() - recovery_wait_start > max_recovery_wait:
                logger.error("GPU到CPU回退超时")
                break

        self.module._force_cpu_after_timeout = True
        self.module.config["n_gpu_layers"] = 0
