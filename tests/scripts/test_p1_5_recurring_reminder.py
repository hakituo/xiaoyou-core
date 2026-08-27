# -*- coding: utf-8 -*-
"""P1-5 周期提醒功能验证脚本"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录（脚本在 tests/scripts/ 下，需要回退两层）
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from core.tools.reminder_tool import (
    ReminderTool, _parse_weekdays, _parse_time_of_day, _compute_first_trigger_ts
)
from core.services.workspace.reminder_service import _compute_next_trigger_ts


def test_unit():
    """单元测试：解析函数和滚动计算"""
    print("=== 测试 weekdays 解析 ===")
    assert _parse_weekdays("1,3,5") == [1, 3, 5], "1,3,5 失败"
    assert _parse_weekdays("周一,周三,周五") == [1, 3, 5], "中文失败"
    assert _parse_weekdays("工作日") == [1, 2, 3, 4, 5], "工作日失败"
    assert _parse_weekdays("周末") == [6, 7], "周末失败"
    assert _parse_weekdays("每天") == [1, 2, 3, 4, 5, 6, 7], "每天失败"
    assert _parse_weekdays("mon,wed,fri") == [1, 3, 5], "英文失败"
    print("  weekdays 解析 OK")

    print("=== 测试 time_of_day 解析 ===")
    assert _parse_time_of_day("14:30") == (14, 30)
    assert _parse_time_of_day("09:00") == (9, 0)
    assert _parse_time_of_day("25:00") is None
    assert _parse_time_of_day("abc") is None
    print("  time_of_day 解析 OK")

    print("=== 测试首次触发时间 ===")
    # 周二 10:00，今天14:30还没到
    now = datetime(2026, 7, 28, 10, 0)  # 周二
    ts1 = _compute_first_trigger_ts("14:30", base_dt=now)
    assert datetime.fromtimestamp(ts1).strftime("%Y-%m-%d %H:%M") == "2026-07-28 14:30"
    # 今天09:00已过，应该明天
    ts2 = _compute_first_trigger_ts("09:00", base_dt=now)
    assert datetime.fromtimestamp(ts2).strftime("%Y-%m-%d %H:%M") == "2026-07-29 09:00"
    print("  首次触发 OK")

    print("=== 测试周期滚动 ===")
    # daily: 7-28 14:30 → 7-29 14:30
    base_ts = datetime(2026, 7, 28, 14, 30).timestamp()
    next_ts = _compute_next_trigger_ts("daily", base_ts, time_of_day="14:30")
    assert datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M") == "2026-07-29 14:30"

    # weekly: 周一 → 下周一
    base_ts = datetime(2026, 7, 27, 9, 0).timestamp()  # 周一
    next_ts = _compute_next_trigger_ts("weekly", base_ts, time_of_day="09:00", weekdays=[1])
    assert datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M") == "2026-08-03 09:00"

    # weekly: 周三五，从周三 → 周五
    base_ts = datetime(2026, 7, 29, 9, 0).timestamp()  # 周三
    next_ts = _compute_next_trigger_ts("weekly", base_ts, time_of_day="09:00", weekdays=[3, 5])
    assert datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M") == "2026-07-31 09:00"

    # monthly: 1月15日 → 2月15日
    base_ts = datetime(2026, 1, 15, 10, 0).timestamp()
    next_ts = _compute_next_trigger_ts("monthly", base_ts, time_of_day="10:00")
    assert datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M") == "2026-02-15 10:00"

    # monthly 月底越界: 1月31日 → 2月28日
    base_ts = datetime(2026, 1, 31, 10, 0).timestamp()
    next_ts = _compute_next_trigger_ts("monthly", base_ts, time_of_day="10:00")
    assert datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M") == "2026-02-28 10:00"

    print("  周期滚动 OK")
    print("\n=== 所有单元测试通过 ===")


async def test_integration():
    """集成测试：通过 ReminderTool 设置周期提醒，验证 check_due_messages 滚动"""
    print("\n=== 集成测试：周期提醒设置+触发滚动 ===")
    tool = ReminderTool()

    # 测试1: 相对时间单次提醒（兼容旧接口）
    print("\n[1] 测试相对时间单次提醒")
    result = await tool._run(message="测试1: 1分钟后提醒", minutes=1)
    print(f"  结果: {result}")
    assert "成功设置提醒" in result, "单次提醒失败"

    # 测试2: 绝对时间单次提醒
    print("\n[2] 测试绝对时间单次提醒")
    # 设置为2分钟后
    future = datetime.now() + timedelta(minutes=2)
    at_time = future.strftime("%H:%M")
    result = await tool._run(
        message="测试2: 绝对时间单次",
        at_time=at_time,
    )
    print(f"  结果: {result}")
    assert "成功设置提醒" in result, "绝对时间单次失败"

    # 测试3: 每天周期提醒
    print("\n[3] 测试每天周期提醒")
    result = await tool._run(
        message="测试3: 每天提醒",
        at_time="23:59",  # 今天的23:59
        recurrence="daily",
    )
    print(f"  结果: {result}")
    assert "周期提醒" in result and "每天" in result, "daily 失败"

    # 测试4: 每周一周五提醒
    print("\n[4] 测试每周一周五提醒")
    result = await tool._run(
        message="测试4: 每周一周五",
        at_time="09:00",
        recurrence="weekly",
        weekdays="1,5",
    )
    print(f"  结果: {result}")
    assert "周期提醒" in result and "周一、周五" in result, "weekly 失败"

    # 测试5: monthly
    print("\n[5] 测试每月提醒")
    result = await tool._run(
        message="测试5: 每月提醒",
        at_time="10:00",
        recurrence="monthly",
    )
    print(f"  结果: {result}")
    assert "周期提醒" in result and "每月" in result, "monthly 失败"

    # 测试6: 完整日期格式（单次）
    print("\n[6] 测试完整日期格式")
    result = await tool._run(
        message="测试6: 完整日期",
        at_time="2026-12-31 23:59",
    )
    print(f"  结果: {result}")
    assert "2026-12-31 23:59" in result, "完整日期失败"

    # 测试7: 错误用例
    print("\n[7] 测试错误用例")
    # 缺少时间
    r = await tool._run(message="测试")
    print(f"  无时间: {r}")
    assert "Error" in r
    # weekly 缺 weekdays
    r = await tool._run(message="测试", at_time="09:00", recurrence="weekly")
    print(f"  weekly缺weekdays: {r}")
    assert "Error" in r
    # 非法 recurrence
    r = await tool._run(message="测试", at_time="09:00", recurrence="hourly")
    print(f"  非法recurrence: {r}")
    assert "Error" in r

    # 验证 check_due_messages 滚动逻辑
    print("\n[8] 验证 check_due_messages 周期滚动")
    from core.services.workspace.service import get_workspace_service
    ws = get_workspace_service()
    pending = await ws.get_pending_messages()
    recurring = [m for m in pending if m.recurrence and m.recurrence != "none"]
    print(f"  当前 pending 提醒数: {len(pending)}, 周期性: {len(recurring)}")
    assert len(recurring) >= 3, "应有至少3个周期提醒"

    # 清理测试数据
    for m in pending:
        if "测试" in m.message:
            await ws.delete_message(m.id)
    print("  已清理测试提醒")

    print("\n=== 集成测试通过 ===")


async def main():
    try:
        test_unit()
    except AssertionError as e:
        print(f"单元测试失败: {e}")
        return 1

    try:
        await test_integration()
    except AssertionError as e:
        print(f"集成测试失败: {e}")
        return 1
    except Exception as e:
        print(f"集成测试异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n=== P1-5 全部测试通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
