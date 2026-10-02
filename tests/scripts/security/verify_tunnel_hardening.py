#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 Cloudflare Tunnel 公网入口安全加固是否仍然存在。"""

from pathlib import Path

from core.middleware.security import (
    create_media_auth_cookie,
    is_protected_path,
    is_trusted_loopback_connection,
    validate_media_auth_cookie,
)


ROOT = Path(__file__).resolve().parents[3]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    # 1. 公网敏感路径必须纳入统一认证。
    for path in (
        "/output",
        "/output/image/uploads/test.png",
        "/docs",
        "/redoc",
        "/openapi.json",
    ):
        require(is_protected_path(path), f"敏感路径未受保护: {path}")

    # 2. 本机反向代理转发外部用户时，不能命中 loopback 免认证。
    require(
        is_trusted_loopback_connection("127.0.0.1", {}),
        "本机直连应继续兼容 loopback 豁免",
    )
    require(
        not is_trusted_loopback_connection(
            "127.0.0.1", {"cf-connecting-ip": "203.0.113.10"}
        ),
        "Cloudflare 外部请求不能因为 socket 对端是 127.0.0.1 而免认证",
    )

    # 3. 媒体 cookie 必须是短期签名，而不是主 Token 的明文副本。
    secret = "verify-secret-token"
    cookie = create_media_auth_cookie(secret, now=1_700_000_000)
    require(secret not in cookie, "媒体 cookie 泄露了主 API Token")
    require(
        validate_media_auth_cookie(cookie, secret, now=1_700_000_001),
        "新签发媒体 cookie 校验失败",
    )
    require(
        not validate_media_auth_cookie(cookie, "wrong-secret", now=1_700_000_001),
        "媒体 cookie 未绑定主 Token",
    )

    # 4. 主 WS 与两个 memory watchdog WS 都必须在业务 handler 前鉴权。
    websocket_router = (ROOT / "routers" / "websocket.py").read_text(encoding="utf-8")
    admin_router = (ROOT / "routers" / "admin" / "__init__.py").read_text(encoding="utf-8")
    require(
        "if not await authorize_websocket(websocket):" in websocket_router,
        "主 /api/v1/ws 缺少统一握手鉴权",
    )
    require(
        '@router.websocket("/admin/memory/ws")' in admin_router
        and '@router.websocket("/memory/ws")' in admin_router
        and "await _secure_memory_websocket(websocket)" in admin_router,
        "memory watchdog WebSocket 未通过安全包装入口",
    )

    # 5. Web 经 Vite 暴露时，/output 必须与 API 一样代理回 8000，
    #    让浏览器自动携带 Path=/output 的 HttpOnly 媒体 cookie。
    vite_config = (
        ROOT / "clients" / "frontend" / "aveline-web" / "vite.config.ts"
    ).read_text(encoding="utf-8")
    require("'/output':" in vite_config, "Vite 未代理 /output 到后端")
    require(
        "target: 'http://127.0.0.1:8000'" in vite_config,
        "Vite /output 代理目标异常",
    )

    print("[OK] Cloudflare Tunnel 安全加固验证通过")


if __name__ == "__main__":
    main()
