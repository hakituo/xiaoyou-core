#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证工具发现元数据、权限内检索和两阶段 schema 扩展。

运行：
    venv_core\Scripts\python.exe tests/scripts/prompt/verify_tool_discovery_metadata.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _build_registry():
    from core.tools.registry import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    return registry


def test_catalog_covers_registry_once() -> None:
    from core.tools.tool_metadata import get_catalog_tool_names

    registry = _build_registry()
    registered_names = {tool.name for tool in registry.list_tools()}
    catalog_names = list(get_catalog_tool_names())
    duplicate_names = sorted(
        name for name, count in Counter(catalog_names).items() if count > 1
    )
    assert not duplicate_names, duplicate_names
    assert registered_names == set(catalog_names), {
        "missing": sorted(registered_names - set(catalog_names)),
        "stale": sorted(set(catalog_names) - registered_names),
    }

    metadata = registry.list_tool_metadata(include_names=list(registered_names))
    assert len(metadata) == len(registered_names)
    assert all(item.short_description and len(item.short_description) <= 60 for item in metadata)
    assert all(item.tags for item in metadata)
    domain_counts = Counter(item.domain for item in metadata)
    assert max(domain_counts.values()) <= 8, domain_counts
    print(
        f"[OK] {len(metadata)} 个工具全部有发现元数据，"
        f"共 {len(domain_counts)} 个领域，最大领域 {max(domain_counts.values())} 个工具"
    )


def test_search_quality_for_unrouted_phrases() -> None:
    registry = _build_registry()
    available = registry.get_active_tools()
    cases = (
        ("帮我看看手机里安装了哪些应用", "list_installed_apps"),
        ("把桌面壁纸换一下", "set_wallpaper"),
        ("我想找以前聊过的内容", "search_chat_history"),
        ("记住我以后不喝咖啡", "record_preference"),
        ("给另一个角色发个消息", "message_peer"),
        ("看看最近心率和步数", "query_health_data"),
        ("半小时后提醒我喝水", "set_reminder"),
    )
    for query, expected in cases:
        names = [
            item.name
            for item in registry.search_tools(query, include_names=available, limit=5)
        ]
        assert expected in names[:3], (query, expected, names)
    print(f"[OK] {len(cases)} 类自然语言请求可在前三个候选中发现目标工具")


def test_search_respects_allowed_names() -> None:
    from core.tools.tool_search_tool import SearchToolsTool

    registry = _build_registry()
    tool = SearchToolsTool()
    tool.set_runtime_context({
        "agent": SimpleNamespace(tool_registry=registry),
        "allowed_tool_names": ["search_tools", "calculator"],
    })
    result = asyncio.run(tool.run(query="把桌面壁纸换一下", limit=5))
    payload = json.loads(result)
    returned_names = {item["name"] for item in payload["tools"]}
    assert returned_names <= {"calculator"}, returned_names
    assert "set_wallpaper" not in returned_names
    print("[OK] search_tools 只返回当前人设权限内的工具")


def test_discovery_expands_only_returned_schemas() -> None:
    from core.agents.chat_agent_components.streaming_pipeline.tag_stream_parser import (
        StreamTagSession,
    )

    registry = _build_registry()
    allowed_names = ["search_tools", "get_current_time", "set_wallpaper"]
    search_tool = registry.get_tool("search_tools")
    assert search_tool is not None
    search_tool.set_runtime_context({
        "agent": SimpleNamespace(tool_registry=registry),
        "allowed_tool_names": allowed_names,
    })
    result = asyncio.run(search_tool.run(query="更换桌面壁纸", limit=5))

    session = StreamTagSession(
        agent=SimpleNamespace(tool_registry=registry),
        user_id="verify",
        is_sensitive_mode=False,
        messages=[],
        model_path="verify",
        allowed_tool_names=allowed_names,
    )
    session._record_discovered_tools("search_tools", result)
    assert session.discovered_tool_names == ["set_wallpaper"], session.discovered_tool_names

    baseline = registry.get_openai_tools(
        include_names=["search_tools", "get_current_time"]
    )
    expanded = registry.get_openai_tools(
        include_names=["search_tools", "get_current_time", *session.discovered_tool_names]
    )
    expanded_names = {item["function"]["name"] for item in expanded}
    assert expanded_names == {"search_tools", "get_current_time", "set_wallpaper"}
    assert len(expanded) == len(baseline) + 1
    print("[OK] 工具发现后只追加命中的 schema，不回退到全量注入")


def main() -> int:
    tests = (
        test_catalog_covers_registry_once,
        test_search_quality_for_unrouted_phrases,
        test_search_respects_allowed_names,
        test_discovery_expands_only_returned_schemas,
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
