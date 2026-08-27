"""
日志配置模块

注意：此模块已简化，主要功能已迁移到 core.utils.logger
保留此模块以保持向后兼容性
"""

import logging
import os
from typing import Dict, Any, Optional


# 确保日志目录存在
LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)
os.makedirs(LOG_DIR, exist_ok=True)

# 日志级别映射
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志记录器实例（委托给 core.utils.logger 的增强版）
    """
    from core.utils.logger import get_logger as _enhanced_get_logger
    return _enhanced_get_logger(name)


def initialize_logging(config: Dict[str, Any] = None):
    """
    初始化日志系统（委托给 core.utils.logger）
    """
    from core.utils.logger import init_logging_system
    init_logging_system()


def log_with_context(logger: logging.Logger, level: int, message: str, **context):
    """
    记录带上下文信息的日志
    """
    extra = {"context": context}
    logger.log(level, message, extra=extra)


def log_request(logger: logging.Logger, request, response=None, error=None):
    """
    记录HTTP请求日志
    """
    context = {
        "method": request.method,
        "url": str(request.url),
        "client_ip": request.client.host if request.client else "unknown",
    }

    if hasattr(request, "headers"):
        # 记录关键头部，但不记录敏感信息
        safe_headers = {}
        for key, value in request.headers.items():
            if key.lower() not in ["authorization", "cookie"]:
                safe_headers[key] = value
        context["headers"] = safe_headers

    if response:
        context["status_code"] = response.status_code
        context["response_size"] = (
            len(response.body) if hasattr(response, "body") else 0
        )

    if error:
        context["error"] = str(error)
        logger.error(
            f"请求处理失败: {request.method} {request.url.path}",
            extra={"context": context},
        )
    else:
        logger.info(
            f"请求处理: {request.method} {request.url.path} {response.status_code if response else 'N/A'}",
            extra={"context": context},
        )
