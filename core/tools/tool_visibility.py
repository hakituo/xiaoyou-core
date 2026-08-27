from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set


DEFAULT_HIDDEN_CATEGORIES: Set[str] = {"playset"}
DEFAULT_HIDDEN_TOOL_NAMES: Set[str] = {
    "list_playsets",
    "enable_playset",
    "disable_playset",
}


@dataclass(frozen=True)
class ToolVisibilityContext:
    """工具可见性上下文。"""

    persona_filename: str = ""
    mode: str = "chat"
    is_sensitive_mode: bool = False


@dataclass
class ToolVisibilityRules:
    """工具可见性规则集合。"""

    allow_names: Set[str] = field(default_factory=set)
    deny_names: Set[str] = field(default_factory=set)
    allow_categories: Set[str] = field(default_factory=set)
    deny_categories: Set[str] = field(default_factory=set)

    def merge(self, other: "ToolVisibilityRules") -> "ToolVisibilityRules":
        self.allow_names.update(other.allow_names)
        self.deny_names.update(other.deny_names)
        self.allow_categories.update(other.allow_categories)
        self.deny_categories.update(other.deny_categories)
        return self


def resolve_persona_filename(persona_filename: Optional[str] = None) -> str:
    """解析当前生效的人设文件名。"""
    explicit_filename = str(persona_filename or "").strip()
    if explicit_filename:
        return explicit_filename

    try:
        from core.character.managers.persona_manager import get_persona_manager

        pm = get_persona_manager()
        return str(pm.get_current_filename() or "").strip()
    except Exception:
        return ""


def resolve_persona_data(
    persona_filename: Optional[str] = None,
    persona_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """解析当前生效的人设配置。"""
    if isinstance(persona_data, dict) and persona_data:
        return persona_data

    effective_filename = resolve_persona_filename(persona_filename)
    try:
        from core.character.managers.persona_manager import get_persona_manager

        pm = get_persona_manager()
        if effective_filename:
            loaded = pm.get_persona_by_filename(effective_filename) or {}
        else:
            loaded = pm.get_current_persona() or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def build_visibility_context(
    persona_filename: Optional[str] = None,
    mode: Optional[str] = None,
    is_sensitive_mode: bool = False,
) -> ToolVisibilityContext:
    """构建工具可见性上下文。"""
    return ToolVisibilityContext(
        persona_filename=resolve_persona_filename(persona_filename),
        mode=str(mode or "chat").strip() or "chat",
        is_sensitive_mode=bool(is_sensitive_mode),
    )


def _normalize_string_set(values: Any) -> Set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {
        str(item).strip()
        for item in values
        if isinstance(item, (str, int, float)) and str(item).strip()
    }


def _rules_from_dict(raw_rules: Any) -> ToolVisibilityRules:
    if not isinstance(raw_rules, dict):
        return ToolVisibilityRules()
    return ToolVisibilityRules(
        allow_names=_normalize_string_set(raw_rules.get("allow_names")),
        deny_names=_normalize_string_set(raw_rules.get("deny_names")),
        allow_categories=_normalize_string_set(raw_rules.get("allow_categories")),
        deny_categories=_normalize_string_set(raw_rules.get("deny_categories")),
    )


def get_tool_access_config(persona_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """从人设配置中读取工具访问控制配置。"""
    if not isinstance(persona_data, dict):
        return {}

    tool_access = persona_data.get("tool_access")
    if isinstance(tool_access, dict):
        return tool_access

    interaction_logic = persona_data.get("interaction_logic")
    if isinstance(interaction_logic, dict):
        nested_access = interaction_logic.get("tool_access")
        if isinstance(nested_access, dict):
            return nested_access
    return {}


def get_effective_visibility_rules(
    context: ToolVisibilityContext,
    persona_data: Optional[Dict[str, Any]] = None,
) -> ToolVisibilityRules:
    """合并默认、人设、模式与 sensitive 的工具可见性规则。"""
    data = resolve_persona_data(context.persona_filename, persona_data)
    config = get_tool_access_config(data)

    rules = ToolVisibilityRules()
    rules.merge(_rules_from_dict(config))

    mode_rules = config.get("mode_rules")
    if isinstance(mode_rules, dict):
        rules.merge(_rules_from_dict(mode_rules.get(context.mode)))

    if context.is_sensitive_mode:
        rules.merge(_rules_from_dict(config.get("sensitive_mode")))

    return rules


def _resolve_tool_category(
    tool_name: str,
    tool_registry: Any = None,
) -> str:
    if tool_registry and hasattr(tool_registry, "get_tool"):
        tool = tool_registry.get_tool(tool_name)
        if tool is not None:
            return str(getattr(tool, "category", "") or "").strip()
    return ""


def filter_tool_names(
    tool_names: Iterable[str],
    *,
    tool_registry: Any = None,
    persona_filename: Optional[str] = None,
    persona_data: Optional[Dict[str, Any]] = None,
    mode: Optional[str] = None,
    is_sensitive_mode: bool = False,
) -> List[str]:
    """
    根据 persona / mode / sensitive 上下文过滤工具列表。

    设计原则：
    - 默认隐藏敏感能力类工具（当前为 intimate 分类）
    - persona 可通过 tool_access 显式放开或禁用工具/分类
    - mode_rules / sensitive_mode 可做上下文覆盖
    """
    context = build_visibility_context(
        persona_filename=persona_filename,
        mode=mode,
        is_sensitive_mode=is_sensitive_mode,
    )
    rules = get_effective_visibility_rules(context, persona_data=persona_data)

    default_hidden_categories = set(DEFAULT_HIDDEN_CATEGORIES)
    default_hidden_names = set(DEFAULT_HIDDEN_TOOL_NAMES)
    default_hidden_categories.difference_update(rules.allow_categories)
    default_hidden_names.difference_update(rules.allow_names)

    filtered_names: List[str] = []
    seen_names: Set[str] = set()
    for raw_name in tool_names:
        tool_name = str(raw_name).strip()
        if not tool_name or tool_name in seen_names:
            continue
        seen_names.add(tool_name)

        tool_category = _resolve_tool_category(tool_name, tool_registry=tool_registry)

        if tool_name in rules.deny_names:
            continue
        if tool_category and tool_category in rules.deny_categories:
            continue
        if not tool_category and tool_name in default_hidden_names:
            continue
        if tool_category and tool_category in default_hidden_categories:
            continue

        filtered_names.append(tool_name)

    return filtered_names
