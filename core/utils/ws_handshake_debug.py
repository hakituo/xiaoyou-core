# -*- coding: utf-8 -*-
"""
WebSocket 握手诊断日志器。

仅当 debug_config.websocket_handshake 开启时启用，将握手关键节点信息
（依赖解析、适配器初始化、host/token/IP 等）追加写入项目根目录的
ws_handshake_debug.log，用于定位移动端连接 403 / 握手失败问题。

设计为「零侵入、可关闭」：
- 通过 is_debug_enabled("websocket_handshake") 统一受 config 控制；
- 即使开关关闭，调用本模块函数也几乎零开销（快速返回）；
- 自行管理文件句柄与轮转，不污染主 logging 体系。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# 项目根目录（main.py 同级）。本文件位于 core/utils/，向上三级即为根。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 统一归入 logs/ 目录，避免根目录堆积调试文件
_LOG_PATH = _PROJECT_ROOT / "logs" / "ws_handshake_debug.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5MB 轮转
_BACKUP_COUNT = 3

_lock = threading.Lock()
_disabled_logged = False


def is_enabled() -> bool:
    """是否启用握手诊断日志（受 config 开关控制）"""
    try:
        from config.debug_config import is_debug_enabled
        return is_debug_enabled("websocket_handshake")
    except Exception:
        return False


def _rotate_if_needed() -> None:
    """简单大小轮转：超过上限则重命名备份"""
    try:
        if not _LOG_PATH.exists():
            return
        if _LOG_PATH.stat().st_size < _MAX_BYTES:
            return
        for i in range(_BACKUP_COUNT - 1, 0, -1):
            src = _LOG_PATH.with_suffix(f".log.{i}")
            dst = _LOG_PATH.with_suffix(f".log.{i + 1}")
            if src.exists():
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        try:
            os.replace(_LOG_PATH, _LOG_PATH.with_suffix(".log.1"))
        except OSError:
            pass
    except Exception:
        pass


def log(event: str, **fields: Any) -> None:
    """
    写入一条握手诊断日志。

    Args:
        event: 事件名，如 "ws_handshake_start" / "dependency_resolve" 等
        **fields: 附加字段（dict/str/int 等可序列化对象）
    """
    if not is_enabled():
        return
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        parts = [f"[{ts}] {event}"]
        for k, v in fields.items():
            if isinstance(v, dict):
                inner = " ".join(f"{kk}={vv!r}" for kk, vv in v.items())
                parts.append(f"{k}={{{inner}}}")
            else:
                parts.append(f"{k}={v!r}")
        line = " | ".join(parts) + "\n"

        with _lock:
            _rotate_if_needed()
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        # 诊断日志本身不得影响主流程
        pass


def log_exception(event: str, exc: BaseException, **fields: Any) -> None:
    """记录带异常信息的诊断日志"""
    if not is_enabled():
        return
    try:
        import traceback

        tb = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        log(event, error_type=type(exc).__name__, error=str(exc), traceback=tb, **fields)
    except Exception:
        pass
