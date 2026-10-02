"""项目根目录解析（零依赖，供全项目最早期的导入使用）。

单独成文件的原因：``core.utils.common`` 在模块级就要取 logger，而 logger 链路
（``core.utils.logger`` → ``core.utils.logging.config`` → ``core.utils.shared_roots``）
反过来又要解析项目根目录。把这份逻辑放在一个不 import 项目内任何模块的文件里，
这条环就被断掉了。``core.utils.common`` 继续 re-export 本函数，调用方无需改动。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_project_root() -> Path:
    """获取项目根目录

    优先级：
    1. XIAOYOU_PROJECT_ROOT 环境变量
    2. PyInstaller frozen 模式（可执行文件所在目录）
    3. 默认：本文件的上两级目录
    """
    env_root = os.environ.get("XIAOYOU_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
