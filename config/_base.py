"""
配置系统共享基础设施
所有 settings_* 模块从此处导入 pydantic 基类，避免重复的兼容性回退逻辑
"""

from __future__ import annotations

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field
except Exception:
    from pydantic import BaseSettings, Field

    class SettingsConfigDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)


__all__ = ["BaseSettings", "SettingsConfigDict", "Field"]
