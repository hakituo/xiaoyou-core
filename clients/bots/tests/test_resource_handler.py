import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from clients.bots.handlers.resources import ResourceHandler


class _DummyConfigHandler:
    def make_cloud_model_hint(self, provider: str, model_name: str) -> str:
        provider = str(provider or "").strip()
        model_name = str(model_name or "").strip()
        if not provider or not model_name or provider == "local":
            return ""
        return f"cloud:{provider}:{model_name}"

    async def persist_user_override(self, user_id, prefs):
        return True


class _DummyAdapter:
    def __init__(self):
        self.logger = _DummyLogger()
        self._list_cache = {}
        self.config_handler = _DummyConfigHandler()
        self.sent = []
        self.responses = {}

    async def _api_request(self, method, path, json_body=None, params=None):
        key = (method, path)
        return self.responses.get(key, (200, {}))

    async def send_to_napcat(self, session_id, content):
        self.sent.append((session_id, content))


class _DummyLogger:
    def warning(self, *args, **kwargs):
        pass


class TestResourceHandler(unittest.IsolatedAsyncioTestCase):
    async def test_show_personas_uses_image_renderer_and_marks_current(self):
        adapter = _DummyAdapter()
        handler = ResourceHandler(adapter)
        adapter.responses[("GET", "/api/personas")] = (
            200,
            [
                {"filename": "qq/Aveline_QQ_Master.json", "name": "七濑 澪", "category": "general", "version": "1.0.0"},
                {"filename": "core_ling.json", "name": "Ling", "category": "general", "version": "1.0.0"},
            ],
        )
        adapter.responses[("GET", "/api/personas/current")] = (
            200,
            {"filename": "core_ling.json", "data": {}},
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with patch("clients.bots.handlers.resources._HAS_STATUS_RENDERER", True), patch(
                "clients.bots.handlers.resources.generate_persona_list_image",
                return_value=tmp_path,
            ):
                await handler.show_personas("s1", {})

            self.assertEqual(adapter._list_cache["s1"]["current"], "core_ling.json")
            self.assertEqual(len(adapter.sent), 1)
            self.assertIn("[CQ:image,file=", adapter.sent[0][1])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def test_handle_switch_persona_syncs_model_state_back_to_prefs(self):
        adapter = _DummyAdapter()
        handler = ResourceHandler(adapter)
        personas = [
            {"filename": "qq/Aveline_QQ_Master.json", "name": "七濑 澪"},
            {"filename": "core_ling.json", "name": "Ling"},
        ]
        adapter._list_cache["s1"] = {"type": "persona", "data": personas, "current": "qq/Aveline_QQ_Master.json"}
        adapter.responses[("POST", "/api/personas/switch")] = (200, {"status": "success", "data": {}})
        adapter.responses[("GET", "/api/models")] = (
            200,
            {"current": {"provider": "deepseek", "model": "deepseek-chat", "path": ""}},
        )
        prefs = {"persona_filename": "qq/Aveline_QQ_Master.json", "model_provider": "local", "model_name": "old-local"}

        ok = await handler.handle_switch_persona("s1", "2", prefs, "u1")

        self.assertTrue(ok)
        self.assertEqual(prefs["persona_filename"], "core_ling.json")
        self.assertEqual(prefs["model_provider"], "deepseek")
        self.assertEqual(prefs["model_name"], "deepseek-chat")
        self.assertEqual(prefs["chat_model"], "cloud:deepseek:deepseek-chat")


if __name__ == "__main__":
    unittest.main()
