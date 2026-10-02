# -*- coding: utf-8 -*-
"""日常数据记录子路由。

从 routers.v1.context 解耦,专门处理喝水、学习、体重、作息等日常数据记录,
以及每日画像、最近文件浏览等接口。
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.data_paths import get_companion_data_dir
from core.utils.time_utils import now_iso, now_str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context", tags=["日常数据"])

_DAILY_DATA_BASE_DIR = get_companion_data_dir()


# ==================== 数据模型 ====================


class DrinkRecordRequest(BaseModel):
    units: Optional[float] = Field(1.0, ge=0.1, le=20)
    amount_ml: Optional[int] = Field(None, ge=1, le=5000)
    beverage: Optional[str] = Field("水")


class StudyRecordRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=80)
    duration_minutes: int = Field(45, ge=1, le=720)
    note: Optional[str] = Field("", max_length=300)
    enter_low_disturbance: bool = Field(True)
    switch_mode_to_study: bool = Field(True)


class BodyMetricsRecordRequest(BaseModel):
    weight_kg: Optional[float] = Field(None, ge=20.0, le=300.0)


class ScheduleUpdateRequest(BaseModel):
    sleep: Optional[str] = Field(None, description="睡觉时间 HH:MM")
    wakeup: Optional[str] = Field(None, description="起床时间 HH:MM")
    date: Optional[str] = Field(None, description="目标日期 YYYY-MM-DD, 默认今天")


# ==================== 辅助函数 ====================


def _resolve_daily_data_path(relative_path: Optional[str]) -> Path:
    if relative_path is None or not str(relative_path).strip():
        return _DAILY_DATA_BASE_DIR
    rel = Path(str(relative_path).strip())
    if rel.is_absolute():
        raise ValueError("path 必须是相对路径")
    base = _DAILY_DATA_BASE_DIR
    target = (base / rel).resolve()
    base_str = str(base)
    target_str = str(target)
    if target_str == base_str:
        return target
    if not target_str.startswith(base_str + os.sep):
        raise ValueError("禁止访问 companion_data 目录之外的路径")
    return target


def _extract_total_drink_ml(record: dict[str, Any]) -> tuple[int, int]:
    meals = record.get("meals")
    if not isinstance(meals, list):
        return 0, 0
    total_ml = 0
    drink_count = 0
    for meal in meals:
        if not isinstance(meal, dict):
            continue
        if str(meal.get("type") or "").strip().lower() != "drink":
            continue
        drink_count += 1
        match = re.search(r"(\d+)\s*ml", str(meal.get("content") or ""), re.IGNORECASE)
        if match:
            total_ml += int(match.group(1))
            continue
        match_any = re.search(r"(\d+)", str(meal.get("content") or ""))
        if match_any:
            total_ml += int(match_any.group(1))
    return total_ml, drink_count


def _extract_study_total_minutes(
    record: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    study = record.get("study")
    sessions = []
    if isinstance(study, dict) and isinstance(study.get("sessions"), list):
        sessions = [s for s in study.get("sessions") if isinstance(s, dict)]
    total_minutes = 0
    for session in sessions:
        text = f"{session.get('content') or ''} {session.get('topic') or ''}"
        m = re.search(r"(\d+)\s*分钟", text)
        if m:
            total_minutes += int(m.group(1))
    return total_minutes, sessions


async def _build_today_portrait_payload() -> dict[str, Any]:
    from core.services.daily.manager import get_daily_manager
    from core.services.active_care.core.service import get_active_care_service
    from core.managers.preference_manager import get_preference_manager
    from core.services.workspace.status_manager import get_user_status_manager

    daily_mgr = get_daily_manager()
    record = await asyncio.to_thread(daily_mgr.get_record, None)
    total_drink_ml, drink_count = _extract_total_drink_ml(record)
    study_minutes, study_sessions = _extract_study_total_minutes(record)

    proactive_state = {}
    preference_mode = "normal"
    try:
        svc = get_active_care_service()
        proactive_state = await svc.storage.get_proactive_state()
    except Exception:
        proactive_state = {}
    try:
        preference_mode = str(get_preference_manager().get_mode() or "normal")
    except Exception:
        preference_mode = "normal"

    # 作息数据在新版 daily record 中位于 sleep_cycle; schedule 字段已弃用并被迁移时 pop 掉
    sleep_cycle = (
        record.get("sleep_cycle") if isinstance(record.get("sleep_cycle"), dict) else {}
    )
    schedule = {
        "wakeup": sleep_cycle.get("wakeup"),
        "sleep": sleep_cycle.get("sleep"),
        "duration": sleep_cycle.get("duration"),
    }
    meals = record.get("meals") if isinstance(record.get("meals"), list) else []
    activities = (
        record.get("activities") if isinstance(record.get("activities"), list) else []
    )
    persistent_statuses: list[dict[str, Any]] = []
    body_metrics: dict[str, Any] = {}
    try:
        status_manager = get_user_status_manager()
        raw_statuses = await asyncio.to_thread(status_manager.get_active_statuses)
        for item in raw_statuses:
            if not isinstance(item, dict):
                continue
            persistent_statuses.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "description": str(item.get("description") or "").strip(),
                    "expires_at": float(item.get("expires_at") or 0.0)
                    if item.get("expires_at") is not None
                    else None,
                    "updated_at": float(item.get("updated_at") or 0.0),
                }
            )
        body_metrics = await asyncio.to_thread(status_manager.get_body_metrics)
    except Exception:
        persistent_statuses = []
        body_metrics = {}
    return {
        "status": "success",
        "date": record.get("date") or now_str("%Y-%m-%d"),
        "portrait": {
            "schedule": {
                "wakeup": schedule.get("wakeup"),
                "sleep": schedule.get("sleep"),
            },
            "drink": {"total_ml": total_drink_ml, "count": drink_count},
            "study": {
                "total_minutes": study_minutes,
                "count": len(study_sessions),
                "sessions": study_sessions[-20:],
            },
            "meals": meals[-20:],
            "activities": activities[-20:],
            "persistent_statuses": persistent_statuses,
            "body_metrics": {
                "weight_kg": float(body_metrics.get("weight_kg"))
                if isinstance(body_metrics.get("weight_kg"), (int, float))
                else None,
                "weight_updated_at": float(
                    body_metrics.get("weight_updated_at") or 0.0
                ),
            },
            "mode": {
                "preference_mode": preference_mode,
                "reduced_mode_active": bool(proactive_state.get("reduced_mode_active")),
                "reduced_mode_reason": str(
                    proactive_state.get("reduced_mode_reason") or "none"
                ),
                "reduced_mode_expected_end_ts": float(
                    proactive_state.get("reduced_mode_expected_end_ts") or 0.0
                ),
            },
        },
        "timestamp": now_iso(),
    }


# ==================== 日常数据记录 ====================


@router.post("/daily/record/drink", summary="记录喝水")
async def record_drink(payload: DrinkRecordRequest):
    try:
        from core.services.daily.manager import get_daily_manager
        from core.services.workspace.status_manager import get_user_status_manager

        amount_ml = int(payload.amount_ml) if payload.amount_ml else 0
        if amount_ml <= 0:
            amount_ml = int(round(float(payload.units or 1.0) * 250))
        amount_ml = max(50, min(amount_ml, 5000))

        beverage = str(payload.beverage or "水").strip() or "水"
        canonical_beverage = "水" if beverage in {"水", "白水", "普通水"} else beverage
        content = f"喝{'' if canonical_beverage == '水' else canonical_beverage + ' '} {amount_ml}ml".replace(
            "  ", " "
        )

        daily_mgr = get_daily_manager()
        message = await asyncio.to_thread(daily_mgr.record_drink, "drink", content)

        manager = get_user_status_manager()
        statuses = await asyncio.to_thread(manager._load_statuses)
        current_total = 0
        for s in statuses:
            if not isinstance(s, dict):
                continue
            if s.get("name") != "今日饮水":
                continue
            m_exist = re.search(r"(\d+)ml", str(s.get("description") or ""))
            if m_exist:
                current_total = int(m_exist.group(1))
            break
        new_total = current_total + amount_ml
        now_hm = now_str("%H:%M")
        await asyncio.to_thread(
            manager.add_status, "今日饮水", f"已喝 {new_total}ml (最近: {now_hm})", 1
        )

        portrait_payload = await _build_today_portrait_payload()
        return {
            "status": "success",
            "message": message,
            "drink_ml": amount_ml,
            "drink_total_ml": new_total,
            "portrait": portrait_payload.get("portrait"),
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"daily-data record drink failed: {e}")
        return error_response(
            ErrorCode.DAILY_DATA_READ_FAILED, message=f"记录喝水失败: {e}"
        )


@router.post("/daily/record/body-metrics", summary="记录体重")
async def record_body_metrics(payload: BodyMetricsRecordRequest):
    try:
        if payload.weight_kg is None:
            return error_response(ErrorCode.INVALID_PARAMETER, message="体重不能为空")
        from core.services.workspace.status_manager import get_user_status_manager

        manager = get_user_status_manager()
        body_metrics = await asyncio.to_thread(
            manager.set_weight_kg, float(payload.weight_kg)
        )
        portrait_payload = await _build_today_portrait_payload()
        return {
            "status": "success",
            "message": f"体重已更新为 {float(payload.weight_kg):.1f}kg",
            "body_metrics": body_metrics,
            "portrait": portrait_payload.get("portrait"),
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"daily-data record body metrics failed: {e}")
        return error_response(
            ErrorCode.DAILY_DATA_READ_FAILED, message=f"记录体重失败: {e}"
        )


@router.post("/daily/record/schedule", summary="更新今日作息")
async def record_schedule(payload: ScheduleUpdateRequest):
    """手动更新指定日期的睡觉/起床时间, 用于用户修正不准确的自动记录。"""
    try:
        if not payload.sleep and not payload.wakeup:
            return error_response(
                ErrorCode.INVALID_PARAMETER, message="sleep 和 wakeup 至少需要一个"
            )
        from core.services.daily.manager import get_daily_manager

        daily_mgr = get_daily_manager()
        message = await asyncio.to_thread(
            daily_mgr.update_sleep_cycle,
            sleep_time=payload.sleep,
            wakeup_time=payload.wakeup,
            target_date=payload.date,
        )
        portrait_payload = await _build_today_portrait_payload()
        return {
            "status": "success",
            "message": message,
            "portrait": portrait_payload.get("portrait"),
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"daily-data record schedule failed: {e}")
        return error_response(
            ErrorCode.DAILY_DATA_READ_FAILED, message=f"更新作息失败: {e}"
        )


@router.post("/daily/record/study", summary="记录学习（进入低打扰）")
async def record_study(payload: StudyRecordRequest):
    try:
        from core.services.daily.manager import get_daily_manager
        from core.services.active_care.core.service import get_active_care_service
        from core.managers.preference_manager import get_preference_manager

        subject = str(payload.subject or "").strip()
        if not subject:
            return error_response(
                ErrorCode.INVALID_PARAMETER, message="学习科目不能为空"
            )
        duration = max(1, min(int(payload.duration_minutes), 720))
        note = str(payload.note or "").strip()
        content = f"学习 {duration}分钟" + (f"；{note}" if note else "")

        daily_mgr = get_daily_manager()
        message = await asyncio.to_thread(daily_mgr.record_study, subject, content)

        now_ts = time.time()
        if payload.enter_low_disturbance:
            svc = get_active_care_service()
            await svc.storage.save_proactive_state(
                {
                    "reduced_mode_active": True,
                    "reduced_mode_reason": "focus",
                    "reduced_mode_label": "study",
                    "reduced_mode_started_ts": now_ts,
                    "reduced_mode_expected_end_ts": now_ts + (duration * 60),
                }
            )
            await svc.checker.set_next_decision_ts(
                now_ts + min(300, duration * 60), source="study_record_enter_reduced"
            )

        if payload.switch_mode_to_study:
            try:
                await get_preference_manager().set_mode("study")
            except Exception as mode_err:
                logger.warning(f"switch mode to study failed: {mode_err}")

        portrait_payload = await _build_today_portrait_payload()
        return {
            "status": "success",
            "message": message,
            "subject": subject,
            "duration_minutes": duration,
            "portrait": portrait_payload.get("portrait"),
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"daily-data record study failed: {e}")
        return error_response(
            ErrorCode.DAILY_DATA_READ_FAILED, message=f"记录学习失败: {e}"
        )


@router.post("/daily/study/finish", summary="结束学习（恢复打扰级别）")
async def finish_study():
    try:
        from core.services.active_care.core.service import get_active_care_service
        from core.managers.preference_manager import get_preference_manager

        now_ts = time.time()
        svc = get_active_care_service()
        await svc.storage.save_proactive_state(
            {
                "reduced_mode_active": False,
                "reduced_mode_reason": "none",
                "reduced_mode_label": "",
                "reduced_mode_started_ts": 0.0,
                "reduced_mode_expected_end_ts": 0.0,
                "last_goodmorning_ts": now_ts,
            }
        )
        await svc.checker.set_next_decision_ts(now_ts + 60, source="study_finish")
        try:
            await get_preference_manager().set_mode("normal")
        except Exception as mode_err:
            logger.warning(f"switch mode to normal failed: {mode_err}")

        portrait_payload = await _build_today_portrait_payload()
        return {
            "status": "success",
            "message": "学习时段已结束，已恢复普通打扰级别。",
            "portrait": portrait_payload.get("portrait"),
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"daily-data finish study failed: {e}")
        return error_response(
            ErrorCode.DAILY_DATA_READ_FAILED, message=f"结束学习失败: {e}"
        )


# ==================== 每日画像与文件 ====================


@router.get("/daily/portrait/today", summary="获取今日用户画像")
async def daily_portrait_today():
    try:
        return await _build_today_portrait_payload()
    except Exception as e:
        logger.error(f"daily-data portrait failed: {e}")
        return error_response(
            ErrorCode.DAILY_DATA_READ_FAILED, message=f"读取用户画像失败: {e}"
        )


@router.get("/daily/recent", summary="获取最近的日常数据文件")
async def daily_recent(
    limit: int = Query(12, ge=1, le=100, description="返回最近文件数"),
):
    try:
        base = _DAILY_DATA_BASE_DIR

        def scan():
            if not base.exists() or not base.is_dir():
                return []
            items = []
            for root, _, files in os.walk(str(base)):
                for filename in files:
                    if filename.startswith(".") or filename == ".gitkeep":
                        continue
                    p = (Path(root) / filename).resolve()
                    try:
                        rel = p.relative_to(base)
                    except Exception:
                        continue
                    try:
                        stat = p.stat()
                        items.append(
                            {
                                "path": str(rel).replace("\\", "/"),
                                "name": filename,
                                "size": int(stat.st_size),
                                "mtime": int(stat.st_mtime),
                                "ext": p.suffix.lower().lstrip("."),
                            }
                        )
                    except Exception:
                        items.append(
                            {
                                "path": str(rel).replace("\\", "/"),
                                "name": filename,
                                "size": None,
                                "mtime": None,
                                "ext": p.suffix.lower().lstrip("."),
                            }
                        )
            items.sort(key=lambda x: x.get("mtime") or 0, reverse=True)
            return items[:limit]

        items = await asyncio.to_thread(scan)
        return {"status": "success", "items": items, "timestamp": now_iso()}
    except Exception as e:
        logger.error(f"daily-data recent failed: {e}")
        return error_response(ErrorCode.DAILY_DATA_RECENT_FAILED, message=str(e))


@router.get("/daily/list", summary="列出日常数据目录")
async def daily_list(
    path: Optional[str] = Query(None, description="相对路径"),
    limit: int = Query(200, ge=1, le=1000),
):
    try:
        target = _resolve_daily_data_path(path)
        if not target.exists() or not target.is_dir():
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND, message="目标目录不存在或不是目录"
            )

        def list_dir():
            entries = []
            for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                if child.name.startswith("."):
                    continue
                try:
                    stat = child.stat()
                    count = None
                    if child.is_dir():
                        try:
                            count = len(
                                [
                                    x
                                    for x in child.iterdir()
                                    if not x.name.startswith(".")
                                ]
                            )
                        except Exception:
                            count = 0
                    entries.append(
                        {
                            "name": child.name,
                            "type": "dir" if child.is_dir() else "file",
                            "size": int(stat.st_size) if child.is_file() else 0,
                            "count": count,
                            "mtime": int(stat.st_mtime),
                            "ext": child.suffix.lower().lstrip(".")
                            if child.is_file()
                            else None,
                        }
                    )
                except Exception:
                    entries.append(
                        {
                            "name": child.name,
                            "type": "dir" if child.is_dir() else "file",
                            "size": None,
                            "count": None,
                            "mtime": None,
                            "ext": child.suffix.lower().lstrip(".")
                            if child.is_file()
                            else None,
                        }
                    )
                if len(entries) >= limit:
                    break
            return entries

        items = await asyncio.to_thread(list_dir)
        relative = "" if not path else str(path).strip().replace("\\", "/")
        return {
            "status": "success",
            "path": relative,
            "items": items,
            "timestamp": now_iso(),
        }
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PATH, message=str(ve))
    except Exception as e:
        logger.error(f"daily-data list failed: {e}")
        return error_response(ErrorCode.DAILY_DATA_LIST_FAILED, message=str(e))


@router.get("/daily/read", summary="读取日常数据文件")
async def daily_read(
    path: str = Query(..., description="相对路径"),
    max_chars: int = Query(200000, ge=1000, le=2000000),
):
    try:
        target = _resolve_daily_data_path(path)
        if not target.exists() or not target.is_file():
            return error_response(ErrorCode.RESOURCE_NOT_FOUND, message="文件不存在")

        def read_file():
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read(max_chars + 1)
            truncated = len(raw) > max_chars
            if truncated:
                raw = raw[:max_chars]
            return raw, truncated

        raw, truncated = await asyncio.to_thread(read_file)
        file_type = "json" if target.suffix.lower() == ".json" else "text"
        json_data = None
        if file_type == "json" and not truncated:
            try:
                json_data = json.loads(raw) if raw.strip() else {}
            except Exception:
                json_data = None
        return {
            "status": "success",
            "path": str(path).strip().replace("\\", "/"),
            "type": file_type,
            "content": raw,
            "truncated": truncated,
            "json": json_data,
            "timestamp": now_iso(),
        }
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PATH, message=str(ve))
    except Exception as e:
        logger.error(f"daily-data read failed: {e}")
        return error_response(ErrorCode.DAILY_DATA_READ_FAILED, message=str(e))
