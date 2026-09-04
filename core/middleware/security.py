"""
安全中间件模块
包含认证、授权、速率限制等安全功能
"""

import asyncio
import hmac
import ipaddress
import time
from collections import deque, defaultdict
from typing import Dict, Deque

from fastapi import Request
from fastapi.responses import JSONResponse

from core.utils.logger import get_logger

logger = get_logger(__name__)

RATE_WINDOW_SECONDS = 60.0
rate_limit_lock = asyncio.Lock()
global_request_timestamps: Deque[float] = deque()
ip_request_timestamps: Dict[str, Deque[float]] = defaultdict(deque)


def is_protected_path(path: str) -> bool:
    """检查路径是否需要保护"""
    return path == "/api" or path == "/v1" or path.startswith(
        ("/api/", "/v1/", "/demo", "/health")
    )


def get_access_token_from_request(request: Request) -> str:
    """从请求中获取访问令牌"""
    authorization = str(request.headers.get("authorization", "")).strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    for header_name in ("x-internal-token", "x-access-token"):
        token = str(request.headers.get(header_name, "")).strip()
        if token:
            return token
    return ""


def get_required_access_token() -> str:
    """获取必需的访问令牌"""
    try:
        from config.integrated_config import get_settings
        return str(get_settings().security.web_access_token or "").strip()
    except Exception:
        return ""


def get_peer_ip(request: Request) -> str:
    """返回实际 TCP peer 地址；认证边界绝不能信任可伪造的转发头。"""
    if request.client and request.client.host:
        return str(request.client.host).strip()
    return "unknown"


def is_loopback_peer(request: Request) -> bool:
    """仅当实际 TCP peer 是 loopback 时允许本地适配器免 token。"""
    peer_ip = get_peer_ip(request)
    try:
        return ipaddress.ip_address(peer_ip).is_loopback
    except ValueError:
        return peer_ip.lower() == "localhost"


def get_client_ip(request: Request) -> str:
    """获取用于日志/限流的客户端 IP。

    转发头仅用于观测和限流，不能用于认证或本地信任判断。未经受信代理
    校验的 X-Forwarded-For / X-Real-IP 都是用户可控输入。
    """
    forwarded_for = str(request.headers.get("x-forwarded-for", "")).strip()
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    real_ip = str(request.headers.get("x-real-ip", "")).strip()
    if real_ip:
        return real_ip
    return get_peer_ip(request)


def json_auth_error(status_code: int, message: str):
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
    )


async def security_middleware(request: Request, call_next):
    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if not is_protected_path(path):
        return await call_next(request)

    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 仅信任实际 socket peer。此前这里使用 get_client_ip()，攻击者可通过
    # X-Forwarded-For: 127.0.0.1 伪造本地来源并绕过受保护 API 的 token 校验。
    if is_loopback_peer(request):
        return await call_next(request)

    required_token = get_required_access_token()
    if not required_token:
        return json_auth_error(
            503,
            "服务未配置访问令牌，已拒绝受保护接口访问，请先在环境变量中设置 XIAOYOU_SECURITY_WEB_ACCESS_TOKEN",
        )

    token = get_access_token_from_request(request)
    if not token or not hmac.compare_digest(token, required_token):
        return json_auth_error(401, "未授权访问，请提供有效访问令牌")

    max_content_length = 0
    max_requests_per_minute = 0
    max_ip_requests_per_minute = 0
    try:
        from config.integrated_config import get_settings

        settings = get_settings()
        max_content_length = int(getattr(settings.server, "max_content_length", 0) or 0)
        max_requests_per_minute = int(
            getattr(settings.server, "max_requests_per_minute", 0) or 0
        )
        max_ip_requests_per_minute = int(
            getattr(settings.server, "max_ip_requests_per_minute", 0) or 0
        )
    except Exception:
        max_content_length = 0
        max_requests_per_minute = 0
        max_ip_requests_per_minute = 0

    if max_content_length > 0:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_content_length:
                    return json_auth_error(
                        413, f"请求体过大，超过限制 {max_content_length} 字节"
                    )
            except ValueError:
                return json_auth_error(400, "非法的 Content-Length 请求头")

    now = time.monotonic()
    client_ip = get_client_ip(request)
    async with rate_limit_lock:
        while global_request_timestamps and (
            now - global_request_timestamps[0]
        ) > RATE_WINDOW_SECONDS:
            global_request_timestamps.popleft()

        ip_queue = ip_request_timestamps[client_ip]
        while ip_queue and (now - ip_queue[0]) > RATE_WINDOW_SECONDS:
            ip_queue.popleft()

        if max_requests_per_minute > 0 and len(global_request_timestamps) >= int(
            max_requests_per_minute
        ):
            return json_auth_error(429, "请求过于频繁，请稍后再试")

        if max_ip_requests_per_minute > 0 and len(ip_queue) >= int(
            max_ip_requests_per_minute
        ):
            return json_auth_error(429, "当前 IP 请求过于频繁，请稍后再试")

        global_request_timestamps.append(now)
        ip_queue.append(now)

    return await call_next(request)


async def strict_origin_middleware(request: Request, call_next, allow_origins: list):
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)
    if not is_protected_path(request.url.path):
        return await call_next(request)

    origin = request.headers.get("origin")
    if not origin:
        return await call_next(request)
    if "*" in allow_origins:
        return await call_next(request)

    if origin not in allow_origins:
        client_ip = get_client_ip(request)
        logger.warning(
            "REJECTED: Unauthorized Origin %r from IP %s requesting %s",
            origin,
            client_ip,
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "Unauthorized Origin"},
        )

    return await call_next(request)


async def request_logging_middleware(request: Request, call_next):
    if request.scope.get("type") != "http":
        return await call_next(request)

    path = request.url.path
    if path in {"/favicon.ico", "/docs", "/openapi.json", "/redoc"} or path.startswith(
        ("/static", "/assets")
    ):
        return await call_next(request)

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if path == "/api" or path == "/v1" or path.startswith(("/api/", "/v1/", "/demo")):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Pragma", "no-cache")
    proto = str(request.headers.get("x-forwarded-proto", "")).strip().lower()
    if request.url.scheme == "https" or proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response