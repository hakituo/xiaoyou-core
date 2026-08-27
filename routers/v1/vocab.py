# -*- coding: utf-8 -*-
"""背单词（vocab）域。

从原 study_router 拆出的「背单词 / 词典」子系统：每日词汇、词典检索、
记忆曲线、错题、复习会话、学习工具等。
"""

from typing import Dict, Any

from fastapi import APIRouter, Body, Query
import time

from core.utils.logger import get_logger
from core.api.contract import error_response
from core.api.error_response import ErrorCode

logger = get_logger("VOCAB_ROUTER")

router = APIRouter(prefix="/vocab", tags=["背单词"])


def _get_study_service():
    """延迟导入，避免启动时加载 tkinter/matplotlib 等重型依赖"""
    from core.services.study.service import get_study_service
    return get_study_service()


# ==================== 每日词汇 ====================

@router.get("/daily", summary="获取每日词汇列表")
async def get_daily_vocabulary(
    count: int = Query(0, ge=0, le=1000, description="每日复习词数量，0=不设上限（默认取昨天 daily 日志全部生词）"),
    order: str = Query("sequential", description="新词排序: sequential(顺序) / shuffle(乱序)"),
):
    try:
        service = _get_study_service()
        words = service.get_daily_words(count, order=order)
        return {"status": "success", "data": words, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"Failed to get daily words: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/new-words", summary="获取从未学过的新词列表")
async def get_new_words(
    count: int = Query(20, ge=1, le=200, description="新词数量"),
    order: str = Query("sequential", description="排序: sequential(顺序) / shuffle(乱序)"),
):
    """从当前词书取不在 progress 里的词（从未学过的新词），标记 status=new。"""
    try:
        service = _get_study_service()
        words = service.get_new_words(count, order=order)
        return {"status": "success", "data": words, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"Failed to get new words: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/subjects", summary="获取学科列表")
async def get_subject_profiles():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_subject_profiles()}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/files", summary="获取学习文件列表")
async def get_study_files():
    """兼容移动端的学习文件列表接口。"""
    try:
        service = _get_study_service()
        data = []
        if hasattr(service, "list_files"):
            data = service.list_files()
        elif hasattr(service, "get_available_files"):
            data = service.get_available_files()

        files = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    files.append({
                        "id": item.get("id", ""),
                        "name": item.get("name", "unknown"),
                        "size": item.get("size", 0),
                        "type": item.get("type", ""),
                        "status": item.get("status", "completed"),
                        "uploaded_at": item.get("uploaded_at", ""),
                    })
        return {"files": files, "total": len(files)}
    except Exception as e:
        logger.warning(f"获取学习文件列表失败，返回空列表: {e}")
        return {"files": [], "total": 0}


@router.get("/mode", summary="获取学习模式状态")
async def get_study_mode():
    """兼容移动端的学习模式状态接口。"""
    try:
        service = _get_study_service()
        enabled = False
        if hasattr(service, "get_mode"):
            raw = service.get_mode()
            if isinstance(raw, dict):
                enabled = str(raw.get("enabled", False)).lower() == "true"
            else:
                enabled = str(raw).lower() not in {"none", "false", ""}
        return {
            "enabled": enabled,
            "active_file_ids": [],
            "total_chunks": 0,
        }
    except Exception as e:
        logger.warning(f"获取学习模式失败，返回默认值: {e}")
        return {"enabled": False, "active_file_ids": [], "total_chunks": 0}


@router.get("/summary", summary="获取学习日摘要")
async def get_study_summary(date: str = Query("", description="日期(YYYY-MM-DD)")):
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_study_daily_digest(date=date)}
    except Exception as e:
        logger.error(f"Study summary failed: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 词典 ====================

@router.get("/dictionary/search", summary="搜索词典")
async def search_dictionary(query: str = Query(..., min_length=1)):
    try:
        service = _get_study_service()
        result = service.search_dictionary(query)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Dictionary search failed: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/dictionary/list", summary="获取词典分页列表")
async def list_dictionary(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
):
    try:
        service = _get_study_service()
        result = service.get_word_list(page, page_size)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Dictionary list failed: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/dictionary/stats", summary="获取词典统计")
async def get_dictionary_stats():
    try:
        service = _get_study_service()
        stats = service.get_dictionary_stats()
        return {"status": "success", "data": stats}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 记忆曲线与错题 ====================

@router.get("/review-overview", summary="获取复习总览（今日待复习/连续天数/到期分布/记忆曲线）")
async def get_review_overview():
    """前端统计页用：今日待复习数、连续学习天数、未来到期分布、记忆曲线预测。"""
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_review_overview()}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/curve", summary="获取记忆保持曲线")
async def get_memory_curve():
    try:
        service = _get_study_service()
        curve = service.get_memory_curve_data()
        return {"status": "success", "data": curve}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/mistakes", summary="获取高错词列表")
