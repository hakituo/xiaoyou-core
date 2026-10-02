#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 连接状态检测

回复延迟醒来后用这个判断是否还能发送——心跳检查器可能在 sleep 期间
关了连接但 cancel 信号还没送达。
"""

from starlette.websockets import WebSocketState


def is_websocket_disconnected(adapter, websocket) -> bool:
    """检测 FastAPI/Starlette WebSocket 是否已经断开。"""
    # 优先复用 WebSocketManager 的检测逻辑（更全面）
    ws_manager = getattr(adapter, "websocket_manager", None)
    if ws_manager is not None:
        try:
            if ws_manager._is_starlette_websocket_closed(websocket):
                return True
        except Exception:
            pass

    # 兜底：直接看 application_state / client_state
    try:
        app_state = getattr(websocket, "application_state", None)
        if app_state == WebSocketState.DISCONNECTED:
            return True
        client_state = getattr(websocket, "client_state", None)
        if client_state == WebSocketState.DISCONNECTED:
            return True
    except Exception:
        pass

    # close_code 被设置也说明已断开
    if getattr(websocket, "close_code", None) is not None:
        return True
    return False
