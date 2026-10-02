"""验证作息记录修正功能（2026-07-30 修复）。

修复背景：
- 系统把聊天时间误识别成睡觉/起床时间，导致 duration 算出 "31m" 这种错误值
- AI 没有工具能主动修正错误数据（record_sleep 保护逻辑会拒绝白天时间覆盖夜间）

修复内容：
1. _calc_sleep_duration 添加合理性校验（<1h 或 >16h 返回 None）
2. DailyActivityManager 新增 update_sleep_cycle 方法（显式修改，绕过保护逻辑）
3. 新增 UpdateSleepRecordTool 工具供 AI 调用

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.daily.verify_sleep_record_correction
"""

import asyncio
import json
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, patch

from core.services.daily.manager import DailyActivityManager
from core.tools.daily_tool import UpdateSleepRecordTool


def test_calc_duration_invalid_too_short():
    """测试1: duration < 1h 应返回 None（修复 31m 错误）"""
    manager = DailyActivityManager()
    # 真实错误数据：sleep=19:29, wakeup=20:00 → 31m
    result = manager._calc_sleep_duration("19:29", "20:00")
    assert result is None, f"31m 应返回 None, 但得到: {result!r}"
    print("[OK] 测试1 (31m 错误数据返回 None)")


def test_calc_duration_invalid_too_long():
    """测试2: duration > 16h 应返回 None（修复 22h45m 错误）"""
    manager = DailyActivityManager()
    # 真实错误数据：sleep=23:05, wakeup=21:50 → 22h45m
    result = manager._calc_sleep_duration("23:05", "21:50")
    assert result is None, f"22h45m 应返回 None, 但得到: {result!r}"
    print("[OK] 测试2 (22h45m 错误数据返回 None)")


def test_calc_duration_normal_cross_day():
    """测试3: 正常跨天睡眠应正确计算（07:00→17:00 = 10h）"""
    manager = DailyActivityManager()
    result = manager._calc_sleep_duration("07:00", "17:00")
    assert result == "10h", f"07:00→17:00 应为 '10h', 但得到: {result!r}"
    print("[OK] 测试3 (07:00→17:00 = 10h)")


def test_calc_duration_normal_with_minutes():
    """测试4: 正常带分钟的睡眠（02:30→10:15 = 7h45m）"""
    manager = DailyActivityManager()
    result = manager._calc_sleep_duration("02:30", "10:15")
    assert result == "7h45m", f"02:30→10:15 应为 '7h45m', 但得到: {result!r}"
    print("[OK] 测试4 (02:30→10:15 = 7h45m)")


def test_calc_duration_boundary_exactly_1h():
    """测试5: 恰好 1 小时应保留（边界值）"""
    manager = DailyActivityManager()
    result = manager._calc_sleep_duration("23:00", "00:00")
    assert result == "1h", f"23:00→00:00 应为 '1h', 但得到: {result!r}"
    print("[OK] 测试5 (23:00→00:00 = 1h 边界值保留)")


def test_calc_duration_boundary_59m():
    """测试6: 59 分钟应返回 None（边界值）"""
    manager = DailyActivityManager()
    result = manager._calc_sleep_duration("23:00", "23:59")
    assert result is None, f"59m 应返回 None, 但得到: {result!r}"
    print("[OK] 测试6 (23:00→23:59 = 59m 返回 None)")