async def get_mistakes():
    try:
        service = _get_study_service()
        mistakes = service.get_mistakes()
        return {"status": "success", "data": mistakes}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 学习工具 ====================

@router.get("/tools", summary="获取可用学习工具列表")
async def list_tools():
    try:
        service = _get_study_service()
        tools = service.list_tools()
        return {"status": "success", "data": tools}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/tools/{category}/{tool_id}/run", summary="执行指定学习工具")
async def run_tool(category: str, tool_id: str, params: Dict[str, Any] = Body(...)):
    try:
        service = _get_study_service()
        result = service.run_tool(category, tool_id, params)
        return result
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 复习与学习队列 ====================

@router.post("/review", summary="提交单词复习结果")
async def submit_review(data: Dict[str, Any] = Body(...)):
    """提交单词复习结果。Body: {"word": "apple", "quality": 4}，quality 0-5。"""
    try:
        word = data.get("word")
        quality = data.get("quality")
        if not word or quality is None:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing word or quality")
        service = _get_study_service()
        result = service.submit_word_review(word, int(quality))
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Review submission failed: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/vocabulary/add", summary="添加单词到学习队列")
async def add_to_learning(data: Dict[str, Any] = Body(...)):
    """Body: {"word": "apple"}"""
    try:
        word = data.get("word")
        if not word:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing word")
        service = _get_study_service()
        result = service.add_to_learning(word)
        return result
    except Exception as e:
        logger.error(f"Failed to add word to learning: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/vocabulary/switch", summary="切换当前词典/句库")
async def switch_vocabulary(data: Dict[str, Any] = Body(...)):
    """Body: {"filename": "CET4.json", "is_sentence": false}"""
    try:
        filename = data.get("filename")
        is_sentence = data.get("is_sentence", False)
        if not filename:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing filename")
        service = _get_study_service()
        result = service.switch_vocabulary(filename, is_sentence)
        return result
    except Exception as e:
        logger.error(f"Vocabulary switch failed: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/vocabulary/trigger", summary="触发词汇推送（已禁用）")
async def trigger_vocabulary_push(user_id: str = "default"):
    """触发词汇推送。当前已禁用，改用聊天驱动记录。"""
    return {
        "status": "success",
        "message": "Vocabulary push is disabled. Use chat-driven recording instead.",
        "count": 0,
        "user_id": user_id,
    }


# ==================== 复习会话（RESTful 化） ====================

@router.get("/sessions/stats", summary="获取当前复习会话统计")
async def get_session_stats():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_session_stats()}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/sessions", summary="开始一个新的复习会话")
async def start_session():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.start_session()}
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.delete("/sessions/current", summary="结束当前复习会话")
async def end_session():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.end_session()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==================== 手动背诵记录 ====================

@router.post("/manual-study", summary="手动记录当天背了多少个单词")
async def add_manual_study(data: Dict[str, Any] = Body(...)):
    """Body: {"count": 20, "date": "2026-08-10"}（date 可选，默认今天）"""
    try:
        count = data.get("count")
        date = data.get("date")
        if count is None:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing count")
        service = _get_study_service()
        result = service.add_manual_study(int(count), date=date)
        if result.get("status") == "error":
            return {"status": "error", "message": result.get("message")}
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Failed to add manual study: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/manual-study/stats", summary="获取手动背诵统计")
async def get_manual_study_stats(
    days: int = Query(7, ge=1, le=365),
    date: str = Query("", description="指定单日 YYYY-MM-DD（优先级高于 days）"),
):
    try:
        service = _get_study_service()
        result = service.get_manual_study_stats(days=days, date=date or None)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Failed to get manual study stats: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
