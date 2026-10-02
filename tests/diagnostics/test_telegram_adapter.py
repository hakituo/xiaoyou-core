"""Telegram 适配器离线可靠性测试。

这些测试不访问 Telegram API，也不启动真实后端；所有结果都通过 assert 判定，
避免旧诊断脚本返回 False 但仍被 pytest 计为通过。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import Chat, Message, PhotoSize, Update, User, Voice

import clients.bots.telegram.adapter as adapter_module
import clients.bots.telegram.session as session_module
from clients.bots.telegram.adapter import TelegramAdapter
from clients.bots.telegram.session import TelegramSession
from config.integrated_config import get_settings
from config.settings_adapters import (
    get_telegram_adapter_settings,
    reset_adapter_settings_cache,
)
from config.yaml_loader import load_resolved_yaml_config_from_disk


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_adapter_singleton():
    reset_adapter_settings_cache()
    yield
    TelegramAdapter._instance = None
    reset_adapter_settings_cache()


def _make_updates() -> dict[str, Update]:
    user = User(id=7, first_name="tester", is_bot=False)
    chat = Chat(id=8, type="private")
    now = datetime.now(timezone.utc)
    return {
        "photo": Update(
            1,
            message=Message(
                1,
                now,
                chat,
                from_user=user,
                photo=(PhotoSize("photo", "photo_unique", 16, 16),),
            ),
        ),
        "voice": Update(
            2,
            message=Message(
                2,
                now,
                chat,
                from_user=user,
                voice=Voice("voice", "voice_unique", 1),
            ),
        ),
        "command": Update(
            3,
            message=Message(3, now, chat, from_user=user, text="/模型"),
        ),
    }


def _first_matching_callback(application, update: Update) -> str:
    for handler in application.handlers[0]:
        matched = handler.check_update(update)
        if matched is not None and matched is not False:
            return handler.callback.__name__
    raise AssertionError("update 没有匹配到任何 handler")


def test_app_yaml_is_telegram_switch_source():
    yaml_config, _, _ = load_resolved_yaml_config_from_disk(
        PROJECT_ROOT / "config" / "yaml" / "app.yaml"
    )
    assert isinstance(yaml_config.get("telegram"), dict)
    settings = get_settings()
    assert settings.telegram.enabled is yaml_config["telegram"]["enabled"]
    assert settings.telegram.ws_url == yaml_config["telegram"]["ws_url"]


def test_legacy_env_cannot_override_app_yaml_switch(monkeypatch):
    yaml_config, _, _ = load_resolved_yaml_config_from_disk(
        PROJECT_ROOT / "config" / "yaml" / "app.yaml"
    )
    monkeypatch.setenv("TELEGRAM_ENABLED", str(not yaml_config["telegram"]["enabled"]))

    resolved = get_telegram_adapter_settings()

    assert resolved.enabled is yaml_config["telegram"]["enabled"]


def test_main_lifespan_owns_telegram_task():
    lifespan_source = (PROJECT_ROOT / "core" / "lifecycle" / "lifespan.py").read_text(
        encoding="utf-8"
    )
    assert "telegram_task = spawn_bg_task(" in lifespan_source
    assert "telegram_adapter.run()" in lifespan_source
    assert "await telegram_adapter.stop()" in lifespan_source
    assert not (PROJECT_ROOT / "config" / "telegram_config.json").exists()


@pytest.mark.asyncio
async def test_media_handlers_are_not_shadowed_by_text_handler(monkeypatch):
    monkeypatch.setattr(adapter_module, "TELEGRAM_BOT_TOKEN", "123456:test-token")
    adapter = TelegramAdapter()
    await adapter.initialize()
    assert adapter.application is not None

    updates = _make_updates()
    assert _first_matching_callback(adapter.application, updates["photo"]) == "handle_photo"
    assert _first_matching_callback(adapter.application, updates["voice"]) == "handle_voice"
    assert _first_matching_callback(adapter.application, updates["command"]) == "handle_message"


@pytest.mark.asyncio
async def test_idle_sessions_are_closed_and_removed():
    adapter = TelegramAdapter()
    adapter.session_timeout_seconds = 10.0
    stale = SimpleNamespace(
        session_id="tg_stale", last_activity=0.0, stop=AsyncMock()
    )
    fresh = SimpleNamespace(
        session_id="tg_fresh", last_activity=15.0, stop=AsyncMock()
    )
    adapter.sessions = {"tg_stale": stale, "tg_fresh": fresh}

    removed = await adapter._cleanup_idle_sessions_once(now=20.0)

    assert removed == 1
    assert "tg_stale" not in adapter.sessions
    assert "tg_fresh" in adapter.sessions
    stale.stop.assert_awaited_once()
    fresh.stop.assert_not_awaited()


class _FakeWebSocket:
    def __init__(self, session: TelegramSession, attempts: list[str], *, fail_send: bool):
        self._session = session
        self._attempts = attempts
        self._fail_send = fail_send

    async def send(self, payload: str):
        self._attempts.append(payload)
        if self._fail_send:
            raise ConnectionError("transient send failure")
        self._session.running = False

    async def close(self):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Event().wait()
        raise StopAsyncIteration


class _FakeConnectContext:
    def __init__(self, websocket: _FakeWebSocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_unconfirmed_ws_message_is_retried_after_reconnect(monkeypatch):
    attempts: list[str] = []
    adapter = SimpleNamespace(
        xiaoyou_ws_url="ws://127.0.0.1:8000/api/v1/ws",
        xiaoyou_access_token="",
        sessions={},
    )
    session = TelegramSession("tg_8", adapter)
    adapter.sessions[session.session_id] = session
    session.running = True
    await session.queue.put({"type": "text_input", "text": "不能丢", "_send_ts": 1})

    connection_count = 0

    def fake_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        ws = _FakeWebSocket(
            session,
            attempts,
            fail_send=connection_count == 1,
        )
        return _FakeConnectContext(ws)

    real_sleep = asyncio.sleep

    async def fast_sleep(_delay: float):
        await real_sleep(0)

    monkeypatch.setattr(session_module.websockets, "connect", fake_connect)
    monkeypatch.setattr(session_module.asyncio, "sleep", fast_sleep)

    await asyncio.wait_for(session._run_loop(), timeout=2.0)

    assert connection_count == 2
    assert len(attempts) == 2
    assert json.loads(attempts[0])["text"] == "不能丢"
    assert attempts[1] == attempts[0]


@pytest.mark.asyncio
async def test_failed_startup_always_cleans_runtime():
    adapter = TelegramAdapter()
    adapter.health_checker.prelight_check = AsyncMock(return_value=True)
    adapter.initialize = AsyncMock(side_effect=RuntimeError("init failed"))

    with pytest.raises(RuntimeError, match="init failed"):
        await adapter._run_once()

    assert adapter.running is False
    assert adapter.application is None
    assert adapter.ready_event.is_set() is False


@pytest.mark.asyncio
async def test_supervisor_restarts_after_failure(monkeypatch):
    monkeypatch.setattr(adapter_module, "ENABLED", True)
    monkeypatch.setattr(adapter_module, "TELEGRAM_BOT_TOKEN", "123456:test-token")
    adapter = TelegramAdapter()
    attempts = 0

    async def fake_run_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first failure")
        adapter._stop_requested = True

    class _ImmediateEvent:
        def clear(self):
            return None

        def set(self):
            return None

        async def wait(self):
            return False

    adapter._stop_event = _ImmediateEvent()
    monkeypatch.setattr(adapter, "_run_once", fake_run_once)

    await adapter.run()

    assert attempts == 2
