#!/usr/bin/env python
# -*- coding: utf-8 -*-

from core.utils.logger import get_logger
import asyncio
import logging
import os
import base64
import aiofiles
from typing import List, Dict, Any

# 核心模块
from memory.weighted_memory_manager import WeightedMemoryManager
from config.integrated_config import get_settings
from core.llm import get_llm_module

# 图像组件
try:
    from core.image.image_manager import get_image_manager, ImageGenerationConfig

    image_generation_available = True
except ImportError:
    image_generation_available = False

# 尝试导入STT管理器
try:
    from core.voice.stt_engine import get_stt_manager

    stt_available = True
except ImportError:
    stt_available = False

# 配置日志器
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = get_logger(__name__)


class TRMAdapter:
    """
    TRM（文本、识别、多媒体）适配器
    提供统一接口访问LLM、STT和图像生成能力。
    """

    def __init__(self):
        """
        Initialize TRM Adapter
        """
        self.stt_manager = None
        self._initialize_stt_if_available()
        # 启动时验证配置
        try:
            get_settings().validate()
        except Exception as e:
            logger.warning(f"Configuration validation warning: {e}")
        logger.info("TRM Adapter initialized")

    def _initialize_stt_if_available(self):
        """
        Initialize STT manager if available
        """
        if stt_available:
            try:
                # STT管理器将在首次使用时异步初始化
                logger.info("STT functionality available, will initialize when needed")
            except Exception as e:
                logger.error(f"Failed to initialize STT manager: {e}")

    async def _ensure_stt_manager(self):
        """
        Ensure STT manager is initialized
        """
        if stt_available and not self.stt_manager:
            try:
                self.stt_manager = get_stt_manager()
                await self.stt_manager.initialize()
                logger.info("STT Manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to get STT manager: {e}")
                raise

    # =======================================================
    # 图像生成与分析辅助
    # =======================================================

    async def _process_image_file(self, file_path):
        """
        Process image file for analysis (Async)
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"Image file not found: {file_path}")
                return None

            settings = get_settings()
            max_size = settings.server.max_upload_image_size
            if os.path.getsize(file_path) > max_size:
                logger.error(
                    f"Image file too large: {file_path} (Max: {max_size} bytes)"
                )
                return None

            async with aiofiles.open(file_path, "rb") as f:
                image_data = await f.read()

            encoded_image = await asyncio.to_thread(
                lambda: base64.b64encode(image_data).decode("utf-8")
            )
            return encoded_image
        except Exception as e:
            logger.error(f"Error processing image file: {e}")
            return None

    def _is_image_query(self, text):
        """
        Check if the query contains image ANALYSIS keywords
        """
        return False  # 分析检测最终也应移至意图服务

    async def _detect_image_generation_intent(self, text):
        """
        Detect if the query is an image generation request using semantic intent service.
        """
        text = str(text or "").strip()
        if not text:
            return False, ""

        try:
            from core.services.intent.service import classify_intent

            res = await classify_intent(text, candidates=["IMAGE_GEN", "NONE"])
            intent = res.get("intent")
            confidence = res.get("confidence", 0)

            if intent == "IMAGE_GEN" and confidence > 0.5:
                prompt = res.get("slots", {}).get("prompt", "").strip()
                if not prompt or len(prompt) <= 1:
                    prompt = text
                return True, prompt
        except ImportError:
            pass  # Intent service not available
        except Exception as e:
            logger.warning(f"Semantic intent classification failed: {e}")

        return False, ""

    async def _handle_image_generation(self, prompt):
        """
        Handle image generation request with a given prompt
        """
        if not image_generation_available:
            return "抱歉，图像生成功能当前不可用。"

        try:
            manager = await get_image_manager()

            if not prompt:
                prompt = "A beautiful artistic image"

            logger.info(f"Processing image generation. Prompt: {prompt}")

            settings = get_settings()
            target_model = settings.model.default_image_model
            fallback_model = settings.model.fallback_image_model

            available_models = await manager.get_available_models()
            if not available_models:
                logger.info(f"No models loaded. Attempting to load {target_model}...")
                try:
                    await manager.load_model(target_model)
                except Exception as e:
                    logger.error(f"Failed to load default model: {e}")
                    logger.info(
                        f"Attempting to load fallback model {fallback_model}..."
                    )
                    await manager.load_model(fallback_model)
                    target_model = fallback_model
            else:
                target_model = list(available_models.keys())[0]

            result = await manager.generate_image(
                prompt=prompt,
                model_id=target_model,
                config=ImageGenerationConfig(
                    width=settings.model.image_gen_width,
                    height=settings.model.image_gen_height,
                    num_inference_steps=settings.model.image_gen_steps,
                ),
            )

            if result["success"]:
                image_path = result["image_path"]
                return f"已为您生成图片：{prompt}\n文件保存于：{image_path}"
            else:
                return f"图片生成失败：{result.get('error', 'Unknown error')}"

        except Exception as e:
            logger.error(f"Image generation error: {e}", exc_info=True)
            return f"处理图片生成请求时出错：{str(e)}"

    def _normalize_messages(self, raw_messages):
        normalized = []
        for msg in raw_messages or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "user").strip().lower()
            content = msg.get("content")
            if content is None:
                continue
            content_str = str(content)
            if role == "user" and content_str.startswith("User says: "):
                content_str = content_str.replace("User says: ", "", 1)
            if role not in ("user", "assistant", "system"):
                role = "user"
            normalized.append({"role": role, "content": content_str})
        return normalized

    # =======================================================
    # 主查询逻辑
    # =======================================================

    async def query_llm_async(
        self, user_id: str, prompt: str, history: List[Dict[str, Any]]
    ) -> str:
        """
        Asynchronously query LLM model
        """
        try:
            logger.info(f"[TRM] Processing LLM request for user {user_id}")

            # 命令处理已收口到 Aveline command_handler（见 core/services/aveline/），
            # 旧版 core/services/command/handler.py 已删除。

            # 1. Check Image Generation Intent
            is_gen, gen_prompt = await self._detect_image_generation_intent(prompt)
            if is_gen:
                return await self._handle_image_generation(gen_prompt)

            # 3. Prepare Context for LLM
            user_content = f"User says: {prompt}"

            # 检查历史中的图像分析上下文
            if self._is_image_query(prompt):
                image_paths = []
                for msg in reversed(history):
                    if (
                        msg.get("role") == "user"
                        and "image" in msg.get("content", "").lower()
                    ):
                        if "file_path" in msg.get("content", ""):
                            # 匹配原始实现的占位逻辑
                            image_paths.append("/path/to/recent/image.jpg")
                        break

                if image_paths:
                    encoded_image = await self._process_image_file(image_paths[0])
                    if encoded_image:
                        user_content += "\n[Image analysis request]"
                        logger.info("Processing image analysis request")

            # 构建LLM消息
            # 直接使用传入的历史，追加当前用户消息
            # 注意：从handler.py传入的历史通常不包含当前消息？
            # 假设历史是"之前的"历史。

            current_history = history + [{"role": "user", "content": user_content}]
            messages = self._normalize_messages(current_history)

            if self._is_image_query(prompt):
                from core.agents.chat_agent_components.persona_system.prompt.service_prompts import IMAGE_ANALYSIS_SYSTEM_PROMPT
                system_prompt = {
                    "role": "system",
                    "content": IMAGE_ANALYSIS_SYSTEM_PROMPT,
                }
                messages = [system_prompt] + messages

            # 4. Call LLM
            settings = get_settings()
            llm = get_llm_module()

            max_tokens_cfg = getattr(settings.model, "max_new_tokens", None)
            max_tokens = int(max_tokens_cfg) if max_tokens_cfg and int(max_tokens_cfg) > 0 else None
            temperature = float(getattr(settings.model, "temperature", 0.7) or 0.7)
            top_p = float(getattr(settings.model, "top_p", 0.95) or 0.95)

            response = await llm.chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )

            if isinstance(response, dict):
                if response.get("status") == "success":
                    response_str = str(response.get("response") or "")
                else:
                    response_str = str(response.get("error") or "")
            else:
                response_str = str(response or "")
            
            # 过滤[VOICE]标签
            if "[VOICE]" in response_str:
                response_str = response_str.replace("[VOICE]", "")

            logger.info(f"[TRM] Got LLM response, length: {len(response_str)} chars")
            return response_str

        except Exception as e:
            logger.error(f"[TRM] LLM query failed: {e}", exc_info=True)
            return f"抱歉，我在处理您的请求时遇到了问题。错误详情: {str(e)}"

    async def transcribe_audio_async(self, audio_data: bytes) -> str:
        """
        Asynchronously transcribe audio data
        """
        try:
            logger.info(
                f"[TRM] Processing audio transcription, size: {len(audio_data)} bytes"
            )

            if not stt_available:
                raise RuntimeError("STT capability not available")

            await self._ensure_stt_manager()

            try:
                result = await self.stt_manager.transcribe(audio_data, language="zh")

                transcription = result.get("text", "")
                error = result.get("error")

                if error:
                    logger.error(f"[TRM] STT Engine Error: {error}")
                    return f"STT Error: {error}"

                logger.info(f"[TRM] Transcription success: {transcription[:50]}...")
                return transcription

            except Exception as e:
                logger.error(f"[TRM] Transcription process error: {e}")
                raise

        except Exception as e:
            logger.error(f"[TRM] Audio transcription failed: {e}", exc_info=True)
            return f"语音识别失败: {str(e)}"

    async def close(self):
        """
        Close adapter and release resources
        """
        try:
            if self.stt_manager:
                await self.stt_manager.shutdown()
                self.stt_manager = None
                logger.info("TRM Adapter resources released")
        except Exception as e:
            logger.error(f"Error closing TRM Adapter: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# 全局适配器实例
global_trm_adapter = None


def get_trm_adapter() -> TRMAdapter:
    """
    Get global TRM Adapter instance
    """
    global global_trm_adapter

    if global_trm_adapter is None:
        global_trm_adapter = TRMAdapter()

    return global_trm_adapter


__all__ = ["TRMAdapter", "get_trm_adapter"]


if __name__ == "__main__":

    async def test_adapter():
        adapter = TRMAdapter()
        try:
            response = await adapter.query_llm_async("test_user", "你好，你是谁？", [])
            print(f"LLM Test Response: {response}")
        except Exception as e:
            print(f"LLM Test Failed: {e}")
        await adapter.close()

    asyncio.run(test_adapter())
