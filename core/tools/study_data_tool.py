from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import aiofiles
from pydantic import BaseModel, Field

from config.integrated_config import get_settings
from core.tools.file_tool_base import FileToolBase
from core.utils.common import get_project_root


class StudyDataInput(BaseModel):
    action: Literal[
        "read_text",
        "write_text",
        "append_text",
        "read_json",
        "write_json",
        "list",
        "mkdir",
        "exists",
        "highlight",
    ] = Field(
        description="要执行的文件操作类型。highlight 用于触发前端高光显示文件内容。"
    )
    path: Optional[str] = Field(
        default=None,
        description="相对路径（基于学习文件夹），如 Mathematics/Aveline_Math_Monitor.md",
    )
    content: Optional[str] = Field(
        default=None,
        description="写入或追加的文本内容；对于 highlight 操作，这是要显示的备注或标题",
    )
    highlight_lines: Optional[List[int]] = Field(
        default=None, description="需要高光显示的行号列表（仅用于 highlight 操作）"
    )
    highlight_text: Optional[str] = Field(
        default=None,
        description="需要高光显示的文本片段（仅用于 highlight 操作）。如果提供，会自动查找并计算行号。",
    )
    json_content: Optional[Dict[str, Any]] = Field(
        default=None, description="写入的 JSON 对象（用于 write_json）"
    )


class StudyDataTool(FileToolBase):
    name = "study_data_management"
    description = "在学习文件夹内安全地读写/列出/管理学习记录、笔记和工具文件。"
    args_schema = StudyDataInput

    def __init__(self):
        self._project_root = get_project_root()
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            if os.path.isabs(study_root):
                self._base_dir = Path(study_root).expanduser().resolve()
            else:
                self._base_dir = (self._project_root / study_root).resolve()
        else:
            self._base_dir = (self._project_root / "Study").resolve()

    async def _run(
        self,
        action: str,
        path: Optional[str] = None,
        content: Optional[str] = None,
        highlight_lines: Optional[List[int]] = None,
        highlight_text: Optional[str] = None,
        json_content: Optional[Dict[str, Any]] = None,
    ) -> str:
        try:
            if not path and action != "list":
                return f"Error: action={action} 需要 path"

            # 如果是 list 且没有 path，则列出根目录
            target = self._resolve_inside_base(path if path else ".")

            if action == "highlight":
                if not target.exists() or not target.is_file():
                    return "Error: 无法高光显示，文件不存在"
                async with aiofiles.open(target, "r", encoding="utf-8") as f:
                    file_content = await f.read()

                final_highlight_lines = highlight_lines or []

                # 如果提供了 highlight_text，尝试自动查找行号
                if highlight_text and highlight_text.strip():
                    lines = file_content.splitlines()
                    search_text = highlight_text.strip().lower()
                    for i, line in enumerate(lines):
                        # 简单的包含匹配
                        if search_text in line.lower():
                            # 行号从1开始
                            if (i + 1) not in final_highlight_lines:
                                final_highlight_lines.append(i + 1)

                # 返回特定的 JSON 格式，ChatAgent 会识别并提取
                return json.dumps(
                    {
                        "type": "study_data_highlight",
                        "data": {
                            "title": content or target.name,
                            "content": file_content,
                            "filePath": path,
                            "highlightLines": sorted(final_highlight_lines),
                        },
                    },
                    ensure_ascii=False,
                )

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

            return f"Error: 未处理的 action: {action}"
        except Exception as e:
            return f"Error executing {action}: {str(e)}"