def test_update_sleep_cycle_with_temp_dir():
    """测试7: update_sleep_cycle 能修正错误数据并绕过保护逻辑"""
    # 用临时目录避免污染真实数据
    tmp_dir = tempfile.mkdtemp(prefix="daily_test_")
    try:
        manager = DailyActivityManager()
        manager.root_dir = tmp_dir

        # 模拟错误数据：sleep=19:29, wakeup=20:00 (duration=31m)
        # 注意：直接写文件，因为 record_sleep 保护逻辑会拒绝这种修改
        target_date = "2026-07-30"
        file_path = os.path.join(tmp_dir, "2026", "7", "30", "daily_record.json")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": target_date,
                    "sleep_cycle": {
                        "sleep": "19:29",
                        "wakeup": "20:00",
                        "duration": "31m",
                    },
                    "meals": [],
                    "study": {"sessions": [], "summary": ""},
                    "activities": [],
                },
                f,
                ensure_ascii=False,
            )

        # 用 update_sleep_cycle 修正为 sleep=07:00, wakeup=17:00
        result = manager.update_sleep_cycle(
            sleep_time="07:00",
            wakeup_time="17:00",
            target_date=target_date,
        )
        assert "已修正作息记录" in result, f"应返回修正成功, 但得到: {result!r}"
        assert "sleep=07:00" in result, f"应包含 sleep=07:00, 但得到: {result!r}"
        assert "wakeup=17:00" in result, f"应包含 wakeup=17:00, 但得到: {result!r}"
        print(f"[OK] 测试7 (update_sleep_cycle 修正成功): {result}")

        # 验证文件已更新
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sc = data["sleep_cycle"]
        assert sc["sleep"] == "07:00", f"sleep 应为 07:00, 但得到: {sc['sleep']!r}"
        assert sc["wakeup"] == "17:00", f"wakeup 应为 17:00, 但得到: {sc['wakeup']!r}"
        assert sc["duration"] == "10h", f"duration 应为 10h, 但得到: {sc['duration']!r}"
        print("[OK] 测试7 (文件数据已更新: sleep=07:00, wakeup=17:00, duration=10h)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_update_sleep_cycle_only_sleep():
    """测试8: 只修正 sleep 字段，wakeup 保持不变"""
    tmp_dir = tempfile.mkdtemp(prefix="daily_test_")
    try:
        manager = DailyActivityManager()
        manager.root_dir = tmp_dir

        target_date = "2026-07-30"
        file_path = os.path.join(tmp_dir, "2026", "7", "30", "daily_record.json")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": target_date,
                    "sleep_cycle": {
                        "sleep": "19:29",
                        "wakeup": "17:00",
                        "duration": None,
                    },
                    "meals": [],
                    "study": {"sessions": [], "summary": ""},
                    "activities": [],
                },
                f,
                ensure_ascii=False,
            )

        # 只修正 sleep
        result = manager.update_sleep_cycle(
            sleep_time="07:00", target_date=target_date
        )
        assert "sleep=07:00" in result, f"应包含 sleep=07:00, 但得到: {result!r}"
        assert "wakeup" not in result, f"不应包含 wakeup, 但得到: {result!r}"
        print(f"[OK] 测试8 (只修正 sleep): {result}")

        # 验证 wakeup 保持不变，duration 被重算
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sc = data["sleep_cycle"]
        assert sc["sleep"] == "07:00", "sleep 应为 07:00"
        assert sc["wakeup"] == "17:00", "wakeup 应保持 17:00"
        assert sc["duration"] == "10h", f"duration 应被重算为 10h, 但得到: {sc['duration']!r}"
        print("[OK] 测试8 (wakeup 保持不变, duration 重算为 10h)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_update_sleep_cycle_no_args():
    """测试9: 不提供任何字段应返回错误提示"""
    manager = DailyActivityManager()
    result = manager.update_sleep_cycle()
    assert "未提供修改字段" in result, f"应提示未提供字段, 但得到: {result!r}"
    print(f"[OK] 测试9 (无参数返回提示): {result}")


def test_record_sleep_protection_still_works():
    """测试10: record_sleep 保护逻辑仍然生效（不被 update_sleep_cycle 破坏）

    用同一个 target_date 强制写入同一天，验证保护逻辑触发。
    """
    tmp_dir = tempfile.mkdtemp(prefix="daily_test_")
    try:
        manager = DailyActivityManager()
        manager.root_dir = tmp_dir

        target_date = "2026-07-30"
        # 先记录夜间睡眠 23:00（强制归到 target_date）
        manager.record_sleep("23:00", target_date=target_date)
        # 尝试用白天时间 07:00 覆盖同一天，应被保护逻辑拒绝
        result = manager.record_sleep("07:00", target_date=target_date)
        assert "Kept existing sleep time" in result, (
            f"保护逻辑应拒绝白天覆盖, 但得到: {result!r}"
        )
        print(f"[OK] 测试10 (record_sleep 保护逻辑仍生效): {result}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_tool_call_via_async():
    """测试11: UpdateSleepRecordTool 工具能被异步调用

    工具内部用 get_daily_manager() 获取单例，所以必须修改单例的 root_dir
    才能避免污染真实数据。
    """
    from core.services.daily.manager import get_daily_manager
    from core.utils.singleton import SingletonFactory

    tmp_dir = tempfile.mkdtemp(prefix="daily_test_")
    original_root = None
    try:
        # 准备测试数据：用单例 manager，修改其 root_dir
        manager = get_daily_manager()
        original_root = manager.root_dir
        manager.root_dir = tmp_dir

        target_date = "2026-07-30"
        file_path = os.path.join(tmp_dir, "2026", "7", "30", "daily_record.json")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": target_date,
                    "sleep_cycle": {
                        "sleep": "19:29",
                        "wakeup": "20:00",
                        "duration": "31m",
                    },
                    "meals": [],
                    "study": {"sessions": [], "summary": ""},
                    "activities": [],
                },
                f,
                ensure_ascii=False,
            )

        # 调用工具（工具内部 get_daily_manager() 返回同一个单例）
        tool = UpdateSleepRecordTool()
        # 本脚本只验证 Daily Record 工具契约；隔离 Active Care 运行时状态。
        with patch.object(
            UpdateSleepRecordTool,
            "_sync_correction_to_active_care",
            new=AsyncMock(return_value=None),
        ):
            result = asyncio.run(
                tool._run(
                    sleep_time="07:00",
                    wakeup_time="17:00",
                    target_date=target_date,
                )
            )
        assert "已修正作息记录" in result, f"工具应返回修正成功, 但得到: {result!r}"
        print(f"[OK] 测试11 (UpdateSleepRecordTool 调用成功): {result}")

        # 验证数据
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sc = data["sleep_cycle"]
        assert sc["sleep"] == "07:00", f"sleep 应为 07:00, 但得到: {sc['sleep']!r}"
        assert sc["wakeup"] == "17:00", f"wakeup 应为 17:00, 但得到: {sc['wakeup']!r}"
        assert sc["duration"] == "10h", f"duration 应为 10h, 但得到: {sc['duration']!r}"
        print("[OK] 测试11 (工具修正后数据正确: 07:00→17:00 = 10h)")
    finally:
        # 恢复单例的 root_dir，避免影响其他测试和真实数据
        if original_root is not None:
            manager = get_daily_manager()
            manager.root_dir = original_root
        SingletonFactory._instances = {}
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_tool_registered_in_registry():
    """测试12: 工具应被注册到 registry"""
    from core.tools.registry import ToolRegistry, register_all_tools

    reg = ToolRegistry()
    register_all_tools(reg)
    tool = reg.get_tool("update_sleep_record")
    assert tool is not None, "update_sleep_record 工具未注册"
    assert tool.category == "daily", f"category 应为 daily, 但得到: {tool.category!r}"
    print("[OK] 测试12 (工具已注册到 registry, category=daily)")


def main():
    print("=" * 60)
    print("作息记录修正功能验证（2026-07-30 修复）")
    print("=" * 60)
    test_calc_duration_invalid_too_short()
    test_calc_duration_invalid_too_long()
    test_calc_duration_normal_cross_day()
    test_calc_duration_normal_with_minutes()
    test_calc_duration_boundary_exactly_1h()
    test_calc_duration_boundary_59m()
    test_update_sleep_cycle_with_temp_dir()
    test_update_sleep_cycle_only_sleep()
    test_update_sleep_cycle_no_args()
    test_record_sleep_protection_still_works()
    test_tool_call_via_async()
    test_tool_registered_in_registry()
    print("=" * 60)
    print("全部 12 个测试通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
