# -*- coding: utf-8 -*-
"""Study Daily 学习日报域 - 结构化计划读取与计划项写入。

设计约定：
- ``plan.json`` / ``DailyPlan`` 是应用数据真源；``plan.md`` 只是人类可读投影。
- 新客户端通过 ``GET /study-daily/plan`` 读取结构化 DailyPlan，不再解析 Markdown。
- 新客户端 CRUD 一律按 ``plan_item_id`` 精确定位。
- 旧客户端未传 ``item_id`` 时，仍兼容 ``time + title`` 的历史定位方式。
- 一旦显式传了 ``item_id``，ID 不存在就直接失败，绝不回退到模糊匹配。
"""

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message

from .study_daily_shared import (
    _plan_file_path,
    _read_text_async,
    _validate_date_string,
)

router = APIRouter(prefix="/study-daily", tags=["study-daily"])

# plan.md 行尾的状态标记会在不同来源之间漂移；仅供旧客户端兼容匹配。
_PLAN_STATUS_MARKS = ("✅", "⏭️", "🔄")
_PLAN_WHITESPACE_RE = re.compile(r"\s+")
_PLAN_TIME_RE = re.compile(r"\d{1,2}:\d{2}")


# ==================== 请求模型 ====================

class PlanItemStatusRequest(BaseModel):
    """勾选 / 取消勾选指定日期计划项的请求体。"""

    date: str = Field(..., description="日期，格式 YYYY-MM-DD")
    item_id: Optional[str] = Field(None, description="计划项稳定 ID；新客户端应始终传入")
    time: str = Field("", description="旧客户端兼容：计划项时间 HH:mm")
    title: str = Field("", description="旧客户端兼容：计划项名称")
    done: bool = Field(..., description="True=标记完成，False=取消完成")


class PlanItemAddRequest(BaseModel):
    """新增计划项的请求体。"""

    date: str = Field(..., description="日期，格式 YYYY-MM-DD")
    time: str = Field("", description="计划项时间 HH:mm，无固定时间可留空")
    title: str = Field(..., description="计划项名称")
    duration_minutes: Optional[int] = Field(
        None, description="预计时长（分钟），留空按默认 60"
    )


class PlanItemUpdateRequest(BaseModel):
    """编辑计划项请求体；新客户端按 item_id 精确定位。"""

    date: str = Field(..., description="日期，格式 YYYY-MM-DD")
    item_id: Optional[str] = Field(None, description="计划项稳定 ID；新客户端应始终传入")
    target_time: str = Field("", description="旧客户端兼容：原计划项时间 HH:mm")
    target_title: str = Field("", description="旧客户端兼容：原计划项名称")
    time: str = Field("", description="新时间 HH:mm，留空表示改为无固定时间")
    title: str = Field(..., description="新名称")
    duration_minutes: Optional[int] = Field(
        None, description="新预计时长（分钟），留空表示不改"
    )


class PlanItemRefRequest(BaseModel):
    """删除计划项请求体；新客户端按 item_id 精确定位。"""

    date: str = Field(..., description="日期，格式 YYYY-MM-DD")
    item_id: Optional[str] = Field(None, description="计划项稳定 ID；新客户端应始终传入")
    time: str = Field("", description="旧客户端兼容：计划项时间 HH:mm")
    title: str = Field("", description="旧客户端兼容：计划项名称")


# ==================== 结构化计划 ====================

def _daily_study_goal_minutes() -> int:
    """读取每日学习目标唯一真源，不把 goal 复制进 plan.json。"""
    from core.services.journal.plan_policy import load_journal_plan_settings

    return load_journal_plan_settings().daily_goal_minutes


def _empty_daily_plan(date_str: str) -> Dict[str, Any]:
    """无计划时返回稳定的 typed contract，Android 无需回退解析 plan.md。"""
    return {
        "date": date_str,
        "daily_goal_minutes": _daily_study_goal_minutes(),
        "items": [],
        "notes": None,
        "source": "empty",
        "checkpoint_reviews": {},
        "revision_count": 0,
        "generated_at": 0.0,
        "updated_at": 0.0,
    }


