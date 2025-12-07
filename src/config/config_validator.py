#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置验证工具
用于验证配置的有效性和完整性
"""
import os
import sys
from typing import Dict, List, Optional, Tuple
from src.config.settings import AppSettings
from src.core.utils.logger import get_logger
logger = get_logger(__name__)
class ConfigValidator:
    """配置验证器"""
    def __init__(self):
        """初始化验证器"""
        self.settings: Optional[AppSettings] = None
        self.errors: List[str] = []
        self.warnings: List[str] = []
def validate_config() -> int:
    """验证配置的命令行入口
    Returns:
        int: 0 表示成功，非0表示失败
    """
    validator = ConfigValidator()
    success, errors, warnings = validator.validate_all()
    print("\n配置验证结果:")
    if warnings:
        print("\n警告:")
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {warning}")
    if errors:
        print("\n错误:")
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {error}")
        print(f"\n验证失败，发现 {len(errors)} 个错误")
        return 1
    else:
        print("\n验证通过！所有配置项都有效。")
        if warnings:
            print(f"发现 {len(warnings)} 个警告，请根据需要调整配置。")
        return 0
if __name__ == "__main__":
    sys.exit(validate_config())