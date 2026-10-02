"""验证角色工具配置、模式覆盖、发现与执行隔离，不调用真实外部工具。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from config import tool_profiles  # noqa: E402
from core.agents.chat_agent_components.context_persona import select_message_tools  # noqa: E402
from core.tools.base import BaseTool  # noqa: E402
from core.tools.execution import execute_tool_call  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402
from core.tools.tool_metadata import get_catalog_tool_names, get_tool_domain  # noqa: E402
from core.tools.tool_policy import resolve_role_tool_policy  # noqa: E402
from core.tools.tool_search_tool import SearchToolsTool  # noqa: E402
from core.tools.tool_visibility import filter_tool_names  # noqa: E402


def verify_config_and_selection():
    config = tool_profiles.get_tool_profiles()
    names = set(get_catalog_tool_names())
    selectors = []
    for entry in [config["defaults"], *config["roles"].values(), *config["modes"].values()]:
        for key in ("resident", "on_demand", "disabled"):
            selectors.extend(entry.get(key, []))
    for route in config["routes"]:
        selectors.extend(route["tools"])
    domains = {get_tool_domain(name) for name in names}
    assert all(name in names or name == "*" or name.removeprefix("domain:") in domains for name in selectors)
    todo_resident = ["manage_todo"]
    # 聊天记录搜索是所有角色常驻：回忆类请求说法太散，关键词路由漏召回率偏高
    history_resident = ["search_chat_history"]
    assert select_message_tools("嗯", persona_filename="core_ye.json") == [
        "search_tools", "update_character_state", *todo_resident, *history_resident,
    ]
    # 同伴消息改为按需：角色想找对方说话时再发现，不再每轮占用 schema
    assert select_message_tools("嗯", persona_filename="core_aveline.json") == [
        "search_tools", *todo_resident, *history_resident,
    ]
    # Aveline把待办当随手记想法的地方，改为按需：常驻里没有待办
    assert select_message_tools("嗯", persona_filename="core_ling.json") == [
        "search_tools", *history_resident,
    ]
    for name in ("get_current_time", "calculator", "text_to_speech", "web_search"):
        assert name not in select_message_tools("嗯", persona_filename="core_ye.json")
    assert "get_study_profile" in select_message_tools("嗯", persona_filename="core_ye.json", mode="study")
    print("[PASS] 全部配置引用有效，角色常驻独立，基础工具按需，学习模式覆盖")


def verify_reconfiguration():
    config = deepcopy(tool_profiles.get_tool_profiles())
    # 不修改Python即可给一个既有角色定义全新工具范围。
    config["roles"]["ye"] = {"resident": ["search_tools", "calculator"], "on_demand": ["domain:information"], "disabled": ["get_weather"]}
    with patch("core.tools.tool_policy.get_tool_profiles", return_value=config):
        assert select_message_tools("嗯", persona_filename="core_ye.json") == ["search_tools", "calculator"]
        policy = resolve_role_tool_policy("core_ye.json")
        assert policy.allows("web_search") and not policy.allows("get_weather")
        assert not policy.allows("update_character_state") and not policy.allows("set_reminder")
        assert filter_tool_names(["calculator", "web_search", "set_reminder"], persona_filename="core_ye.json") == ["calculator", "web_search"]
        assert not filter_tool_names(["calculator"], persona_filename="core_ye.json", persona_data={"tool_access": {"deny_names": ["calculator"]}})
        assert select_message_tools("嗯", persona_filename="core_ling.json") == [
            "search_tools", "search_chat_history",
        ]
    # 文件热更新生效；损坏配置不能默默放开全部能力。
    with tempfile.TemporaryDirectory(prefix="tool_profile_") as directory:
        path = Path(directory) / "profiles.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with patch.object(tool_profiles, "CONFIG_PATH", path):
            assert tool_profiles.get_tool_profiles()["roles"]["ye"]["resident"][-1] == "calculator"
            config["roles"]["ye"]["resident"] = ["search_tools"]
            path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            assert tool_profiles.get_tool_profiles()["roles"]["ye"]["resident"] == ["search_tools"]
            path.write_text("{}", encoding="utf-8")
            try:
                tool_profiles.get_tool_profiles()
            except ValueError:
                pass
            else:
                raise AssertionError("无效配置未被拒绝")
    print("[PASS] 仅修改配置即可调整角色工具，禁用优先、其他角色不受影响，支持热更新")


async def verify_execution():
    class Probe(BaseTool):
        name = "calculator"
        description = "测试上下文隔离"

        async def _run(self):
            await asyncio.sleep(0)
            return self._get_ctx("persona_filename")

    registry = ToolRegistry()
    registry.register(Probe())
    registry.register(SearchToolsTool())
    agent = SimpleNamespace(tool_registry=registry)
    async def run(persona, allowed):
        return await execute_tool_call(agent=agent, tool_name="calculator", arguments={}, user_id="test", allowed_tool_names=allowed, persona_filename=persona)
    result = await asyncio.gather(run("core_ye.json", ["calculator"]), run("core_ling.json", ["calculator"]))
    assert result == ["core_ye.json", "core_ling.json"]
    assert not hasattr(registry.get_tool("calculator"), "_runtime_context")
    assert not json.loads(await run("core_ye.json", []))["ok"]
    registry.disable_tool("calculator")
    assert not json.loads(await run("core_ye.json", ["calculator"]))["ok"]
    result = await execute_tool_call(agent=agent, tool_name="search_tools", arguments={"query": "计算器"}, user_id="test", allowed_tool_names=["search_tools"], persona_filename="core_ye.json")
    assert not json.loads(result)["tools"]
    print("[PASS] 执行端拒绝越权和停用工具，共享工具实现不共享角色上下文，发现不扩权")


def main():
    verify_config_and_selection()
    verify_reconfiguration()
    asyncio.run(verify_execution())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
