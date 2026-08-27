# -*- coding: utf-8 -*-
"""人格（personas）域。

管理 Aveline / Ling 等角色人格的列表与切换。
注意：当前后端仅支持只读列表 + 切换，不提供增删改。
"""

from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/personas", tags=["人格系统"])


def _get_persona_manager():
    from core.character.managers.persona_manager import get_persona_manager
    return get_persona_manager()


class SwitchPersonaRequest(BaseModel):
    filename: str


@router.get("", response_model=List[Dict[str, Any]], summary="获取所有可用人格列表")
async def list_personas():
    return _get_persona_manager().list_personas()


@router.get("/active", summary="获取当前激活人格（兼容旧前端）")
async def get_active_persona():
    manager = _get_persona_manager()
    return {
        "status": "success",
        "filename": manager.get_current_filename(),
        "data": manager.get_current_persona(),
    }


@router.get("/current", summary="获取当前人格详情")
async def get_current_persona():
    manager = _get_persona_manager()
    return {
        "filename": manager.get_current_filename(),
        "data": manager.get_current_persona(),
    }


@router.post("/switch", summary="切换到指定人格")
async def switch_persona(request: SwitchPersonaRequest):
    manager = _get_persona_manager()
    success = manager.set_persona(request.filename)
    if not success:
        raise HTTPException(
            status_code=404, detail="Persona not found or failed to load"
        )

    # 立即重载 AvelineCharacter 以应用变更
    from core.character.aveline import AvelineCharacter

    AvelineCharacter().load_config()

    # 根据人设自动切换模型
    _auto_switch_model_for_persona(request.filename)

    # 根据人设自动切换参考音频
    _auto_switch_audio_for_persona(request.filename)

    return {
        "status": "success",
        "current_persona": request.filename,
        "data": manager.get_current_persona(),
    }


def _auto_switch_model_for_persona(persona_filename: str):
    """根据人设自动切换对应的模型提供商"""
    try:
        import importlib
        config_mod = importlib.import_module("config.integrated_config")
        get_settings = getattr(config_mod, "get_settings", None)
        if not get_settings:
            return
        settings = get_settings()
        persona_model_map = getattr(settings.model, "persona_model_map", None)
        if not persona_model_map:
            return

        fn_lower = str(persona_filename or "").strip().lower()
        for persona_key, model_hint in persona_model_map.items():
            key_lower = str(persona_key).strip().lower()
            if key_lower in fn_lower:
                if model_hint.startswith("cloud:"):
                    parts = model_hint.split(":")
                    if len(parts) >= 2:
                        settings.model.llm.provider = parts[1]
                    # 支持传统格式（3段）和多API key格式（4段）
                    # 传统格式: cloud:deepseek:model -> parts[2]
                    # 多API key格式: cloud:deepseek:qqbot1:model -> parts[3]
                    if len(parts) == 3:
                        settings.model.llm.model = parts[2]
                    elif len(parts) >= 4:
                        settings.model.llm.model = ":".join(parts[3:])
                    import logging
                    logging.getLogger("personas").info(
                        f"Auto-switched model for persona '{persona_filename}': "
                        f"provider={settings.model.llm.provider}, model={settings.model.llm.model}"
                    )
                return
    except Exception:
        pass


def _auto_switch_audio_for_persona(persona_filename: str):
    """根据人设自动切换对应的参考音频"""
    try:
        import importlib
        config_mod = importlib.import_module("config.integrated_config")
        get_settings = getattr(config_mod, "get_settings", None)
        if not get_settings:
            return
        settings = get_settings()
        persona_audio_map = getattr(settings.model, "persona_audio_map", None)
        if not persona_audio_map:
            return

        fn_lower = str(persona_filename or "").strip().lower()
        for persona_key, audio_path in persona_audio_map.items():
            key_lower = str(persona_key).strip().lower()
            if key_lower in fn_lower:
                settings.voice.reference_audio = audio_path
                if hasattr(settings, "limits") and hasattr(settings.limits, "reference_audio"):
                    settings.limits.reference_audio = audio_path
                import logging
                logging.getLogger("personas").info(
                    f"Auto-switched reference audio for persona '{persona_filename}': {audio_path}"
                )
                return
    except Exception:
        pass
