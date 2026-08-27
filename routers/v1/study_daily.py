# -*- coding: utf-8 -*-
"""Study Daily 学习日报域。

提供对 D:\\AI\\Study\\Daily 目录的结构化访问：
- 日历视图：按月查看哪些日期有日记/计划/进度
- 按日期读取：获取指定日期的 diary/plan/progress 全部内容
- 专题笔记：列出并读取 Daily/YYYY/MM/ 下的专题笔记
- 最新进度：获取最近一份学习进度文件内容

目录结构约定：
- Daily/YYYY/MM/DD.md        每日学习进度文件（progress）
- Daily/YYYY/MM/DD/diary.md  每日日记
- Daily/YYYY/MM/DD/plan.md   每日计划
- Daily/YYYY/MM/专题笔记.md   专题知识笔记（文件名非 DD.md 的 .md 文件）
"""

import asyncio
import re
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message
from core.utils.data_paths import get_study_daily_dir, get_study_root_dir

router = APIRouter(prefix="/study-daily", tags=["study-daily"])

# 日期字符串校验：YYYY-MM-DD
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# 进度文件名格式：DD.md（两位数字 + .md）
_DAY_FILE_RE = re.compile(r"^(\d{2})\.md$")
# 日期子目录名格式：DD（两位数字）
_DAY_DIR_RE = re.compile(r"^\d{2}$")


# ==================== 工具函数 ====================

