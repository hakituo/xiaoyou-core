"""验证 read_daily_summary / read_monthly_summary 工具能正常读取总结

用法：
    d:\\AI\\xiaoyou-core\\venv_core\\scripts\\python.exe ^
        tests\\scripts\\journal\\verify_summary_tools.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> int:
    from core.tools.registry import register_all_tools, ToolRegistry

    registry = ToolRegistry()
    register_all_tools(registry)

    # 1. read_monthly_summary：默认读上月（6月）
    print("\n" + "=" * 60)
    print("  read_monthly_summary() —— 默认上月")
    print("=" * 60)
    tool_monthly = registry.get_tool("read_monthly_summary")
    out1 = await tool_monthly.run()
    print(out1)

    # 2. read_monthly_summary：指定 2026-06
    print("\n" + "=" * 60)
    print("  read_monthly_summary(month='2026-06')")
    print("=" * 60)
    out2 = await tool_monthly.run(month="2026-06")
    print(out2)

    # 3. read_monthly_summary：指定不存在的月份 2026-01
    print("\n" + "=" * 60)
    print("  read_monthly_summary(month='2026-01') —— 不存在")
    print("=" * 60)
    out3 = await tool_monthly.run(month="2026-01")
    print(out3)

    # 4. read_daily_summary：默认今天
    print("\n" + "=" * 60)
    print("  read_daily_summary() —— 默认今天")
    print("=" * 60)
    tool_daily = registry.get_tool("read_daily_summary")
    out4 = await tool_daily.run()
    print(out4)

    # 5. read_daily_summary：指定 2026-06-30
    print("\n" + "=" * 60)
    print("  read_daily_summary(date='2026-06-30')")
    print("=" * 60)
    out5 = await tool_daily.run(date="2026-06-30")
    print(out5)

    # 6. read_daily_summary：days_back=3，从 6/30 往前 3 天
    print("\n" + "=" * 60)
    print("  read_daily_summary(date='2026-06-30', days_back=3)")
    print("=" * 60)
    out6 = await tool_daily.run(date="2026-06-30", days_back=3)
    print(out6)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
