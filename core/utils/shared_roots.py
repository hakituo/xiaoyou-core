"""跨系统共享目录解析（Windows / Linux 双启动共用同一份数据）。

同一台机器上 Windows 与 Linux 各有一份仓库，但同一个物理分区（例如 G 盘）
两边都能挂载。把日志、学习数据中转目录放进共享根后，两个系统读写的是同一份
文件，不再需要互相复制，也不会出现"这边改了那边看不见"。

共享根由环境变量 ``XIAOYOU_SHARED_ROOT`` 指定，各系统填自己的挂载路径即可
（Windows 填 ``G:\\xiaoyou-shared``、Linux 填 ``/mnt/G/xiaoyou-shared``）。
未设置时全部退回项目根目录下的原位置，行为与加这个模块之前完全一致。

注意：项目根取自零依赖的 ``core.utils.project_root``，不能走 ``core.utils.common``
—— 后者模块级就要取 logger，会与本模块的使用方形成导入环。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from core.utils.project_root import get_project_root

#: 共享根环境变量名
SHARED_ROOT_ENV = "XIAOYOU_SHARED_ROOT"

_LOGS_DIR_NAME = "logs"
_LEARNING_HUB_DIR_NAME = "learning_hub"


def get_shared_root() -> Optional[Path]:
    """返回共享根目录；未配置 ``XIAOYOU_SHARED_ROOT`` 时返回 None。"""
    env_root = os.environ.get(SHARED_ROOT_ENV, "").strip()
    if not env_root:
        return None
    return Path(env_root).expanduser()


def get_logs_root() -> Path:
    """返回日志根目录：共享根下的 ``logs``，未配置共享根时为项目根下的 ``logs``。

    两个系统配好共享根后即读写同一个日志文件夹。
    """
    shared = get_shared_root()
    if shared is not None:
        return shared / _LOGS_DIR_NAME
    return get_project_root() / _LOGS_DIR_NAME


def get_learning_hub_root() -> Optional[Path]:
    """返回学习数据中转目录；未配置共享根时返回 None（需显式传 ``--hub``）。"""
    shared = get_shared_root()
    return None if shared is None else shared / _LEARNING_HUB_DIR_NAME
