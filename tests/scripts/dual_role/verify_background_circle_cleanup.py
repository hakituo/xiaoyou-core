"""验证旧后台圈子已清理，且历史事件不会污染关系热度。"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _Logger:
    def warning(self, *_args, **_kwargs) -> None:
        pass


def verify_removed_files_and_config() -> None:
    removed = (
        "core/services/dual_role/runtime.py",
        "core/services/dual_role/service.py",
        "core/services/dual_role/storage.py",
        "core/services/dual_role/models.py",
        "tests/unit/test_background_circle.py",
    )
    for relative in removed:
        assert not (PROJECT_ROOT / relative).exists(), f"旧文件仍存在: {relative}"

    settings = (PROJECT_ROOT / "config/settings_life.py").read_text(encoding="utf-8")
    app_yaml = (PROJECT_ROOT / "config/yaml/app.yaml").read_text(encoding="utf-8")
    assert "bg_circle_" not in settings
    assert "bg_trigger_" not in settings
    assert "weight_background_chat" not in settings
    assert "bg_circle_" not in app_yaml


def verify_peer_chat_has_no_circle_side_effects() -> None:
    hooks = (
        PROJECT_ROOT / "core/services/active_care/peer_chat/peer_script_hooks.py"
    ).read_text(encoding="utf-8")
    assert "write_diary_entry" in hooks, "互聊普通日记被误删"
    assert "append_proactive_message" in hooks, "互聊会话记录被误删"
    assert "background_circle" not in hooks
    assert "register_peer_chat_social_event" not in hooks
    assert "_write_peer_chat_ling_diary" not in hooks


def verify_persona_export_stops_circle_output() -> None:
    source = (
        PROJECT_ROOT / "core/services/journal/persona_exports.py"
    ).read_text(encoding="utf-8")
    assert "get_background_circle_service" not in source
    assert '"background_circle.json"' not in source
    assert "background_circle_entries" not in source


def verify_legacy_events_do_not_raise_heat() -> None:
    from core.services.dual_role.social_events import SocialEventEngine

    settings = SimpleNamespace(
        event_decay_half_life_hours=24.0,
        weight_meal=1.1,
        weight_care=1.4,
        weight_switch=0.5,
        weight_mention=0.4,
        summary_hot_threshold=4.5,
        summary_warm_threshold=2.0,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        engine = SocialEventEngine("", settings, _Logger())
        engine._social_events_dir = temp_dir
        event_file = Path(temp_dir) / "default.json"
        event_file.write_text(
            json.dumps(
                {
                    "conversation_id": "default",
                    "events": [
                        {
                            "ts": time.time(),
                            "type": "background_circle",
                            "detail": "历史自动互聊",
                        },
                        {
                            "ts": time.time(),
                            "type": "meal",
                            "detail": "用户发起的饮食互动",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        summary = engine._build_relationship_summary("default")
        assert 1.0 <= summary["score"] <= 1.1, summary
        assert summary["evidences"] == ["用户发起的饮食互动"], summary


def main() -> int:
    verify_removed_files_and_config()
    verify_peer_chat_has_no_circle_side_effects()
    verify_persona_export_stops_circle_output()
    verify_legacy_events_do_not_raise_heat()
    print("PASS: 后台圈子代码、配置和副作用已清理，历史事件不再污染关系热度")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
