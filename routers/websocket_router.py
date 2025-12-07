#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket路由模块
处理所有WebSocket连接和消息
"""
import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, Depends, Query

from core.interfaces.websocket.fastapi_websocket_adapter import (
    get_fastapi_websocket_adapter,
    FastAPIWebSocketAdapter
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])


async def get_websocket_adapter() -> FastAPIWebSocketAdapter:
    """
    获取WebSocket适配器依赖
    """
    adapter = get_fastapi_websocket_adapter()
    if not adapter:
        raise Exception("WebSocket适配器未初始化")
    return adapter


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None),
    user_agent: Optional[str] = Query(None),
    adapter: FastAPIWebSocketAdapter = Depends(get_websocket_adapter)
):
    """
    WebSocket端点 - 处理客户端连接
    """
    # 委托给适配器处理
    await adapter.handle_connection(websocket)

@router.websocket("/")
async def websocket_endpoint_slash(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None),
    user_agent: Optional[str] = Query(None),
    adapter: FastAPIWebSocketAdapter = Depends(get_websocket_adapter)
):
    await adapter.handle_connection(websocket)
