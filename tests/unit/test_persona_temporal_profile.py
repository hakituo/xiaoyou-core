"""Temporal Profile 的日期筛选、动态注入与现场优先级回归。"""

from datetime import datetime, timezone

from core.agents.chat_agent_components.persona_system.prompt.layered_context import (
    build_layered_persona_context,
    clear_persona_context_cache,
)


def _build(tmp_path, *, now: datetime, temporal_profile: dict, runtime_state=None):
    profile = {
        "core": {"identity": {"real_name": "测试角色"}},
        "voice": {"baseline": "自然聊天"},
        "relationship": {},
        "temporal_profile": temporal_profile,
        "knowledge": [],
    }
    return build_layered_persona_context(
        persona_filename="fixture_temporal.json",
        persona_data={"meta": {"scope": "fixture_temporal"}},
        profile=profile,
        root=tmp_path,
        memory_root=tmp_path / "memory",
        runtime_state=runtime_state or {"state": {}},
        message="普通消息",
        conversation_id="temporal-test",
        now=now,
    )


def test_temporal_profile_only_projects_entries_active_on_current_date(tmp_path):
    clear_persona_context_cache()
    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    layers = _build(
        tmp_path,
        now=now,
        temporal_profile={
            "entries": [
                {
                    "id": "expired",
                    "valid_until": "2026-09-14",
                    "facts": {"stage": "旧阶段"},
                },
                {
                    "id": "active",
                    "valid_from": "2026-09-01",
                    "valid_until": "2027-06-30",
                    "facts": {"stage": "当前阶段"},
                },
                {
                    "id": "future",
                    "valid_from": "2027-07-01",
                    "facts": {"stage": "未来阶段"},
                },
            ]
        },
    )

    assert layers is not None
    assert "[TEMPORAL PROFILE]" in layers.dynamic_prompt
    assert "当前阶段" in layers.dynamic_prompt
    assert "旧阶段" not in layers.dynamic_prompt
    assert "未来阶段" not in layers.dynamic_prompt
    assert "当前阶段" not in layers.static_prompt
    assert layers.context_trace["temporal_profile_ids"] == ["active"]


def test_temporal_profile_is_inclusive_and_current_state_is_later(tmp_path):
    clear_persona_context_cache()
    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    temporal = {
        "entries": [
            {
                "id": "one-day",
                "valid_from": "2026-09-15",
                "valid_until": "2026-09-15",
                "facts": {"school_background": "默认在校"},
            }
        ]
    }
    runtime_state = {
        "state": {
            "location": {
                "value": "家里",
                "source": "user_explicit",
                "updated_at": now.isoformat(),
                "confidence": 1.0,
            }
        }
    }
    layers = _build(
        tmp_path,
        now=now,
        temporal_profile=temporal,
        runtime_state=runtime_state,
    )

    assert layers is not None
    temporal_index = layers.dynamic_prompt.index("[TEMPORAL PROFILE]")
    current_index = layers.dynamic_prompt.index("[CURRENT STATE]")
    assert temporal_index < current_index
    assert "默认在校" in layers.dynamic_prompt
    assert "家里" in layers.dynamic_prompt

    next_day = _build(
        tmp_path,
        now=datetime(2026, 9, 16, 12, tzinfo=timezone.utc),
        temporal_profile=temporal,
    )
    assert next_day is not None
    assert "[TEMPORAL PROFILE]" not in next_day.dynamic_prompt
    assert next_day.context_trace["temporal_profile_ids"] == []


def test_invalid_temporal_window_is_skipped_instead_of_leaking(tmp_path):
    clear_persona_context_cache()
    layers = _build(
        tmp_path,
        now=datetime(2026, 9, 15, 12, tzinfo=timezone.utc),
        temporal_profile={
            "entries": [
                {
                    "id": "broken-date",
                    "valid_from": "not-a-date",
                    "facts": {"stage": "不应出现"},
                },
                {
                    "id": "reversed",
                    "valid_from": "2026-10-01",
                    "valid_until": "2026-09-01",
                    "facts": {"stage": "也不应出现"},
                },
            ]
        },
    )

    assert layers is not None
    assert "[TEMPORAL PROFILE]" not in layers.dynamic_prompt
    assert "不应出现" not in layers.dynamic_prompt
    assert layers.context_trace["temporal_profile_ids"] == []
