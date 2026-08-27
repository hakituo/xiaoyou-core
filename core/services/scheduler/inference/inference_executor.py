"""
推理任务执行器模块
负责LLM推理任务的提交和执行
架构：Python 是路由层，C++ 是执行层，不存在 Python 后端降级
"""

from core.utils.logger import get_logger
import asyncio

from typing import Any, AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from ..cpp_scheduler_engine import CPPSchedulerEngine

logger = get_logger(__name__)


class InferenceExecutor:
    """推理任务执行器"""

    def __init__(self, engine: "CPPSchedulerEngine"):
        self.engine = engine

    async def submit_llm_task(self, prompt: str, **kwargs) -> AsyncGenerator[Any, None]:
        """
        提交 LLM 推理任务并 yield tokens。
        架构：Python 路由层 → C++ 执行层
        """
        if not self.engine.enabled:
            raise RuntimeError("C++ Scheduler is disabled.")

        if self.engine._llm_backend == "cpp":
            # 断路器熔断中，直接报错
            if self.engine._breaker_is_open("llm"):
                raise RuntimeError("C++ 调度器 LLM 断路器熔断中，请稍后重试")

            yielded_any = False
            try:
                async for t in self._submit_llm_task_cpp(prompt, **kwargs):
                    yielded_any = True
                    yield t
                self.engine._breaker_on_success("llm")
                return
            except Exception as e:
                self.engine._breaker_on_failure("llm")
                if yielded_any:
                    raise
                logger.error("C++ 后端推理失败: %s", e, exc_info=True)
                raise RuntimeError(f"C++ 调度器推理失败: {e}") from e

        # 非 C++ 后端（不应该到达这里）
        raise RuntimeError(
            f"不支持的 LLM 后端: {self.engine._llm_backend}，"
            "当前架构仅支持 C++ 执行层"
        )

    async def _submit_llm_task_cpp(self, prompt: str, **kwargs) -> AsyncGenerator[Any, None]:
        """C++ 后端推理任务提交"""
        from .cpp_llm_handler import submit_cpp_llm_task
        from .inference_utils import clamp_messages, clamp_text, messages_to_text
        from ..utils.error_utils import friendly_llm_error

        n_ctx = 0
        max_chars = kwargs.get("max_chars", 0)
        if self.engine._gpu_config:
            try:
                n_ctx = int(self.engine._gpu_config.get("max_context_size") or 0)
            except Exception:
                n_ctx = 0
            if max_chars <= 0:
                try:
                    max_chars = int(self.engine._gpu_config.get("max_chars") or 0)
                except Exception:
                    max_chars = 0

        _messages_to_text = messages_to_text

        def _prompt_to_text_for_bio(p: Any) -> str:
            return _messages_to_text(p)

        if max_chars > 0:
            if isinstance(prompt, list):
                prompt = clamp_messages(prompt, max_chars)
            else:
                prompt = clamp_text(prompt, max_chars)

        try:
            bio_text = _prompt_to_text_for_bio(prompt)
            if max_chars > 0:
                bio_text = clamp_text(bio_text, max_chars)
            await self.engine.bio_system_manager.apply_bio_before_infer(bio_text)
        except Exception as e:
            logger.debug("应用生物系统状态失败（非致命）: %s", e)

        try:
            await self.engine._maybe_switch_cpp_model(kwargs.get("model_path"))
        except Exception as e:
            logger.debug("模型切换检查失败（非致命）: %s", e)

        if not self.engine._gpu_worker_ready:
            if self.engine._gpu_config:
                from core.resource_manager import get_resource_manager

                resource_manager = get_resource_manager()
                await resource_manager.prepare_for_heavy_task("llm")
                async with self.engine._llm_setup_lock:
                    if not self.engine._gpu_worker_ready:
                        await asyncio.to_thread(
                            self.engine._setup_gpu_worker, self.engine._gpu_config
                        )

            if not self.engine._gpu_worker_ready:
                raise RuntimeError("C++ GPU Worker 未就绪，无法执行 LLM 推理任务")

        raw_max_tokens = kwargs.get("max_tokens")
        try:
            max_tokens = int(raw_max_tokens) if raw_max_tokens is not None else 2048
        except (TypeError, ValueError):
            max_tokens = 2048
        if max_tokens <= 0:
            max_tokens = 2048

        raw_temperature = kwargs.get("temperature")
        try:
            temperature = (
                float(raw_temperature) if raw_temperature is not None else 0.7
            )
        except (TypeError, ValueError):
            temperature = 0.7

        top_p = kwargs.get("top_p")
        if top_p is None and isinstance(self.engine._gpu_config, dict):
            top_p = self.engine._gpu_config.get("top_p")

        top_k = kwargs.get("top_k")
        if top_k is None and isinstance(self.engine._gpu_config, dict):
            top_k = self.engine._gpu_config.get("top_k")

        repetition_penalty = kwargs.get("repetition_penalty")
        if repetition_penalty is None:
            repetition_penalty = kwargs.get("repeat_penalty")
        if repetition_penalty is None and isinstance(self.engine._gpu_config, dict):
            repetition_penalty = self.engine._gpu_config.get("repetition_penalty")

        if n_ctx > 0:
            max_allowed_tokens = max(512, int(n_ctx * 0.8))
            if max_tokens > max_allowed_tokens:
                logger.warning(
                    "Clamping max_tokens from %s to %s based on n_ctx=%s",
                    max_tokens, max_allowed_tokens, n_ctx,
                )
                max_tokens = max_allowed_tokens

        # 防止 kwargs 中重复传递已提取的参数
        clean_kwargs = {k: v for k, v in kwargs.items()
                        if k not in ("max_tokens", "temperature", "top_p", "top_k",
                                      "repetition_penalty", "repeat_penalty",
                                      "min_p", "n_ctx", "max_chars",
                                      "prompt_to_text", "friendly_llm_error")}

        async for t in submit_cpp_llm_task(
            self.engine,
            prompt,
            n_ctx=n_ctx,
            max_chars=max_chars,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            friendly_llm_error=friendly_llm_error,
            logger=logger,
            **clean_kwargs,
        ):
            yield t
