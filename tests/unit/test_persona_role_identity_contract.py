"""稳定角色 ID 必须作为新增字段发布，不得再次覆盖旧客户端的展示名键。"""

from unittest.mock import Mock

import pytest

from routers.v1 import personas


@pytest.mark.asyncio
async def test_persona_identity_preserves_legacy_role(monkeypatch):
    rows = [{"filename": "role.json", "name": "角色甲", "role": "角色甲"}]
    monkeypatch.setattr(personas, "_get_persona_manager", lambda: Mock(list_personas=lambda: rows))
    monkeypatch.setattr(personas, "_resolve_default_model", lambda _: "")
    monkeypatch.setattr(personas, "_resolve_default_voice", lambda _: "")
    monkeypatch.setattr("core.utils.data.scope_registry.resolve_persona_slug_scope", lambda _: "role_a")
    monkeypatch.setattr("core.utils.data.scope_registry.get_registered_role_scopes", lambda: {"role_a"})
    result = await personas.list_personas()
    assert result[0]["role"] == "角色甲"
    assert result[0]["role_id"] == "role_a"
    assert set(result[0]["role_aliases"]) == {"角色甲", "role_a"}


def test_unknown_persona_must_not_be_assigned_default_role(monkeypatch):
    monkeypatch.setattr("core.utils.data.scope_registry.resolve_persona_slug_scope", lambda _: "")
    monkeypatch.setattr("core.utils.data.scope_registry.get_registered_role_scopes", lambda: {"aveline"})
    assert personas._resolve_role_identity({"filename": "unknown.json", "role": "未知"}) == {}
