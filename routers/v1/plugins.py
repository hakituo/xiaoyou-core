# -*- coding: utf-8 -*-
"""插件（plugins）域。

当前包含敏感模式（Sensitive / 隐私模式）的状态查询与开关。
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("PluginRouter")
router = APIRouter(prefix="/plugins", tags=["插件系统"])


class SensitiveToggleRequest(BaseModel):
    enabled: bool
    user_id: str = "default"


def _get_latest_sensitive_mode_content(mm) -> Optional[str]:
    candidates = []

    items = getattr(mm, "short_term_memory", None)
    if isinstance(items, list):
        for m in items:
            if not isinstance(m, dict):
                continue
            topics = m.get("topics")
            if isinstance(topics, list) and "sensitive_mode_control" in topics:
                candidates.append(m)

    weighted_memories = getattr(mm, "weighted_memories", None)
    if isinstance(weighted_memories, dict):
        for m in weighted_memories.values():
            if not isinstance(m, dict):
                continue
            topics = m.get("topics")
            if isinstance(topics, list) and "sensitive_mode_control" in topics:
                candidates.append(m)

    if not candidates:
        return None

    candidates.sort(key=lambda x: x.get("timestamp", 0) or 0, reverse=True)
    content = candidates[0].get("content")
    return str(content) if content is not None else None


@router.get("/sensitive/status", summary="查询敏感模式是否开启")
async def get_sensitive_status(user_id: str = "default"):
    from core.agents.chat_agent import get_default_chat_agent
    agent = get_default_chat_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="ChatAgent not initialized")

    try:
        mm = agent._get_memory_manager(user_id)
        content = _get_latest_sensitive_mode_content(mm)
        if content and "SENSITIVE_MODE_ON" in content:
            return {"enabled": True}
    except Exception as e:
        logger.error(f"Failed to check Sensitive status: {e}")

    return {"enabled": False}


@router.post("/sensitive/toggle", summary="开关敏感模式")
async def toggle_sensitive(request: SensitiveToggleRequest):
    from core.agents.chat_agent import get_default_chat_agent
    agent = get_default_chat_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="ChatAgent not initialized")

    try:
        from core.managers.preference_manager import get_preference_manager

        prefs = get_preference_manager()

        if request.enabled:
            await prefs.set_mode("privacy")
        else:
            await prefs.set_mode("normal")

        mm = agent._get_memory_manager(request.user_id)

        content = (
            "SYSTEM_COMMAND: SENSITIVE_MODE_ON"
            if request.enabled
            else "SYSTEM_COMMAND: SENSITIVE_MODE_OFF"
        )

        mm.add_memory(
            content=content,
            source="system",
            topics=["sensitive_mode_control"],
            is_important=True,
            scopes=["local"],
            metadata={"type": "system_control", "timestamp": time.time()},
        )

        return {
            "status": "success",
            "enabled": request.enabled,
            "mode": prefs.get_mode(),
        }

    except Exception as e:
        logger.error(f"Failed to toggle Sensitive: {e}")
        raise HTTPException(status_code=500, detail=str(e))
