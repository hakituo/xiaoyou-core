#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视觉/图像服务模块。

负责图像分析与生成相关任务：
- analyze_screen：使用视觉模型分析屏幕内容
- _process_image_data：将图像数据转换为 PIL Image（纯函数）
- _execute_vision_task：执行视觉任务（多模态 LLM 优先，回退到 VisionModule）
- _execute_multimodal_llm_task：通过多模态 LLM 执行图像理解
- _generate_image_task：通过 SD 适配器生成图像

所有带 service 参数的函数为模块级函数，第一参数为 `service`（AvelineService 实例），
与 stream_orchestrator.py 风格保持一致。
"""
from __future__ import annotations

import asyncio
import base64
import io
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

from core.utils.logger import get_logger

try:
    from PIL import Image
except ImportError:
    Image = None

logger = get_logger("AVELINE_SERVICE")


async def analyze_screen(
    service: Any,
    image_data: Union[str, bytes],
    prompt: str = "描述屏幕上的内容",
    **kwargs,
) -> Dict[str, Any]:
    """Analyze screen content using Vision Model"""
    start_time = time.time()
    request_id = str(uuid.uuid4())

    try:
        if not Image:
            return {"status": "error", "error": "缺少依赖：Pillow（PIL）未安装"}

        image = None
        if isinstance(image_data, str):
            token = str(image_data or "").strip().strip('"').strip("'")
            resolved_path = None

            if token:
                if token.startswith("file://"):
                    token = token[7:]

                candidates = [token]
                if token.startswith("/"):
                    candidates.append(token.lstrip("/"))

                for cand in candidates:
                    p = Path(cand)
                    if not p.is_absolute():
                        try:
                            p = (service._get_project_root() / p).resolve()
                        except Exception:
                            pass
                    if p.exists() and p.is_file():
                        resolved_path = p
                        break

                if resolved_path is None:
                    token_lower = token.lower()
                    if token_lower.startswith(
                        ("output/", "/output/", "static/", "/static/")
                    ) or token_lower.endswith(
                        (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
                    ):
                        p2 = Path(token.lstrip("/"))
                        if not p2.is_absolute():
                            try:
                                p2 = (service._get_project_root() / p2).resolve()
                            except Exception:
                                p2 = p2
                        if p2.exists() and p2.is_file():
                            resolved_path = p2

            if resolved_path is not None:

                def _read_bytes() -> bytes:
                    return resolved_path.read_bytes()

                image_bytes = await asyncio.to_thread(_read_bytes)
                image = _process_image_data(image_bytes)
            else:
                image = _process_image_data(image_data)
        else:
            image = _process_image_data(image_data)
        if not image:
            raise ValueError("Invalid image data")

        # Execute vision task
        response = await _execute_vision_task(service, image, prompt)

        if isinstance(response, dict) and response.get("status") == "error":
            return response

        response_text = (
            response
            if isinstance(response, str)
            else response.get("description", "")
        )
        if not response_text and isinstance(response, dict):
            response_text = response.get("text", "")
        if not response_text and isinstance(response, dict):
            response_text = response.get("response", "")

        return {
            "status": "success",
            "description": response_text,
            "request_id": request_id,
            "processing_time": time.time() - start_time,
        }

    except Exception as e:
        logger.error(f"Screen analysis failed: {e}")
        return {"status": "error", "error": str(e)}


def _process_image_data(image_data: Union[str, bytes]):
    """Helper to process image data into PIL Image"""
    try:
        if isinstance(image_data, bytes):
            return Image.open(io.BytesIO(image_data)).convert("RGB")
        elif isinstance(image_data, str):
            if "base64," in image_data:
                image_data = image_data.split("base64,")[1]
            image_bytes = base64.b64decode(image_data)
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        logger.error(f"Image processing failed: {e}")
    return None


async def _execute_vision_task(service: Any, image, prompt):
    llm_result = await _execute_multimodal_llm_task(service, image, prompt)
    if isinstance(llm_result, dict) and llm_result.get("status") == "success":
        return llm_result
    try:
        from core.core_engine.service_singletons import get_vision_module

        vm = get_vision_module()
        if vm is None:
            return {"status": "error", "error": "VisionModule 未初始化"}
        return await vm.describe_image(image, prompt)
    except ImportError:
        return {"status": "error", "error": "VisionModule not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _execute_multimodal_llm_task(service: Any, image, prompt):
    try:
        llm_conf = getattr(getattr(service.settings, "model", None), "llm", None) if service.settings else None
        if llm_conf is None:
            return {"status": "skip"}
        provider = str(getattr(llm_conf, "provider", "") or "").strip().lower()
        base_url = str(getattr(llm_conf, "base_url", "") or "").strip().lower()
        model_name = str(getattr(llm_conf, "model", "") or "").strip()
        if provider != "custom" or "integrate.api.nvidia.com" not in base_url:
            return {"status": "skip"}
        if Image is None or image is None:
            return {"status": "skip"}

        def _to_data_url() -> str:
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"

        image_data_url = await asyncio.to_thread(_to_data_url)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": str(prompt or "描述这张图片的内容")},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ]

        from core.llm import get_llm_module

        llm = get_llm_module()
        kwargs: Dict[str, Any] = {"max_tokens": 1024}
        if model_name:
            kwargs["model"] = model_name
            kwargs["model_path"] = f"cloud:custom:{model_name}"
        response = await llm.chat(messages, **kwargs)
        if isinstance(response, str) and response.strip().startswith("Error:"):
            return {"status": "error", "error": response}
        return {"status": "success", "response": str(response)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _generate_image_task(
    service: Any,
    prompt: str,
    model_name: Optional[str] = None,
    vae_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Async wrapper for image generation"""

    def _task():
        try:
            from core.modules.image.sd_adapter import create_sd_adapter

            # Initialize adapter with default config
            adapter = create_sd_adapter()

            # Check/Load model (ensure at least something is loaded)
            if not adapter.load_model():
                return {"status": "error", "error": "Failed to load SD model"}

            # Generate
            # Use 1024x1024 as requested by user
            result = adapter.generate_image(
                prompt=prompt,
                model_name=model_name,
                vae_name=vae_name,
                width=1024,
                height=1536,
                num_inference_steps=20,
            )
            return result
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return {"status": "error", "error": str(e)}

    return await asyncio.to_thread(_task)
