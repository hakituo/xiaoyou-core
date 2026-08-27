#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全中间件模块
包含认证、授权、速率限制等安全功能
"""

import asyncio
import hmac
import time
from collections import deque, defaultdict
from typing import Dict, Deque

from fastapi import Request
from fastapi.responses import JSONResponse

from core.utils.logger import get_logger

logger = get_logger(__name__)

# 速率限制配置
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


def get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    forwarded_for = str(request.headers.get("x-forwarded-for", "")).strip()
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    real_ip = str(request.headers.get("x-real-ip", "")).strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return str(request.client.host)
    return "unknown"


def json_auth_error(status_code: int, message: str):
    """返回JSON格式的认证错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
    )


async def security_middleware(request: Request, call_next):
    """安全中间件，处理认证和速率限制"""
    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if not is_protected_path(path):
        return await call_next(request)

    # 跳过 WebSocket 升级请求，由 WebSocket 层自行处理认证
    # 内部适配器（如 QQ）通过本地连接，不需要 web_access_token
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 内部适配器（QQ bot 客户端等）通过本地连接访问 HTTP API 时，跳过 token 校验
    client_ip = get_client_ip(request)
    if client_ip in ("127.0.0.1", "::1", "localhost"):
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

    response = await call_next(request)
    return response


async def strict_origin_middleware(request: Request, call_next, allow_origins: list):
    """严格 Origin 校验中间件"""
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    # 跳过 WebSocket 升级请求：原生 App（Android/iOS）发起 WS 握手时不带 Origin 头，
    # 而经 Cloudflare tunnel / 反向代理转发时可能被注入代理域名 Origin，
    # 命中白名单校验会错误返回 403，导致客户端报
    # "Expected HTTP 101 response but was '403 Forbidden'"。
    # WebSocket 的认证由连接层（握手 token / 业务层）自行处理，无需此处 Origin 校验。
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 仅针对受保护的 API 路径进行严格 Origin 检查
    if not is_protected_path(request.url.path):
        return await call_next(request)

    # 获取请求的 Origin
    origin = request.headers.get("origin")

    # 如果没有 Origin (非浏览器请求)，或者 Origin 在白名单中，或者是本地请求，则放行
    if not origin:
        return await call_next(request)
    
    # 获取配置的允许来源列表
    if "*" in allow_origins:
        # 如果配置为允许所有，则不做额外拦截
        return await call_next(request)

    if origin not in allow_origins:
        # 记录警告日志
        client_ip = get_client_ip(request)
        logger.warning(
            f"REJECTED: Unauthorized Origin '{origin}' from IP {client_ip} "
            f"requesting {request.url.path}"
        )
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "Unauthorized Origin"},
        )
            
    return await call_next(request)


async def request_logging_middleware(request: Request, call_next):
    """请求日志中间件"""
    # WebSocket 握手请求直接放行，不要操作其响应对象。
    # WebSocket 的 response 是 WebSocketResponse，对其设置 HTTP header 会在
    # 握手阶段触发内部异常，被全局异常处理器包装成 500，使客户端收到
    # "Expected HTTP 101 response but was '500 Internal Server Error'"。
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