def _serialize_daily_plan(plan: Any, date_str: str) -> Dict[str, Any]:
    if plan is None:
        return _empty_daily_plan(date_str)
    if hasattr(plan, "model_dump"):
        data = plan.model_dump(mode="json")
    elif hasattr(plan, "dict"):  # pragma: no cover - pydantic v1 compatibility
        data = plan.dict()
    else:  # tests / legacy simple objects
        items = []
        for item in getattr(plan, "items", []) or []:
            if hasattr(item, "model_dump"):
                items.append(item.model_dump(mode="json"))
            elif hasattr(item, "dict"):
                items.append(item.dict())
            else:
                items.append(dict(vars(item)))
        data = {
            "date": getattr(plan, "date", date_str),
            "items": items,
            "notes": getattr(plan, "notes", None),
            "source": getattr(plan, "source", "manual"),
            "checkpoint_reviews": getattr(plan, "checkpoint_reviews", {}),
            "revision_count": getattr(plan, "revision_count", 0),
            "generated_at": getattr(plan, "generated_at", 0.0),
            "updated_at": getattr(plan, "updated_at", 0.0),
        }
    data["date"] = data.get("date") or date_str
    # goal 是配置真源的运行时投影，绝不从持久化 DailyPlan 读取。
    data["daily_goal_minutes"] = _daily_study_goal_minutes()
    return data


@router.get("/plan", summary="获取结构化 DailyPlan")
async def get_typed_daily_plan(
    date: str = Query(..., description="日期，格式 YYYY-MM-DD"),
):
    """直接读取计划真源并返回 typed JSON。

    ``plan.md`` 继续保留给人查看，但应用客户端不应再依赖 Markdown 解析计划项。
    """
    parsed = _validate_date_string(date)
    if not parsed:
        return _invalid_plan_date_response(date)
    year, month, day = parsed
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    try:
        from core.services.journal.service import get_journal_service

        plan = await get_journal_service().get_plan(date_str)
        return success_response(data=_serialize_daily_plan(plan, date_str))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 计划项定位 ====================

def _normalize_plan_title(text: str) -> str:
    """旧客户端兼容：剥掉行尾状态标记与全部空白。"""
    value = (text or "").strip()
    changed = True
    while value and changed:
        changed = False
        for mark in _PLAN_STATUS_MARKS:
            if value.endswith(mark):
                value = value[: -len(mark)].strip()
                changed = True
    return _PLAN_WHITESPACE_RE.sub("", value)


def _plan_title_matches(client_key: str, item_key: str) -> bool:
    """旧客户端兼容：允许 Markdown 解析造成的标题前后缀漂移。"""
    if not client_key or not item_key:
        return False
    return (
        client_key == item_key
        or client_key.startswith(item_key)
        or item_key.startswith(client_key)
    )


def _normalize_plan_time(text: str) -> str:
    match = _PLAN_TIME_RE.search(text or "")
    return match.group(0) if match else ""


def _match_plan_item(plan: Any, time_token: str, title_key: str) -> Optional[Any]:
    """旧客户端兼容：按名称 + 时间定位。"""
    if not title_key:
        return None
    candidates = [
        item
        for item in plan.items
        if _plan_title_matches(
            title_key, _normalize_plan_title(getattr(item, "title", ""))
        )
    ]
    if not candidates:
        return None
    if time_token:
        for item in candidates:
            if _normalize_plan_time(getattr(item, "time", "") or "") == time_token:
                return item
    else:
        for item in candidates:
            if not getattr(item, "time", None):
                return item
    return candidates[0] if len(candidates) == 1 else None


def _invalid_plan_date_response(date_str: str) -> Dict[str, Any]:
    return error_response(
        ErrorCode.INVALID_PARAMETER,
        message=f"日期格式无效：{date_str}，应为 YYYY-MM-DD",
    )


def _missing_title_response() -> Dict[str, Any]:
    return error_response(
        ErrorCode.MISSING_PARAMETER,
        message="计划项名称不能为空",
    )


def _missing_item_ref_response() -> Dict[str, Any]:
    return error_response(
        ErrorCode.MISSING_PARAMETER,
        message="缺少计划项 item_id；旧客户端需提供名称与时间",
    )


async def _load_plan_item(
    date_str: str,
    *,
    item_id: Optional[str] = None,
    time_text: str = "",
    title_text: str = "",
):
    """优先按稳定 ID 精确定位；仅未传 ID 时允许旧式名称+时间匹配。"""
    from core.services.journal.service import get_journal_service

    journal = get_journal_service()
    plan = await journal.get_plan(date_str)
    if plan is None:
        return None, None, error_response(
            ErrorCode.RESOURCE_NOT_FOUND,
            message=f"{date_str} 暂无计划",
        )

    stable_id = (item_id or "").strip()
    if stable_id:
        item = next(
            (candidate for candidate in plan.items if getattr(candidate, "id", "") == stable_id),
            None,
        )
        if item is None:
            return None, None, error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message="计划项不存在或已变化，请刷新后重试",
            )
        return journal, item, None

    title_key = _normalize_plan_title(title_text)
    if not title_key:
        return None, None, _missing_item_ref_response()
    item = _match_plan_item(plan, _normalize_plan_time(time_text), title_key)
    if item is None:
        return None, None, error_response(
            ErrorCode.RESOURCE_NOT_FOUND,
            message="计划项不存在或已变化，请刷新后重试",
        )
    return journal, item, None


