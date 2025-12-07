"""
统一错误处理模块

提供标准化的异常处理装饰器和上下文管理器，确保系统中错误处理的一致性。
"""

import functools
import asyncio
import traceback
from typing import Callable, Any, Optional, TypeVar, cast
from functools import wraps

from .logger import get_logger

logger = get_logger("ERROR_HANDLER")

# 类型变量
t_async_func = TypeVar('t_async_func', bound=Callable[..., Any])
t_sync_func = TypeVar('t_sync_func', bound=Callable[..., Any])

class ErrorHandler:
    """统一错误处理器"""
    
    @staticmethod
    def handle_error(error, default_return=None):
        """处理错误的静态方法"""
        logger.error(f"处理错误: {str(error)}")
        return default_return

# 创建上下文管理器版本
class error_handling:
    """错误处理上下文管理器"""
    
    def __init__(
        self,
        default_return: Any = None,
        log_level: str = "error",
        error_message: Optional[str] = None,
        re_raise: bool = False,
        raise_exception: Optional[Exception] = None
    ):
        self.default_return = default_return
        self.log_level = log_level
        self.error_message = error_message
        self.re_raise = re_raise
        self.raise_exception = raise_exception
        self.result = default_return
        
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if exc_type is not None:
            # 记录日志
            msg = self.error_message or f"操作失败: {str(exc_value)}"
            if self.log_level == "error":
                logger.error(f"{msg}\n{''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}")
            elif self.log_level == "warning":
                logger.warning(f"{msg}\n{''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}")
            elif self.log_level == "info":
                logger.info(f"{msg}\n{''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}")
            
            # 异常处理
            if self.re_raise:
                if self.raise_exception:
                    if isinstance(self.raise_exception, Exception):
                        raise self.raise_exception
                    else:
                        raise self.raise_exception(str(exc_value)) from exc_value
                else:
                    return False  # 不抑制异常
            
            return True  # 抑制异常
        return False

# 导出所有功能
__all__ = [
    "ErrorHandler",
    "error_handling"
]