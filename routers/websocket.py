# -*- coding: utf-8 -*-
"""WebSocket 域。

处理所有 WebSocket 连接。挂载在 /api/v1/ws（顶层 /api/v1 + 本域 /ws）。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket

from core.interfaces.websocket.fastapi_websocket_adapter import (
    get_fastapi_websocket_adapter,
    FastAPIWebSocketAdapter,
)
from core.utils.ws_handshake_debug import log as ws_log, log_exception as ws_log_exc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])


async def _resolve_adapter(websocket: WebSocket) -> Optional[FastAPIWebSocketAdapter]:
    """获取 WebSocket 适配器（手动解析，避免 Depends 抛异常直接返回 403）。

    诊断说明：
    FastAPI 对 WebSocket 的 Depends 只要抛出非 HTTPException 异常，就会向客户端
    返回 403 Forbidden（这是 FastAPI 的确定性行为，不是应用层 401）。
    为精确定位「移动端连接 403」问题，这里改为手动解析并在失败时：
      1. 写入根目录 ws_handshake_debug.log 诊断日志（host/token/IP/异常）；
      2. 以明确的 1011/1013 关闭握手，而不是让客户端看到含糊的 403。
    """
    client_host = ""
    if hasattr(websocket, "client") and websocket.client:
        client_host = str(getattr(websocket.client, "host", ""))
    raw_url = ""
    try:
        raw_url = str(getattr(websocket, "url", "")) or str(
            getattr(websocket, "scope", {}).get("path", "")
        )
    except Exception:
        raw_url = "<unreadable>"

    ws_log(
        "ws_handshake_start",
        path=raw_url,
        client_host=client_host,
        has_encoded_colon=("%3A" in raw_url or "%3a" in raw_url),
        query_token_present=bool(
            getattr(websocket, "query_params", {}).get("token")
        ),
        user_id=getattr(websocket, "query_params", {}).get("user_id"),
    )

    try:
        adapter = await get_fastapi_websocket_adapter()
    except Exception as e:  # 依赖解析失败 → 这是 403 的真实来源
        ws_log_exc(
            "dependency_resolve_failed",
            exc=e,
            client_host=client_host,
            path=raw_url,
            note="Depends 解析失败会触发 FastAPI 返回 403，此处改为友好关闭",
        )
        try:
            await websocket.close(
                code=1011, reason="WebSocket 适配器未就绪，请稍后重试"
            )
        except Exception:
            pass
        return None

    if not adapter:
        ws_log(
            "adapter_none",
            client_host=client_host,
            path=raw_url,
            note="get_fastapi_websocket_adapter 返回 None",
        )
        try:
            await websocket.close(code=1013, reason="服务暂不可用，请稍后重试")
        except Exception:
            pass
        return None

    ws_log(
        "adapter_resolved",
        client_host=client_host,
        initialized=getattr(adapter, "_initialized", None),
    )
    return adapter


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None),
    _user_agent: Optional[str] = Query(None),
):
    """WebSocket 端点 - 处理客户端连接"""
    adapter = await _resolve_adapter(websocket)
    if adapter is None:
        return
    await adapter.handle_connection(websocket)


@router.websocket("/")
async def websocket_endpoint_slash(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None),
    _user_agent: Optional[str] = Query(None),
):
    """WebSocket 端点（带斜杠）"""
    adapter = await _resolve_adapter(websocket)
    if adapter is None:
        return
    await adapter.handle_connection(websocket)
