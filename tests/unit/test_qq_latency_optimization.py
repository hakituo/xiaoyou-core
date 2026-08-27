import asyncio
from types import SimpleNamespace


def test_qq_adapter_latency_defaults():
    from clients.bots.qq.config import QQAdapterConfig

    cfg = QQAdapterConfig()
    assert cfg.qq_message_buffer_window_seconds == 0.35
    assert cfg.qq_message_buffer_max == 8
    assert cfg.qq_skip_backend_merge_wait is True


def test_server_skip_merge_wait_platform_defaults():
    from config.settings_server import ServerSettings

    settings = ServerSettings()
    assert settings.ws_skip_merge_wait_platforms == "qq"


def test_chat_handlers_skip_merge_wait_for_qq():
    from core.interfaces.websocket.adapters.handlers.chat_handlers import ChatHandlers

    class _DummyAdapter:
        def _get_ws_key(self, websocket):
            return id(websocket)

    calls = []
    handlers = ChatHandlers(_DummyAdapter())

    async def _fake_handle_now(websocket, message, streaming_handler):
        calls.append(
            {
                "platform": getattr(websocket, "platform", ""),
                "content": message.get("content"),
            }
        )

    handlers._handle_chat_message_now = _fake_handle_now
    handlers._get_merge_wait_seconds = lambda: 0.2

    websocket = SimpleNamespace(user_id="qq_user", platform="qq")
    message = {"type": "chat", "content": "你好", "message_id": "m1"}

    asyncio.run(handlers.handle_chat_message(websocket, message, streaming_handler=None))

    assert len(calls) == 1
    assert calls[0]["content"] == "你好"


def test_chat_handlers_keep_merge_wait_for_web():
    from core.interfaces.websocket.adapters.handlers.chat_handlers import ChatHandlers

    class _DummyAdapter:
        def _get_ws_key(self, websocket):
            return id(websocket)

    calls = []
    handlers = ChatHandlers(_DummyAdapter())

    async def _fake_handle_now(websocket, message, streaming_handler):
        calls.append(message.get("content"))

    async def _run_case():
        handlers._handle_chat_message_now = _fake_handle_now
        handlers._get_merge_wait_seconds = lambda: 0.1

        websocket = SimpleNamespace(user_id="web_user", platform="web")
        message = {"type": "chat", "content": "你好", "message_id": "m1"}

        await handlers.handle_chat_message(websocket, message, streaming_handler=None)
        assert calls == []
        await asyncio.sleep(0.2)

    asyncio.run(_run_case())

    assert calls == ["你好"]
