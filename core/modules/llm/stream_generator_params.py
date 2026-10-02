"""流式生成的提示词估算、超时计算与上下文窗口重试（混入 StreamGenerator）。

从 ``core/modules/llm/stream_generator.py`` 拆出：
- ``_prompt_to_text`` / ``_calculate_first_token_timeout``：首 token 超时估算
- ``_parse_context_window_error`` / ``_retry_context_window_stream``：上下文窗口超限重试
- ``_adjust_timeout`` / ``_clamp_max_tokens_for_gguf``：生成参数按 n_ctx 调整

⚠️ 模块级 patch 语义：测试会 patch 门面模块的 ``re``（``sg.re.search``，
实为 patch ``re`` 模块自身的属性，全局生效），因此这里可以直接 ``import re``。
"""
from __future__ import annotations

import re

from core.services.scheduler.inference.inference_utils import (
    clamp_text,
    clamp_messages,
    rough_estimate_tokens_from_text,
)
from core.utils.logger import get_logger

from .inference_utils import strip_unexpected_llama_cpp_kwargs
from .utils import is_local_runtime_ready

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGeneratorParamsMixin:
    """提示词长度/超时估算与上下文窗口保护。"""

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