async def _plan_item_success(
    date_str: str, parsed: tuple, item_id: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    """兼容旧客户端：仍回传最新 plan.md；typed 客户端成功后重新 GET /plan。"""
    year, month, day = parsed
    plan_text = await _read_text_async(_plan_file_path(year, month, day))
    data: Dict[str, Any] = {"date": date_str, "plan": plan_text}
    if item_id:
        data["item_id"] = item_id
    data.update(extra)
    return success_response(data=data)


# ==================== 写端点 ====================

@router.post("/plan/item/status", summary="勾选 / 取消勾选指定日期的计划项")
async def update_plan_item_status(payload: PlanItemStatusRequest = Body(...)):
    parsed = _validate_date_string(payload.date)
    if not parsed:
        return _invalid_plan_date_response(payload.date)
    if not (payload.item_id or "").strip() and not _normalize_plan_title(payload.title):
        return _missing_item_ref_response()
    year, month, day = parsed
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    try:
        journal, item, error = await _load_plan_item(
            date_str,
            item_id=payload.item_id,
            time_text=payload.time,
            title_text=payload.title,
        )
        if error is not None:
            return error
        status = "completed" if payload.done else "pending"
        updated = await journal.mark_plan_item_status(date_str, item.id, status)
        if updated is None:
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                message="写入计划项状态失败",
            )
        return await _plan_item_success(date_str, parsed, item.id, status=status)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/plan/item/add", summary="新增计划项")
async def add_plan_item(payload: PlanItemAddRequest = Body(...)):
    parsed = _validate_date_string(payload.date)
    if not parsed:
        return _invalid_plan_date_response(payload.date)
    title = (payload.title or "").strip()
    if not title:
        return _missing_title_response()
    year, month, day = parsed
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    try:
        from core.services.journal.service import get_journal_service

        item_dict: Dict[str, Any] = {"time": payload.time, "title": title}
        if payload.duration_minutes is not None:
            item_dict["estimated_duration_minutes"] = payload.duration_minutes
        plan = await get_journal_service().add_plan_item(date_str, item_dict)
        if plan is None:
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                message="新增计划项失败",
            )
        # PlanCRUDService 当前语义是 append 后保存；回传新稳定 ID 供 typed 客户端立即使用。
        new_item_id = getattr(plan.items[-1], "id", None) if getattr(plan, "items", None) else None
        return await _plan_item_success(date_str, parsed, new_item_id)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/plan/item/update", summary="编辑计划项")
async def update_plan_item(payload: PlanItemUpdateRequest = Body(...)):
    parsed = _validate_date_string(payload.date)
    if not parsed:
        return _invalid_plan_date_response(payload.date)
    title = (payload.title or "").strip()
    if not title:
        return _missing_title_response()
    if not (payload.item_id or "").strip() and not _normalize_plan_title(payload.target_title):
        return _missing_item_ref_response()
    year, month, day = parsed
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    try:
        journal, item, error = await _load_plan_item(
            date_str,
            item_id=payload.item_id,
            time_text=payload.target_time,
            title_text=payload.target_title,
        )
        if error is not None:
            return error
        updates: Dict[str, Any] = {"time": payload.time, "title": title}
        if payload.duration_minutes is not None:
            updates["estimated_duration_minutes"] = payload.duration_minutes
        updated = await journal.update_plan_item(date_str, item.id, updates)
        if updated is None:
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                message="编辑计划项失败",
            )
        return await _plan_item_success(date_str, parsed, item.id)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/plan/item/remove", summary="删除计划项")
async def remove_plan_item(payload: PlanItemRefRequest = Body(...)):
    parsed = _validate_date_string(payload.date)
    if not parsed:
        return _invalid_plan_date_response(payload.date)
    if not (payload.item_id or "").strip() and not _normalize_plan_title(payload.title):
        return _missing_item_ref_response()
    year, month, day = parsed
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    try:
        journal, item, error = await _load_plan_item(
            date_str,
            item_id=payload.item_id,
            time_text=payload.time,
            title_text=payload.title,
        )
        if error is not None:
            return error
        updated = await journal.remove_plan_item(date_str, item.id)
        if updated is None:
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                message="删除计划项失败",
            )
        return await _plan_item_success(date_str, parsed, item.id)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))