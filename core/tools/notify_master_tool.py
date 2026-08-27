"""NotifyMasterTool — 双角色互聊时，让角色可以给主人（Master）发QQ消息。

当两个角色私聊中聊到主人、觉得应该告诉主人某件事时，
LLM 可以调用此工具主动给主人发一条QQ消息。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("NotifyMasterTool")

_ADAPTERS: dict = {}


def register_qq_adapters(adapters: dict) -> None:
    """注册QQ适配器实例，供 NotifyMasterTool 使用"""
    global _ADAPTERS
    _ADAPTERS = adapters or {}


def get_qq_adapters() -> dict:
    """获取已注册的QQ适配器实例"""
    return _ADAPTERS


class NotifyMasterInput(BaseModel):
    message: str = Field(
        description="要发给主人（Master）的消息内容。应该简洁自然，像正常QQ聊天一样。"
    )
    reason: Optional[str] = Field(
        default=None,
        description="为什么要给主人发消息（简要说明，不会发给主人，仅用于决策）",
    )


class NotifyMasterTool(BaseTool):
    name = "notify_master"
    description = (
        "在双角色私聊中，主动给主人（Master）发一条QQ消息。"
        "当你们聊到主人、觉得应该告诉主人某件事、或者想跟主人打招呼时使用。"
        "比如：Ling说'好想Master啊'，你可以给Master发条消息说'Ling想你了'；"
        "或者你们聊到主人该吃饭了，可以提醒他。"
        "不要滥用，只在确实有话想跟主人说时才调用。"
    )
    short_description = "双角色私聊时给主人发QQ消息"
    args_schema = NotifyMasterInput
    category = "communication"
    enabled_by_default = True

    async def _run(self, message: str = "", reason: Optional[str] = None) -> str:
        if not message or not message.strip():
            return "消息内容不能为空。"

        message = message.strip()
        if len(message) > 500:
            message = message[:500]

        adapters = get_qq_adapters()
        if not adapters:
            return "发送失败：QQ适配器未注册。"

        for role_id, adapter in adapters.items():
            try:
                master_qq = str(getattr(adapter.cfg, "master_qq_id", "") or "").strip()
                if not master_qq:
                    continue
                session_id = f"private_{master_qq}"
                await adapter.send_to_napcat(session_id, message)
                return f"已给主人发送消息：{message}"
            except Exception as e:
                logger.warning(f"通过{role_id}给主人发消息失败: {e}")
                continue

        return "发送失败：无法找到有效的QQ适配器。"
