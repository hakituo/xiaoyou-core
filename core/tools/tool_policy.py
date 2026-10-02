"""角色工具策略：共享实现目录，角色独立决定常驻、按需和禁止的能力。"""

from dataclasses import dataclass
from typing import Mapping, Optional

from config.tool_profiles import get_tool_profiles
from core.tools.tool_metadata import get_tool_domain
from core.utils.data.scope_registry import resolve_persona_slug_scope


def _matches(name: str, selectors: tuple[str, ...]) -> bool:
    return name in selectors or "*" in selectors or f"domain:{get_tool_domain(name)}" in selectors


@dataclass(frozen=True)
class RoleToolPolicy:
    scope: str
    resident: tuple[str, ...]
    on_demand: tuple[str, ...]
    disabled: tuple[str, ...]

    def allows(self, name: str) -> bool:
        return not _matches(name, self.disabled) and (name in self.resident or _matches(name, self.on_demand))


def resolve_role_tool_policy(
    persona_filename: Optional[str] = None, *, mode: str = "chat",
    persona_data: Optional[Mapping] = None,
) -> RoleToolPolicy:
    data = get_tool_profiles()
    meta = persona_data.get("meta", {}) if isinstance(persona_data, Mapping) else {}
    scope = str(meta.get("scope") or "") if isinstance(meta, Mapping) else ""
    scope = scope or (resolve_persona_slug_scope(persona_filename) if persona_filename else "")
    defaults = data["defaults"]
    role = data.get("roles", {}).get(scope, {})
    mode_config = data.get("modes", {}).get(mode, {})
    resident = tuple(dict.fromkeys(role.get("resident", defaults.get("resident", [])) + mode_config.get("resident", [])))
    on_demand = tuple(mode_config.get("on_demand", role.get("on_demand", defaults.get("on_demand", []))))
    disabled = tuple(dict.fromkeys(defaults.get("disabled", []) + role.get("disabled", []) + mode_config.get("disabled", [])))
    return RoleToolPolicy(scope, resident, on_demand, disabled)


def select_role_tools(message: str, *, persona_filename: Optional[str] = None, mode: str = "chat", include_web_search: bool = True) -> list[str]:
    """首轮常驻加关键词命中；最终仍须经过现有人设权限和可用性过滤。"""
    policy = resolve_role_tool_policy(persona_filename, mode=mode)
    selected = list(policy.resident)
    lower = str(message or "").lower()
    for route in get_tool_profiles()["routes"]:
        if any(keyword.lower() in lower for keyword in route["keywords"]):
            selected.extend(route["tools"])
    return [name for name in dict.fromkeys(selected) if policy.allows(name) and (include_web_search or name != "web_search")]
