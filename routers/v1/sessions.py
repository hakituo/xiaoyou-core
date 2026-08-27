# -*- coding: utf-8 -*-
"""会话（sessions）域。

管理对话会话的生命周期，以及会话内的消息历史与单条消息操作。
"""

from typing import Dict, Any, Optional
import time

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from core.managers.session_manager import get_session_manager
from core.utils.logger import get_logger
from core.utils.conversation_labels import is_primary_user_conversation_id
from core.api.contract import error_response
from core.api.error_response import ErrorCode

logger = get_logger("SESSION_ROUTER")

router = APIRouter(prefix="/sessions", tags=["会话管理"])


@router.get("", summary="获取会话列表")
async def list_sessions(include_external: bool = Query(False)):
    try:
        manager = get_session_manager()
        sessions = manager.get_sessions()
        if not include_external:
            sessions = [
                item
                for item in sessions
                if is_primary_user_conversation_id((item or {}).get("id"))
            ]
        return {"status": "success", "data": sessions, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("", summary="创建新会话")
async def create_session(data: Dict[str, Any] = Body(...)):
    try:
        manager = get_session_manager()
        title = data.get("title", "新话题")
        session_id = manager.create_session(title)
        return {
            "status": "success",
            "data": {"id": session_id, "title": title},
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/{session_id}/history", summary="获取会话历史消息")
async def get_session_history(
    session_id: str,
    limit: int = Query(100, ge=1),
    before: Optional[float] = Query(None),
):
    try:
        from core.agents.chat_agent import get_default_chat_agent

        agent = get_default_chat_agent()
        mm = agent._get_memory_manager(session_id)

        logger.info(
            f"Getting history for session {session_id}, limit={limit}, before={before}"
        )

        history = []
        has_more = False
        if hasattr(mm, "get_recent_history"):
            fetch_limit = max(int(limit), 1) + 1
            try:
                history = await mm.get_recent_history(
                    session_id, fetch_limit, before=before
                )
            except TypeError:
                history = await mm.get_recent_history(session_id, fetch_limit)
            if len(history) > limit:
                has_more = True
                history = history[-limit:]
            logger.info(f"Found {len(history)} messages for session {session_id}")
        else:
            logger.warning(
                f"Memory manager for {session_id} does not support get_recent_history"
            )

        return {
            "status": "success",
            "data": history,
            "meta": {
                "count": len(history),
                "session_id": session_id,
                "has_more": has_more,
                "before": before,
            },
        }
    except Exception as e:
        logger.error(f"获取会话历史失败: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.put("/{session_id}", summary="更新会话（如重命名）")
async def update_session(session_id: str, data: Dict[str, Any] = Body(...)):
    try:
        manager = get_session_manager()
        title = data.get("title")
        if not title:
            return JSONResponse(
                status_code=400,
                content=error_response(
                    ErrorCode.MISSING_PARAMETER, message="Title required"
                ),
            )

        success = manager.update_session(session_id, title)
        if success:
            return {"status": "success", "timestamp": time.time()}
        return JSONResponse(
            status_code=404,
            content=error_response(
                ErrorCode.RESOURCE_NOT_FOUND, message="Session not found"
            ),
        )
    except Exception as e:
        logger.error(f"更新会话失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.delete("/{session_id}", summary="删除会话")
async def delete_session(session_id: str):
    try:
        manager = get_session_manager()
        success = manager.delete_session(session_id)
        if success:
            return {"status": "success", "timestamp": time.time()}
        return JSONResponse(
            status_code=404,
            content=error_response(
                ErrorCode.RESOURCE_NOT_FOUND, message="Session not found"
            ),
        )
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.delete(
    "/{session_id}/messages/{message_id}",
    summary="删除会话中的单条消息",
)
async def delete_session_message(session_id: str, message_id: str):
    try:
        from core.agents.chat_agent import get_default_chat_agent

        agent = get_default_chat_agent()
        mm = agent._get_memory_manager(session_id)

        if hasattr(mm, "delete_message"):
            success = mm.delete_message(message_id)
            if success:
                return {"status": "success", "message": "Message deleted"}
            else:
                return {
                    "status": "warning",
                    "message": "Message not found or could not be deleted",
                }
        else:
            return error_response(
                ErrorCode.INVALID_REQUEST,
                message="Memory manager does not support deletion",
            )

    except Exception as e:
        logger.error(f"删除消息失败: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
