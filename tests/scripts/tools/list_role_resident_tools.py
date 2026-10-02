"""列出每个角色/模式的常驻工具策略与过滤后实际生效结果。

只读脚本，不写任何状态。用途：改完 config/tool_profiles.json 后快速确认
「谁常驻了什么、谁被权限过滤掉了」。

运行：
    venv_core/Scripts/python.exe tests/scripts/tools/list_role_resident_tools.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_registry():
    from core.tools.registry import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    return registry


def main() -> int:
    from core.tools.tool_policy import resolve_role_tool_policy
    from core.tools.tool_visibility import filter_tool_names
    from core.utils.data.scope_registry import resolve_persona_slug_scope

    registry = _build_registry()

    profiles = json.loads(
        (PROJECT_ROOT / "config" / "tool_profiles.json").read_text(encoding="utf-8")
    )
    scopes = ["<defaults>"] + sorted(profiles.get("roles", {}))
    modes = ["chat", "study"]

    for scope in scopes:
        persona_filename = "" if scope == "<defaults>" else scope
        if persona_filename and resolve_persona_slug_scope(persona_filename) != scope:
            print(f"[warn] 无法把 {scope!r} 解析回同名 scope，适用性过滤可能不准")
        persona_data = {} if scope == "<defaults>" else {"meta": {"scope": scope}}
        print(f"\n=== {scope} ===")
        for mode in modes:
            policy = resolve_role_tool_policy(
                persona_filename or None, mode=mode, persona_data=persona_data
            )
            effective = filter_tool_names(
                list(policy.resident),
                tool_registry=registry,
                persona_filename=persona_filename or None,
                persona_data=persona_data,
                mode=mode,
            )
            dropped = [n for n in policy.resident if n not in effective]
            print(f"  [{mode}] 常驻 {len(effective)} 个: {', '.join(effective)}")
            if dropped:
                print(f"         被过滤: {', '.join(dropped)}")

    print("\n=== update_character_state 各角色可用性 ===")
    tool = registry.get_tool("update_character_state")
    availability = getattr(tool, "is_available_for_persona", None)
    for scope in [s for s in scopes if s != "<defaults>"]:
        state = (
            "可用"
            if callable(availability) and availability(scope)
            else "不可用（被适用性过滤）"
        )
        print(f"  {scope}: {state}")

    print(f"\n注册表共 {len(registry.list_tools())} 个工具，活跃 {len(registry.get_active_tools())} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
