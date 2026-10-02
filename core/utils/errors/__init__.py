"""
Errors / 错误处理与日志脱敏 子包。

原 core.utils.error_collector / error_handler / error_handlers / log_sanitizer
已分组到此子包。本文件 re-export 全部公开符号。
"""

from core.utils.errors.error_collector import *
from core.utils.errors.error_handler import *
from core.utils.errors.error_handlers import *
from core.utils.errors.log_sanitizer import *

__all__ = [
    "ErrorCollectorHandler",
    "is_upstream_transient_error",
    "ErrorHandler",
    "error_handling",
    "global_exception_handler",
    "ErrorReporter",
    "LogSanitizer",
    "sanitize_log",
    "initialize_sanitizer",
    "register_error_callback",
    "unregister_error_callback",
    "dispatch_error_to_callbacks",
    "get_error_count",
    "clear_error_queue",
    "update_config",
    "with_log_sanitization",
]
