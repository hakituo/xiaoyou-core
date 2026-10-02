# -*- coding: utf-8 -*-
"""统一的「推送到 App」入口。

此前每个想弹手机通知的地方都得自己拼一遍 WebSocket 广播 + NotificationManager
入队，结果是：有的只入队（App 不在线就永远看不到）、有的只广播（后端重启后
通知就凭空消失）、字段名还不统一（安卓端读 `body`，后端一直发 `content`，
通知内容直接是空的）。

这里统一成三个出口：
1. `NotificationManager` 入队 —— 保证 App 下次打开能拉到（`/api/v1/tutor/notifications`）；
2. WebSocket `notification` 广播 —— 保证 App 在线时立刻弹系统通知；
3. FCM 离线推送（`fcm_push.py`）—— 保证 App 被杀 / 常驻关闭时也能收到。

三者共用同一份载荷（title / body / target / data），安卓端才能用同一套深链规则；
其中 FCM 是可选通道：`push.*` 配置齐全才发，缺凭据时静默降级为前两者。

广播是异步的，但调用方可能是 APScheduler / 夜批处理这类**后台线程**，
所以提供同步版 `push_app_notification`：有主事件循环时丢回主循环执行，
没有（如单测、未启动服务）就只走入队 + FCM，绝不抛异常打断业务。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from core.utils.logger import get_logger

logger = get_logger("APP_PUSH")

# 安卓端 WebSocketMessage.Notification 的 target 取值（深链目标页）
TARGET_CHAT = "chat"
TARGET_VOCAB = "vocab"
TARGET_STUDY = "study"
TARGET_LIFE = "life"
TARGET_SETTINGS = "settings"


def _build_payload(
    title: str,
    content: str,
    target: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    notification_type: str = "system",
) -> Dict[str, Any]:
    """构造同时兼容两种消费方式的通知载荷。

    `body` 与 `content` 都带上：安卓 WebSocketManager 目前读 `body`，
    而历史后端代码一直用 `content`，两个都发可避免一边改一边漏。
    """
    payload = dict(data or {})
    payload.setdefault("type", notification_type)
    return {
        "type": "notification",
        "title": title,
        "body": content,
        "content": content,
        "target": target or TARGET_CHAT,
        "data": payload,
        "timestamp": time.time(),
    }


def _enqueue(title: str, content: str, data: Dict[str, Any], notification_type: str) -> None:
    """入轮询队列，保证 App 不在线时通知也不丢。"""
    try:
        from core.managers.notification_manager import get_notification_manager

        get_notification_manager().add_notification(
            user_id="default",
            type=notification_type,
            title=title,
            content=content,
            payload=data,
        )
    except Exception as e:  # pragma: no cover - 队列失败不能影响主流程
        logger.warning(f"通知入队失败: {e}")


def _dispatch_fcm(
    title: str,
    content: str,
    target: Optional[str],
    data: Dict[str, Any],
) -> None:
    """附加 FCM 离线推送：配置齐全才发，缺失/失败静默降级。

    用模块属性调用而不是 `from ... import`：验证脚本会替换这个函数观察载荷。
    """
    try:
        from core.services.notification.fcm_push import dispatch_fcm_notification

        dispatch_fcm_notification(title, content, target, data)
    except Exception as e:  # pragma: no cover - FCM 不能影响主流程
        logger.debug(f"FCM 派发跳过: {e}")


def _deliver_offline(
    title: str,
    content: str,
    target: Optional[str],
    data: Dict[str, Any],
    notification_type: str,
) -> None:
    """非实时通道：通知队列（下次打开 App 能拉到）+ FCM（App 被杀也能弹）。"""
    _enqueue(title, content, data, notification_type)
    _dispatch_fcm(title, content, target, data)


async def async_push_app_notification(
    title: str,
    content: str,
    target: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    notification_type: str = "system",
) -> bool:
    """异步推送：入队 + WebSocket 广播。

    Returns:
        是否成功发出广播（False 通常表示当前没有客户端连接）。
    """
    message = _build_payload(title, content, target, data, notification_type)
    _deliver_offline(title, content, message["target"], message["data"], notification_type)
    try:
        from core.interfaces.websocket.websocket_manager import get_websocket_manager

        ws_manager = get_websocket_manager()
        if ws_manager is None:
            return False
        return bool(await ws_manager.broadcast(message))
    except Exception as e:
        logger.warning(f"通知广播失败: {e}")
        return False


def push_app_notification(
    title: str,
    content: str,
    target: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    notification_type: str = "system",
) -> bool:
    """同步推送，供后台线程（APScheduler 等）调用。

    在主事件循环上调度广播并**限时等待**结果：不等的话，进程关闭时
    协程可能还没跑就被丢弃，日志里就会看到"提醒触发了但手机没收到"。
    """
    try:
        from core.lifecycle.lifespan import get_main_loop

        loop = get_main_loop()
    except Exception as e:
        logger.debug(f"获取主事件循环失败，仅入队不广播: {e}")
        loop = None

    if loop is None or loop.is_closed():
        message = _build_payload(title, content, target, data, notification_type)
        _deliver_offline(title, content, message["target"], message["data"], notification_type)
        logger.debug("主事件循环不可用，通知走离线通道（队列 + FCM）: %s", title)
        return False

    coro = async_push_app_notification(title, content, target, data, notification_type)
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return bool(future.result(timeout=5))
    except Exception as e:
        logger.warning(f"跨线程推送通知失败: {e}")
        return False
