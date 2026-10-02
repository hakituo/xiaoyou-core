# -*- coding: utf-8 -*-
"""Study Daily 学习日报域 - 日报内容读取。

- GET /study-daily/calendar          月度日历：哪些日期有 diary/plan/progress
- GET /study-daily/date/{date}       按日期读取 diary/plan/progress 全文
- GET /study-daily/latest-progress   最近一份学习进度文件
"""

import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Query

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message
from core.utils.data_paths import get_study_daily_dir

from .study_daily_shared import (
    _DAY_DIR_RE,
    _DAY_FILE_RE,
    _diary_file_path,
    _is_progress_filename,
    _plan_file_path,
    _progress_file_path,
    _read_text_async,
    _validate_date_string,
)

router = APIRouter(prefix="/study-daily", tags=["study-daily"])


# ==================== 日历 ====================

@router.get("/calendar", summary="获取月度日历数据")
async def get_calendar(
    year: int = Query(..., ge=1900, le=9999, description="年份，如 2026"),
    month: int = Query(..., ge=1, le=12, description="月份，如 6"),
):
    """返回指定月份中哪些日期有内容（diary/plan/progress）。

    返回 data.days 数组，每个元素包含 date/day/has_diary/has_plan/has_progress。
    """
    try:
        base = get_study_daily_dir()
        month_dir = base / f"{year:04d}" / f"{month:02d}"

        # 用字典收集每天的内容标记
        day_map: Dict[int, Dict[str, bool]] = {}

        def _ensure(day: int) -> Dict[str, bool]:
            if day not in day_map:
                day_map[day] = {
                    "has_diary": False,
                    "has_plan": False,
                    "has_progress": False,
                }
            return day_map[day]

        def _scan() -> None:
            if not month_dir.exists() or not month_dir.is_dir():
                return
            for entry in month_dir.iterdir():
                name = entry.name
                # 进度文件 DD.md
                m = _DAY_FILE_RE.match(name)
                if m and entry.is_file():
                    day = int(m.group(1))
                    if 1 <= day <= 31:
                        _ensure(day)["has_progress"] = True
                    continue
                # 日期子目录 DD/（包含 diary.md / plan.md）
                if entry.is_dir() and _DAY_DIR_RE.match(name):
                    day = int(name)
                    if 1 <= day <= 31:
                        flags = _ensure(day)
                        if (entry / "diary.md").is_file():
                            flags["has_diary"] = True
                        if (entry / "plan.md").is_file():
                            flags["has_plan"] = True

        await asyncio.to_thread(_scan)

        days = []
        for day in sorted(day_map.keys()):
            flags = day_map[day]
            days.append({
                "date": f"{year:04d}-{month:02d}-{day:02d}",
                "day": day,
                **flags,
            })

        return success_response(data={
            "year": year,
            "month": month,
            "days": days,
        })
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 按日期读取 ====================

@router.get("/date/{date}", summary="获取指定日期的所有内容")
async def get_date_content(date: str):
    """获取指定日期的日记、计划、进度内容（date 格式：YYYY-MM-DD）。

    返回 {date, diary, plan, progress}，文件不存在时对应字段为空字符串。
    """
    parsed = _validate_date_string(date)
    if not parsed:
        return error_response(
            ErrorCode.INVALID_PARAMETER,
            message=f"日期格式无效：{date}，应为 YYYY-MM-DD",
        )
    year, month, day = parsed
    try:
        # 并发读取三类文件
        progress, diary, plan = await asyncio.gather(
            _read_text_async(_progress_file_path(year, month, day)),
            _read_text_async(_diary_file_path(year, month, day)),
            _read_text_async(_plan_file_path(year, month, day)),
        )
        return success_response(data={
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "diary": diary,
            "plan": plan,
            "progress": progress,
        })
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 最新进度 ====================

def _find_latest_progress_sync(base: Path) -> Optional[Path]:
    """查找最新的进度文件（Daily/YYYY/MM/DD.md）。

    按路径名字典序倒序排列（YYYY/MM/DD.md 零填充格式下字典序即时间序）。
    """
    if not base.exists() or not base.is_dir():
        return None
    progress_files: List[Path] = []
    for year_dir in base.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for entry in month_dir.iterdir():
                if entry.is_file() and _is_progress_filename(entry.name):
                    progress_files.append(entry)
    if not progress_files:
        return None
    progress_files.sort(key=lambda p: str(p.relative_to(base)), reverse=True)
    return progress_files[0]


@router.get("/latest-progress", summary="获取最新的学习进度文件内容")
async def get_latest_progress():
    """获取最新的学习进度文件内容"""
    try:
        base = get_study_daily_dir()
        target = await asyncio.to_thread(_find_latest_progress_sync, base)
        if target is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message="暂无学习进度文件",
            )
        content = await _read_text_async(target)
        rel = target.relative_to(base)
        parts = rel.parts  # (YYYY, MM, DD.md)
        day_str = parts[2][:-3] if parts[2].endswith(".md") else parts[2]
        return success_response(data={
            "date": f"{parts[0]}-{parts[1]}-{day_str}",
            "path": str(rel).replace("\\", "/"),
            "content": content,
        })
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
