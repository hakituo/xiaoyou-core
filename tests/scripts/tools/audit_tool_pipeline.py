"""工具管线确定性审计：route → carryover → search_tools → visibility。

不调用 LLM / 网络，只跑确定性层，本地和 CI 都能执行。
每例输出 direct_route / carryover / search_rank / final_available / extra_rounds，
并汇总 Direct Hit Rate、Discovery Recall@3、Final Availability Rate、
Carryover Opportunity Hit Rate、Discovery Avoided。

运行：
    venv_core/Scripts/python.exe tests/scripts/tools/audit_tool_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

AVELINE = "core_aveline.json"
YE = "core_ye.json"


@dataclass
class Case:
    group: str
    turn1: str
    turn1_tool: str
    turn2: str = ""
    turn2_tool: str = ""
    persona: str = AVELINE
    # 期望最终可见性：权限切换用例期望「被过滤掉」，不能算失败
    expect_visible: bool = True


# A 独立明确请求：期望直接 route 命中
CASES_A = [
    Case("A", "现在几点", "get_current_time"),
    Case("A", "算一下123*456", "calculator"),
    Case("A", "明天重庆天气怎么样", "get_weather"),
    Case("A", "半小时后提醒我喝水", "set_reminder"),
]

# B 独立自然语言请求：route 或 search 命中即可
CASES_B = [
    Case("B", "明天出门要不要带伞", "get_weather"),
    Case("B", "看看我今天走了多少步", "query_health_data"),
    Case("B", "把手机桌面换一下", "set_wallpaper"),
    # 这条刻意不用任何路由关键词，只能靠 search_tools 兜底，用来观测 discovery 质量
    Case("B", "帮我把微信打开", "start_app"),
]

# C 连续 follow-up：第二轮应靠 carryover 直接拿到工具
CASES_C = [
    Case("C", "明天天气怎么样", "get_weather", "那后天呢", "get_weather"),
    Case("C", "看看我最近步数", "query_health_data", "那昨天呢", "query_health_data"),
    Case(
        "C", "查一下之前聊过的那个显示器", "search_chat_history",
        "那再找找我们说过ROG的", "search_chat_history",
    ),
]

# D 话题切换：carryover 可以还在，但不能妨碍新话题正确召回
CASES_D = [
    Case("D", "明天天气怎么样", "get_weather", "对了我数学作业写完了", "mark_plan_item_status"),
]

# E 权限切换：叶的 carryover 里有 buy_food，也必须被过滤掉
CASES_E = [
    Case("E", "买点吃的", "buy_food", "再买一份", "buy_food", persona=YE, expect_visible=False),
]


def _simulate(
    *, agent, registry, message: str, persona: str, user_id: str, mode: str = "chat"
) -> dict:
    """模拟一轮确定性选择：route → carryover，再判断 discovery 与最终可用性。

    同时给出不含 carryover 的 route 结果，否则无法区分「这轮是路由命中」
    还是「靠上一轮延续拿到」。
    """
    from core.agents.chat_agent_components.context_persona import (
        prepare_active_tools,
        select_message_tools,
    )
    from core.tools.tool_visibility import filter_tool_names

    route_only = select_message_tools(
        message, mode=mode, include_web_search=True, persona_filename=persona
    )
    active = asyncio.run(
        prepare_active_tools(agent, message, None, persona_filename=persona, user_id=user_id)
    )
    visible = filter_tool_names(
        active,
        tool_registry=registry,
        persona_filename=persona,
        mode=mode,
    )
    return {"route_only": list(route_only), "active": list(active), "visible": visible}


def _search_rank(registry, query: str, allowed: list[str], target: str) -> int:
    """目标工具在 search_tools 结果里的排名，未进入返回 0。"""
    matches = registry.search_tools(query, include_names=allowed, limit=8)
    for index, item in enumerate(matches, start=1):
        if item.name == target:
            return index
    return 0


def main() -> int:
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_carryover import (
        ToolCarryoverManager,
        get_tool_carryover_manager,
        record_request_tools,
    )

    registry = ToolRegistry()
    register_all_tools(registry)
    agent = SimpleNamespace()
    manager = get_tool_carryover_manager()

    stats = {
        "a_total": 0, "a_direct": 0,
        "search_total": 0, "search_top3": 0,
        "total": 0, "final_ok": 0,
        "followup_eligible": 0, "followup_reused": 0, "discovery_avoided": 0,
        "extra_rounds": 0,
    }
    rows: list[str] = []

    def run_case(case: Case, index: int) -> None:
        user_id = f"audit_{case.group}_{index}"
        manager.clear()

        first = _simulate(
            agent=agent, registry=registry, message=case.turn1,
            persona=case.persona, user_id=user_id,
        )
        direct = case.turn1_tool in first["route_only"]
        # 第一轮真正执行了目标工具后落 carryover
        record_request_tools(user_id, case.persona, "chat", [case.turn1_tool])

        stats["total"] += 1
        if case.group == "A":
            stats["a_total"] += 1
            stats["a_direct"] += int(direct)

        if not case.turn2:
            final_ok = (case.turn1_tool in first["visible"]) == case.expect_visible
            stats["final_ok"] += int(final_ok)
            rank = 0
            if not direct:
                stats["search_total"] += 1
                rank = _search_rank(registry, case.turn1, first["visible"], case.turn1_tool)
                stats["search_top3"] += int(0 < rank <= 3)
                stats["extra_rounds"] += 1
            rows.append(
                f"  [{case.group}] {case.turn1!r} -> {case.turn1_tool}\n"
                f"       direct_route={direct} carryover=False search_rank={rank} "
                f"final_visible={case.turn1_tool in first['visible']} "
                f"as_expected={final_ok} extra_rounds={0 if direct else 1}"
            )
            return

        second = _simulate(
            agent=agent, registry=registry, message=case.turn2,
            persona=case.persona, user_id=user_id,
        )
        route_hit_2 = case.turn2_tool in second["route_only"]
        carried = (not route_hit_2) and case.turn2_tool in second["active"]
        final_ok = (case.turn2_tool in second["visible"]) == case.expect_visible
        stats["final_ok"] += int(final_ok)
        stats["followup_eligible"] += 1

        rank = 0
        if carried:
            stats["followup_reused"] += 1
            stats["discovery_avoided"] += 1
            extra = 0
        elif route_hit_2:
            # 路由已经命中，不需要再走 discovery
            extra = 0
        else:
            stats["search_total"] += 1
            rank = _search_rank(registry, case.turn2, second["visible"], case.turn2_tool)
            stats["search_top3"] += int(0 < rank <= 3)
            extra = 1
            stats["extra_rounds"] += 1

        rows.append(
            f"  [{case.group}] {case.turn2!r} (上一轮 {case.turn1_tool})\n"
            f"       direct_route={route_hit_2} "
            f"carryover={carried} search_rank={rank} "
            f"final_visible={case.turn2_tool in second['visible']} "
            f"as_expected={final_ok} extra_rounds={extra}"
        )

    for cases in (CASES_A, CASES_B, CASES_C, CASES_D, CASES_E):
        for index, case in enumerate(cases):
            run_case(case, index)

    print("=" * 74)
    print("工具管线确定性审计（route → carryover → search_tools → visibility）")
    print("=" * 74)
    print("\n逐例结果")
    print("\n".join(rows))

    def _rate(hit: int, total: int) -> str:
        return f"{hit / total:.0%}" if total else "n/a"

    print("\n指标")
    print(f"  Direct Hit Rate            {stats['a_direct']}/{stats['a_total']}  "
          f"({_rate(stats['a_direct'], stats['a_total'])})")
    print(f"  Discovery Recall@3         {stats['search_top3']}/{stats['search_total']}  "
          f"({_rate(stats['search_top3'], stats['search_total'])})")
    print(f"  Final Availability Rate    {stats['final_ok']}/{stats['total']}  "
          f"({_rate(stats['final_ok'], stats['total'])})")
    print(f"  Carryover Opportunity Hit  {stats['followup_reused']}/{stats['followup_eligible']}  "
          f"({_rate(stats['followup_reused'], stats['followup_eligible'])})")
    print(f"  Discovery Avoided          {stats['discovery_avoided']}")
    print(f"  Extra LLM Rounds           {stats['extra_rounds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