def _validate_date_string(date_str: str) -> Optional[tuple]:
    """校验日期字符串，返回 (year, month, day) 或 None"""
    m = _DATE_RE.match(date_str or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        _date(y, mo, d)
    except ValueError:
        return None
    return (y, mo, d)


def _is_safe_filename(filename: str) -> bool:
    """校验文件名是否安全（防止路径穿越攻击）"""
    if not filename:
        return False
    # 禁止路径分隔符、空字节、上级目录引用
    if "/" in filename or "\\" in filename or "\x00" in filename:
        return False
    if filename in (".", ".."):
        return False
    return True


def _read_text_sync(path: Path) -> str:
    """同步读取文本文件，不存在或读取失败返回空字符串"""
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


async def _read_text_async(path: Path) -> str:
    """异步读取文本文件（用线程池包装同步 IO）"""
    return await asyncio.to_thread(_read_text_sync, path)


def _progress_file_path(year: int, month: int, day: int) -> Path:
    """获取进度文件路径：Daily/YYYY/MM/DD.md"""
    return get_study_daily_dir() / f"{year:04d}" / f"{month:02d}" / f"{day:02d}.md"


def _date_dir_path(year: int, month: int, day: int) -> Path:
    """获取日期子目录路径：Daily/YYYY/MM/DD/"""
    return get_study_daily_dir() / f"{year:04d}" / f"{month:02d}" / f"{day:02d}"


def _diary_file_path(year: int, month: int, day: int) -> Path:
    """获取日记文件路径：Daily/YYYY/MM/DD/diary.md"""
    return _date_dir_path(year, month, day) / "diary.md"


def _plan_file_path(year: int, month: int, day: int) -> Path:
    """获取计划文件路径：Daily/YYYY/MM/DD/plan.md"""
    return _date_dir_path(year, month, day) / "plan.md"


def _is_progress_filename(name: str) -> bool:
    """判断文件名是否为进度文件（DD.md 格式）"""
    return bool(_DAY_FILE_RE.match(name))


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


# ==================== 专题笔记 ====================

def _list_topic_notes_sync(base: Path) -> List[Dict[str, Any]]:
    """扫描所有专题笔记。

    专题笔记 = .md 文件且文件名不是 DD.md / diary.md / plan.md。
    支持两种目录结构 (兼容历史和当前实际存放方式):
      1. Daily/YYYY/MM/专题笔记.md          (旧约定, 月目录直接放文件)
      2. Daily/YYYY/MM/DD/专题笔记.md       (实际结构, 笔记放在日子目录内)
    """
    notes: List[Dict[str, Any]] = []
    if not base.exists() or not base.is_dir():
        return notes

    def _collect_md_files(directory: Path, year: str, month: str, day: Optional[str]) -> None:
        """收集 directory 下所有合法专题笔记 .md 文件 (非 progress/diary/plan)"""
        if not directory.is_dir():
            return
        for entry in sorted(directory.iterdir()):
            if not entry.is_file() or not entry.name.endswith(".md"):
                continue
            # 排除进度文件 DD.md / 每日日记 diary.md / 每日计划 plan.md
            if _is_progress_filename(entry.name):
                continue
            if entry.name.lower() in ("diary.md", "plan.md"):
                continue
            # path 字段: 优先带 day, 否则只到 month
            path_suffix = f"{year}/{month}/{day}/{entry.name}" if day else f"{year}/{month}/{entry.name}"
            notes.append({
                "filename": entry.name,
                "path": path_suffix,
                "year": int(year),
                "month": int(month),
            })

    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = year_dir.name
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            month = month_dir.name
            # 结构 1: 月目录直接放的 .md (旧约定)
            _collect_md_files(month_dir, year, month, day=None)
            # 结构 2: 月目录下的日子子目录里放的 .md (实际结构)
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                _collect_md_files(day_dir, year, month, day=day_dir.name)
    return notes


@router.get("/notes", summary="获取所有专题笔记列表")
async def list_notes():
    """获取所有专题笔记列表（文件名和路径）"""
    try:
        base = get_study_daily_dir()
        notes = await asyncio.to_thread(_list_topic_notes_sync, base)
        return success_response(data={"notes": notes, "total": len(notes)})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


def _find_note_sync(base: Path, filename: str) -> Optional[Path]:
    """按文件名查找专题笔记，返回最近修改的一份（跨年月/日子目录可能重名）

    支持两种目录结构 (与 _list_topic_notes_sync 一致):
      1. Daily/YYYY/MM/filename           (旧约定)
      2. Daily/YYYY/MM/DD/filename        (实际结构)
    """
    if not base.exists() or not base.is_dir():
        return None
    candidates: List[Path] = []
    for year_dir in base.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            # 结构 1: 月目录直接查
            candidate = month_dir / filename
            if candidate.is_file():
                candidates.append(candidate)
            # 结构 2: 进入日子目录查
            for day_dir in month_dir.iterdir():
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                candidate_in_day = day_dir / filename
                if candidate_in_day.is_file():
                    candidates.append(candidate_in_day)
    if not candidates:
        return None
    # 按修改时间倒序，取最新一份
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


@router.get("/notes/{filename}", summary="读取指定专题笔记内容")
async def get_note(filename: str):
    """读取指定专题笔记内容（按文件名查找，返回最近修改的一份）"""
    if not _is_safe_filename(filename):
        return error_response(
            ErrorCode.INVALID_PARAMETER,
            message=f"文件名无效：{filename}",
        )
    try:
        base = get_study_daily_dir()
        target = await asyncio.to_thread(_find_note_sync, base, filename)
        if target is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message=f"专题笔记不存在：{filename}",
            )
        content = await _read_text_async(target)
        rel_path = str(target.relative_to(base)).replace("\\", "/")
        return success_response(data={
            "filename": filename,
            "path": rel_path,
            "content": content,
        })
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 学习库（study_root 科目文件夹笔记） ====================

# 学习库扫描时排除的顶层目录（Daily 由日报域接口覆盖，media 为媒体资源）
_LIBRARY_EXCLUDED_DIRS = {"daily", "media", "study_tools"}


def _is_hidden_path(path: Path) -> bool:
    """判断路径中是否包含隐藏文件/目录（以 . 开头的路径段）。"""
    return any(part.startswith(".") for part in path.parts)


