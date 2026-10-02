"""
QQ适配器 - 消息聚合缓冲
将同一会话短时间内的多条消息合并后再处理
"""

import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class MessageAggregator:
    """消息聚合器"""

    def __init__(
        self,
        buffer_window: float = 3.0,
        buffer_max: int = 8,
    ):
        self._msg_buffer: dict[str, list[tuple[str, bool]]] = {}
        self._msg_timer: dict[str, asyncio.TimerHandle] = {}
        self._msg_buffer_window = buffer_window
        self._msg_buffer_max = buffer_max

    @staticmethod
    def classify_message(raw_message: str) -> str:
        """消息分类：command / sticker / context

        - command: / 或 ／ 开头的命令
        - sticker: 纯表情包/贴纸（只有 CQ:face 或动画表情 CQ:image sub_type=1，无文本）
        - context: 包含文本或真实图片的消息，应进入上下文
        """
        import re
        msg = str(raw_message or "").strip()

        # 命令：/ 或 ／ 开头
        if msg.startswith("/") or msg.startswith("／"):
            return "command"

        # 提取所有 CQ 码
        cq_codes = re.findall(r"\[CQ:[^\]]+\]", msg)
        # 去掉所有 CQ 码后的纯文本
        text_only = re.sub(r"\[CQ:[^\]]+\]", "", msg).strip()

        # 如果去掉 CQ 码后还有文本内容，一定是 context
        if text_only:
            return "context"

        # 纯 CQ 码消息：判断是否只有表情/贴纸
        has_context_media = False  # 真实图片或语音
        has_sticker_only = True    # 假设只有贴纸

        for cq in cq_codes:
            # 真实图片（sub_type=0 或无 sub_type）
            if "[CQ:image" in cq:
                if "sub_type=1" in cq:
                    # sub_type=1 是动画表情/贴纸，不算 context
                    pass
                else:
                    # 真实图片，进入上下文
                    has_context_media = True
                    has_sticker_only = False
            elif "[CQ:record" in cq:
                # 语音消息，进入上下文
                has_context_media = True
                has_sticker_only = False
            elif "[CQ:at" in cq:
                # @消息，不算贴纸也不算 context 媒体
                pass
            elif "[CQ:face" in cq:
                # QQ 原生表情，不算 context
                pass
            elif "[CQ:mface" in cq:
                # 商城表情包，不算 context
                pass
            else:
                # 其他 CQ 码类型（如 json、xml 等），保守起见算 context
                has_sticker_only = False

        if has_context_media:
            return "context"
        if has_sticker_only and cq_codes:
            return "sticker"
        # 兜底：空消息或其他
        return "context"

    async def buffer_message(
        self,
        session_id: str,
        raw_message: str,
        flush_callback: Callable[[str, list[tuple[str, bool]]], Awaitable[None]],
    ) -> None:
        """将消息添加到缓冲区，达到条件时刷新

        Args:
            session_id: 会话ID
            raw_message: 原始消息
            flush_callback: 刷新回调函数，接收 (session_id, messages)
        """
        if session_id not in self._msg_buffer:
            self._msg_buffer[session_id] = []
        self._msg_buffer[session_id].append((raw_message, True))

        # 如果已有定时器，取消它（重置等待窗口）
        old_timer = self._msg_timer.get(session_id)
        if old_timer and not old_timer.cancelled():
            old_timer.cancel()

        # 达到最大聚合数，立即刷新
        if len(self._msg_buffer[session_id]) >= self._msg_buffer_max:
            await self._flush_buffer(session_id, flush_callback)
            return

        # 设置新的定时器，窗口结束后刷新
        loop = asyncio.get_event_loop()
        timer = loop.call_later(
            self._msg_buffer_window,
            lambda: asyncio.ensure_future(
                self._flush_buffer(session_id, flush_callback)
            ),
        )
        self._msg_timer[session_id] = timer

    async def _flush_buffer(
        self,
        session_id: str,
        flush_callback: Callable[[str, list[tuple[str, bool]]], Awaitable[None]],
    ) -> None:
        """刷新缓冲区"""
        messages = self._msg_buffer.pop(session_id, [])
        self._msg_timer.pop(session_id, None)
        if not messages:
            return
        await flush_callback(session_id, messages)

    def get_merged_message(self, messages: list[tuple[str, bool]]) -> tuple[str, list[str]]:
        """合并缓冲区中的消息

        Returns:
            (合并后的消息, 上下文消息列表)
        """
        context_messages = [msg for msg, _has_ctx in messages if _has_ctx]
        if not context_messages:
            return "", []
        if len(context_messages) == 1:
            return context_messages[0], context_messages
        merged = "\n".join(context_messages)
        return merged, context_messages
