import asyncio
import base64
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from clients.bots.handlers.openclaw import OpenClawHandler
from clients.bots.qq.face import QQFaceInjector
from clients.bots.qq.main import QQAdapter
from clients.bots.qq.utils import extract_leading_reaction_delay, strip_all_reaction_delay_tags
from clients.bots.qq.session.session import XiaoyouSession
from clients.bots.qq.utils import _split_message_for_qq
from core.agents.chat_agent_components.persona_system.prompt.qq_integration import build_qq_reaction_delay_prompt


class _FakeResponse:
    def __init__(self, status, payload, content_type="application/json"):
        self.status = status
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload, ensure_ascii=False)

    async def read(self):
        if isinstance(self._payload, (bytes, bytearray)):
            return bytes(self._payload)
        return b""


class _FakeSession:
    def __init__(self, queue):
        self._queue = list(queue)

    def post(self, *args, **kwargs):
        item = self._queue.pop(0)
        return _FakeResponse(item["status"], item["payload"], item.get("content_type", "application/json"))

    def get(self, *args, **kwargs):
        if self._queue:
            item = self._queue.pop(0)
            return _FakeResponse(item["status"], item["payload"], item.get("content_type", "application/json"))
        return _FakeResponse(200, {"status": "ok"})


class _FakeAdapter:
    def __init__(self, queue):
        self._session = _FakeSession(queue)
        self.sent = []
        self.cfg = SimpleNamespace(persona_filename="", auto_tts_for_voice_input=True)
        self._session_prefs = {}

    async def _get_http_session(self):
        return self._session

    async def send_to_napcat(self, session_id, content):
        self.sent.append((session_id, content))


class TestOpenClawRetry(unittest.IsolatedAsyncioTestCase):
    async def test_openclaw_retry_then_success(self):
        handler = OpenClawHandler(_FakeAdapter([
            {"status": 500, "payload": {"error": {"message": "temporary"}}},
            {"status": 200, "payload": {"output_text": "done"}},
        ]))
        ok, text = await handler._run_openclaw("do task", "model-x")
        self.assertTrue(ok)
        self.assertEqual(text, "done")

    async def test_openclaw_show_models(self):
        adapter = _FakeAdapter([
            {"status": 200, "payload": {"data": [{"id": "m1"}, {"id": "m2"}]}},
        ])
        handler = OpenClawHandler(adapter)
        await handler.show_models("private_1")
        self.assertTrue(
            any(("OpenClaw 模型列表" in msg) or ("OpenClaw 未启用" in msg) for _, msg in adapter.sent)
        )


class TestQQAdapterQueue(unittest.IsolatedAsyncioTestCase):
    async def test_message_event_processed_in_background_task(self):
        adapter = QQAdapter()
        event = asyncio.Event()

        async def _fake_process_post_message(data, self_id):
            await asyncio.sleep(0.05)
            event.set()

        adapter._process_post_message = _fake_process_post_message
        await adapter.handle_napcat_message(
            json.dumps(
                {
                    "post_type": "message",
                    "message_type": "private",
                    "user_id": "123",
                    "self_id": "999",
                    "raw_message": "你好",
                },
                ensure_ascii=False,
            )
        )
        self.assertGreaterEqual(len(adapter._pending_message_tasks), 1)
        await asyncio.wait_for(event.wait(), timeout=1.0)

    async def test_augment_face_label_from_session_emotion(self):
        adapter = QQAdapter()
        adapter._session_emotions["default_user"] = {"happy": 0.99}
        text = adapter._augment_face_label("default_user", "今天效率很高")
        self.assertIn("[微笑]", text)

    async def test_augment_face_label_skip_when_existing_markup(self):
        adapter = QQAdapter()
        adapter._session_emotions["default_user"] = {"angry": 0.99}
        text = adapter._augment_face_label("default_user", "你好 [惊讶]")
        self.assertEqual(text, "你好 [惊讶]")

    async def test_extract_emo_label(self):
        adapter = QQAdapter()
        cleaned, label = adapter._extract_emo_label("[emo:happy] 今天不错")
        self.assertEqual(cleaned.strip(), "今天不错")
        self.assertEqual(label, "微笑")

    async def test_extract_emo_label_with_payload(self):
        adapter = QQAdapter()
        cleaned, label = adapter._extract_emo_label("[EMO: {mood: 'concerned', intensity: 0.6}] 睡这么久？")
        self.assertEqual(cleaned.strip(), "睡这么久？")
        self.assertEqual(label, "疑问")

    async def test_send_voice_response_accepts_json_tts_payload(self):
        adapter = QQAdapter()
        raw_audio = b"RIFF0000TEST"
        fake_session = _FakeSession(
            [
                {
                    "status": 200,
                    "payload": {
                        "success": True,
                        "data": {"audio_base64": base64.b64encode(raw_audio).decode("utf-8")},
                    },
                }
            ]
        )
        adapter._get_http_session = AsyncMock(return_value=fake_session)
        adapter.send_to_napcat = AsyncMock(return_value=True)
        ok = await adapter._send_voice_response("private_1", "测试语音发送")
        self.assertTrue(ok)
        self.assertTrue(adapter.send_to_napcat.await_count >= 1)
        args = adapter.send_to_napcat.await_args[0]
        self.assertEqual(args[0], "private_1")
        self.assertIn("[CQ:record,file=base64://", args[1])


class TestQQFaceInjector(unittest.TestCase):
    def test_prefer_kaomoji_label_should_replace_label(self):
        injector = QQFaceInjector()
        out = injector.apply("你别这样 [委屈]", scope="private_1")
        self.assertNotIn("[委屈]", out)


