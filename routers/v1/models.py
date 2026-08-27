# -*- coding: utf-8 -*-
"""模型（models）域。

管理 LLM 模型列表与运行时切换。
"""

from typing import Dict, Any
from pydantic import BaseModel
import logging
import asyncio

from fastapi import APIRouter
from config.integrated_config import get_settings

logger = logging.getLogger("ModelRouter")
router = APIRouter(prefix="/models", tags=["模型管理"])

# 可选模型预置项（供 control_intent 等模块引用，保持向后兼容）
MODEL_OPTIONS: list = []


class SwitchModelRequest(BaseModel):
    model_name: str
    provider: str = "local"


@router.get("", response_model=Dict[str, Any], summary="获取所有可用模型列表")
async def list_models():
    from core.core_engine.model_manager import get_model_manager
    manager = get_model_manager()

    raw_models = manager.list_models(model_type="llm")

    available_models = []
    for m in raw_models:
        category = "cloud" if str(m.get("path", "")).startswith("cloud:") else "local"
        m["category"] = category
        available_models.append(m)

    settings = get_settings()
    current_model = {
        "provider": settings.model.llm.provider,
        "model": settings.model.llm.model,
        "path": settings.model.text_path,
    }

    return {
        "current": current_model,
        "available": available_models,
        "options": [],
        "models": available_models,
        "selected_model_id": (str(current_model.get("provider") or "") + ":" + str(current_model.get("model") or "")) if current_model.get("provider") and current_model.get("provider") != "local" else "local",
    }


@router.post("/switch", summary="切换当前 LLM 模型")
async def switch_model(request: SwitchModelRequest):
    from core.core_engine.model_manager import get_model_manager
    from core.llm import get_llm_module
    from core.interfaces.websocket.websocket_manager import get_websocket_manager as get_manager
    from core.modules.llm.utils import normalize_local_path

    settings = get_settings()
    manager = get_model_manager()

    logger.info(f"Switching model to {request.model_name} ({request.provider})")

    model_info = manager._models.get(request.model_name)
    if not model_info:
        for k, v in manager._models.items():
            if k.lower() == request.model_name.lower():
                model_info = v
                break

    if model_info:
        path = model_info.model_path
        if path.startswith("cloud:"):
            parts = path.split(":")
            if len(parts) >= 2:
                settings.model.llm.provider = parts[1]
            # 支持传统格式（3段）和多API key格式（4段）
            # 传统格式: cloud:deepseek:model -> parts[2]
            # 多API key格式: cloud:deepseek:qqbot1:model -> parts[3]
            if len(parts) == 3:
                settings.model.llm.model = parts[2]
            elif len(parts) >= 4:
                settings.model.llm.model = ":".join(parts[3:])

            logger.info(
                f"Switched to cloud model: {settings.model.llm.provider}/{settings.model.llm.model}"
            )

            try:
                from core.character.managers.persona_manager import get_persona_manager

                persona_manager = get_persona_manager()
                target_persona = _find_persona_for_provider(parts[1], settings)
                if target_persona:
                    if persona_manager.set_persona(target_persona):
                        logger.info(f"Auto-switched persona to {target_persona}")
                        ws_manager = get_manager()
                        await ws_manager.broadcast(
                            {
                                "type": "persona_update",
                                "data": persona_manager.get_current_persona(),
                            }
                        )
                    else:
                        logger.warning(
                            f"Failed to auto-switch persona to {target_persona}"
                        )
            except Exception as e:
                logger.error(f"Error auto-switching persona: {e}")
        else:
            settings.model.llm.provider = "local"
            normalized_path = normalize_local_path(path)
            settings.model.text_path = normalized_path
            logger.info(f"Switched to local model: {normalized_path}")
    else:
        settings.model.llm.provider = request.provider
        if request.provider == "local":
            normalized_path = normalize_local_path(request.model_name)
            settings.model.text_path = normalized_path
        else:
            settings.model.llm.model = request.model_name
        logger.warning(
            f"Model {request.model_name} not found in manager, using raw request parameters"
        )

    try:
        module = get_llm_module()

        if settings.model.llm.provider != "local":
            logger.info("Switching to cloud model, unloading local model first...")
            if hasattr(module, "unload_model"):
                if asyncio.iscoroutinefunction(module.unload_model):
                    await module.unload_model()
                else:
                    module.unload_model()
            logger.info("Local model unloaded successfully")

        if hasattr(module, "reload"):
            if asyncio.iscoroutinefunction(module.reload):
                await module.reload()
            else:
                module.reload()
        logger.info("LLM Module reload triggered successfully")
    except Exception as e:
        logger.error(f"Failed to reload LLM module: {e}")
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "current": {
            "provider": settings.model.llm.provider,
            "model": settings.model.llm.model,
            "path": settings.model.text_path,
        },
    }


def _find_persona_for_provider(provider: str, settings) -> str | None:
    """根据 persona_model_map 反向查找：给定 provider，找到对应的人设文件名"""
    try:
        persona_model_map = getattr(settings.model, "persona_model_map", None)
        if not persona_model_map:
            return None

        from core.character.managers.persona_manager import get_persona_manager
        pm = get_persona_manager()
        all_personas = pm.list_personas()

        for persona_key, model_hint in persona_model_map.items():
            if not model_hint.startswith("cloud:"):
                continue
            parts = model_hint.split(":", 2)
            if len(parts) >= 2 and parts[1] == provider:
                key_lower = str(persona_key).strip().lower()
                for p in all_personas:
                    fn = str(p.get("filename", "") or "").lower()
                    if key_lower in fn:
                        return p["filename"]
        return None
    except Exception as e:
        logger.warning(f"Failed to find persona for provider '{provider}': {e}")
        return None
