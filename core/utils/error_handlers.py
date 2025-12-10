import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from core.log_config import log_request

logger = logging.getLogger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    # 记录请求详情
    log_request(logger, request, error=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)}
    )
