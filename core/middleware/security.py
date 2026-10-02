#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全中间件模块
包含认证、授权、速率限制等安全功能
"""

import asyncio
import hashlib
import hmac
import ipaddress
import time
from collections import deque, defaultdict
from collections.abc import Mapping
from typing import Dict, Deque, Optional

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse

from core.utils.logger import get_logger

logger = get_logger(__name__)

# 速率限制配置
RATE_WINDOW_SECONDS = 60.0
rate_limit_lock = asyncio.Lock()
global_request_timestamps: Deque[float] = deque()
ip_request_timestamps: Dict[str, Deque[float]] = defaultdict(deque)

# 受保护媒体 cookie：只用于浏览器加载 /output 静态媒体，不可调用 API。
MEDIA_AUTH_COOKIE_NAME = "xiaoyou_media_auth"
MEDIA_AUTH_TTL_SECONDS = 3600


def is_protected_path(path: str) -> bool:
    """检查路径是否需要保护。

    `/output` 中包含用户上传与生成媒体，不能把“知道 URL”当作访问凭证；
    FastAPI 文档也不应在公网入口匿名暴露完整 API 面。
    """
    normalized = str(path or "")
    if normalized in {"/docs", "/redoc", "/openapi.json"}:
        return True
    return normalized in {"/api", "/v1", "/output"} or normalized.startswith(
        ("/api/", "/v1/", "/demo", "/health", "/output/")
    )


def _get_mapping_value(mapping: Optional[Mapping], key: str) -> str:
    if mapping is None:
        return ""
    try:
        return str(mapping.get(key, "") or "").strip()
    except Exception:
        return ""


def get_access_token_from_headers(
    headers: Optional[Mapping], query_params: Optional[Mapping] = None
) -> str:
    """从通用 headers/query 中获取访问令牌，HTTP/WS 共用。"""
    query_token = _get_mapping_value(query_params, "token")
    if query_token:
        return query_token

    authorization = _get_mapping_value(headers, "authorization")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token

    for header_name in ("x-internal-token", "x-access-token"):
        token = _get_mapping_value(headers, header_name)
        if token:
            return token
    return ""


def get_access_token_from_request(request: Request) -> str:
    """从请求中获取访问令牌。"""
    return get_access_token_from_headers(request.headers)


def get_required_access_token() -> str:
    """获取必需的访问令牌。"""
    try:
        from config.integrated_config import get_settings

        return str(get_settings().security.web_access_token or "").strip()
    except Exception:
        return ""


def is_loopback_address(host: str) -> bool:
    """判断地址是否为回环地址。"""
    normalized = str(host or "").strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def get_forwarded_client_ip(headers: Optional[Mapping]) -> str:
    """读取反向代理声明的原始客户端 IP。

    Cloudflare Tunnel 优先使用 `CF-Connecting-IP`；其它反向代理退回 XFF。
    该值只用于识别“loopback 对端其实是代理转发的外部请求”和限流，
    绝不单独作为认证凭据。
    """
    cf_ip = _get_mapping_value(headers, "cf-connecting-ip")
    if cf_ip:
        return cf_ip

    forwarded_for = _get_mapping_value(headers, "x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = _get_mapping_value(headers, "x-real-ip")
    if real_ip:
        return real_ip
    return ""


def is_trusted_loopback_connection(peer_host: str, headers: Optional[Mapping]) -> bool:
    """判断是否真的是可豁免认证的本机直连。

    cloudflared/nginx 等本机反向代理的 socket 对端也可能是 127.0.0.1。
    如果代理头明确给出了非回环客户端，则必须按公网请求鉴权，不能因为
    socket 对端是 loopback 就放行。这样即使 Uvicorn 的 proxy-headers 配置
    被关闭或改变，Tunnel 请求也不会退化成“本机免认证”。
    """
    if not is_loopback_address(peer_host):
        return False

    forwarded_client = get_forwarded_client_ip(headers)
    if not forwarded_client:
        return True
    return is_loopback_address(forwarded_client)


def get_client_ip(request: Request) -> str:
    """获取用于日志和限流的逻辑客户端 IP。"""
    forwarded_client = get_forwarded_client_ip(request.headers)
    if forwarded_client:
        return forwarded_client
    if request.client and request.client.host:
        return str(request.client.host)
    return "unknown"


def get_peer_ip(request: Request) -> str:
    """获取 ASGI 暴露的 socket/代理处理后对端 IP。"""
    if request.client and request.client.host:
        return str(request.client.host).strip()
    return "unknown"


def is_loopback_peer(request: Request) -> bool:
    """兼容旧调用：仅判断 request.client 是否为回环。"""
    return is_loopback_address(get_peer_ip(request))


def is_loopback_auth_bypass_enabled() -> bool:
    """读取本地连接免认证开关；默认保持现有内部适配器兼容性。"""
    try:
        from config.integrated_config import get_settings

        return bool(get_settings().security.allow_loopback_auth_bypass)
    except Exception:
        return True


def _media_cookie_signature(required_token: str, expires_at: int) -> str:
    message = f"media:{int(expires_at)}".encode("utf-8")
    return hmac.new(
        required_token.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def create_media_auth_cookie(
    required_token: str, *, now: Optional[float] = None
) -> str:
    """创建仅用于 `/output` 的短期签名 cookie。"""
    current = time.time() if now is None else float(now)
    expires_at = int(current) + MEDIA_AUTH_TTL_SECONDS
    signature = _media_cookie_signature(required_token, expires_at)
    return f"{expires_at}.{signature}"


def validate_media_auth_cookie(
    cookie_value: str, required_token: str, *, now: Optional[float] = None
) -> bool:
    """校验媒体 cookie；cookie 本身不包含主 API Token。"""
    value = str(cookie_value or "").strip()
    secret = str(required_token or "").strip()
    if not value or not secret or "." not in value:
        return False

    expires_raw, signature = value.split(".", 1)
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False

    current = time.time() if now is None else float(now)
    if expires_at < int(current):
        return False

    expected = _media_cookie_signature(secret, expires_at)
    return bool(signature) and hmac.compare_digest(signature, expected)


def _request_is_https(request: Request) -> bool:
    proto = _get_mapping_value(request.headers, "x-forwarded-proto").lower()
    return request.url.scheme == "https" or proto == "https"


def json_auth_error(status_code: int, message: str):
    """返回JSON格式的认证错误响应。"""
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": message},
    )


async def authorize_websocket(websocket: WebSocket) -> bool:
    """统一 WebSocket 握手鉴权。

    本机直连可按配置豁免；但如果 socket 对端是 loopback、代理头却表明真实
    客户端来自外部（Cloudflare Tunnel 的典型形态），仍必须校验 Token。
    """
    client_host = ""
    if getattr(websocket, "client", None):
        client_host = str(getattr(websocket.client, "host", "") or "").strip()

    if (
        is_loopback_auth_bypass_enabled()
        and is_trusted_loopback_connection(client_host, websocket.headers)
    ):
        return True

    required_token = get_required_access_token()
    if not required_token:
        await websocket.close(
            code=1008,
            reason="服务未配置访问令牌，请设置 XIAOYOU_SECURITY_WEB_ACCESS_TOKEN",
        )
        return False

    token = get_access_token_from_headers(
        websocket.headers, getattr(websocket, "query_params", None)
    )
    if not token or not hmac.compare_digest(token, required_token):
        await websocket.close(code=1008, reason="未授权的 WebSocket 访问")
        return False
    return True


async def security_middleware(request: Request, call_next):
    """安全中间件，处理认证和速率限制。"""
    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if not is_protected_path(path):
        return await call_next(request)

    # WebSocket 由连接层统一执行 authorize_websocket；HTTP 中间件不处理 upgrade。
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 本机免认证仅允许“真实本机直连”。如果 loopback 对端携带非本机代理来源，
    # 视为公网转发请求，必须继续 Token 校验。
    if (
        is_loopback_auth_bypass_enabled()
        and is_trusted_loopback_connection(get_peer_ip(request), request.headers)
    ):
        return await call_next(request)

    required_token = get_required_access_token()
    if not required_token:
        return json_auth_error(
            503,
            "服务未配置访问令牌，已拒绝受保护接口访问，请先在环境变量中设置 XIAOYOU_SECURITY_WEB_ACCESS_TOKEN",
        )

    token = get_access_token_from_request(request)
    authenticated_with_token = bool(token) and hmac.compare_digest(token, required_token)

    # 浏览器 <img>/<video> 无法自动附加 Authorization。允许使用服务器签发的
    # HttpOnly 短期媒体 cookie；该 cookie 的 Path=/output，不能调用其它 API。
    media_cookie_ok = False
    if path == "/output" or path.startswith("/output/"):
        media_cookie_ok = validate_media_auth_cookie(
            request.cookies.get(MEDIA_AUTH_COOKIE_NAME, ""), required_token
        )

    if not authenticated_with_token and not media_cookie_ok:
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

    # 只在主 Token 真正校验成功后签发媒体 cookie。媒体 cookie 自己不能续期自己，
    # 避免被单独窃取后无限延长寿命。
    if authenticated_with_token:
        response.set_cookie(
            key=MEDIA_AUTH_COOKIE_NAME,
            value=create_media_auth_cookie(required_token),
            max_age=MEDIA_AUTH_TTL_SECONDS,
            path="/output",
            secure=_request_is_https(request),
            httponly=True,
            samesite="strict",
        )
    return response


async def strict_origin_middleware(request: Request, call_next, allow_origins: list):
    """严格 Origin 校验中间件"""
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    # 跳过 WebSocket 升级请求：原生 App（Android/iOS）发起 WS 握手时不带 Origin 头，
    # WebSocket 的认证由连接层自行处理。
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 仅针对受保护的 API/媒体路径进行严格 Origin 检查
    if not is_protected_path(request.url.path):
        return await call_next(request)

    origin = request.headers.get("origin")

    # 非浏览器请求通常没有 Origin；认证仍由 security_middleware 保证。
    if not origin:
        return await call_next(request)

    if "*" in allow_origins:
        return await call_next(request)

    if origin not in allow_origins:
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
    if (
        path in {"/api", "/v1", "/output"}
        or path.startswith(("/api/", "/v1/", "/demo", "/output/"))
    ):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Pragma", "no-cache")
    proto = str(request.headers.get("x-forwarded-proto", "")).strip().lower()
    if request.url.scheme == "https" or proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response
