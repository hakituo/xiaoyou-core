"""
异步持久化操作

注意：此模块已简化，主要功能已迁移到 core.utils.atomic_io
保留此模块以保持向后兼容性
"""

from pathlib import Path
from typing import Any, Union

# 从统一模块导入
from core.utils.atomic_io import (
    async_safe_json_dump as _async_safe_json_dump,
    async_safe_json_load as _async_safe_json_load,
)


async def async_safe_json_dump(
    data: Any,
    file_path: Union[str, Path],
    encoding: str = "utf-8",
) -> None:
    """异步安全写入 JSON 文件（委托给 core.utils.atomic_io）"""
    await _async_safe_json_dump(data, file_path, encoding)


async def async_safe_json_load(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: Any = None,
) -> Any:
    """异步安全读取 JSON 文件（委托给 core.utils.atomic_io）"""
    return await _async_safe_json_load(file_path, encoding, default)
