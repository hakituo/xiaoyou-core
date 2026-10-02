# -*- coding: utf-8 -*-
"""请求体 gzip 解压中间件。

背景：Android 客户端会把最多 200 条历史当 ``history_override`` 塞进聊天请求体，
实测文本量 44-95KB。内网直连无所谓，但走 Cloudflare Tunnel 时这段上传要 0.75s 以上
（实测 100KB body 比 1KB body 的首字节多 0.75s），叠加 TLS 握手就变成用户感知的
「点发送卡 2-3 秒」。客户端因此对 JSON 请求体做 gzip（实测体积降到 1/4~1/5）。

Starlette 只有响应侧的 GZipMiddleware，**默认不解压请求体**，所以这里补上请求侧。

刻意写成纯 ASGI 中间件，而不是 BaseHTTPMiddleware：
后者会把响应包一层，而聊天接口返回的是 SSE 流式响应，包一层容易破坏流式语义。
"""

from __future__ import annotations

import gzip
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# 认这两个 Content-Encoding（x-gzip 是历史别名）。
_GZIP_ENCODINGS = ("gzip", "x-gzip")

# 解压后体积上限：防止构造极小的 gzip 炸弹把内存打爆。
# 正常聊天请求体是几十 KB 量级，留 32MB 足够宽松。
MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024


def _header_value(scope: dict, name: bytes) -> bytes:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value
    return b""


async def _read_body(receive: Callable[[], Awaitable[dict]]) -> Optional[bytes]:
    """读完整请求体；客户端提前断开时返回 None。"""
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return None
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


def _single_body_receive(
    payload: bytes,
    upstream_receive: Callable[[], Awaitable[dict]],
) -> Callable[[], Awaitable[dict]]:
    """构造只发一次 body 的 receive：下游首次读取拿到完整解压后 body。

    第二次及以后的读取**必须交还给上游真实的 receive**，不能伪造
    ``http.disconnect``：

    ASGI spec < 2.4 时（uvicorn 的 http 协议报的是 2.3），Starlette 的
    ``StreamingResponse`` 会额外起一个 ``listen_for_disconnect`` 协程，
    不停 ``await receive()``，一旦拿到 ``http.disconnect`` 就立刻取消整个
    流式响应。也就是说伪造断连等于在第一个 chunk 之前把 SSE 掐掉——
    安卓端（请求体必然 gzip）就会表现为「发消息 AI 完全不回」。

    真实 receive 在客户端没断连时会挂起，断连时才返回 http.disconnect，
    这才是流式响应要的语义。
    """
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return await upstream_receive()

    return receive


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


class GzipRequestBodyMiddleware:
    """把 ``Content-Encoding: gzip`` 的请求体解压后再交给下游。

    只改 scope 里的 headers 与 receive，不碰响应链路；非 gzip 请求原样透传，
    因此对文件上传（走 multipart 且未压缩）没有任何影响。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        encoding = _header_value(scope, b"content-encoding").decode("latin-1").lower()
        if not any(enc in encoding for enc in _GZIP_ENCODINGS):
            return await self.app(scope, receive, send)

        raw = await _read_body(receive)
        if raw is None:
            # 客户端没发完就断开：按断连交给下游处理，不在这里编造响应。
            return await self.app(scope, receive, send)

        try:
            payload = gzip.decompress(raw)
        except Exception as exc:
            logger.warning("gzip 请求体解压失败: %s", exc)
            await _send_json(send, 400, b'{"detail":"gzip request body decode failed"}')
            return

        if len(payload) > MAX_DECOMPRESSED_BYTES:
            logger.warning(
                "gzip 请求体解压后过大: %s bytes (上限 %s)",
                len(payload),
                MAX_DECOMPRESSED_BYTES,
            )
            await _send_json(send, 413, b'{"detail":"decompressed request body too large"}')
            return

        # 重建 headers：去掉 content-encoding，并把 content-length 改成解压后的长度。
        # 这样下游（含安全中间件的内容长度校验）看到的是真实体积，而不是压缩后的。
        new_scope = dict(scope)
        new_scope["headers"] = [
            (key, value)
            for key, value in (scope.get("headers") or [])
            if key.lower() not in (b"content-encoding", b"content-length")
        ]
        new_scope["headers"].append(
            (b"content-length", str(len(payload)).encode("latin-1"))
        )

        return await self.app(
            new_scope, _single_body_receive(payload, receive), send
        )
