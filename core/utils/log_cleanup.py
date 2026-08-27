#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志自动清理工具
定期清理超过保留天数的日志目录和文件
"""

from core.utils.logger import get_logger
import asyncio

import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

logger = get_logger(__name__)

_DEFAULT_RETENTION_DAYS = 15
_CLEANUP_INTERVAL_SECONDS = 12 * 3600


def _find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "main.py").exists() or (parent / "core").is_dir() and (parent / "config").is_dir():
            return parent
    return current.parent.parent


def scan_old_log_dirs(logs_root: Path, retention_days: int) -> List[Path]:
    """扫描超过保留天数的日期日志目录 (logs/{year}/{month}/{day}/)"""
    cutoff = datetime.now() - timedelta(days=retention_days)
    old_dirs: List[Path] = []

    if not logs_root.is_dir():
        return old_dirs

    for year_dir in logs_root.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year_val = int(year_dir.name)
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            month_val = int(month_dir.name)
            for day_dir in month_dir.iterdir():
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                day_val = int(day_dir.name)
                try:
                    dir_date = datetime(year_val, month_val, day_val)
                except ValueError:
                    continue
                if dir_date < cutoff:
                    old_dirs.append(day_dir)

    return old_dirs


def scan_old_files(directory: Path, retention_days: int, pattern: str = "*") -> List[Path]:
    """扫描目录下超过保留天数的文件"""
    cutoff_time = time.time() - retention_days * 86400
    old_files: List[Path] = []

    if not directory.is_dir():
        return old_files

    for f in directory.iterdir():
        if f.is_file() and f.match(pattern):
            if f.stat().st_mtime < cutoff_time:
                old_files.append(f)

    return old_files


def cleanup_logs(retention_days: int = _DEFAULT_RETENTION_DAYS) -> Tuple[int, int, List[str]]:
    """
    执行日志清理

    Returns:
        (deleted_dirs, deleted_files, errors)
    """
    project_root = _find_project_root()
    logs_root = project_root / "logs"
    deleted_dirs = 0
    deleted_files = 0
    errors: List[str] = []

    old_dirs = scan_old_log_dirs(logs_root, retention_days)
    for d in old_dirs:
        try:
            shutil.rmtree(d)
            deleted_dirs += 1
            logger.info("日志清理: 已删除目录 %s", d)
        except Exception as e:
            errors.append(f"删除目录 {d} 失败: {e}")
            logger.warning("日志清理: 删除目录 %s 失败: %s", d, e)

    for sub_dir_name in ("auto_heal_reports",):
        report_dir = logs_root / sub_dir_name
        old_files = scan_old_files(report_dir, retention_days)
        for f in old_files:
            try:
                f.unlink()
                deleted_files += 1
                logger.info("日志清理: 已删除文件 %s", f)
            except Exception as e:
                errors.append(f"删除文件 {f} 失败: {e}")
                logger.warning("日志清理: 删除文件 %s 失败: %s", f, e)

    api_log = project_root / "logs" / "api_calls_simple.log"
    if api_log.is_file() and api_log.stat().st_mtime < time.time() - retention_days * 86400:
        try:
            api_log.unlink()
            deleted_files += 1
            logger.info("日志清理: 已删除 %s", api_log)
        except Exception as e:
            errors.append(f"删除 {api_log} 失败: {e}")
            logger.warning("日志清理: 删除 %s 失败: %s", api_log, e)

    for year_dir in list(logs_root.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in list(year_dir.iterdir()):
            if month_dir.is_dir() and not any(month_dir.iterdir()):
                try:
                    month_dir.rmdir()
                    logger.info("日志清理: 已删除空月目录 %s", month_dir)
                except OSError:
                    pass
        if year_dir.is_dir() and not any(year_dir.iterdir()):
            try:
                year_dir.rmdir()
                logger.info("日志清理: 已删除空年目录 %s", year_dir)
            except OSError:
                pass

    if deleted_dirs > 0 or deleted_files > 0:
        logger.info(
            "日志清理完成: 删除 %d 个目录, %d 个文件, %d 个错误",
            deleted_dirs, deleted_files, len(errors),
        )
    else:
        logger.debug("日志清理: 无需清理")

    return deleted_dirs, deleted_files, errors


async def log_cleanup_loop(retention_days: int = _DEFAULT_RETENTION_DAYS):
    """异步日志清理循环，每隔一段时间执行一次清理"""
    logger.info("日志清理循环已启动，保留天数=%d，清理间隔=%ds", retention_days, _CLEANUP_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(cleanup_logs, retention_days)
        except asyncio.CancelledError:
            logger.info("日志清理循环已停止")
            break
        except Exception as e:
            logger.error("日志清理循环异常: %s", e)
        try:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("日志清理循环已停止")
            break
