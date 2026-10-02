#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证主对话工具 schema 按需注入与 prompt 去重优化。

运行：
    venv_core\Scripts\python.exe tests/scripts/prompt/verify_prompt_tool_schema_budget.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _schema_chars(items: list[dict]) -> int:
    return len(json.dumps(items, ensure_ascii=False, separators=(",", ":")))


def _build_registry():
    from core.tools.registry import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    return registry


def test_default_chat_schema_is_small() -> None:
    from core.agents.chat_agent_components.context_persona import select_message_tools
    from core.agents.chat_agent_components.streaming_pipeline.model_resolution import (
        prepare_native_tools,
    )

    registry = _build_registry()
    agent = SimpleNamespace(tool_registry=registry)
    all_schemas = registry.get_openai_tools(include_names=registry.get_active_tools())
    selected_names = select_message_tools("今天心情还不错", include_web_search=True, persona_filename="core_aveline.json")
    selected_schemas = prepare_native_tools(
        agent,
        persona_filename="core_aveline.json",
        is_sensitive_mode=False,
        use_server_side_search=False,
        active_tool_names=selected_names,
    )

    assert selected_schemas is not None
    # Aveline 常驻发现入口、待办与聊天记录搜索；同伴消息改为按需，时间、计算、语音亦按需。
    assert selected_names == [
        "search_tools", "manage_todo", "search_chat_history",
    ], selected_names
    assert len(selected_schemas) == 3, selected_names
    assert _schema_chars(selected_schemas) < _schema_chars(all_schemas) * 0.1
    print(
        "[OK] 普通闲聊工具 schema: "
        f"{len(all_schemas)} 个/{_schema_chars(all_schemas)} 字符 -> "
        f"{len(selected_schemas)} 个/{_schema_chars(selected_schemas)} 字符"
    )


def test_schema_budget_by_source() -> None:
    """按来源拆分常驻 schema：resident / route / carryover / discovery 各贡献多少。

    字符数只能近似归因——schema 由 Registry 按固定注册顺序整体生成，
    所以用相邻工具集合的差集算增量，不要去切最终 JSON 字符串。
    """
    from core.agents.chat_agent_components.context_persona import select_message_tools
    from core.tools.tool_carryover import ToolCarryoverManager, get_tool_carryover_manager
    from core.tools.tool_policy import resolve_role_tool_policy
    from core.tools.tool_visibility import filter_tool_names

    registry = _build_registry()
    persona = "core_aveline.json"
    message = "明天出门要不要带伞"

    def visible(names: list[str]) -> list[str]:
        return filter_tool_names(
            names, tool_registry=registry, persona_filename=persona, mode="chat"
        )

    def chars(names: list[str]) -> int:
        return _schema_chars(registry.get_openai_tools(include_names=list(names)))

    resident = visible(list(resolve_role_tool_policy(persona, mode="chat").resident))
    routed = visible(select_message_tools(message, persona_filename=persona))
    route_added = [name for name in routed if name not in resident]

    manager = get_tool_carryover_manager()
    manager.clear()
    try:
        key = ToolCarryoverManager.build_key("budget-probe", "aveline", "chat")
        manager.record(key, ["query_health_data"])
        carried = [name for name in manager.get(key) if name not in routed]
    finally:
        manager.clear()

    # discovery 用一个当前没被命中的工具模拟「模型搜出来之后追加」
    discovered = ["get_character_daily_plan"]

    base_chars = chars(resident)
    route_chars = chars([*resident, *route_added])
    carry_chars = chars([*resident, *route_added, *carried])
    discovery_chars = chars([*resident, *route_added, *carried, *discovered])

    assert route_chars >= base_chars
    assert carry_chars >= route_chars
    assert discovery_chars >= carry_chars
    print(
        "[OK] schema 来源拆分（aveline /「明天出门要不要带伞」）: "
        f"resident {len(resident)} 个/{base_chars} 字符, "
        f"route +{len(route_added)} 个/+{route_chars - base_chars} 字符, "
        f"carryover +{len(carried)} 个/+{carry_chars - route_chars} 字符, "
        f"discovery +{len(discovered)} 个/+{discovery_chars - carry_chars} 字符"
    )


def test_domain_routes_are_reachable() -> None:
    from core.agents.chat_agent_components.context_persona import select_message_tools

    cases = (
        ("算一下这笔费用", "calculator"),
        ("现在几点", "get_current_time"),
        ("请朗读这段话", "text_to_speech"),
        ("查一下最新消息", "web_search"),
        ("上海今天会下雨吗", "get_weather"),
        ("数学作业写完了", "mark_plan_item_status"),
        ("你还记得我之前说过什么吗", "search_chat_history"),
        ("看看我的手机应用使用时长", "get_app_usage_time"),
        ("最近的手表心率怎么样", "query_health_data"),
        ("半小时后提醒我喝水", "set_reminder"),
    )
    for message, expected in cases:
        selected = select_message_tools(message, include_web_search=True)
        assert expected in selected, (message, expected, selected)
        assert len(selected) == len(set(selected)), selected
    print(f"[OK] {len(cases)} 类常用意图均能路由到对应工具")


def test_all_routed_tools_exist() -> None:
    from config.tool_profiles import get_tool_profiles

    registry = _build_registry()
    registered = set(registry.get_active_tools())
    config = get_tool_profiles()
    routed = set(config["defaults"]["resident"])
    for route in config["routes"]:
        routed.update(route["tools"])
    for role in config["roles"].values():
        routed.update(role.get("resident", []))

    missing = sorted(routed - registered)
    assert not missing, f"路由引用了未注册工具: {missing}"
    print(f"[OK] 路由表引用的 {len(routed)} 个工具均已注册")


def test_server_side_search_removes_local_schema() -> None:
    from core.agents.chat_agent_components.context_persona import select_message_tools
    from core.agents.chat_agent_components.streaming_pipeline.model_resolution import (
        prepare_native_tools,
    )

    registry = _build_registry()
    agent = SimpleNamespace(tool_registry=registry)
    selected = select_message_tools("查一下最新消息", include_web_search=True)
    schemas = prepare_native_tools(
        agent,
        persona_filename="core_aveline.json",
        is_sensitive_mode=False,
        use_server_side_search=True,
        active_tool_names=selected,
    )
    names = {item["function"]["name"] for item in schemas or []}
    assert "web_search" not in names
    print("[OK] 服务端搜索启用时不会重复发送本地 web_search schema")


def main() -> int:
    tests = (
        test_default_chat_schema_is_small,
        test_schema_budget_by_source,
        test_domain_routes_are_reachable,
        test_all_routed_tools_exist,
        test_server_side_search_removes_local_schema,
    )
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"结果: {len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
