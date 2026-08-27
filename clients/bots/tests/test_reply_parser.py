import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from clients.bots.handlers.media import MediaHandler


class _FakeAdapter:
    async def call_napcat_action(self, action, params=None, timeout_seconds=8.0):
        if action == "get_msg":
            return 0, {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "raw_message": "被引用的原始消息",
                    "message": [{"type": "text", "data": {"text": "被引用文本"}}],
                },
            }
        return -1, {}


class TestReplyParser(unittest.IsolatedAsyncioTestCase):
    async def test_process_reply_in_message(self):
        handler = MediaHandler(_FakeAdapter())
        out = await handler.process_reply_in_message(
            raw_message="[CQ:reply,id=123456] 你好",
            current_display_msg="[CQ:reply,id=123456] 你好",
        )
        self.assertIn("引用消息", out)
        self.assertIn("被引用文本", out)
        self.assertTrue(out.endswith("你好"))

    def test_extract_text_from_segments(self):
        handler = MediaHandler(_FakeAdapter())
        text = handler._extract_text_from_segments(
            [
                {"type": "text", "data": {"text": "hello"}},
                {"type": "image", "data": {}},
                {"type": "at", "data": {"qq": "10001"}},
            ]
        )
        self.assertIn("hello", text)
        self.assertIn("[图片]", text)
        self.assertIn("@10001", text)


if __name__ == "__main__":
    unittest.main()
