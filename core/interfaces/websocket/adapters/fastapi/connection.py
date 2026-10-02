"""FastAPI WebSocket 连接握手与接收循环。"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from core.utils.logger import get_logger

logger = get_logger(__name__)


def _adapter_asyncio() -> Any:
    """读取门面模块的 asyncio，保留既有 monkeypatch 注入点。"""
    from .. import adapter

    return adapter.asyncio


class WebSocketConnectionMixin:
    """连接鉴权、身份绑定与持续接收职责。"""

    async def handle_connection(self, websocket: WebSocket) -> None:
        try:
            if not self._initialized:
                await self.initialize()
        except Exception as exc:  # noqa: BLE001
            logger.error("WebSocket 适配器初始化失败，拒绝握手: %s", exc, exc_info=True)
            try:
                await websocket.close(code=1013, reason="服务暂不可用，请稍后重试")
            except Exception:  # noqa: BLE001
                pass
            return

        client_host = ""
        if hasattr(websocket, "client") and websocket.client:
            client_host = str(getattr(websocket.client, "host", ""))
        from core.middleware.security import (
            is_loopback_address,
            is_loopback_auth_bypass_enabled,
        )

        is_local = is_loopback_auth_bypass_enabled() and is_loopback_address(client_host)
        try:
            from config.integrated_config import get_settings

            required_token = str(get_settings().security.web_access_token or "").strip()
        except Exception:  # noqa: BLE001
            required_token = ""

        if not is_local and not required_token:
            await websocket.close(
                code=1008,
                reason="服务未配置访问令牌，请设置 XIAOYOU_SECURITY_WEB_ACCESS_TOKEN",
            )
            return

        query_params = getattr(websocket, "query_params", None)
        ws_token = (
            str(query_params.get("token")).strip()
            if query_params and query_params.get("token") is not None
            else ""
        )
        if not ws_token:
            authorization = str(websocket.headers.get("authorization", "")).strip()
            if authorization.lower().startswith("bearer "):
                ws_token = authorization[7:].strip()
        if not ws_token:
            ws_token = str(websocket.headers.get("x-internal-token", "")).strip()

        if not is_local:
            token_ok = bool(ws_token) and hmac.compare_digest(ws_token, required_token)
            try:
                from core.utils.ws_handshake_debug import log as ws_log

                ws_log(
                    "token_check",
                    client_host=client_host,
                    is_local=is_local,
                    ws_token_present=bool(ws_token),
                    required_token_present=bool(required_token),
                    token_ok=token_ok,
                    user_id=(
                        str(query_params.get("user_id"))
                        if query_params and query_params.get("user_id") is not None
                        else None
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
            if not token_ok:
                await websocket.close(code=1008, reason="未授权的 WebSocket 访问")
                return

        await websocket.accept()
        user_id = (
            str(query_params.get("user_id")).strip()
            if query_params and query_params.get("user_id") is not None
            else str(getattr(websocket, "user_id", "unknown")).strip()
        ) or "unknown"
        platform = (
            str(query_params.get("platform")).strip().lower()
            if query_params and query_params.get("platform") is not None
            else str(getattr(websocket, "platform", "unknown")).strip().lower()
        ) or "unknown"
        client_id = (
            str(query_params.get("client_id")).strip()
            if query_params and query_params.get("client_id") is not None
            else str(getattr(websocket, "client_id", "")).strip()
        )
        setattr(websocket, "user_id", user_id)
        setattr(websocket, "platform", platform)
        if client_id:
            setattr(websocket, "client_id", client_id)
        logger.info(
            "New WebSocket connection from user: %s, platform: %s, client_id: %s",
            user_id,
            platform,
            client_id or "n/a",
        )
        if self.websocket_manager:
            await self.websocket_manager.add_connection(
                websocket, user_id=user_id, platform=platform
            )

        try:
            while True:
                try:
                    message = await websocket.receive_json()
                except WebSocketDisconnect as exc:
                    log = logger.info if exc.code in (1000, 1001) else logger.warning
                    log(
                        "WebSocket disconnected for user %s: (%s, '%s')",
                        user_id,
                        exc.code,
                        exc.reason or "",
                    )
                    break
                except RuntimeError as exc:
                    text = str(exc)
                    if "not connected" in text or "accept" in text:
                        logger.info(
                            "WebSocket connection lost before receive for user %s: %s",
                            user_id,
                            text,
                        )
                        break
                    logger.error(
                        "Runtime error receiving message for user %s: %s",
                        user_id,
                        exc,
                        exc_info=True,
                    )
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error receiving message: %s", exc, exc_info=True)
                    raise
                _adapter_asyncio().create_task(self._safe_process_message(websocket, message))
        except Exception as exc:  # noqa: BLE001
            if "disconnect" not in str(exc).lower() and "closed" not in str(exc).lower():
                logger.error(
                    "WebSocket connection error for user %s: %s", user_id, exc, exc_info=True
                )
            else:
                logger.info("WebSocket connection closed for user %s: %s", user_id, exc)
        finally:
            await self.handlers.cleanup_websocket(websocket)
            await self._cancel_chat_tasks(websocket)
            if self.websocket_manager:
                await self.websocket_manager.remove_connection(websocket)
            logger.info("WebSocket connection cleaned up for user: %s", user_id)

    async def _safe_process_message(self, websocket: WebSocket, message: dict) -> None:
        try:
            await self._process_message(websocket, message)
        except _adapter_asyncio().CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if "disconnect" in str(exc).lower() or "closed" in str(exc).lower():
                logger.debug(
                    "后台消息处理时连接已关闭 (user: %s): %s",
                    getattr(websocket, "user_id", "?"),
                    exc,
                )
            else:
                logger.error(
                    "后台消息处理异常 (user: %s): %s",
                    getattr(websocket, "user_id", "?"),
                    exc,
                    exc_info=True,
                )
