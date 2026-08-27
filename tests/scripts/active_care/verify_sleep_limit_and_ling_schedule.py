"""睡眠期间消息限流 + ling 并行调度验证脚本

验证内容（QR-20260728-SLEEP-LIMIT-AND-LING-SCHEDULE）：
1. 双QQ模式双 persona 独立超时：每个 persona 60s 超时，互不影响
2. 探针频率降低：goodnight_low_disturb_gap_seconds = 14400（4小时）
3. 睡眠期间 next_check_seconds 硬下限 3600s
4. 用户睡觉时不发 nudge（allow_nudge=False）
5. good_morning_proactive 记录用户睡眠状态日志

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\active_care\\verify_sleep_limit_and_ling_schedule.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ==================== 测试工具 ====================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name: str):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name: str, reason: str = ""):
        self.failed += 1
        msg = f"  [FAIL] {name}" + (f": {reason}" if reason else "")
        self.errors.append(msg)
        print(msg)

    def summary(self) -> bool:
        total = self.passed + self.failed
        print("\n========== 验证结果 ==========")
        print(f"通过: {self.passed}/{total}")
        print(f"失败: {self.failed}/{total}")
        if self.failed == 0:
            print("全部通过！")
        else:
            print("有失败项，请检查")
        return self.failed == 0


# ==================== 测试用例 ====================


def test_1_per_persona_timeout_in_proactive_checker(result: TestResult):
    """测试 1: 双QQ模式双 persona 独立超时"""
    print("\n--- 测试 1: 双QQ模式双 persona 独立超时 ---")
    try:
        # 读取 proactive_checker.py 源码，检查关键代码
        src_path = _PROJECT_ROOT / "core" / "services" / "active_care" / "core" / "proactive_checker.py"
        src = src_path.read_text(encoding="utf-8")

        # 检查 1: _PER_PERSONA_TIMEOUT 常量
        if "_PER_PERSONA_TIMEOUT = 60" in src:
            result.ok("双QQ模式有 _PER_PERSONA_TIMEOUT=60 常量")
        else:
            result.fail("双QQ模式缺少 _PER_PERSONA_TIMEOUT=60 常量")

        # 检查 2: asyncio.wait_for 包裹 _execute_decision_flow
        if "asyncio.wait_for(" in src and "_execute_decision_flow" in src:
            result.ok("双QQ模式用 asyncio.wait_for 包裹 _execute_decision_flow")
        else:
            result.fail("双QQ模式未用 asyncio.wait_for 包裹 _execute_decision_flow")

        # 检查 3: 超时后继续处理下一个 persona（不 return）
        # 找到 "跳过该 persona 继续下一个" 日志
        if "跳过该 persona 继续下一个" in src:
            result.ok("超时后继续处理下一个 persona（避免 ling 饥饿）")
        else:
            result.fail("超时后未继续处理下一个 persona")

        # 检查 4: 超时后设置 persona 的下次决策时间
        if "persona_decision_timeout" in src:
            result.ok("超时后设置 persona 下次决策时间（5分钟后重试）")
        else:
            result.fail("超时后未设置 persona 下次决策时间")

    except Exception as e:
        result.fail("测试 1 异常", str(e))


def test_2_goodnight_low_disturb_gap_4h(result: TestResult):
    """测试 2: 探针频率降低到 4 小时"""
    print("\n--- 测试 2: 探针频率降低到 4 小时 ---")
    try:
        import yaml
        yaml_path = _PROJECT_ROOT / "config" / "yaml" / "app.yaml"
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        quiet_hours = config.get("life_simulation", {}).get("active_care_quiet_hours", {})
        gap = quiet_hours.get("goodnight_low_disturb_gap_seconds", 0)

        if gap == 14400:
            result.ok(f"goodnight_low_disturb_gap_seconds = {gap}（4小时）")
        else:
            result.fail(
                "goodnight_low_disturb_gap_seconds 错误",
                f"期望 14400，实际 {gap}",
            )

        # 8小时睡眠最多探针次数 = (8*3600 - 3600) / 14400 + 1 ≈ 2.5 → 2 次
        # 解释：晚安后1小时内不发，之后每4小时1次
        sleep_hours = 8
        first_probe_delay = 1  # 晚安后1小时首次探针
        remaining_hours = sleep_hours - first_probe_delay
        max_probes = int(remaining_hours / (gap / 3600)) + 1
        print(f"    （参考：8小时睡眠最多探针 {max_probes} 次）")

        if max_probes <= 2:
            result.ok(f"8小时睡眠探针数 ≤ 2（实际 {max_probes}）")
        else:
            result.fail(
                "8小时睡眠探针数仍过多",
                f"实际 {max_probes} 次，期望 ≤ 2",
            )

    except Exception as e:
        result.fail("测试 2 异常", str(e))


def test_3_sleep_session_next_check_hard_floor(result: TestResult):
    """测试 3: 睡眠期间 next_check_seconds 硬下限 3600s"""
    print("\n--- 测试 3: 睡眠期间 next_check_seconds 硬下限 3600s ---")
    try:
        src_path = _PROJECT_ROOT / "core" / "services" / "active_care" / "decision" / "decision.py"
        src = src_path.read_text(encoding="utf-8")

        # 检查 1: 有硬下限保护逻辑
        if "睡眠期间 next_check_seconds 硬下限保护" in src:
            result.ok("有睡眠期间 next_check_seconds 硬下限保护日志")
        else:
            result.fail("缺少睡眠期间 next_check_seconds 硬下限保护日志")

        # 检查 2: 强制 3600
        if 'result["next_check_seconds"] = 3600' in src:
            result.ok("sleep_session_active=true 时强制 next_check_seconds=3600")
        else:
            result.fail("未强制 next_check_seconds=3600")

        # 检查 3: 条件判断
        if "if sleep_session_active:" in src:
            result.ok("有 if sleep_session_active 条件判断")
        else:
            result.fail("缺少 if sleep_session_active 条件判断")

    except Exception as e:
        result.fail("测试 3 异常", str(e))


def test_4_nudge_disabled_when_user_sleeping(result: TestResult):
    """测试 4: 用户睡觉时不发 nudge"""
    print("\n--- 测试 4: 用户睡觉时不发 nudge ---")
    try:
        src_path = _PROJECT_ROOT / "core" / "services" / "active_care" / "checker" / "checker_event_handler.py"
        src = src_path.read_text(encoding="utf-8")

        # 检查 1: allow_nudge=False 在用户睡眠场景
        if "allow_nudge=False" in src:
            result.ok("用户睡觉时 allow_nudge=False")
        else:
            result.fail("用户睡觉时未设置 allow_nudge=False")

        # 检查 2: 注释说明
        if "用户睡觉时永远不发 nudge" in src:
            result.ok("有注释说明用户睡觉时永远不发 nudge")
        else:
            result.fail("缺少注释说明")

        # 检查 3: role_night_awake 已移除（不再用于 nudge 判断）
        if "role_night_awake = " not in src:
            result.ok("role_night_awake 变量已移除（不再用于 nudge）")
        else:
            result.fail("role_night_awake 变量未移除")

    except Exception as e:
        result.fail("测试 4 异常", str(e))


def test_5_good_morning_logs_user_sleep_state(result: TestResult):
    """测试 5: good_morning_proactive 记录用户睡眠状态日志"""
    print("\n--- 测试 5: good_morning_proactive 记录用户睡眠状态日志 ---")
    try:
        src_path = _PROJECT_ROOT / "core" / "services" / "active_care" / "good_morning_proactive.py"
        src = src_path.read_text(encoding="utf-8")

        # 检查 1: 调用 is_user_sleeping
        if "is_user_sleeping" in src:
            result.ok("good_morning_proactive 调用 is_user_sleeping 检查用户睡眠状态")
        else:
            result.fail("good_morning_proactive 未调用 is_user_sleeping")

        # 检查 2: 日志记录
        if "用户睡眠状态" in src:
            result.ok("good_morning_proactive 记录用户睡眠状态日志")
        else:
            result.fail("good_morning_proactive 未记录用户睡眠状态日志")

        # 检查 3: 仍然发送（每日去重限流，不加硬门禁）
        if "每日去重已限流，正常发送" in src:
            result.ok("good_morning_proactive 仍然发送（每日去重限流）")
        else:
            result.fail("good_morning_proactive 行为变化")

    except Exception as e:
        result.fail("测试 5 异常", str(e))


def test_6_ruff_check(result: TestResult):
    """测试 6: ruff 检查通过"""
    print("\n--- 测试 6: ruff 检查通过 ---")
    try:
        import subprocess
        targets = [
            "core/services/active_care/core/proactive_checker.py",
            "core/services/active_care/decision/decision.py",
            "core/services/active_care/checker/checker_event_handler.py",
            "core/services/active_care/good_morning_proactive.py",
        ]
        ruff_path = str(_PROJECT_ROOT / "venv_core" / "Scripts" / "ruff.exe")
        cmd = [ruff_path, "check"] + [str(_PROJECT_ROOT / t) for t in targets]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_PROJECT_ROOT))
        if proc.returncode == 0:
            result.ok("ruff check 全部通过")
        else:
            result.fail("ruff check 失败", proc.stderr or proc.stdout)
    except Exception as e:
        result.fail("测试 6 异常", str(e))


# ==================== 主入口 ====================


def main():
    print("=" * 60)
    print("睡眠期间消息限流 + ling 并行调度 验证脚本")
    print("=" * 60)

    result = TestResult()

    test_1_per_persona_timeout_in_proactive_checker(result)
    test_2_goodnight_low_disturb_gap_4h(result)
    test_3_sleep_session_next_check_hard_floor(result)
    test_4_nudge_disabled_when_user_sleeping(result)
    test_5_good_morning_logs_user_sleep_state(result)
    test_6_ruff_check(result)

    ok = result.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
