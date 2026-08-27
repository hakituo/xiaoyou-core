"""
自我改进系统 — 每日日志生成

生成 memories/core_memory/YYYY-MM-DD.md 格式的每日日志，记录当天关键事件、决策、任务进展。
与 JournalService 联动，但定位不同：
- JournalService: 用户日记（情感、生活）
- DailyLogger: 开发/运维日志（决策、事件、任务进展）

注意：路径与 core_memory.py 保持一致（memories/core_memory/），避免再生成旧版 memory/ 目录。
"""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("DailyLogger")


class DailyLogger:
    """每日日志生成器"""

    def __init__(self, base_dir: Path):
        # 与 CoreMemory._archive_dir 同级，统一落在 memories/core_memory/ 下
        self._base_dir = base_dir / "memories" / "core_memory"
        self._archive_dir = self._base_dir / "archive"

    # ── 初始化 ──────────────────────────────────────────

    def ensure_dirs(self) -> None:
        """确保目录存在"""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    # ── 日志写入 ────────────────────────────────────────

    def append_event(
        self,
        event: str,
        *,
        category: str = "general",
        details: str = "",
        tags: Optional[List[str]] = None,
    ) -> None:
        """追加事件到今日日志"""
        self.ensure_dirs()
        date_str = time.strftime("%Y-%m-%d")
        log_file = self._base_dir / f"{date_str}.md"

        ts = time.strftime("%H:%M")
        tag_str = " ".join(f"[{t}]" for t in (tags or []))
        line = f"- [{ts}] [{category}] {event}"
        if tag_str:
            line += f" {tag_str}"
        if details:
            line += f"\n  {details}"

        try:
            if not log_file.exists():
                header = f"# {date_str} 日志\n\n"
                log_file.write_text(header, encoding="utf-8")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning("追加每日日志失败: %s", e)

    def append_decision(self, decision: str, reason: str = "", tags: Optional[List[str]] = None) -> None:
        """追加决策到今日日志"""
        self.append_event(
            f"决策: {decision}",
            category="decision",
            details=f"原因: {reason}" if reason else "",
            tags=tags,
        )

    def append_task_progress(self, task: str, status: str, details: str = "") -> None:
        """追加任务进展到今日日志"""
        self.append_event(
            f"任务: {task} → {status}",
            category="task",
            details=details,
        )

    def append_correction_event(self, correction: str, root_cause: str = "") -> None:
        """追加纠正事件到今日日志"""
        self.append_event(
            f"纠正: {correction}",
            category="correction",
            details=f"根因: {root_cause}" if root_cause else "",
        )

    # ── 日志读取 ────────────────────────────────────────

    def read_today_log(self) -> str:
        """读取今日日志"""
        date_str = time.strftime("%Y-%m-%d")
        return self.read_log(date_str)

    def read_log(self, date_str: str) -> str:
        """读取指定日期的日志"""
        log_file = self._base_dir / f"{date_str}.md"
        if not log_file.exists():
            return ""
        try:
            return log_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("读取日志失败: %s", e)
            return ""

    def read_recent_logs(self, days: int = 7) -> Dict[str, str]:
        """读取最近 N 天的日志"""
        result = {}
        now = get_current_time()
        for i in range(days):
            date = now - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            content = self.read_log(date_str)
            if content:
                result[date_str] = content
        return result

    # ── 日志归档 ────────────────────────────────────────

    def archive_old_logs(self, keep_days: int = 30) -> int:
        """归档超过保留天数的日志"""
        self.ensure_dirs()
        cutoff = (get_current_time() - timedelta(days=keep_days))
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        archived = 0

        for log_file in self._base_dir.glob("????-??-??.md"):
            date_str = log_file.stem
            if date_str < cutoff_str:
                try:
                    archive_path = self._archive_dir / log_file.name
                    if not archive_path.exists():
                        log_file.rename(archive_path)
                    else:
                        log_file.unlink()
                    archived += 1
                except Exception as e:
                    logger.warning("归档日志失败 %s: %s", log_file, e)

        if archived > 0:
            logger.info("归档了 %d 个旧日志", archived)
        return archived
