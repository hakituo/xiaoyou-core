from types import SimpleNamespace

import pytest

from routers.v1 import chat as chat_router


class _FakeAvelineService:
    def __init__(self):
        self.kwargs = None

    async def handle_conversation(self, **kwargs):
        self.kwargs = kwargs
        return {
            "response": "ok",
            "conversation_id": kwargs["conversation_id"],
            "model": kwargs.get("model_hint"),
        }


def _cloud_settings():
    return SimpleNamespace(
        model=SimpleNamespace(
            llm=SimpleNamespace(provider="deepseek", model="global-default"),
            text_path="",
        )
    )


@pytest.mark.asyncio
async def test_body_model_and_session_id_are_request_scoped(monkeypatch):
    """Android role model/session must reach one request without mutating global routing."""
    service = _FakeAvelineService()

    async def _fake_ensure(_request_id=""):
        return service

    monkeypatch.setattr(chat_router, "_ensure_aveline_service", _fake_ensure)

    import config.integrated_config as integrated_config

    monkeypatch.setattr(integrated_config, "get_settings", _cloud_settings)

    result = await chat_router.handle_message(
        message={
            "text": "hello",
            "session_id": "web_role_abc123",
            "model": "cloud:deepseek:role-a:deepseek-v4-pro",
            "persona_filename": "role_a_variant_2.json",
        },
        conversation_id=None,
        model=None,
        voice_id=None,
        stream=False,
        length=None,
    )

    assert result["status"] == "success"
    assert service.kwargs is not None
    assert service.kwargs["model_hint"] == "cloud:deepseek:role-a:deepseek-v4-pro"
    assert service.kwargs["conversation_id"] == "web_role_abc123"
    # persona changes must not rewrite an explicit role/session conversation id.
    assert result["conversation_id"] == "web_role_abc123"


@pytest.mark.asyncio
async def test_query_model_still_has_priority_over_body_model(monkeypatch):
    service = _FakeAvelineService()

    async def _fake_ensure(_request_id=""):
        return service

    monkeypatch.setattr(chat_router, "_ensure_aveline_service", _fake_ensure)

    import config.integrated_config as integrated_config

    monkeypatch.setattr(integrated_config, "get_settings", _cloud_settings)

    await chat_router.handle_message(
        message={
            "text": "hello",
            "session_id": "web_role_xyz789",
            "model": "cloud:deepseek:body-model",
        },
        conversation_id=None,
        model="cloud:deepseek:query-model",
        voice_id=None,
        stream=False,
        length=None,
    )

    assert service.kwargs is not None
    assert service.kwargs["model_hint"] == "cloud:deepseek:query-model"
    assert service.kwargs["conversation_id"] == "web_role_xyz789"
