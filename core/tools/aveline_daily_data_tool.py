from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from core.tools.file_tool_base import FileToolBase
from core.utils.data_paths import get_companion_data_dir


class AvelineDailyDataInput(BaseModel):
    action: Literal[
        "read_text",
        "write_text",
        "append_text",
        "read_json",
        "write_json",
        "list",
        "mkdir",
        "exists",
        "ensure_daily_dir",
    ] = Field(description="要执行的文件操作类型")
    path: Optional[str] = Field(
        default=None,
        description="相对路径（基于 companion_data），如 user_data/schedule/push_schedule.json",
    )
    content: Optional[str] = Field(
        default=None, description="写入或追加的文本内容（用于 write_text/append_text）"
    )
    json_content: Optional[Dict[str, Any]] = Field(
        default=None, description="写入的 JSON 对象（用于 write_json）"
    )
    date: Optional[str] = Field(
        default=None, description="日期（YYYY-MM-DD，用于 ensure_daily_dir）"
    )
    category: Optional[str] = Field(
        default=None,
        description="分类目录名（用于 ensure_daily_dir，例如 diary/todo/events）",
    )


class AvelineDailyDataTool(FileToolBase):
    name = "aveline_daily_data"
    description = "在 companion_data 目录内安全地读写/列出/创建文件与文件夹。必须通过此工具真实查看和写入文件内容，绝对不要自己编造(hallucinate)文件内容。"
    short_description = "读写companion_data文件"
    category = "daily"
    args_schema = AvelineDailyDataInput

    def __init__(self):
        self._base_dir = get_companion_data_dir()
        self._ensure_base_skeleton()

    def _ensure_base_skeleton(self) -> None:
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            (self._base_dir / "user_data").mkdir(parents=True, exist_ok=True)
            (self._base_dir / "aveline_data").mkdir(parents=True, exist_ok=True)
            (self._base_dir / "ling_data").mkdir(parents=True, exist_ok=True)
        except Exception:
            return

    async def _run(
        self,
        action: str,
        path: Optional[str] = None,
        content: Optional[str] = None,
        json_content: Optional[Dict[str, Any]] = None,
        date: Optional[str] = None,
        category: Optional[str] = None,
    ) -> str:
        if action == "ensure_daily_dir":
            if not date or not category:
                return "Error: ensure_daily_dir 需要 date 与 category"
            parts = date.split("-")
            if len(parts) != 3 or any(not p.isdigit() for p in parts):
                return "Error: date 格式必须为 YYYY-MM-DD"
            year, month, day = parts
            rel = f"user_data/daily/{year}/{month}/{day}/{category}"
            target_dir = self._resolve_inside_base(rel)
            target_dir.mkdir(parents=True, exist_ok=True)
            return str(target_dir)

        if not path:
            return f"Error: action={action} 需要 path"

        if action == "exists":
            return await self.exists(path)

        if action == "mkdir":
            return await self.mkdir(path)

        if action == "list":
            return await self.list_dir(path)

        if action == "read_text":
            return await self.read_text(path)

        if action == "write_text":
            if content is None:
                return "Error: write_text 需要 content"
            return await self.write_text(path, content)

        if action == "append_text":
            if content is None:
                return "Error: append_text 需要 content"
            return await self.append_text(path, content)

        if action == "read_json":
            return await self.read_json(path)

        if action == "write_json":
            if json_content is None:
                return "Error: write_json 需要 json_content"
            return await self.write_json(path, json_content)

        return f"Error: 未知 action: {action}"