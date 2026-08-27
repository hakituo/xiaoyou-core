#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
演示功能模块
处理演示相关的图片生成和事件发送
"""

from core.utils.logger import get_logger
import asyncio

import time
from typing import Optional, Dict, Any
from fastapi import WebSocket

logger = get_logger(__name__)


class DemoHandler:
    """演示功能处理器"""

    def __init__(self, adapter):
        self.adapter = adapter

    async def send_demo_event(
        self,
        websocket: WebSocket,
        event: str,
        data: Dict[str, Any],
        message_id: str,
        conversation_id: str,
        request_id: Optional[str] = None,
    ):
        """发送演示事件"""
        payload: Dict[str, Any] = {
            "type": "demo_event",
            "event": event,
            "data": data,
            "timestamp": time.time(),
            "message_id": message_id,
            "conversation_id": conversation_id,
        }
        if request_id:
            payload["request_id"] = request_id

        try:
            from core.utils.demo_utils import add_demo_log

            display_text = data.get("display_text") or event
            if event == "resource_matrix_update":
                status = "LOADED" if data.get("is_loaded") else "RELEASED"
                display_text = f"Resource {data.get('model_id')}: {status} ({data.get('memory_usage')}MB)"
            elif event == "stt_result":
                display_text = f"STT Result: {data.get('text')}"

            add_demo_log(display_text, "info")
        except Exception:
            pass

        await websocket.send_json(payload)

    async def poll_forge_progress(
        self,
        websocket: WebSocket,
        message_id: str,
        conversation_id: str,
        request_id: Optional[str],
        base_url: str,
        stop_task: asyncio.Task,
    ):
        """轮询 Forge 进度"""
        try:
            import aiohttp
        except Exception:
            return

        url = str(base_url).rstrip("/") + "/sdapi/v1/progress"

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while not stop_task.done():
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                obj = await resp.json()
                                progress = obj.get("progress")
                                eta = obj.get("eta_relative")
                                if progress is not None:
                                    await self.send_demo_event(
                                        websocket,
                                        "image_progress",
                                        {
                                            "progress": float(progress),
                                            "eta_relative": float(eta)
                                            if eta is not None
                                            else None,
                                        },
                                        message_id,
                                        conversation_id,
                                        request_id,
                                    )
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
        except Exception:
            return

    async def generate_image_pipeline(
        self,
        websocket: WebSocket,
        user_text: str,
        message_id: str,
        conversation_id: str,
        request_id: Optional[str],
        num_images: int = 1,
    ):
        """演示图片生成管道"""
        from config.integrated_config import get_settings

        settings = get_settings()

        try:
            num_images = int(num_images)
        except Exception:
            num_images = 1
        if num_images < 1:
            num_images = 1
        if num_images > 4:
            num_images = 4

        try:
            from core.resource_manager import get_resource_manager, ResourcePriority

            rm = get_resource_manager()
            if "image_gen_module" not in rm.models:
                rm.register_model(
                    model_id="image_gen_module",
                    model_type="image_gen",
                    priority=ResourcePriority.MEDIUM,
                    load_func=lambda: None,
                    unload_func=lambda: None,
                )
        except Exception as e:
            rm = None
            logger.error(f"注册生图模型失败: {e}")

        try:
            # 2. LLM 思考与润色阶段
            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "prompt",
                    "status": "started",
                    "display_text": "正在理解您的意图并润色提示词...",
                },
                message_id,
                conversation_id,
                request_id,
            )
            # 矩阵同步：LLM 加载中
            if rm is not None:
                try:
                    rm.mark_model_loaded("llm_engine", True)
                    if "llm_engine" in rm.models:
                        rm.models["llm_engine"].memory_usage_mb = 1850
                except Exception:
                    pass

            await self.send_demo_event(
                websocket,
                "resource_matrix_update",
                {
                    "model_id": "llm_engine",
                    "is_loaded": True,
                    "memory_usage": 1850,
                    "device": "GPU",
                },
                message_id,
                conversation_id,
                request_id,
            )

            await self.send_demo_event(
                websocket,
                "chat_response",
                {
                    "content": "好的，我正在为您构思画面。我会将您的描述转化为高精度的生图提示词，并协调 GPU 资源...",
                    "role": "assistant",
                },
                message_id,
                conversation_id,
                request_id,
            )

            from core.llm import get_llm_module
            from core.utils.json_utils import extract_json_object

            llm = get_llm_module()
            try:
                from core.utils.demo_utils import add_demo_log

                add_demo_log(
                    "LLM is constructing the visual prompt using DeepSeek-V3...", "info"
                )
            except Exception:
                pass

            from core.agents.chat_agent_components.persona_system.prompt.service_prompts import SD_PROMPT_ENGINEER_SYSTEM
            sys_prompt = SD_PROMPT_ENGINEER_SYSTEM
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": str(user_text or "").strip()},
            ]

            raw = await llm.chat(
                messages,
                temperature=0.4,
                max_new_tokens=220,
                conversation_id=conversation_id,
            )
            if isinstance(raw, dict):
                if raw.get("status") == "success":
                    raw = str(raw.get("response") or "").strip()
                else:
                    raw = ""
            else:
                raw = str(raw or "").strip()
            obj = extract_json_object(raw)
            prompt_en = ""
            prompt_cn = ""
            style = ""
            if isinstance(obj, dict):
                prompt_en = str(obj.get("prompt_en") or "").strip()
                prompt_cn = str(obj.get("prompt_cn") or "").strip()
                style = str(obj.get("style") or "").strip()

            if not prompt_en:
                prompt_en = raw
            if not prompt_en:
                raise RuntimeError("提示词生成失败")

            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "prompt",
                    "status": "done",
                    "prompt_en": prompt_en,
                    "prompt_cn": prompt_cn,
                    "style": style,
                    "display_text": f"提示词已就绪：{prompt_cn}",
                },
                message_id,
                conversation_id,
                request_id,
            )

            # 3. 资源分配与模型加载阶段
            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "resource",
                    "status": "started",
                    "display_text": "正在通过 C++ Scheduler 调度 GPU 资源...",
                },
                message_id,
                conversation_id,
                request_id,
            )

            if rm is not None:
                try:
                    await rm.prepare_for_heavy_task("image_gen")
                except Exception:
                    pass

                try:
                    llm_model = rm.models.get("llm_engine")
                    if llm_model and llm_model.is_loaded:
                        await rm.unload_model("llm_engine")
                        await self.send_demo_event(
                            websocket,
                            "resource_matrix_update",
                            {
                                "model_id": "llm_engine",
                                "is_loaded": False,
                                "memory_usage": 0,
                                "device": "GPU",
                            },
                            message_id,
                            conversation_id,
                            request_id,
                        )
                except Exception as e:
                    logger.warning(f"卸载LLM模型失败: {e}")

                try:
                    await rm.load_model("image_gen_module")
                    await self.send_demo_event(
                        websocket,
                        "resource_matrix_update",
                        {
                            "model_id": "image_gen_module",
                            "is_loaded": True,
                            "memory_usage": 2140,
                            "device": "GPU",
                        },
                        message_id,
                        conversation_id,
                        request_id,
                    )
                except Exception as e:
                    logger.error(f"加载生图模型失败: {e}")

            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "resource",
                    "status": "done",
                    "display_text": "GPU 资源已就绪，正在启动图像生成...",
                },
                message_id,
                conversation_id,
                request_id,
            )

            # 4. 图像生成阶段
            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "generation",
                    "status": "started",
                    "display_text": "正在生成图像...",
                },
                message_id,
                conversation_id,
                request_id,
            )

            from core.image.image_manager import (
                get_image_manager,
                ImageGenerationConfig,
            )

            manager = await get_image_manager()
            config = ImageGenerationConfig(
                width=settings.model.image_gen_width,
                height=settings.model.image_gen_height,
                num_inference_steps=settings.model.image_gen_steps,
            )

            result = await manager.generate_image(
                prompt=prompt_en,
                model_id=settings.model.default_image_model,
                config=config,
                save_to_file=True,
            )

            if not result.get("prompt"):
                result["prompt"] = prompt_en

            payload = await self.adapter._prepare_image_payload(result)

            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "generation",
                    "status": "done",
                    "display_text": "图像生成完成！",
                },
                message_id,
                conversation_id,
                request_id,
            )

            await self.send_demo_event(
                websocket,
                "image_result",
                payload,
                message_id,
                conversation_id,
                request_id,
            )

            # 5. 资源释放阶段
            await self.send_demo_event(
                websocket,
                "pipeline_stage",
                {
                    "stage": "cleanup",
                    "status": "started",
                    "display_text": "正在释放 GPU 资源...",
                },
                message_id,
                conversation_id,
                request_id,
            )

            if rm is not None:
                try:
                    await rm.unload_model("image_gen_module")
                    await self.send_demo_event(
                        websocket,
                        "resource_matrix_update",
                        {
                            "model_id": "image_gen_module",
                            "is_loaded": False,
                            "memory_usage": 0,
                            "device": "GPU",
                        },
                        message_id,
                        conversation_id,
                        request_id,
                    )
                except Exception as e:
                    logger.warning(f"卸载生图模型失败: {e}")

                try:
                    rm.mark_model_loaded("llm_engine", False)
                except Exception:
                    pass

                try:
                    add_demo_log(
                        "Scheduler: All demo resources released. GPU Memory reclaimed.",
                        "info",
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            await self.send_demo_event(
                websocket,
                "pipeline_error",
                {
                    "message": f"演示流程出错: {str(e)}",
                    "details": {"error_type": type(e).__name__},
                },
                message_id,
                conversation_id,
                request_id,
            )
        finally:
            try:
                current = asyncio.current_task()
                existing_task = self.adapter._image_generation_tasks.get(message_id)
                if existing_task is current:
                    self.adapter._image_generation_tasks.pop(message_id, None)
            except Exception:
                pass
