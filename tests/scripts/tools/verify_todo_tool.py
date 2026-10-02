#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证待办工具：每个角色一份清单、单工具常驻、执行链路可用、prompt 注入有效。

运行：
    venv_core\Scripts\python.exe tests/scripts/tools/verify_todo_tool.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from config import tool_profiles  # noqa: E402
from core.services.workspace.todo_store import TodoStore  # noqa: E402
from core.tools.execution import execute_tool_call  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402
from core.tools.todo_tool import ManageTodoTool  # noqa: E402


# Aveline把待办当成随手记想法的地方，五分钟内灌进七条且从不关闭，
# 因此改为按需：不再常驻，只保留关键词路由与 search_tools 两条发现路径。
ROLES_WITHOUT_TODO_RESIDENT = {"ling"}


def verify_resident_for_every_role() -> None:
    config = tool_profiles.get_tool_profiles()
    assert "manage_todo" in config["defaults"]["resident"], config["defaults"]["resident"]
    missing = [
        scope for scope, role in config["roles"].items()
        if scope not in ROLES_WITHOUT_TODO_RESIDENT
        and "manage_todo" not in role.get("resident", [])
    ]
    assert not missing, missing
    # 只读一个工具常驻，避免每轮多付几份 schema
    stale = [
        name for name in ("get_todo_list", "add_todo_item", "update_todo_item", "remove_todo_item")
        if name in config["defaults"]["resident"]
    ]
    assert not stale, stale
    print(f"[PASS] {len(config['roles'])} 个角色 + 默认配置只常驻 manage_todo 一个工具")


def verify_on_demand_roles_still_reachable() -> None:
    """不常驻的角色必须仍能通过路由召回或搜索发现，否则等于关掉这个能力。"""
    from core.tools.tool_policy import resolve_role_tool_policy

    config = tool_profiles.get_tool_profiles()
    routes = [
        route for route in config["routes"] if "manage_todo" in route["tools"]
    ]
    assert routes, "缺少待办关键词路由，不常驻的角色将无法召回 manage_todo"
    for scope in sorted(ROLES_WITHOUT_TODO_RESIDENT):
        policy = resolve_role_tool_policy(scope, mode="chat")
        assert "manage_todo" not in policy.resident, (scope, policy.resident)
        assert policy.allows("manage_todo"), f"{scope} 不常驻待办后仍须按需可用"
    print(f"[PASS] {', '.join(sorted(ROLES_WITHOUT_TODO_RESIDENT))} 不常驻待办，"
          f"但有 {len(routes)} 条关键词路由兜底")


def verify_store_is_role_scoped() -> None:
    with tempfile.TemporaryDirectory(prefix="verify_todo_") as directory:
        root = Path(directory)
        with patch("core.services.workspace.todo_store.get_role_data_dir") as get_dir:
            get_dir.side_effect = lambda scope: root / f"{scope}_data"
            aveline = TodoStore("aveline")
            ling = TodoStore("ling")
        assert aveline.file_path.parent.name == "aveline_data", aveline.file_path
        assert ling.file_path.parent.name == "ling_data", ling.file_path
        assert aveline.file_path != ling.file_path

        aveline.add_item("Aveline记的事")
        assert aveline.count_pending() == 1
        assert ling.count_pending() == 0, "另一个角色不应看到Aveline记的待办"
    print("[PASS] 待办按角色目录隔离，Aveline记的只有Aveline看得到")


def verify_discovery_by_search() -> None:
    from core.tools.tool_search_tool import SearchToolsTool

    registry = ToolRegistry()
    registry.register(ManageTodoTool())
    allowed = ["search_tools", "manage_todo"]
    tool = SearchToolsTool()
    tool.set_runtime_context({
        "agent": SimpleNamespace(tool_registry=registry),
        "allowed_tool_names": allowed,
    })
    for query in ("帮我记一下明天要交作业", "作业写完了，划掉吧", "现在还有什么没做的"):
        names = [
            item.name
            for item in registry.search_tools(query, include_names=allowed, limit=5)
        ]
        assert names[:1] == ["manage_todo"], (query, names)
    print("[PASS] 待办意图能被 search_tools 命中")


def _call(registry: ToolRegistry, arguments: dict, persona: str, allowed=None):
    return asyncio.run(execute_tool_call(
        agent=SimpleNamespace(tool_registry=registry),
        tool_name="manage_todo",
        arguments=arguments,
        user_id="verify_todo",
        allowed_tool_names=allowed if allowed is not None else ["manage_todo"],
        persona_filename=persona,
    ))


def verify_execution_chain() -> None:
    registry = ToolRegistry()
    registry.register(ManageTodoTool())
    persona = "core/character/configs/core_aveline.json"

    with tempfile.TemporaryDirectory(prefix="verify_todo_") as directory:
        root = Path(directory)
        with patch("core.services.workspace.todo_store.get_role_data_dir") as get_dir:
            get_dir.side_effect = lambda scope: root / f"{scope}_data"
            assert "现在没有待办" in _call(registry, {"action": "list"}, persona)

            added = _call(registry, {"action": "add", "title": "交数学作业"}, persona)
            assert "交数学作业" in added, added

            # 换个角色看：看不到Aveline记的这条
            ye_persona = "core/character/configs/ye/core_ye.json"
            assert "现在没有待办" in _call(registry, {"action": "list"}, ye_persona)

            listed = _call(registry, {"action": "list"}, persona)
            assert "待办 1 条" in listed, listed

            done = _call(registry, {"action": "done", "item_id": "1"}, persona)
            assert "已划掉" in done, done
            assert "现在没有待办" in _call(registry, {"action": "list"}, persona)

            removed = _call(registry, {"action": "remove", "item_id": "1"}, persona)
            assert "删掉了" in removed, removed

        denied = _call(registry, {"action": "add", "title": "不该被记下"}, persona, allowed=["search_tools"])
        assert "未获准" in denied, denied
        assert not (root / "aveline_data" / "todo_list.json").exists()
    print("[PASS] 记一条→划掉→删除全链路可用，角色之间互不可见，越权被拒")


def verify_prompt_injection() -> None:
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        build_todo_context,
    )

    persona = "core/character/configs/core_aveline.json"
    ye_persona = "core/character/configs/ye/core_ye.json"
    with tempfile.TemporaryDirectory(prefix="verify_todo_") as directory:
        aveline_store = TodoStore(file_path=Path(directory) / "aveline_todo.json")
        ye_store = TodoStore(file_path=Path(directory) / "ye_todo.json")
        with patch("core.services.workspace.todo_store.get_todo_store") as getter:
            getter.side_effect = lambda scope: aveline_store if scope == "aveline" else ye_store
            assert build_todo_context(persona) == "", "没有待办时不应注入任何内容"
            aveline_store.add_item("交数学作业")
            aveline_store.add_item("买牛奶")
            ye_store.add_item("叶自己的事")
            text = build_todo_context(persona)
            other = build_todo_context(ye_persona)
        assert "当前待办 2 条" in text, text
        assert "叶自己的事" not in text, text
        assert "manage_todo" in text, text
        assert text.startswith("<system-reminder>") and text.endswith("</system-reminder>")
        assert "叶自己的事" in other and "交数学作业" not in other, other
    print("[PASS] 有待办才注入 system-reminder，且只注入当前角色那份")


def main() -> int:
    verify_resident_for_every_role()
    verify_on_demand_roles_still_reachable()
    verify_store_is_role_scoped()
    verify_discovery_by_search()
    verify_execution_chain()
    verify_prompt_injection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
