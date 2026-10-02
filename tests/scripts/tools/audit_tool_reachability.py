"""审计每个工具的可达性：模型到底有没有路径能看到它。

只读脚本，不写任何状态。改完 config/tool_profiles.json 或 core/tools/tool_metadata.py
后重跑，可快速发现「注册了但永远触达不到」的僵尸工具。

分类口径：
  A 常驻       —— 至少一个角色/模式把它列进 resident
  B 关键词路由 —— 至少一条 route 会召回它（仍需通过角色授权）
  C 仅可搜索   —— 不在 A/B，但在发现目录里，可被 search_tools 检索到
  D 不可达     —— 三条路都没有，模型永远看不到，等同于死代码

运行：
    venv_core/Scripts/python.exe tests/scripts/tools/audit_tool_reachability.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_metadata import get_catalog_tool_names
    from core.tools.tool_policy import resolve_role_tool_policy
    from core.tools.tool_visibility import filter_tool_names

    registry = ToolRegistry()
    register_all_tools(registry)

    profiles = json.loads(
        (PROJECT_ROOT / "config" / "tool_profiles.json").read_text(encoding="utf-8")
    )
    scopes = ["<defaults>"] + sorted(profiles.get("roles", {}))
    modes = ["chat", "study"]

    route_tools: dict[str, list[str]] = {}
    for route in profiles.get("routes", []):
        for name in route.get("tools", []):
            route_tools.setdefault(name, []).append(route["keywords"][0])

    catalog_names = set(get_catalog_tool_names())
    registered_names = {t.name for t in registry.list_tools()}

    resident_map: dict[str, set[str]] = {}
    allowed_map: dict[str, set[str]] = {}
    for scope in scopes:
        persona_filename = "" if scope == "<defaults>" else scope
        persona_data = {} if scope == "<defaults>" else {"meta": {"scope": scope}}
        resident: set[str] = set()
        allowed: set[str] = set()
        for mode in modes:
            policy = resolve_role_tool_policy(
                persona_filename or None, mode=mode, persona_data=persona_data
            )
            resident.update(policy.resident)
            # 该角色/模式下「理论上可用」= 通过策略授权
            allowed.update(n for n in registered_names if policy.allows(n))
        # 再叠加可见性：人设权限与角色适用性
        allowed = set(
            filter_tool_names(
                sorted(allowed),
                tool_registry=registry,
                persona_filename=persona_filename or None,
                persona_data=persona_data,
            )
        )
        resident_map[scope] = set(
            filter_tool_names(
                sorted(resident),
                tool_registry=registry,
                persona_filename=persona_filename or None,
                persona_data=persona_data,
            )
        )
        allowed_map[scope] = allowed

    print("=" * 78)
    print(f"注册表 {len(registered_names)} 个工具 | 发现目录 {len(catalog_names)} 个")
    print("=" * 78)

    only_registered = sorted(registered_names - catalog_names)
    only_catalog = sorted(catalog_names - registered_names)
    if only_registered:
        print(f"\n[!] 已注册但不在发现目录（search_tools 搜不到）: {', '.join(only_registered)}")
    if only_catalog:
        print(f"\n[!] 在发现目录但未注册（搜到了也执行不了）: {', '.join(only_catalog)}")

    buckets: dict[str, list[str]] = {"A": [], "B": [], "C": [], "D": []}
    detail: dict[str, str] = {}
    for name in sorted(registered_names):
        meta = registry.get_tool_metadata(name)
        domain = meta.domain if meta else "无元数据"
        resident_scopes = [s for s in scopes if name in resident_map[s]]
        route_hit = name in route_tools
        in_catalog = name in catalog_names

        if resident_scopes:
            bucket = "A"
        elif route_hit:
            bucket = "B"
        elif in_catalog:
            bucket = "C"
        else:
            bucket = "D"
        buckets[bucket].append(name)

        usable_scopes = [s for s in scopes if name in allowed_map[s]]
        flags = []
        if not in_catalog:
            flags.append("搜索不可见")
        if not usable_scopes:
            flags.append("无角色可用")
        detail[name] = (
            f"  领域={domain:<14} 常驻={','.join(resident_scopes) or '-':<10}"
            f" 路由={'有' if route_hit else '无'} 可用角色数={len(usable_scopes)}"
            + (f"  [{' '.join(flags)}]" if flags else "")
        )

    labels = {
        "A": "A 常驻（每轮直接发 schema）",
        "B": "B 关键词路由可召回",
        "C": "C 仅 search_tools 可发现",
        "D": "D 完全不可达（僵尸）",
    }
    for key in ("A", "B", "C", "D"):
        print(f"\n{labels[key]}  —— {len(buckets[key])} 个")
        for name in buckets[key]:
            print(f"  - {name}")
            print(detail[name])

    # 默认隐藏类目（scene）只在人设显式 allow_categories 后才可见，
    # 这里用真实的 sensitive 人设样本确认它们不是死代码。
    sensitive_samples = {
        "Ling_love": {"meta": {"scope": "ling"}, "tool_access": {"allow_categories": ["scene"]}},
        "Mian": {"meta": {"scope": "mianmian"}, "tool_access": {"allow_categories": ["scene"]}},
    }
    print("\n默认隐藏类目（scene）在 sensitive 人设下的可见性")
    for label, persona_data in sensitive_samples.items():
        visible = filter_tool_names(
            ["list_scenes", "enable_scene", "disable_scene"],
            tool_registry=registry,
            persona_data=persona_data,
            is_sensitive_mode=True,
        )
        print(f"  {label}: {', '.join(visible) if visible else '全部不可见'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
