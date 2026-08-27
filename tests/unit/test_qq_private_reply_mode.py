#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQ 私聊消息路由回归测试。"""

from types import SimpleNamespace
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

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
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def debug(self, message):
        self.messages.append(("debug", message))


def _build_context(*, msg_type: str, is_at_me: bool = False) -> MessageContext:
    return MessageContext(
        session_id="private_10001",
        msg_type=msg_type,
        user_id="10001",
        raw_message="小澪～",
        self_id="123456",
        is_at_me=is_at_me,
        group_id="",
        session=SimpleNamespace(),
        display_msg="小澪～",
    )


class TestQQPrivateReplyMode(unittest.IsolatedAsyncioTestCase):
    async def test_private_message_always_enters_backend(self):
        logger = _FakeLogger()
        processor = IntentRoutingProcessor(
            semantic_recognizer=_FakeSemanticRecognizer(),
            intent_handler=_FakeIntentHandler(),
            reply_mode="at_only",
            enable_llm_intent_router=False,
            logger=logger,
        )

        context = await processor.process(_build_context(msg_type="private"))

        self.assertTrue(context.should_process_semantic)
        self.assertEqual(context.clean_msg, "小澪～")
        self.assertFalse(
            any("跳过后端处理" in msg for _level, msg in logger.messages),
            "私聊消息不应在 at_only 模式下被拦截",
        )

    async def test_group_message_requires_at_when_at_only(self):
        logger = _FakeLogger()
        processor = IntentRoutingProcessor(
            semantic_recognizer=_FakeSemanticRecognizer(),
            intent_handler=_FakeIntentHandler(),
            reply_mode="at_only",
            enable_llm_intent_router=False,
            logger=logger,
        )

        context = await processor.process(_build_context(msg_type="group", is_at_me=False))

        self.assertFalse(context.should_process_semantic)
        self.assertTrue(
            any("跳过后端处理" in msg for _level, msg in logger.messages),
            "群聊未 @ 时应记录跳过原因",
        )

    async def test_group_message_can_enter_backend_when_reply_mode_all(self):
        logger = _FakeLogger()
        processor = IntentRoutingProcessor(
            semantic_recognizer=_FakeSemanticRecognizer(),
            intent_handler=_FakeIntentHandler(),
            reply_mode="all",
            enable_llm_intent_router=False,
            logger=logger,
        )

        context = await processor.process(_build_context(msg_type="group", is_at_me=False))

        self.assertTrue(context.should_process_semantic)


if __name__ == "__main__":
    unittest.main()
