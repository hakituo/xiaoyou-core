from __future__ import annotations

from pathlib import Path

from core.character.managers.persona_manager import PersonaManager


PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _make_manager() -> PersonaManager:
    manager = object.__new__(PersonaManager)
    manager.configs_dir = str(PROJECT_ROOT / "core/character/configs")
    manager.current_persona_file = "core_ling.json"
    manager.current_persona_data = {}
    manager.model_persona_map = {}
    manager._revision = 0
    return manager


def test_ling_default_entry_is_layered_v2_and_v1_stays_selectable() -> None:
    manager = _make_manager()
    personas = manager.list_personas()
    by_filename = {str(item.get("filename") or ""): item for item in personas}

    default_entry = by_filename["core_ling.json"]
    legacy = by_filename["core_ling_v1.json"]

    # 默认入口沿用稳定文件名 core_ling.json（客户端偏好与会话 id 不变），内容是分层 V2。
    assert default_entry["name"] == "Ling"
    assert legacy["name"] == "Ling（V1）"
    assert default_entry["role"] == legacy["role"] == "Ling"
    assert default_entry["is_default"] is True
    assert legacy["is_default"] is False
    assert personas.index(default_entry) < personas.index(legacy)

    loaded = manager.get_persona_by_filename("core_ling.json")
    assert loaded["meta"]["scope"] == "ling"
    profile = loaded["meta"]["context_profile"]
    assert profile["enabled"] is True
    assert profile["root"] == "ling"
    assert profile["voice"] == "voice_ling.json"
    assert profile["relationship"] == "relationship_ling.json"
    assert profile["temporal_profile"] == "temporal_profile.json"
    assert "selected_overlay" not in profile

    # V1 保留为可选回退版本，但它是最初的扁平人设，不声明分层上下文。
    legacy_loaded = manager.get_persona_by_filename("core_ling_v1.json")
    assert "context_profile" not in (legacy_loaded.get("meta") or {})
    assert legacy_loaded["identity"]["name"] == "Ling（V1）"


def test_ling_love_inherits_v2_and_adds_only_selected_variant() -> None:
    manager = _make_manager()
    love = manager.get_persona_by_filename("sensitive/Ling_love.json")

    assert love["meta"]["scope"] == "ling"
    profile = love["meta"]["context_profile"]
    assert profile["enabled"] is True
    assert profile["root"] == "ling"
    assert profile["core"] == "core_ling.json"
    assert profile["voice"] == "voice_ling.json"
    assert profile["relationship"] == "relationship_ling.json"
    assert profile["temporal_profile"] == "temporal_profile.json"
    assert profile["knowledge"] == "knowledge"
    assert profile["selected_overlay"] == "overlays/love_ling.json"

    # Love 仍是一个显式可选敏感 persona，工具权限由子层拥有；V2 base 不需要知道它。
    assert {"scene", "sensitive_meme"} <= set(
        love.get("tool_access", {}).get("allow_categories") or []
    )
