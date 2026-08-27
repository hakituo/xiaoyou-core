from types import SimpleNamespace

from core.services.active_care.core.executor import ActiveCareExecutor
from core.services.active_care.core.qq_connection_resolver import QQConnectionResolver


def test_get_qq_connections_can_suppress_logs():
    executor = ActiveCareExecutor.__new__(ActiveCareExecutor)
    calls = []
    executor.qq_connection_resolver = SimpleNamespace(
        resolve=lambda **kwargs: calls.append(kwargs) or []
    )

    result = executor._get_qq_connections(emit_logs=False)

    assert result == []
    assert calls == [{"emit_logs": False}]


def test_user_response_handler_scans_connections_silently():
    from core.services.active_care.core.user_response_handler import UserResponseHandler

    calls = []
    service = SimpleNamespace(
        executor=SimpleNamespace(
            _get_qq_connections=lambda **kwargs: calls.append(kwargs)
            or [
                {"persona_filename": "qq/Aveline_QQ_Master.json"},
                {"persona_filename": "qq/Ling_QQ_Master.json"},
            ]
        )
    )
    handler = UserResponseHandler(service)

    persona_filenames = handler._get_active_persona_filenames()

    assert persona_filenames == [
        "qq/Aveline_QQ_Master.json",
        "qq/Ling_QQ_Master.json",
    ]
    assert calls == [{"emit_logs": False}]


def test_connection_state_log_only_emits_on_change():
    resolver = QQConnectionResolver()

    assert resolver._should_emit_state_log("multi_qq_config_connections", [("aveline", "a.json")]) is True
    assert resolver._should_emit_state_log("multi_qq_config_connections", [("aveline", "a.json")]) is False
    assert resolver._should_emit_state_log("multi_qq_config_connections", [("aveline", "a.json"), ("ling", "b.json")]) is True
