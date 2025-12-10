from fastapi import APIRouter, HTTPException, Query, Body
from typing import List, Dict, Optional, Any
import time
from memory.weighted_memory_manager import get_weighted_memory_manager
from core.utils.logger import get_logger

logger = get_logger("MEMORY_ROUTER")

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

@router.delete("/weighted")
async def clear_weighted_memories(user_id: str = Query("default", description="User ID")):
    """
    清除所有加权记忆
    """
    try:
        manager = get_weighted_memory_manager(user_id)
        count = manager.clear_weighted_memories()
        return {
            "status": "success",
            "message": f"Cleared {count} weighted memories",
            "count": count,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"清除加权记忆失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.get("/weighted")
async def get_weighted_memories(
    user_id: str = Query("default", description="User ID"),
    limit: int = Query(10, description="Limit")
):
    """
    获取加权记忆列表
    """
    try:
        manager = get_weighted_memory_manager(user_id)
        memories = manager.get_weighted_memories(limit=limit)
        return {
            "status": "success",
            "data": memories,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"获取加权记忆失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
