"""WebSocket 图像生成执行与结果序列化。"""

from __future__ import annotations

import base64
import io
import os
import time
from typing import Any, Dict

from fastapi import WebSocket
from PIL import Image

from core.utils.logger import get_logger

logger = get_logger(__name__)


def _adapter_asyncio() -> Any:
    from .. import adapter

    return adapter.asyncio


class WebSocketImageGenerationMixin:
    """执行图像生成并构建可发送的图片结果。"""

    async def _generate_image_and_send(
        self,
        websocket: WebSocket,
        raw_prompt: str,
        message_id: str,
        conversation_id: str,
    ) -> None:
        try:
            prompt = str(raw_prompt or "")
        except Exception:  # noqa: BLE001
            logger.debug("解析图片生成prompt失败", exc_info=True)
            return
        if "|" in prompt:
            prompt = prompt.split("|", 1)[0].strip()
        prompt = prompt.strip()
        if not prompt:
            return

        try:
            from core.utils.resource_lock import get_resource_lock

            gate_status = get_resource_lock().get_status()
            position = 1
            if bool(gate_status.get("enabled")):
                position = (
                    int(gate_status.get("active") or 0)
                    + int(gate_status.get("waiting") or 0)
                    + 1
                )
            if position > 1:
                try:
                    await websocket.send_json(
                        {
                            "type": "image_status",
                            "data": {"status": "queued", "prompt": prompt, "position": position},
                            "timestamp": time.time(),
                            "message_id": message_id,
                            "conversation_id": conversation_id,
                        }
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("发送图片排队状态失败", exc_info=True)
            try:
                await websocket.send_json(
                    {
                        "type": "image_status",
                        "data": {"status": "started", "prompt": prompt},
                        "timestamp": time.time(),
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:  # noqa: BLE001
                logger.debug("发送图片开始状态失败", exc_info=True)

            from config.integrated_config import get_settings
            from core.image.image_manager import ImageGenerationConfig, get_image_manager

            settings = get_settings()
            manager = await get_image_manager()
            config = ImageGenerationConfig(
                width=settings.model.image_gen_width,
                height=settings.model.image_gen_height,
                num_inference_steps=settings.model.image_gen_steps,
            )
            async with get_resource_lock().acquire("IMG", reject_if_full=True):
                result = await manager.generate_image(
                    prompt=prompt,
                    model_id=settings.model.default_image_model,
                    config=config,
                    save_to_file=True,
                )
            if not result.get("prompt"):
                result["prompt"] = prompt
            payload = await self._prepare_image_payload(result)
            await websocket.send_json(
                {
                    "type": "image_result",
                    "data": payload,
                    "timestamp": time.time(),
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            try:
                error_text = str(exc)
                lowered = error_text.lower()
                if "out of memory" in lowered or "cuda" in lowered or "显存" in error_text:
                    try:
                        from core.resource_manager import get_global_resource_manager
                        from core.utils.async_tasks import spawn_bg_task

                        resource_manager = await get_global_resource_manager()
                        spawn_bg_task(
                            resource_manager.optimize_resources(), name="cuda_oom_optimize"
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug("CUDA OOM后资源优化失败", exc_info=True)
                from core.api.error_response import map_exception_to_error_code

                error_code = map_exception_to_error_code(exc)
                await websocket.send_json(
                    {
                        "type": "image_result",
                        "data": {
                            "success": False,
                            "prompt": prompt,
                            "error_code": error_code.value,
                            "message": "图像生成失败",
                            "error": "图像生成失败",
                            "details": {"error_type": type(exc).__name__},
                        },
                        "timestamp": time.time(),
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:  # noqa: BLE001
                logger.debug("发送图像生成错误响应失败", exc_info=True)
        finally:
            try:
                current = _adapter_asyncio().current_task()
                existing_task = self._image_generation_tasks.get(message_id)
                if existing_task is current:
                    self._image_generation_tasks.pop(message_id, None)
            except Exception:  # noqa: BLE001
                logger.debug("清理图像生成任务失败", exc_info=True)

    async def _prepare_image_payload(self, result: Dict[str, Any]) -> Dict[str, Any]:
        from core.image.image_utils import get_image_url

        payload: Dict[str, Any] = {
            "success": bool(result.get("success")),
            "prompt": result.get("prompt"),
        }
        image_path = result.get("image_path")
        if image_path:
            payload["image_path"] = image_path
            payload["image_url"] = get_image_url(image_path)

            def generate_thumbnail() -> str | None:
                if not os.path.exists(image_path):
                    return None
                with Image.open(image_path) as image:
                    image.thumbnail((128, 128))
                    if image.mode in ("RGBA", "P"):
                        image = image.convert("RGB")
                    buffered = io.BytesIO()
                    image.save(buffered, format="JPEG", quality=60)
                    return base64.b64encode(buffered.getvalue()).decode("utf-8")

            try:
                thumbnail = await _adapter_asyncio().to_thread(generate_thumbnail)
                if thumbnail:
                    payload["thumbnail_base64"] = f"data:image/jpeg;base64,{thumbnail}"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to generate thumbnail: %s", exc)

        images = result.get("images")
        if isinstance(images, list):
            output_images = []
            for item in images:
                if not isinstance(item, dict):
                    continue
                path = item.get("image_path")
                if path:
                    output_images.append({"image_path": path, "url": get_image_url(path)})
            if output_images:
                payload["images"] = output_images
                if "image_url" not in payload and output_images[0].get("url"):
                    payload["image_url"] = output_images[0]["url"]
        return payload
