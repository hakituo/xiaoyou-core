"""验证自动进食的"按时吃饭"逻辑。

背景：hunger 衰减极慢（约 4 点/小时），实测常年停在 99 附近，
永远到不了触发线 65，导致正餐从不被触发——每天按点做出来的饭放到过期没人吃。
本脚本验证把"吃正餐"与饥饿阈值解耦后的调度式进食：
1. 饭点到了、即使不饿(hunger=99)也应吃正餐
2. 当天同一餐窗已吃过正餐则不重复触发
3. 昨天吃过、今天同餐窗仍应再次触发（跨天）
4. 优先级：危急口渴 > 极度饥饿 > 按时吃饭 > 夜宵 > 补水 > 零食
5. 非餐窗时段不误判正餐
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.services.life_simulation.meal_policy import (
    is_scheduled_meal_due,
    resolve_food_decision,
)


def _ts(hour: int, minute: int = 0, day_offset: int = 0) -> float:
    """构造（可带天偏移的）指定时刻时间戳。"""
    now = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return (now + timedelta(days=day_offset)).timestamp()


def _check(name: str, got, expected) -> bool:
    ok = got == expected
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={got}, expected={expected}")
    return ok


def main() -> int:
    results: list[bool] = []

    # 1. 饭点到了、即使完全不饿(hunger=99)也应吃正餐（核心：按时吃饭）
    d = resolve_food_decision(now_ts=_ts(12, 30), hunger=99.0, thirst=80.0)
    results.append(_check("午餐窗 hunger=99 仍吃正餐", d["target_type"], "meal"))

    d = resolve_food_decision(now_ts=_ts(18, 30), hunger=95.0, thirst=80.0)
    results.append(_check("晚餐窗 hunger=95 仍吃正餐", d["target_type"], "meal"))

    d = resolve_food_decision(now_ts=_ts(8, 0), hunger=90.0, thirst=80.0)
    results.append(_check("早餐窗 hunger=90 仍吃正餐", d["target_type"], "meal"))

    # 2. 当天同一餐窗已吃过正餐 → 不重复触发调度进食
    lunch_meal = {
        "food_type": "meal",
        "meal_window": "lunch",
        "eaten_at_ts": _ts(12, 0),
    }
    results.append(
        _check(
            "午餐已吃 不重复触发",
            is_scheduled_meal_due(_ts(13, 0), lunch_meal),
            False,
        )
    )

    # 3. 昨天午餐吃过、今天午餐窗仍应触发（跨天不串味）
    yesterday_lunch = {
        "food_type": "meal",
        "meal_window": "lunch",
        "eaten_at_ts": _ts(12, 0, day_offset=-1),
    }
    results.append(
        _check(
            "昨天午餐 今天午餐窗仍触发",
            is_scheduled_meal_due(_ts(12, 30), yesterday_lunch),
            True,
        )
    )

    # 4. 上一餐是零食（非正餐）→ 本餐窗仍应吃正餐
    snack_meal = {
        "food_type": "snack",
        "meal_window": "lunch",
        "eaten_at_ts": _ts(12, 0),
    }
    results.append(
        _check(
            "上一餐是零食 仍触发正餐",
            is_scheduled_meal_due(_ts(12, 30), snack_meal),
            True,
        )
    )

    # 5. 危急口渴优先于按时吃饭（thirst<25 即便饭点也先补水）
    d = resolve_food_decision(now_ts=_ts(12, 30), hunger=99.0, thirst=20.0)
    results.append(_check("饭点但危急口渴 先补水", d["target_type"], "drink"))

    # 6. 非餐窗 + 不太饿 → 零食（不误判正餐）
    d = resolve_food_decision(now_ts=_ts(15, 0), hunger=60.0, thirst=80.0)
    results.append(_check("下午茶时段轻饿 吃零食", d["target_type"], "snack"))

    # 7. 非餐窗但极度饥饿(hunger<18) → 任何时段吃正餐
    d = resolve_food_decision(now_ts=_ts(15, 0), hunger=10.0, thirst=80.0)
    results.append(_check("非餐窗但极饿 吃正餐", d["target_type"], "meal"))

    # 8. 深夜熬夜窗 → 走夜宵零食，不吃正餐
    d = resolve_food_decision(now_ts=_ts(23, 30), hunger=50.0, thirst=80.0, allow_late_snack=True)
    results.append(_check("深夜熬夜 走夜宵零食", d["target_type"], "snack"))

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 40}\n结果: {passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
