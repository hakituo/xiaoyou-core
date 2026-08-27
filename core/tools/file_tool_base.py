#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件工具基类模块
提供通用的文件操作功能，减少重复代码
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import aiofiles

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("FILE_TOOL_BASE")


class FileToolBase(BaseTool):
    """
    文件工具基类
    提供通用的文件读写、路径解析等功能
    """

    # 子类需要设置的基础目录
    _base_dir: Path = None

    def _resolve_inside_base(self, relative_path: str) -> Path:
        """
        解析相对路径，确保在基础目录内

        Args:
            relative_path: 相对路径

        Returns:
            解析后的绝对路径

        Raises:
            ValueError: 路径为空或超出基础目录范围
        """
        if not relative_path or not str(relative_path).strip():
            raise ValueError("path 不能为空")

        rel = Path(relative_path)
        if rel.is_absolute():
            # 允许绝对路径，但必须在 _base_dir 内部
            target = rel.resolve()
        else:
            target = (self._base_dir / rel).resolve()

        base_str = str(self._base_dir)
        target_str = str(target)

        if target_str == base_str:
            return target

        # 安全检查：确保目标路径在基础目录下
        if not target_str.startswith(base_str + os.sep) and target_str != base_str:
            raise ValueError(f"禁止访问基础目录之外的路径: {target_str}")

        return target

    async def read_text(self, path: str) -> str:
        """
        读取文本文件

        Args:
            path: 相对路径

        Returns:
            文件内容
        """
        target = self._resolve_inside_base(path)
        if not target.exists() or not target.is_file():
            return "Error: 文件不存在"
        async with aiofiles.open(target, "r", encoding="utf-8") as f:
            return await f.read()

    async def write_text(self, path: str, content: str) -> str:
        """
        写入文本文件

        Args:
            path: 相对路径
            content: 内容

        Returns:
            JSON 格式的操作结果
        """
        target = self._resolve_inside_base(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "w", encoding="utf-8") as f:
            await f.write(content)
        return json.dumps(
            {"written": True, "path": str(target)}, ensure_ascii=False
        )

    async def append_text(self, path: str, content: str) -> str:
        """
        追加文本到文件

        Args:
            path: 相对路径
            content: 内容

        Returns:
            JSON 格式的操作结果
        """
        target = self._resolve_inside_base(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "a", encoding="utf-8") as f:
            await f.write(content)
        return json.dumps(
            {"appended": True, "path": str(target)}, ensure_ascii=False
        )

    async def read_json(self, path: str) -> str:
        """
        读取 JSON 文件

        Args:
            path: 相对路径

        Returns:
            JSON 格式的内容
        """
        target = self._resolve_inside_base(path)
        if not target.exists() or not target.is_file():
            return "Error: 文件不存在"
        async with aiofiles.open(target, "r", encoding="utf-8") as f:
            raw = await f.read()
        data = json.loads(raw) if raw.strip() else {}
        return json.dumps(data, ensure_ascii=False, indent=2)

    async def write_json(self, path: str, json_content: Dict[str, Any]) -> str:
        """
        写入 JSON 文件

        Args:
            path: 相对路径
            json_content: JSON 内容

        Returns:
            JSON 格式的操作结果
        """
        target = self._resolve_inside_base(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "w", encoding="utf-8") as f:
            await f.write(
                json.dumps(json_content, ensure_ascii=False, indent=2)
            )
        return json.dumps(
            {"written": True, "path": str(target)}, ensure_ascii=False
        )

    async def list_dir(self, path: str = ".") -> str:
        """
        列出目录内容

        Args:
            path: 相对路径，默认为当前目录

        Returns:
            JSON 格式的目录列表
        """
        target = self._resolve_inside_base(path)
        if not target.exists() or not target.is_dir():
            return "Error: 目标目录不存在或不是目录"
        items: List[Dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            try:
                stat = child.stat()
                items.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": stat.st_size,
                        "mtime": int(stat.st_mtime),
                    }
                )
            except Exception:
                items.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                    }
                )
        return json.dumps(
            {"path": str(target), "items": items}, ensure_ascii=False, indent=2
        )

    async def mkdir(self, path: str) -> str:
        """
        创建目录

        Args:
            path: 相对路径

        Returns:
            JSON 格式的操作结果
        """
        target = self._resolve_inside_base(path)
        target.mkdir(parents=True, exist_ok=True)
        return json.dumps(
            {"created": True, "path": str(target)}, ensure_ascii=False
        )

    async def exists(self, path: str) -> str:
        """
        检查路径是否存在

        Args:
            path: 相对路径

        Returns:
            JSON 格式的检查结果
        """
        target = self._resolve_inside_base(path)
        return json.dumps({"exists": target.exists()}, ensure_ascii=False)