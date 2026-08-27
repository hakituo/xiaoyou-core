"""
FastAPI 全局异常处理器
注意：本文件与 error_handler.py 不同！
- error_handler.py: 通用错误处理工具类（ErrorHandler 类、error_handling 上下文管理器）
- error_handlers.py（本文件）: FastAPI 专用全局异常处理器（注册到 app.exception_handler）
"""

from core.utils.logger import get_logger
from fastapi import Request
from fastapi.responses import JSONResponse
from core.api.contract import error_response
from core.api.error_response import map_exception_to_error_code, APIError
from core.utils.errors.log_sanitizer import ErrorReporter

logger = get_logger(__name__)


async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    # WebSocket 握手/连接阶段的异常不能用 HTTP JSON 响应返回，
    # 否则会返回 500 而非正常的 101 握手失败，客户端会报
    # "Expected HTTP 101 response but was '500 Internal Server Error'"。
    # 这种情况下原样抛出，让 Starlette 走 WebSocket 自身的错误处理（关闭连接），
    # 并在日志中保留真实异常信息。
    if request.scope.get("type") != "http":
        logger.error(
            f"WebSocket 处理异常: {str(exc)}",
            exc_info=True,
            extra={"_skip_collector": True},
        )
        raise exc

    # 构造请求上下文
    context = {
        "path": getattr(request.url, "path", str(request.url)),
        "method": request.method,
        "client_ip": request.client.host if request.client else None,
    }

    # 直接报告错误（写入 logs/errors/ 批次文件）
    error_id = ""
    try:
        error_id = await ErrorReporter.report_error(
            exc, context=context, severity="ERROR"
        )
    except Exception:
        error_id = ""

    # 记录日志：带 _skip_collector 标记，避免 ErrorCollectorHandler 重复收集
    # error_context 供 ErrorCollectorHandler 写入每日根目录文件时使用
    logger.error(
        f"全局异常: {str(exc)} [error_id={error_id}]",
        exc_info=True,
        extra={
            "_skip_collector": True,
            "error_context": {**context, "error_id": error_id},
        },
    )

    request_id = None
    try:
        request_id = request.headers.get("x-request-id") or request.headers.get(
            "X-Request-ID"
        )
    except Exception:
        request_id = None

    error_code = map_exception_to_error_code(exc)
    client_message = "Internal server error"
    details = {"error_id": error_id or None}
    if isinstance(exc, APIError):
        client_message = exc.message
        details.update(exc.details or {})

    return JSONResponse(
        status_code=500,
        content=error_response(
            error_code, message=client_message, request_id=request_id, details=details
        ),
    )
