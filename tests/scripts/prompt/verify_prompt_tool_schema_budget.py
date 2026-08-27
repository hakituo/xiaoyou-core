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
    selected_names = select_message_tools("今天心情还不错", include_web_search=True)
    selected_schemas = prepare_native_tools(
        agent,
        persona_filename="qq/Aveline_QQ_Master.json",
        is_sensitive_mode=False,
        use_server_side_search=False,
        active_tool_names=selected_names,
    )

    assert selected_schemas is not None
    # 常驻 search_tools 负责兜底发现，其余仍保持极小基线。
    assert len(selected_schemas) <= 5, selected_names
    assert _schema_chars(selected_schemas) < _schema_chars(all_schemas) * 0.1
    print(
        "[OK] 普通闲聊工具 schema: "
        f"{len(all_schemas)} 个/{_schema_chars(all_schemas)} 字符 -> "
        f"{len(selected_schemas)} 个/{_schema_chars(selected_schemas)} 字符"
    )


def test_domain_routes_are_reachable() -> None:
    from core.agents.chat_agent_components.context_persona import select_message_tools

    cases = (
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
    from core.agents.chat_agent_components import context_persona

    registry = _build_registry()
    registered = set(registry.get_active_tools())
    routed = set(context_persona._BASE_TOOL_NAMES)
    for _, names in context_persona._MESSAGE_TOOL_ROUTES:
        routed.update(names)

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
        persona_filename="qq/Aveline_QQ_Master.json",
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
