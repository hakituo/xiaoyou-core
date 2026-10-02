"""WebSocket 演示消息编排。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import WebSocket

from core.utils.logger import get_logger

logger = get_logger(__name__)


def _adapter_asyncio() -> Any:
    from .. import adapter

    return adapter.asyncio


class WebSocketDemoFlowMixin:
    """解析演示消息并启动异步生图流水线。"""

    async def _handle_demo_message(self, websocket: WebSocket, message: dict) -> None:
        msg_type = message.get("type")
        message_id = message.get("message_id") or str(int(time.time() * 1000))
        conversation_id = (
            message.get("conversation_id") or getattr(websocket, "user_id", None) or "demo"
        )
        request_id = message.get("request_id") or message_id
        text = str(message.get("content") or message.get("text") or "").strip()
        num_images = message.get("num_images")

        try:
            from core.services.life_simulation.service import get_life_simulation_service

            get_life_simulation_service().update_interaction(xp_gain=0)
        except Exception:  # noqa: BLE001
            logger.debug("更新生活模拟交互状态失败", exc_info=True)

        if num_images is None:
            num_images = message.get("numImages")
        if num_images is None:
            num_images = message.get("num")
        try:
            num_images = int(num_images) if num_images is not None else 1
        except Exception:  # noqa: BLE001
            logger.debug("解析num_images参数失败，使用默认值1", exc_info=True)
            num_images = 1

        if msg_type == "demo_voice_input":
            await self.demo.send_demo_event(
                websocket,
                "stt_started",
                {"status": "listening"},
                message_id,
                conversation_id,
                request_id,
            )
            await _adapter_asyncio().sleep(0.5)

        await websocket.send_json(
            {
                "type": "demo_event",
                "event": "ack",
                "data": {"accepted": True, "mode": "image"},
                "timestamp": time.time(),
                "message_id": message_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )
        if not text:
            await self.demo.send_demo_event(
                websocket,
                "pipeline_error",
                {"message": "请输入有效的生图意图"},
                message_id,
                conversation_id,
                request_id,
            )
            return

        existing_task = self._image_generation_tasks.get(message_id)
        if existing_task and not existing_task.done():
            await self.demo.send_demo_event(
                websocket,
                "pipeline_error",
                {"message": "当前生图任务仍在进行中"},
                message_id,
                conversation_id,
                request_id,
            )
            return
        task = _adapter_asyncio().create_task(
            self.demo.generate_image_pipeline(
                websocket=websocket,
                user_text=text,
                message_id=message_id,
                conversation_id=conversation_id,
                request_id=request_id,
                num_images=num_images,
            )
        )
        self._image_generation_tasks[message_id] = task
