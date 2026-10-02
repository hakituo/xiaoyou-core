"""跨请求工具延续（carryover）的单元测试。

覆盖：TTL 以 request 为单位、按会话/角色/模式隔离、上限与淘汰、
search_tools 与常驻工具不占名额，以及「延续不是授权」。
"""

from __future__ import annotations

import pytest

from core.tools.tool_carryover import (
    ToolCarryoverManager,
    get_tool_carryover_manager,
    record_request_tools,
)


@pytest.fixture()
def manager() -> ToolCarryoverManager:
    return ToolCarryoverManager(max_tools=2, max_entries=3)


def test_ttl_is_one_request(manager: ToolCarryoverManager) -> None:
    """读一次就消耗掉，第三个请求不再继承。"""
    key = manager.build_key("conv1", "ling", "chat")
    manager.record(key, ["get_weather"])

    assert manager.get(key) == ["get_weather"]
    assert manager.get(key) == []
    assert manager.peek(key) == []


def test_key_isolates_conversation_persona_and_mode(manager: ToolCarryoverManager) -> None:
    """同一次工具使用不能串到别的会话、角色或模式。"""
    base = manager.build_key("conv1", "ling", "chat")
    manager.record(base, ["get_weather"])

    assert manager.get(manager.build_key("conv2", "ling", "chat")) == []
    assert manager.get(manager.build_key("conv1", "aveline", "chat")) == []
    assert manager.get(manager.build_key("conv1", "ling", "study")) == []
    assert manager.get(base) == ["get_weather"]


def test_max_tools_keeps_only_recent(manager: ToolCarryoverManager) -> None:
    """一个请求调用很多工具时只留最近两个，避免下一轮 schema 膨胀。"""
    key = manager.build_key("conv1", "ling", "chat")
    manager.record(key, ["get_weather", "calculator", "set_reminder"])
    assert manager.get(key) == ["get_weather", "calculator"]


def test_search_tools_never_carries(manager: ToolCarryoverManager) -> None:
    """发现器本身不参与延续，它每轮都在常驻里。"""
    key = manager.build_key("conv1", "ling", "chat")
    manager.record(key, ["search_tools", "get_weather"])
    assert manager.get(key) == ["get_weather"]


def test_resident_tools_can_be_excluded(manager: ToolCarryoverManager) -> None:
    """常驻工具下一轮本来就有，不该占用延续名额。"""
    key = manager.build_key("conv1", "ling", "chat")
    manager.record(key, ["manage_todo", "get_weather"], exclude=["manage_todo"])
    assert manager.get(key) == ["get_weather"]


def test_empty_record_clears_previous(manager: ToolCarryoverManager) -> None:
    """这一轮完全没用工具时，不应继续延续上一轮的结果。"""
    key = manager.build_key("conv1", "ling", "chat")
    manager.record(key, ["get_weather"])
    manager.record(key, [])
    assert manager.peek(key) == []


def test_missing_conversation_id_disables_carryover(manager: ToolCarryoverManager) -> None:
    """没有 conversation_id 时既不写也不读，避免跨会话共用状态。"""
    key = manager.build_key("", "ling", "chat")
    manager.record(key, ["get_weather"])
    assert manager.get(key) == []


def test_lru_eviction(manager: ToolCarryoverManager) -> None:
    """条目数超过上限时淘汰最旧的会话。"""
    keys = [manager.build_key(f"conv{i}", "ling", "chat") for i in range(4)]
    for index, key in enumerate(keys):
        manager.record(key, [f"tool_{index}"])

    assert len(manager) == 3
    assert manager.peek(keys[0]) == []
    assert manager.peek(keys[3]) == ["tool_3"]


def test_record_request_tools_resolves_persona_scope() -> None:
    """便捷入口按 persona 文件名解析稳定 scope 后再落表。"""
    manager = get_tool_carryover_manager()
    manager.clear()
    try:
        record_request_tools("conv-scope", "core_ling.json", "chat", ["get_weather"])
        key = ToolCarryoverManager.build_key("conv-scope", "ling", "chat")
        assert manager.peek(key) == ["get_weather"]
    finally:
        manager.clear()


def test_stats_track_opportunity_hit_rate(manager: ToolCarryoverManager) -> None:
    """统计口径：分母是「真的有工具可延续」的请求数，空记录不计入。"""
    key = manager.build_key("conv1", "ling", "chat")
    manager.record(key, ["get_weather"])
    manager.get(key)
    manager.record(key, [])

    stats = manager.stats()
    assert stats["recorded_requests"] == 1
    assert stats["hit_requests"] == 1
    assert stats["hit_tools"] == 1


def test_carryover_is_not_authorization() -> None:
    """延续只是候选名，最终仍要过 tool_visibility；被禁用的角色不会因此拿到工具。"""
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_visibility import filter_tool_names

    registry = ToolRegistry()
    register_all_tools(registry)

    # 叶的配置里 food 领域是禁用的
    visible = filter_tool_names(
        ["buy_food"],
        tool_registry=registry,
        persona_filename="core_ye.json",
        persona_data={"meta": {"scope": "ye"}},
    )
    assert visible == []

    # 同一份候选在允许它的角色下仍然可见
    visible_for_ling = filter_tool_names(
        ["buy_food"],
        tool_registry=registry,
        persona_filename="core_ling.json",
        persona_data={"meta": {"scope": "ling"}},
    )
    assert visible_for_ling == ["buy_food"]
