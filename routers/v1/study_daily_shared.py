# -*- coding: utf-8 -*-
"""Study Daily 学习日报域 - 共享基建。

各 study_daily 子域共用的日期校验、Daily 目录路径推导、文本读取与文件名安全校验；
集中在此避免子模块之间互相 import 形成环。本模块**只放工具，不放端点**。

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
from typing import Optional

from core.utils.data_paths import get_study_daily_dir

# 日期字符串校验：YYYY-MM-DD
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# 进度文件名格式：DD.md（两位数字 + .md）
_DAY_FILE_RE = re.compile(r"^(\d{2})\.md$")
# 日期子目录名格式：DD（两位数字）
_DAY_DIR_RE = re.compile(r"^\d{2}$")


# ==================== 日期与文件名校验 ====================

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


def _is_progress_filename(name: str) -> bool:
    """判断文件名是否为进度文件（DD.md 格式）"""
    return bool(_DAY_FILE_RE.match(name))


# ==================== 文本读取 ====================

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


# ==================== Daily 目录路径 ====================

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