class TestQQSessionTypingDelay(unittest.TestCase):
    def test_surprise_delay_applies_once(self):
        session = XiaoyouSession("private_1", _FakeAdapter([]))
        with patch("clients.bots.qq_adapter_session.QQ_TYPING_DELAY_SURPRISE_PROBABILITY", 1.0), patch(
            "clients.bots.qq_adapter_session.QQ_TYPING_DELAY_SURPRISE_MIN_SECONDS", 120.0
        ), patch("clients.bots.qq_adapter_session.QQ_TYPING_DELAY_SURPRISE_MAX_SECONDS", 120.0), patch(
            "clients.bots.qq_adapter_session.random.random", return_value=0.0
        ), patch("clients.bots.qq_adapter_session.random.uniform", side_effect=[1.0, 120.0, 1.0]):
            first_delay = session._calc_typing_delay("第一句", allow_surprise_delay=True)
            second_delay = session._calc_typing_delay("第二句", allow_surprise_delay=True)
        self.assertEqual(first_delay, 120.0)
        self.assertLess(second_delay, 120.0)

    def test_bionic_profile_adjusts_base_delay(self):
        session = XiaoyouSession("private_2", _FakeAdapter([]))
        session._bionic_profile = {"delay": {"base_multiplier": 1.5}}
        with patch("clients.bots.qq_adapter_session.random.uniform", return_value=1.0):
            delay = session._calc_typing_delay("测试仿生延迟")
        self.assertGreater(delay, 1.6)


class TestQQSessionSplitSend(unittest.IsolatedAsyncioTestCase):
    async def test_default_reply_should_not_enable_surprise_delay(self):
        session = XiaoyouSession("private_3", _FakeAdapter([]))
        session._send_response = AsyncMock()
        with patch.object(session, "_calc_typing_delay", return_value=0.01) as mock_delay, patch(
            "clients.bots.qq_adapter_session.asyncio.sleep", new=AsyncMock()
        ):
            await session._send_full_response_with_split("你好，世界")
        self.assertGreaterEqual(mock_delay.call_count, 1)
        first_call_kwargs = mock_delay.call_args_list[0].kwargs
        self.assertFalse(bool(first_call_kwargs.get("allow_surprise_delay", True)))

    async def test_full_response_should_split_on_slash_n_markers(self):
        session = XiaoyouSession("private_5", _FakeAdapter([]))
        session._cfg.qq_max_bubble_len = 150
        session._cfg.qq_min_split_len = 40
        session._cfg.auto_tts_for_voice_input = False
        session._load_bionic_profile = AsyncMock()
        session._resolve_comma_split_probability = lambda: 0.2
        session._send_response = AsyncMock()
        session._smart_sleep = AsyncMock()
        with patch.object(session, "_calc_typing_delay", return_value=0.01):
            await session._send_full_response_with_split("就/n像/n这/n样")
        sent_chunks = [call.args[0] for call in session._send_response.await_args_list]
        self.assertEqual(sent_chunks, ["就", "像", "这", "样"])

    async def test_stream_buffer_should_preserve_remaining_newlines(self):
        session = XiaoyouSession("private_6", _FakeAdapter([]))
        session._cfg.qq_max_bubble_len = 150
        session._cfg.qq_min_split_len = 40
        session._load_bionic_profile = AsyncMock()
        session._resolve_comma_split_probability = lambda: 0.2
        session._send_response = AsyncMock()
        session._smart_sleep = AsyncMock()
        with patch.object(session, "_calc_typing_delay", return_value=0.01):
            remaining, sent_any = await session._process_stream_buffer("第一句……\n第二句\n第三句")
        sent_chunks = [call.args[0] for call in session._send_response.await_args_list]
        self.assertTrue(sent_any)
        self.assertEqual(sent_chunks, ["第一句……"])
        self.assertEqual(remaining, "第二句\n第三句")


class TestQQSplitUtils(unittest.TestCase):
    def test_decimal_should_not_split_at_dot(self):
        chunks = _split_message_for_qq("你压力0.55，昨晚睡6小时。", max_len=60)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0], "你压力0.55")
        self.assertEqual(chunks[1], "昨晚睡6小时")


class TestQQReactionDelay(unittest.TestCase):
    def test_extract_leading_reaction_delay(self):
        text, delay = extract_leading_reaction_delay("[DELAY:2.5s]嗯……我刚看到")
        self.assertEqual(text, "嗯……我刚看到")
        self.assertEqual(delay, 2.5)

    def test_strip_all_reaction_delay_tags(self):
        cleaned = strip_all_reaction_delay_tags("[DELAY:3s]好。[WAIT:1.5s]我来了")
        self.assertEqual(cleaned, "好。我来了")

    def test_qq_prompt_contains_reaction_delay_capability(self):
        prompt = build_qq_reaction_delay_prompt()
        self.assertIn("[DELAY:2.5s]", prompt)
        self.assertIn("反应时间", prompt)


class TestQQSessionReactionDelay(unittest.IsolatedAsyncioTestCase):
    async def test_send_full_response_should_wait_reaction_delay_before_first_chunk(self):
        session = XiaoyouSession("private_4", _FakeAdapter([]))
        session._split_disabled = True
        session._send_response = AsyncMock()
        session._smart_sleep = AsyncMock()
        with patch.object(session, "_calc_typing_delay", return_value=0.01):
            await session._send_full_response_with_split("[DELAY:2s]嗯，我刚看到")
        session._smart_sleep.assert_awaited_once_with(2.0)
        session._send_response.assert_awaited_once()
        self.assertEqual(session._send_response.await_args.args[0], "嗯，我刚看到")

if __name__ == "__main__":
    unittest.main()
