#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 QQ 私聊消息是否会进入后端处理。"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from clients.bots.qq.message_pipeline import IntentRoutingProcessor, MessageContext


class _FakeSemanticRecognizer:
    def match(self, _text):
        return None


class _FakeIntentHandler:
    async def handle_semantic_intent(self, *_args, **_kwargs):
        return False

    async def classify_intent(self, *_args, **_kwargs):
        return None


class _FakeLogger:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str):
        self.messages.append(("info", message))

    def debug(self, message: str):
        self.messages.append(("debug", message))


def _build_context(*, msg_type: str, is_at_me: bool) -> MessageContext:
    return MessageContext(
        session_id="private_10001",
        msg_type=msg_type,
        user_id="10001",
        raw_message="小澪～",
        self_id="123456",
        is_at_me=is_at_me,
        group_id="114514",
        session=SimpleNamespace(),
    )


async def main() -> int:
    logger = _FakeLogger()
    processor = IntentRoutingProcessor(
        semantic_recognizer=_FakeSemanticRecognizer(),
        intent_handler=_FakeIntentHandler(),
        reply_mode="at_only",
        enable_llm_intent_router=False,
        logger=logger,
    )

    private_context = await processor.process(
        _build_context(msg_type="private", is_at_me=False)
    )
    group_context = await processor.process(
        _build_context(msg_type="group", is_at_me=False)
    )

    print("=== QQ 私聊路由验证 ===")
    print(f"私聊消息进入后端: {private_context.should_process_semantic}")
    print(f"群聊未@时进入后端: {group_context.should_process_semantic}")

    if not private_context.should_process_semantic:
        print("验证失败：私聊消息仍然被错误拦截。")
        return 1
    if group_context.should_process_semantic:
        print("验证失败：群聊未 @ 消息不应在 at_only 模式下直通后端。")
        return 1

    print("验证通过：私聊会进入后端，群聊仍按 at_only 规则工作。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
