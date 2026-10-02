"""WebSocket 资源状态广播。"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict

from core.utils.logger import get_logger

logger = get_logger(__name__)


class WebSocketResourceBroadcastMixin:
    """聚合资源状态、去重并广播给活跃连接。"""

    async def _handle_resource_update(self, **kwargs: Any) -> None:
        try:
            if not self.websocket_manager:
                return
            stats = self.websocket_manager.get_stats()
            if stats.get("active_connections", 0) == 0:
                return

            from core.resource_manager import get_resource_manager

            resource_manager = get_resource_manager()
            models_data = {
                model_id: {
                    "device": getattr(model, "device", "GPU"),
                    "priority": model.priority.name,
                    "is_loaded": model.is_loaded,
                    "memory_usage": getattr(model, "vram_usage_mb", 0),
                }
                for model_id, model in resource_manager.models.items()
            }
            try:
                from config.integrated_config import get_settings

                settings = get_settings()
                if settings and settings.model and settings.model.llm:
                    models_data["llm"] = {
                        "provider": settings.model.llm.provider,
                        "model": settings.model.llm.model,
                        "text_path": settings.model.text_path,
                    }
            except Exception:  # noqa: BLE001
                logger.debug("注入LLM设置到模型数据失败", exc_info=True)

            gpu_info = resource_manager.monitor.get_gpu_memory_usage()
            gpu_gate_status = None
            scheduler_status = None
            try:
                from core.utils.resource_lock import get_resource_lock

                gpu_gate_status = get_resource_lock().get_status()
            except Exception:  # noqa: BLE001
                logger.debug("获取GPU gate状态失败", exc_info=True)
            try:
                from core.services.scheduler.cpp_scheduler_engine import get_scheduler_engine

                scheduler_engine = get_scheduler_engine()
                if scheduler_engine:
                    scheduler_status = scheduler_engine.get_status()
            except Exception as exc:  # noqa: BLE001
                logger.debug("获取调度器状态失败：%s", exc)

            current_time = time.time()
            if current_time - self._last_broadcast_time < self._min_broadcast_interval:
                return
            system_data = {
                "cpu_percent": round(resource_manager.monitor.get_cpu_usage(), 1),
                "cpu_model": resource_manager.monitor.get_cpu_model(),
                "memory_percent": round(resource_manager.monitor.get_memory_usage(), 1),
                "gpu_memory_used": gpu_info[0] if gpu_info else 0,
                "gpu_memory_total": gpu_info[1] if gpu_info else 8192,
                "gpu_model": resource_manager.monitor.get_gpu_model(),
                "gpu_gate": gpu_gate_status,
                "scheduler": scheduler_status,
            }
            status_message = {
                "type": "system_status",
                "timestamp": current_time,
                "models": models_data,
                "system": system_data,
                "stats": kwargs,
            }
            current_hash = hashlib.md5(
                json.dumps(
                    {"models": models_data, "system": system_data},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            if self._last_broadcast_hash == current_hash:
                return

            connection_count = stats.get("active_connections", 0)
            if connection_count != self._last_logged_connection_count:
                logger.info("[WebSocket] 当前连接数：%s", connection_count)
                self._last_logged_connection_count = connection_count
            loaded_count = sum(1 for model in models_data.values() if model.get("is_loaded"))
            if self._last_logged_models_state != loaded_count:
                logger.info("[资源状态] 已加载模型数：%s", loaded_count)
                self._last_logged_models_state = loaded_count

            self._last_broadcast_hash = current_hash
            self._last_broadcast_time = current_time
            await self.broadcast_message(status_message)
        except Exception as exc:  # noqa: BLE001
            logger.error("处理资源更新广播失败：%s", exc)

    async def broadcast_message(self, data: Dict[str, Any]) -> None:
        if not self._initialized:
            await self.initialize()
        if not self.websocket_manager:
            return
        try:
            await self.websocket_manager.broadcast(data)
        except Exception as exc:  # noqa: BLE001
            logger.error("广播消息失败：%s", exc, exc_info=True)
