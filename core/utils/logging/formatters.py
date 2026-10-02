"""日志格式化器（Formatter）实现。

与脱敏/Handler 解耦，仅负责把 LogRecord 渲染成字符串或 JSON。
JSONFormatter 通过 context.get_request_id 读取请求上下文。
"""
import json
import traceback
import logging
from datetime import datetime, timezone

from core.utils.logging.context import get_request_id


class SanitizingFormatter(logging.Formatter):
    def format(self, record):
        return super().format(record)


class ColoredFormatter(logging.Formatter):
    """彩色格式化器（兼容旧版）。

    实际颜色由 _setup_handlers 传入的格式字符串里的 colorama 转义控制
    （时间青、模块名品红），level/message 保持默认色——与重构前一致。
    """

    def format(self, record):
        return super().format(record)


class JSONFormatter(SanitizingFormatter):
    """JSON格式的日志格式化器"""

    def format(self, record):
        # 构建JSON日志记录
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id() or "N/A",
            "error_id": getattr(record, "error_id", None),
        }
        # 添加异常信息
        if record.exc_info:
            log_record["exception"] = traceback.format_exception(*record.exc_info)
        # 添加进程和线程信息
        log_record["process_id"] = record.process
        log_record["thread_id"] = record.thread
        return json.dumps(log_record)
