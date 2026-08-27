"""用户学习画像查询工具 - AI 需要时才调用，而非每次自动注入"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("StudyProfileTool")


def _get_study_root() -> str:
    """从配置读取 Study 根路径，消除硬编码。"""
    try:
        from config.integrated_config import get_settings
        from pathlib import Path
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            p = Path(study_root).expanduser()
            if not p.is_absolute():
                from core.utils.common import get_project_root
                p = get_project_root() / p
            return str(p.resolve())
    except Exception:
        pass
    return os.path.join("D:", os.sep, "AI", "Study")


class StudyProfileInput(BaseModel):
    subject: Optional[str] = Field(
        default=None,
        description="要查询的学科，如 '数学'、'英语'。不传则返回所有学科的画像摘要。",
    )
    date: Optional[str] = Field(
        default=None,
        description="要查询的日期，格式 YYYY-MM-DD，如 '2026-06-02'。不传则查询最新一天的记录。",
    )


class GetStudyProfileTool(BaseTool):
    name = "get_study_profile"
    description = (
        "查询用户的学习画像，包括各学科的知识掌握情况、易错点、学习进度等。"
        "当用户聊到学习相关话题、你想了解用户的学习状态、或需要根据学习情况给出建议时调用。"
    )
    short_description = "查询用户学习画像（学科掌握/进度/易错点）"
    args_schema = StudyProfileInput
    category = "study"
    enabled_by_default = True

    async def _run(self, subject: Optional[str] = None, date: Optional[str] = None) -> str:
        # P1-4: _load_daily_progress / _load_math_profile_legacy 内部用 os.walk + open
        # 是同步阻塞 IO，放到线程池执行避免阻塞事件循环
        # 1. 尝试从 Daily/yyyy/MM/DD.md 读取
        daily_content = await asyncio.to_thread(self._load_daily_progress, date)
        if daily_content:
            # 如果指定了学科，只返回该学科部分
            if subject:
                section = self._extract_subject_section(daily_content, subject)
                if section:
                    return f"【用户学习画像 - {subject}】\n{section}"
                return f"暂无 {subject} 学科的学习画像数据。"
            return f"【用户学习画像】\n{daily_content}"

        # 2. 回退：从各科独立文件读取（兼容旧格式）
        profile_parts = []
        if not subject or subject in ("数学", "math", "mathematics"):
            math_profile = await asyncio.to_thread(self._load_math_profile_legacy)
            if math_profile:
                profile_parts.append(math_profile)

        if not profile_parts:
            if subject:
                return f"暂无 {subject} 学科的学习画像数据。"
            return "暂无学习画像数据。"

        header = "【用户学习画像】" if not subject else f"【用户学习画像 - {subject}】"
        return header + "\n" + "\n".join(profile_parts)

    # ---- Daily 进度文件读取 ----

    def _load_daily_progress(self, date_str: Optional[str] = None) -> str:
        """从 Daily/YYYY/MM/DD.md 读取学习进度"""
        daily_dir = os.path.join(_get_study_root(), "Daily")

        if date_str:
            # 指定日期：直接读取
            try:
                parts = date_str.split("-")
                y, m, d = parts[0], parts[1], parts[2]
            except (ValueError, IndexError):
                return ""
            target = os.path.join(daily_dir, y, m, f"{d}.md")
            if os.path.exists(target):
                return self._read_file(target)
            return ""

        # 未指定日期：找最新的一天
        return self._find_latest_daily(daily_dir)

    def _find_latest_daily(self, daily_dir: str) -> str:
        """在 Daily/ 目录下找到最新的 YYYY/MM/DD.md"""
        if not os.path.isdir(daily_dir):
            return ""
        try:
            md_files = []
            for root, dirs, files in os.walk(daily_dir):
                for f in files:
                    if f.endswith(".md"):
                        md_files.append(os.path.join(root, f))
            if not md_files:
                return ""
            # 按修改时间排序，取最新的
            md_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return self._read_file(md_files[0])
        except Exception:
            return ""

    def _extract_subject_section(self, content: str, subject: str) -> str:
        """从进度文件中提取指定学科的部分"""
        # 学科名映射
        subject_map = {
            "math": "数学", "mathematics": "数学",
            "english": "英语",
            "biology": "生物",
            "geography": "地理",
            "history": "历史",
            "chinese": "语文",
            "chemistry": "化学",
        }
        target = subject_map.get(subject.lower(), subject)

        # 按 ## 分割，找到目标学科
        sections = content.split("## ")
        for section in sections:
            if section.startswith(target):
                return "## " + section
        return ""

    # ---- 旧格式兼容 ----

    def _load_math_profile_legacy(self) -> str:
        """从旧格式文件加载数学画像（兼容）"""
        parts = []

        study_root = _get_study_root()
        monitor_path = os.path.join(study_root, "Mathematics", "Aveline_Math_Monitor.md")
        if os.path.exists(monitor_path):
            try:
                content = self._read_file(monitor_path)
                sections = content.split("##")
                for section in sections:
                    if any(kw in section for kw in ["数学体质", "性能优化", "Debug 库", "易错点"]):
                        lines = section.strip().split("\n")
                        summary_lines = []
                        for line in lines:
                            line = line.strip()
                            if line and not line.startswith("|") and not line.startswith("---"):
                                summary_lines.append(line)
                        if summary_lines:
                            parts.append("数学: " + "; ".join(summary_lines[:5]))
                        break
            except Exception:
                pass

        handover_path = os.path.join(study_root, "Mathematics", "Gaokao_Math_Progress_Handover.md")
        if os.path.exists(handover_path):
            try:
                content = self._read_file(handover_path)
                sections = content.split("##")
                for section in sections:
                    if "已攻克" in section or "进行中" in section or "尚未启动" in section:
                        lines = section.strip().split("\n")
                        summary_lines = [
                            line.strip().lstrip("- ").lstrip("* ")
                            for line in lines
                            if line.strip().startswith(("-", "*"))
                        ]
                        if summary_lines:
                            parts.append("进度: " + "; ".join(summary_lines[:5]))
                        break
            except Exception:
                pass

        return "\n".join(parts) if parts else ""

    # ---- 工具方法 ----

    @staticmethod
    def _read_file(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
