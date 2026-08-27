"""Active Care 主动消息生成器。

负责 LLM 调用、生成参数、超时兜底与 reasoning 泄漏处理。
执行器只关心“拿到可发送内容”，不再直接管理模型生成细节。
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.llm import get_llm_module
from core.services.active_care.postprocess.postprocessor import ActiveCarePostprocessor
from core.services.active_care.postprocess.leak_detector import LeakDetector
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class ActiveCareResponseGenerator:
    """生成 Active Care 主动消息内容。"""

    def __init__(self, settings):
        self.settings = settings

    async def generate(
        self,
        *,
        model_user_input: str,
        sys_prompt: str,
        model_hint: str,
        dynamic_prompt: str = "",
    ) -> Dict[str, Any]:
        """生成 Active Care 响应。

        缓存优化：system message 只放静态内容，dynamic_prompt 拼入 user message 前缀。
        """
        llm = get_llm_module()
        model_path = self._resolve_model_path(model_hint)
        temperature, max_tokens = self._get_generation_params()
        user_content = ""
        if dynamic_prompt:
            user_content += dynamic_prompt + "\n\n"
        user_content += str(model_user_input or "")
        messages = [
            {"role": "system", "content": str(sys_prompt or "")},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = await asyncio.wait_for(
                llm.chat(
                    messages,
                    temperature=temperature,
                    max_new_tokens=max_tokens,
                    model_path=model_path,
                ),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            return await self._handle_llm_timeout(messages, temperature, max_tokens, model_path)

        if isinstance(raw, dict) and raw.get("reasoning_only"):
            logger.info(
                "Active Care: 模型返回 reasoning_only 标志（reasoning_split模式），"
                "原始模型=%s，推理长度=%d。直接走 fallback。",
                model_path,
                len(raw.get("reasoning_text") or ""),
            )
            return await self._handle_reasoning_only_response(
                str(raw.get("reasoning_text") or raw.get("response") or ""),
                messages,
                temperature,
                max_tokens,
                model_path,
            )

        text = self.extract_text_from_llm_response(raw)
        if text.startswith("[DEBUG_ERROR]"):
            logger.error("Active Care generated error response: %s", text)
            return {"content": "", "full_content": "", "message_type": "text", "error": text}

        return await self._handle_reasoning_only_response(
            text, messages, temperature, max_tokens, model_path
        )

    @staticmethod
    def extract_text_from_llm_response(raw) -> str:
        """从 LLM 响应中提取正文。"""
        if isinstance(raw, dict):
            if raw.get("status") == "success":
                return str(raw.get("response") or raw.get("text") or "").strip()
            if raw.get("response"):
                return str(raw.get("response") or "").strip()
            if raw.get("error"):
                return f"[DEBUG_ERROR] {raw.get('error')}"
            return ""
        return str(raw or "").strip()

    def _resolve_model_path(self, model_hint: str) -> Optional[str]:
        """解析模型路径。"""
        from config.model_config import resolve_active_care_model_path

        return resolve_active_care_model_path(
            model_hint=model_hint,
            model_type="content",
            persona_name="",
            settings=self.settings,
            llm_module=None,
        ) or None

    def _get_generation_params(self) -> Tuple[float, int]:
        """获取生成参数。"""
        temperature = float(
            get_active_care_config(
                "active_care_generation_temperature", default=0.65, settings=self.settings
            )
            or 0.65
        )
        max_tokens = int(
            get_active_care_config(
                "active_care_generation_max_tokens", default=400, settings=self.settings
            )
            or 400
        )
        return temperature, max_tokens

    async def _handle_llm_timeout(
        self,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        model_path: Optional[str],
    ) -> Dict[str, Any]:
        """处理 LLM 超时。"""
        logger.error("Active Care: LLM generation timed out (>45s) with model=%s.", model_path)
        fallback_model = None
        try:
            from config.model_config import get_chat_model

            fallback_model = get_chat_model("aveline")
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("获取fallback模型配置失败", exc_info=True)

        if fallback_model and fallback_model != model_path:
            logger.info("Active Care: Retrying with fallback model=%s", fallback_model)
            try:
                llm = get_llm_module()
                raw = await asyncio.wait_for(
                    llm.chat(
                        messages,
                        temperature=temperature,
                        max_new_tokens=max_tokens,
                        model_path=fallback_model,
                    ),
                    timeout=35.0,
                )
                content = self.extract_text_from_llm_response(raw)
                return {"content": content, "full_content": content, "message_type": "text"}
            except asyncio.TimeoutError:
                logger.error("Active Care: Fallback model also timed out. Aborting.")
                return {
                    "content": "",
                    "full_content": "",
                    "message_type": "text",
                    "error": "llm_timeout_fallback",
                }
            except Exception as e:
                logger.error("Active Care: Fallback model failed: %s", e)
                return {"content": "", "full_content": "", "message_type": "text", "error": str(e)}

        return {"content": "", "full_content": "", "message_type": "text", "error": "llm_timeout"}

    async def _handle_reasoning_only_response(
        self,
        text: str,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        model_path: Optional[str],
    ) -> Dict[str, Any]:
        """处理包含 reasoning 的响应。"""
        stripped = ActiveCarePostprocessor.strip_reasoning_segments(text)
        if not stripped.strip():
            logger.warning(
                "Active Care: 模型只返回了推理内容（无实际消息），原始模型=%s，"
                "推理长度=%d，剥离后长度=%d。尝试 fallback 模型重试。",
                model_path,
                len(text),
                len(stripped),
            )
            return await self._try_fallback_for_reasoning(
                messages, temperature, max_tokens, model_path
            )

        if LeakDetector.looks_like_prompt_or_reasoning_dump(stripped):
            safe_msg = LeakDetector.extract_safe_message_from_dump(stripped)
            if (
                safe_msg
                and safe_msg.strip()
                and not LeakDetector.looks_like_prompt_or_reasoning_dump(safe_msg)
            ):
                logger.info(
                    "Active Care: 从推理泄漏中提取到安全消息，长度=%d，预览=%s",
                    len(safe_msg),
                    safe_msg[:80],
                )
                return {"content": safe_msg, "full_content": safe_msg, "message_type": "text"}
            logger.warning(
                "Active Care: 剥离后的内容仍像推理泄漏（原始模型=%s，长度=%d），走 fallback。",
                model_path,
                len(stripped),
            )
            return await self._try_fallback_for_reasoning(
                messages, temperature, max_tokens, model_path
            )

        return {"content": stripped, "full_content": stripped, "message_type": "text"}

    async def _try_fallback_for_reasoning(
        self,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        model_path: Optional[str],
    ) -> Dict[str, Any]:
        """推理内容泄漏时尝试 fallback 模型。"""
        fallback_model = await self._get_fallback_model()
        if fallback_model and fallback_model != model_path:
            try:
                llm = get_llm_module()
                logger.info("Active Care: 使用 fallback 模型=%s 重试生成", fallback_model)
                raw = await asyncio.wait_for(
                    llm.chat(
                        messages,
                        temperature=temperature,
                        max_new_tokens=max_tokens,
                        model_path=fallback_model,
                    ),
                    timeout=35.0,
                )
                text = self.extract_text_from_llm_response(raw)
                stripped = ActiveCarePostprocessor.strip_reasoning_segments(text)
                if stripped.strip() and not LeakDetector.looks_like_prompt_or_reasoning_dump(stripped):
                    logger.info(
                        "Active Care: fallback 模型成功生成内容，长度=%d，预览=%s",
                        len(stripped),
                        stripped[:80],
                    )
                    return {"content": stripped, "full_content": stripped, "message_type": "text"}
                logger.warning("Active Care: fallback 模型返回的内容仍像推理泄漏或为空")
            except Exception as e:
                logger.error("Active Care: Fallback model failed: %s", e)
        else:
            if not fallback_model:
                logger.warning("Active Care: 无可用的 fallback 模型")
            elif fallback_model == model_path:
                logger.warning("Active Care: fallback 模型与原始模型相同，跳过重试")

        return {
            "content": "",
            "full_content": "",
            "message_type": "text",
            "error": "reasoning_only_no_fallback",
        }

    async def _get_fallback_model(self) -> Optional[str]:
        """获取后备模型路径。"""
        try:
            from config.model_config import get_fallback_model_for_active_care

            fallback = get_fallback_model_for_active_care()
            if fallback:
                return fallback
        except Exception as e:
            logger.warning("Active Care: Failed to load fallback model from config: %s", e)
        return None