def _list_library_notes_sync(root: Path) -> List[Dict[str, Any]]:
    """扫描学习根目录下的科目文件夹，收集所有 .md 笔记。

    目录结构约定：
    - Study/<科目>/xxx.md            → subject=科目名
    - Study/<科目>/<子目录>/xxx.md   → subject=科目名（递归收集）
    - Study/备忘录.md                → subject="未分类"（根目录散文件）

    过滤规则：
    - 排除隐藏文件/目录（以 . 开头）
    - 排除 _LIBRARY_EXCLUDED_DIRS 指定的顶层目录

    返回元素: {subject, filename, rel_path, updated_ts}
    rel_path 使用正斜杠，相对于学习根目录。
    """
    notes: List[Dict[str, Any]] = []
    if not root.exists() or not root.is_dir():
        return notes

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except Exception:
            return 0.0

    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        # 跳过隐藏目录/文件
        if entry.name.startswith("."):
            continue
        # 根目录散放的 .md 文件归入"未分类"
        if entry.is_file() and entry.name.endswith(".md"):
            notes.append({
                "subject": "未分类",
                "filename": entry.name,
                "rel_path": entry.name,
                "updated_ts": _mtime(entry),
            })
            continue
        if not entry.is_dir():
            continue
        if entry.name.lower() in _LIBRARY_EXCLUDED_DIRS:
            continue
        subject = entry.name
        for md_file in sorted(entry.rglob("*.md"), key=lambda p: p.name.lower()):
            if not md_file.is_file():
                continue
            rel = md_file.relative_to(root)
            # 排除隐藏目录/文件
            if _is_hidden_path(rel):
                continue
            notes.append({
                "subject": subject,
                "filename": md_file.name,
                "rel_path": rel.as_posix(),
                "updated_ts": _mtime(md_file),
            })
    return notes


@router.get("/library", summary="获取学习库笔记列表（study_root 科目文件夹）")
async def list_library_notes():
    """列出 D:\\AI\\Study 根目录下各科目文件夹中的所有 .md 笔记。

    返回 data.notes 数组（含 subject/filename/rel_path/updated_ts）和 data.total。
    """
    try:
        root = get_study_root_dir()
        notes = await asyncio.to_thread(_list_library_notes_sync, root)
        return success_response(data={"notes": notes, "total": len(notes)})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


def _resolve_library_note_path(root: Path, rel_path: str) -> Optional[Path]:
    """将相对路径解析为绝对路径并做安全校验（防路径穿越，仅限 .md）。"""
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or not rel.endswith(".md"):
        return None
    if "\x00" in rel:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


@router.get("/library/note", summary="读取学习库笔记内容（按相对路径）")
async def get_library_note(
    path: str = Query(..., description="相对于学习根目录的路径，如 Mathematics/极限.md"),
):
    """读取学习库中指定笔记的完整 Markdown 内容。"""
    try:
        root = get_study_root_dir()
        target = _resolve_library_note_path(root, path)
        if target is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message=f"学习库笔记不存在或路径无效：{path}",
            )
        content = await _read_text_async(target)
        rel = target.relative_to(root).as_posix()
        return success_response(data={
            "filename": target.name,
            "path": rel,
            "content": content,
        })
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 计划写入 ====================

class PlanUpdateRequest(BaseModel):
    """更新指定日期 plan.md 的请求体"""

    date: str = Field(..., description="日期，格式 YYYY-MM-DD")
    plan: str = Field("", description="计划 Markdown 全文")


def _write_text_sync(path: Path, content: str) -> None:
    """同步写入文本文件，自动创建父目录"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@router.post("/plan", summary="更新指定日期的学习计划")
async def update_plan(payload: PlanUpdateRequest = Body(...)):
    """覆盖写入指定日期的 plan.md（目录不存在时自动创建）。

    用于 App 端手动编辑计划项（名称/时间/完成状态）后持久化。
    """
    parsed = _validate_date_string(payload.date)
    if not parsed:
        return error_response(
            ErrorCode.INVALID_PARAMETER,
            message=f"日期格式无效：{payload.date}，应为 YYYY-MM-DD",
        )
    year, month, day = parsed
    try:
        target = _plan_file_path(year, month, day)
        await asyncio.to_thread(_write_text_sync, target, payload.plan or "")
        return success_response(data={
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "path": str(target.relative_to(get_study_daily_dir())).replace("\\", "/"),
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
