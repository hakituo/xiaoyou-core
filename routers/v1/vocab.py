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
    count: int = Query(0, ge=0, le=1000, description="每日复习词数量，0=返回当天固定队列全部词"),
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

async def _mark_vocab_plan_completed_if_done(service) -> bool:
    """若今日词汇任务已完成，把当天计划里的英语词汇项标记为 completed。

    背景（2026-09-03）：用户在安卓端背完单词后，计划项从未变成 completed，
    到晚上睡眠结算时被统一打成 ``skipped``（settlement_reason=sleep）。
    而 ``plan_candidate_builder`` 允许这类 skipped 项结转到次日，与当天
    新生成的计划叠加，于是"复习到期英语词汇（N 个）"每天出现多条、数字
    天天漂移（166 / 169 / 34 / 72 …），AI 读到的其实是前几天结转来的旧数字。

    本函数在安卓端提交评分后检测实时完成态，一旦完成就把计划项勾上，
    从源头切断结转链。所有异常都吞掉只记日志，不影响复习主流程。
    """
    try:
        status = None
        if hasattr(service, "get_today_review_status"):
            status = service.get_today_review_status()
        elif getattr(service, "vocab_manager", None) is not None:
            status = service.vocab_manager.get_today_review_status()
        if not isinstance(status, dict) or not status.get("completed"):
            return False

        from core.services.journal.service import get_journal_service

        journal = get_journal_service()
        plan = await journal.get_plan(None)
        if plan is None:
            return False

        # 必须显式传日期：JournalService 里 get_plan(None) 取今日，但
        # mark_plan_item_status(None) 会落到"明日"，两边语义不一致，
        # 直接传 None 会去改明天的计划、因 item_id 对不上而静默失败。
        plan_date = str(getattr(plan, "date", "") or "").strip() or None
        for it in plan.items:
            if str(getattr(it, "status", "") or "") == "completed":
                continue
            key = str(getattr(it, "source_key", "") or "")
            title = str(getattr(it, "title", "") or "")
            if key != "vocab:due_review" and "复习到期英语词汇" not in title:
                continue
            updated = await journal.mark_plan_item_status(
                plan_date, it.id, "completed"
            )
            if updated is not None:
                logger.info(
                    "Vocab: 今日词汇复习已完成，自动标记计划项为 completed: item_id=%s",
                    it.id,
                )
                return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Vocab: 自动标记词汇计划项完成失败: {e}")
    return False


@router.post("/review", summary="提交单词复习结果")
async def submit_review(data: Dict[str, Any] = Body(...)):
    """提交单词复习结果。quality: 1=Again, 2=Hard, 3=Good, 4=Easy。

    Body 可选 source：manual_review / quiz / daily_retry /
    same_session_retry / ai_unfamiliar_check，仅作历史溯源，不影响调度。
    """
    try:
        word = data.get("word")
        quality = data.get("quality")
        source = data.get("source") or "manual_review"
        if not word or quality is None:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing word or quality")
        service = _get_study_service()
        result = service.submit_word_review(word, int(quality), str(source))
        # 安卓端背完当天队列后，同步把计划里的英语词汇项勾上
        await _mark_vocab_plan_completed_if_done(service)
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
