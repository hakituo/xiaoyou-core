"""WebSocket 传输日志降噪。"""

from __future__ import annotations

import logging
from typing import Optional


def _find_windows_error(error: Optional[BaseException], winerror: int) -> bool:
    """沿异常链查找指定 Windows 错误码。"""
    seen: set[int] = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "winerror", None) == winerror:
            return True
        current = current.__cause__ or current.__context__
    return False


class RecoverableWebSocketDisconnectFilter(logging.Filter):
    """把 Windows 读超时断连转换为无堆栈的可恢复信息日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "recoverable_websocket_disconnect", False):
            return True
        if record.getMessage() != "data transfer failed":
            return True
        error = record.exc_info[1] if record.exc_info else None
        if not _find_windows_error(error, 121):
            return True

        record.levelno = logging.INFO
        record.levelname = "INFO"
        record.msg = "WebSocket 客户端读取超时（WinError 121），连接已清理并等待客户端重连"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.recoverable_websocket_disconnect = True
        return True
