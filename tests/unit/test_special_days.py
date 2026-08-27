"""
测试特殊日子检测功能
"""

import sys
from datetime import date, datetime

# 添加项目路径
sys.path.insert(0, "d:\\AI\\xiaoyou-core")

from core.agents.chat_agent_components.persona_system.prompt.special_days import (
    get_special_days,
    get_special_day_prompt,
    check_upcoming_birthdays,
    get_upcoming_birthday_prompt,
)


def test_current_day():
    """测试当前日期的检测"""
    print("=" * 60)
    print("测试当前日期检测")
    print("=" * 60)

    today = date.today()
    print(f"当前日期: {today.strftime('%Y-%m-%d')}")

    special_days = get_special_days()
    print(f"检测到的特殊日子: {special_days}")

    assert isinstance(special_days, list), "get_special_days 应返回列表"

    prompt = get_special_day_prompt()
    print(f"生成的提示文本:\n{prompt if prompt else '(没有特殊日子)'}")

    assert prompt is None or isinstance(prompt, str), "get_special_day_prompt 应返回 None 或字符串"


def test_mock_dates():
    """测试模拟日期"""
    print("\n" + "=" * 60)
    print("测试模拟日期")
    print("=" * 60)

    # 测试日期列表
    test_dates = [
        ("用户生日", "2026-05-12"),
        ("Aveline 生日", "2026-11-04"),
        ("情人节", "2026-02-14"),
        ("圣诞节", "2026-12-25"),
        ("普通日子", "2026-06-15"),
    ]

    for name, date_str in test_dates:
        print(f"\n--- {name} ({date_str}) ---")

        mock_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        special_days = get_special_days(mock_date)
        prompt = get_special_day_prompt(mock_date)

        assert isinstance(special_days, list), f"{name}: get_special_days 应返回列表"
        assert prompt is None or isinstance(prompt, str), f"{name}: prompt 应为 None 或字符串"

        print(f"检测到的特殊日子: {special_days}")
        if prompt:
            print(f"提示文本:\n{prompt}")


def test_upcoming_birthdays():
    """测试即将到来的生日"""
    print("\n" + "=" * 60)
    print("测试即将到来的生日检测")
    print("=" * 60)

    # 测试几种情况
    test_scenarios = [
        ("今天是用户生日前1天", "2026-05-11"),
        ("今天是 Aveline 生日前3天", "2026-11-01"),
        ("离两个生日都很远", "2026-07-01"),
    ]

    for name, date_str in test_scenarios:
        print(f"\n--- {name} ({date_str}) ---")

        mock_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        upcoming = check_upcoming_birthdays(mock_date, days_ahead=7)
        prompt = get_upcoming_birthday_prompt(mock_date, days_ahead=7)

        assert isinstance(upcoming, list), f"{name}: check_upcoming_birthdays 应返回列表"
        assert prompt is None or isinstance(prompt, str), f"{name}: prompt 应为 None 或字符串"

        print(f"即将到来的生日: {upcoming}")
        if prompt:
            print(f"提示文本:\n{prompt}")


def test_lunar_holidays():
    """测试农历节日动态换算（七夕年年不同，不能硬编码）"""
    print("\n" + "=" * 60)
    print("测试农历节日（七夕）动态换算")
    print("=" * 60)

    # 已知对照：七夕(农历七月初七) 对应公历（由 lunar-python 权威换算）
    # 2025 -> 08-29, 2026 -> 08-19, 2027 -> 08-08
    expected = {
        2025: "2025-08-29",
        2026: "2026-08-19",
        2027: "2027-08-08",
    }

    for year, solar_str in expected.items():
        solar_date = datetime.strptime(solar_str, "%Y-%m-%d").date()
        # 七夕当天应命中
        days = get_special_days(solar_date)
        names = [d["name"] for d in days]
        print(f"{year} 七夕应为 {solar_str}，命中: {names}")
        assert "七夕节" in names, f"{year} 七夕应在 {solar_str} 命中，实际: {names}"

        # 原错误硬编码 08-15 不应再命中七夕
        wrong_date = datetime.strptime(f"{year}-08-15", "%Y-%m-%d").date()
        wrong_days = get_special_days(wrong_date)
        wrong_names = [d["name"] for d in wrong_days]
        assert "七夕节" not in wrong_names, f"{year}-08-15 不应再被识别为七夕，实际: {wrong_names}"

    # 今天（2026-08-16）不应命中七夕
    today = date(2026, 8, 16)
    today_days = get_special_days(today)
    today_names = [d["name"] for d in today_days]
    print(f"2026-08-16 命中: {today_names}")
    assert "七夕节" not in today_names, f"2026-08-16 不应是七夕，实际: {today_names}"


if __name__ == "__main__":
    test_current_day()
    test_mock_dates()
    test_upcoming_birthdays()
    test_lunar_holidays()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
