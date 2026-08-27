# -*- coding: utf-8 -*-
"""双角色对话（peer-chat）域。

提供 Aveline / Ling 双角色对话的历史、触发、状态与剧本查询。
注意：本域前缀为 /peer-chat，挂载在 /api/v1 下后实际路径为 /api/v1/peer-chat/*。
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.utils.time_utils import now_str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/peer-chat", tags=["双角色对话"])


# ==================== 数据模型 ====================

class PeerChatMessage(BaseModel):
    """双角色对话消息"""
    id: str = ""
    script_id: str = ""
    role: str = ""
    role_name: str = ""
    text: str = ""
    emotion: Optional[str] = None
    round_index: int = 0
    timestamp: float = 0.0


class PeerChatScript(BaseModel):
    """双角色对话剧本"""
    script_id: str = ""
    topic: str = ""
    participants: List[str] = []
    messages: List[PeerChatMessage] = []
    total_rounds: int = 0
    summary: str = ""
    mentioned_user: bool = False
    start_time: float = 0.0
    end_time: Optional[float] = None


class PeerChatStatus(BaseModel):
    """双角色对话状态"""
    enabled: bool = True
    is_script_active: bool = False
    current_script_id: Optional[str] = None
    today_count: int = 0
    daily_limit: int = 6
    last_chat_timestamp: float = 0.0
    recent_topics: List[str] = []
    scheduler_running: bool = False
    scheduler_task_alive: bool = False
    scheduler_last_run_ago_seconds: int = -1
    scheduler_last_success_ago_seconds: int = -1
    scheduler_consecutive_failures: int = 0
    scheduler_last_error: str = ""
    scheduler_next_check_in_seconds: int = -1
    scheduler_total_runs: int = 0
    scheduler_total_successes: int = 0


class TriggerRequest(BaseModel):
    """触发双角色对话请求"""
    topic: str = Field(default="", description="对话话题，为空则自动生成")


class TriggerResponse(BaseModel):
    """触发双角色对话响应"""
    success: bool
    script_id: Optional[str] = None
    message: str = ""


# ==================== 辅助函数 ====================

def _get_dual_role_dir() -> Path:
    from core.utils.data_paths import get_dual_role_data_dir
    return get_dual_role_data_dir()


def _load_peer_chat_history_from_dir(
    role_id: str,
    date_str: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    dual_dir = _get_dual_role_dir()
    if not dual_dir.exists():
        return []

    rows = []

    if date_str:
        persona_slugs = [f"qq_{role_id}"] if role_id else ["qq_aveline", "qq_ling"]
        for persona_slug in persona_slugs:
            chat_dir = dual_dir / persona_slug / date_str
            if not chat_dir.exists():
                continue
            for jsonl_file in chat_dir.glob("*.jsonl"):
                try:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            text = line.strip()
                            if not text:
                                continue
                            try:
                                payload = json.loads(text)
                                if isinstance(payload, dict):
                                    payload["_source_role"] = persona_slug.replace("qq_", "")
                                    rows.append(payload)
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    continue
    else:
        for persona_slug in ["qq_aveline", "qq_ling"]:
            persona_dir = dual_dir / persona_slug
            if not persona_dir.exists():
                continue
            for date_dir in sorted(persona_dir.iterdir(), reverse=True):
                if not date_dir.is_dir():
                    continue
                for jsonl_file in date_dir.glob("*.jsonl"):
                    try:
                        with open(jsonl_file, "r", encoding="utf-8") as f:
                            for line in f:
                                text = line.strip()
                                if not text:
                                    continue
                                try:
                                    payload = json.loads(text)
                                    if isinstance(payload, dict):
                                        payload["_source_role"] = persona_slug.replace("qq_", "")
                                        rows.append(payload)
                                except json.JSONDecodeError:
                                    continue
                    except Exception:
                        continue
                if len(rows) >= limit * 2:
                    break

    rows.sort(key=lambda x: float(x.get("timestamp") or 0.0))
    return rows[-limit:]


def _load_peer_chat_scripts(limit: int = 10) -> List[Dict[str, Any]]:
    dual_dir = _get_dual_role_dir()
    if not dual_dir.exists():
        return []

    scripts_dir = dual_dir / "scripts"
    if not scripts_dir.exists():
        return []

    scripts = []
    for json_file in sorted(scripts_dir.glob("*.json"), reverse=True):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    scripts.append(data)
        except Exception:
            continue

    return scripts[:limit]


def _get_peer_chat_state() -> Dict[str, Any]:
    from config.settings_life import get_life_settings

    settings = get_life_settings()

    dual_dir = _get_dual_role_dir()
    state_file = dual_dir / "state.json"

    state_data = {}
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception:
            pass

    today_key = now_str("%Y-%m-%d")
    today_count = int(state_data.get(f"peer_chat_count_{today_key}", 0))

    scheduler_health = {}
    try:
        from core.services.active_care.peer_chat.peer_chat_scheduler import get_peer_chat_scheduler
        scheduler = get_peer_chat_scheduler()
        if scheduler:
            scheduler_health = scheduler.get_health_status()
    except Exception:
        pass

    return {
        "enabled": getattr(settings, "peer_chat_enabled", True),
        "is_script_active": bool(state_data.get("is_script_active", False)),
        "current_script_id": state_data.get("current_script_id"),
        "today_count": today_count,
        "daily_limit": getattr(settings, "peer_chat_daily_limit", 6),
        "last_chat_timestamp": float(state_data.get("last_peer_chat_ts", 0.0)),
        "recent_topics": state_data.get("recent_peer_chat_topics", []),
        "scheduler_running": scheduler_health.get("running", False),
        "scheduler_task_alive": scheduler_health.get("task_alive", False),
        "scheduler_last_run_ago_seconds": scheduler_health.get("last_run_ago_seconds", -1),
        "scheduler_last_success_ago_seconds": scheduler_health.get("last_success_ago_seconds", -1),
        "scheduler_consecutive_failures": scheduler_health.get("consecutive_failures", 0),
        "scheduler_last_error": scheduler_health.get("last_error", ""),
        "scheduler_next_check_in_seconds": scheduler_health.get("next_check_in_seconds", -1),
        "scheduler_total_runs": scheduler_health.get("total_runs", 0),
        "scheduler_total_successes": scheduler_health.get("total_successes", 0),
    }


def _format_message(raw: Dict[str, Any]) -> PeerChatMessage:
    role = str(raw.get("role", raw.get("_source_role", "unknown"))).strip().lower()
    role_name_map = {
        "aveline": "七濑 澪",
        "ling": "Ling",
    }

    return PeerChatMessage(
        id=str(raw.get("id", f"{raw.get('timestamp', time.time())}_{role}")),
        script_id=str(raw.get("script_id", "")),
        role=role,
        role_name=role_name_map.get(role, role),
        text=str(raw.get("content", raw.get("text", ""))),
        emotion=raw.get("emotion"),
        round_index=int(raw.get("round_index", 0)),
        timestamp=float(raw.get("timestamp", time.time())),
    )


# ==================== API 端点 ====================

@router.get("/history", response_model=List[PeerChatMessage], summary="获取双角色对话历史")
async def get_peer_chat_history(
    limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
    date: Optional[str] = Query(default=None, description="日期过滤 (YYYY-MM-DD)"),
    role: Optional[str] = Query(default=None, description="角色过滤 (aveline/ling)"),
):
    try:
        raw_messages = _load_peer_chat_history_from_dir(
            role_id=role or "",
            date_str=date,
            limit=limit,
        )

        messages = [_format_message(msg) for msg in raw_messages]

        if role:
            role = role.strip().lower()
            messages = [m for m in messages if m.role == role]

        return messages
    except Exception as e:
        logger.error(f"获取双角色对话历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取历史失败: {str(e)}")


@router.get("/status", response_model=PeerChatStatus, summary="获取双角色对话状态")
async def get_peer_chat_status():
    try:
        state = _get_peer_chat_state()
        return PeerChatStatus(**state)
    except Exception as e:
        logger.error(f"获取双角色对话状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.post("/trigger", response_model=TriggerResponse, summary="手动触发一次双角色对话")
async def trigger_peer_chat(request: TriggerRequest):
    try:
        from core.services.active_care.peer_chat.peer_chat_scheduler import get_peer_chat_scheduler

        scheduler = get_peer_chat_scheduler()
        if not scheduler:
            return TriggerResponse(
                success=False,
                message="PeerChatScheduler 未初始化，请确认 ActiveCareService 已启动"
            )

        result = await scheduler.run_single_check()

        return TriggerResponse(
            success=result.get("success", False),
            script_id=f"manual_{int(time.time() * 1000)}",
            message=result.get("message", "触发完成"),
        )
    except Exception as e:
        logger.error(f"触发双角色对话失败: {e}", exc_info=True)
        return TriggerResponse(
            success=False,
            message=f"触发失败: {str(e)}"
        )


@router.get("/scripts", response_model=List[PeerChatScript], summary="获取双角色对话剧本列表")
async def get_peer_chat_scripts(
    limit: int = Query(default=10, ge=1, le=50, description="返回条数"),
):
    try:
        raw_scripts = _load_peer_chat_scripts(limit=limit)

        scripts = []
        for raw in raw_scripts:
            messages = [_format_message(msg) for msg in raw.get("messages", [])]
            scripts.append(PeerChatScript(
                script_id=raw.get("script_id", ""),
                topic=raw.get("topic", ""),
                participants=raw.get("participants", []),
                messages=messages,
                total_rounds=raw.get("total_rounds", len(messages)),
                summary=raw.get("summary", ""),
                mentioned_user=raw.get("mentioned_user", False),
                start_time=raw.get("start_time", 0.0),
                end_time=raw.get("end_time"),
            ))

        return scripts
    except Exception as e:
        logger.error(f"获取双角色对话剧本失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取剧本失败: {str(e)}")
