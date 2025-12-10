from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from typing import List, Dict, Optional, Any
import time
from core.managers.session_manager import get_session_manager
from core.utils.logger import get_logger

logger = get_logger("SESSION_ROUTER")

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

@router.get("")
async def list_sessions():
    """
    获取所有会话列表
    """
    try:
        manager = get_session_manager()
        sessions = manager.get_sessions()
        return {
            "status": "success",
            "data": sessions,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        return {
            "status": "error", 
            "message": str(e)
        }

@router.post("")
async def create_session(data: Dict[str, Any] = Body(...)):
    """
    创建新会话
    """
    try:
        manager = get_session_manager()
        title = data.get("title", "新话题")
        session_id = manager.create_session(title)
        return {
            "status": "success",
            "data": {
                "id": session_id,
                "title": title
            },
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话
    """
    try:
        manager = get_session_manager()
        success = manager.delete_session(session_id)
        if success:
            return {"status": "success", "timestamp": time.time()}
        return JSONResponse(status_code=404, content={"status": "error", "message": "Session not found"})
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.put("/{session_id}")
async def update_session(session_id: str, data: Dict[str, Any] = Body(...)):
    """
    更新会话标题
    """
    try:
        manager = get_session_manager()
        title = data.get("title")
        if not title:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Title required"})
        
        success = manager.update_session(session_id, title)
        if success:
             return {"status": "success", "timestamp": time.time()}
        return JSONResponse(status_code=404, content={"status": "error", "message": "Session not found"})
    except Exception as e:
        logger.error(f"更新会话失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.get("/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 100):
    """
    获取会话历史消息
    """
    try:
        from core.agents.chat_agent import get_default_chat_agent
        agent = get_default_chat_agent()
        mm = agent._get_memory_manager(session_id)
        
        # Log the request
        logger.info(f"Getting history for session {session_id}, limit={limit}")
        
        if hasattr(mm, "get_recent_history"):
            history = await mm.get_recent_history(session_id, limit)
            logger.info(f"Found {len(history)} messages for session {session_id}")
        else:
            # Fallback for older memory managers
            logger.warning(f"Memory manager for {session_id} does not support get_recent_history")
            history = []
            
        return {
            "status": "success",
            "data": history,
            "meta": {
                "count": len(history),
                "session_id": session_id
            }
        }
    except Exception as e:
        logger.error(f"获取会话历史失败: {e}", exc_info=True)
        return {
            "status": "error", 
            "message": str(e)
        }
