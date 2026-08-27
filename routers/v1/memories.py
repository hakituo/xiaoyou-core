# -*- coding: utf-8 -*-
"""记忆（memories）域。

管理加权记忆的列表、统计、标签、单条删除与批量清除。
注意：记忆降噪任务（denoise）已迁移至 admin/data-ops 域。
"""

import asyncio
import time
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Query, Path
from pydantic import BaseModel

from core.api.contract import error_response
from core.api.error_response import ErrorCode

logger = logging.getLogger("MEMORY_ROUTER")

router = APIRouter(prefix="/memories", tags=["记忆系统"])


def _resolve_user_id(user_id: str = "default", persona: str = None):
    """解析记忆 user_id。

    优先使用显式 user_id；若传入 persona 文件名（如 "qq/Aveline_QQ_Master.json"），
    则用后端权威映射 build_shared_persona_conversation_id + resolve_memory_user_id
    生成跨平台共享的 shared__scope__{scope} user_id，保证按角色隔离且 Android/QQ/Telegram 互通。

    这样前端无需自己拼 slug，避免前端 slug 与后端 scope 不一致的问题。
    """
    if persona:
        try:
            from core.utils.data_paths import (
                build_shared_persona_conversation_id,
                resolve_memory_user_id,
            )
            cid = build_shared_persona_conversation_id(persona)
            return resolve_memory_user_id(cid)
        except Exception as e:
            logger.warning(f"按 persona 解析记忆 user_id 失败，回退默认: {e}")
    return user_id


def _wmm(user_id: str = "default", persona: str = None):
    from memory.weighted_memory_manager import get_weighted_memory_manager
    return get_weighted_memory_manager(_resolve_user_id(user_id, persona))


# ==================== 列表（合并去重：原 /weighted 与 / 两个入口合一） ====================

@router.get("", summary="获取加权记忆列表（支持过滤）")
async def list_memories(
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名（如 qq/Aveline_QQ_Master.json），传入后按角色隔离记忆"),
    limit: int = Query(50, ge=1, le=500, description="返回条数上限"),
    min_weight: Optional[float] = Query(None, description="按最小权重过滤"),
    category: Optional[str] = Query(None, description="按分类过滤"),
    emotion: Optional[str] = Query(None, description="按情绪过滤 / 加权"),
    include_thinking: bool = Query(False, description="是否包含隐藏的 thinking 分类"),
):
    """获取加权记忆列表。

    原 /memory/weighted（带 category/emotion 过滤）与 /memory（固定 limit=50）
    两个重复入口已合并为本端点，统一用 query 参数过滤。
    """
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        analysis_limit = max(32, min(256, int(limit) * 4))
        await asyncio.to_thread(manager.process_pending_analysis, analysis_limit)
        exclude_categories = (
            None if include_thinking or (category == "thinking") else ["thinking"]
        )
        memories = await asyncio.to_thread(
            manager.get_weighted_memories,
            min_weight=min_weight,
            limit=limit,
            category=category,
            emotion=emotion,
            exclude_categories=exclude_categories,
        )
        return {
            "status": "success",
            "data": memories,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"获取加权记忆失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


# ==================== 单条操作 ====================

class MarkImportantRequest(BaseModel):
    """标记重要请求体"""
    important: bool


@router.patch("/{memory_id}/important", summary="标记/取消标记记忆为重要")
async def mark_memory_important(
    memory_id: str = Path(..., description="记忆 ID"),
    payload: MarkImportantRequest = ...,
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
):
    """标记或取消标记某条记忆为重要。

    重要记忆会进入 important_prompts 层，并在权重计算时获得加成。
    """
    request_id = str(uuid.uuid4())
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        if hasattr(manager, "set_memory_important"):
            ok = await asyncio.to_thread(manager.set_memory_important, memory_id, payload.important)
            if not ok:
                return error_response(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    message=f"记忆不存在: {memory_id}",
                    request_id=request_id,
                )
        else:
            return error_response(
                ErrorCode.INVALID_REQUEST,
                message="记忆管理器不支持标记重要",
                request_id=request_id,
            )
        return {
            "status": "success",
            "message": f"已{'标记' if payload.important else '取消'}记忆重要: {memory_id}",
            "request_id": request_id,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"标记记忆重要失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.delete("/{memory_id}", summary="删除指定加权记忆")
async def delete_memory(
    memory_id: str = Path(..., description="待删除的加权记忆 ID"),
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
):
    request_id = str(uuid.uuid4())
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        if hasattr(manager, "delete_memory"):
            await asyncio.to_thread(manager.delete_memory, memory_id)
        else:
            return error_response(
                ErrorCode.INVALID_REQUEST,
                message="记忆管理器不支持删除",
                request_id=request_id,
            )
        return {
            "status": "success",
            "message": f"已删除记忆 {memory_id}",
            "request_id": request_id,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"删除加权记忆失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


# ==================== 批量清除 ====================

@router.delete("", summary="批量清除加权记忆")
async def clear_weighted_memories(
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
):
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        count = await asyncio.to_thread(manager.clear_weighted_memories)
        return {
            "status": "success",
            "message": f"已清除 {count} 条加权记忆",
            "count": count,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"清除加权记忆失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/clear", summary="清除会话历史（兼容旧入口）")
async def clear_session_history(payload: dict = None):
    """清除聊天会话历史（all / short）。

    保留此端点以兼容 clear_history 调用链，实际清理由 ChatAgent 负责。
    """
    request_id = str(uuid.uuid4())
    try:
        from core.agents.chat_agent import get_default_chat_agent

        agent = await asyncio.to_thread(get_default_chat_agent)
        payload = payload or {}
        mode = str(payload.get("mode", "all")).strip().lower()
        if mode in ("short_term", "short-term", "shortterm"):
            mode = "short"
        if mode not in ("all", "short"):
            mode = "all"
        uid = str(payload.get("user_id", "default"))

        if hasattr(agent, "clear_history"):
            import inspect
            sig = inspect.signature(agent.clear_history)
            if "mode" in sig.parameters:
                await agent.clear_history(uid, mode=mode)
            else:
                await agent.clear_history(uid)

        return {
            "status": "success",
            "message": f"Memory ({mode}) cleared for user {uid}",
            "user_id": uid,
            "mode": mode,
            "request_id": request_id,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to clear memory: {e}")
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message="清除记忆失败",
            request_id=request_id,
            details={"error_type": type(e).__name__},
        )


# ==================== 统计与标签 ====================

@router.get("/stats", summary="获取记忆分类统计")
async def get_memory_stats(
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
):
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        stats = await asyncio.to_thread(manager.get_category_stats)

        # 过滤掉 thinking 分类
        try:
            if isinstance(stats, dict):
                counts = stats.get("counts")
                avg = stats.get("avg_weight")
                dist = stats.get("distribution")
                if isinstance(counts, dict):
                    counts.pop("thinking", None)
                if isinstance(avg, dict):
                    avg.pop("thinking", None)
                if isinstance(dist, dict):
                    dist.pop("thinking", None)
        except Exception:
            pass

        return {
            "status": "success",
            "data": stats,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"获取记忆统计信息失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/tags", summary="获取记忆标签（话题权重）")
async def get_memory_tags(
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
):
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        topic_weights = getattr(manager, "topic_weights", {}) or {}
        tags = [
            {"name": key, "weight": value}
            for key, value in sorted(
                topic_weights.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]
        return {
            "status": "success",
            "data": tags,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"获取记忆标签失败: {e}")
        return {
            "status": "success",
            "data": [],
            "message": str(e),
            "timestamp": time.time(),
        }
