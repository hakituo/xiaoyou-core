"""
持久化操作模块

注意：此模块已简化，主要功能已迁移到 core.utils.atomic_io
保留此模块以保持向后兼容性
"""

from typing import Any, Union
from pathlib import Path

# 从统一模块导入
from core.utils.atomic_io import (
    safe_json_dump as _safe_json_dump,
    safe_json_load as _safe_json_load,
)


def safe_json_dump(data: Any, file_path: Union[str, Path], encoding: str = "utf-8"):
    """同步安全写入 JSON 文件（委托给 core.utils.atomic_io）"""
    _safe_json_dump(data, file_path, encoding)


def safe_json_load(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: Any = None,
) -> Any:
    """同步安全读取 JSON 文件（委托给 core.utils.atomic_io）"""
    return _safe_json_load(file_path, encoding, default)



