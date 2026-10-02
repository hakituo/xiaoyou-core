"""QQ 传输层辅助：WebSocket 连接与文本截断。"""

from __future__ import annotations

import websockets


async def _ws_connect(url: str, headers: dict | None = None):
    """建立到 NapCat 的 WebSocket 连接。

    启用客户端主动心跳：每 20 秒发送 ping，60 秒内未收到 pong 才关闭连接。
    兼顾空闲保活，并容忍模型加载、Windows 调度抖动等短时事件循环阻塞。
    """
    headers = headers if isinstance(headers, dict) and headers else None
    return websockets.connect(
        url,
        extra_headers=headers,
        open_timeout=5,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=60,
        max_queue=32,
        compression=None,
    )


def _truncate_text(text: str, limit: int = 1500) -> str:
    """超长文本截断，末尾追加省略提示。"""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...（已截断）"
