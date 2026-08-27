"""
主动关怀时段分工机制验证脚本

验证内容：
1. get_time_slot_from_hour 时段判断（3时段 + night）
2. parse_proactive_assignment_from_script 解析（标签/裸JSON/异常）
3. build_proactive_assignment_negotiation_suffix prompt 构建
4. ProactiveAssignmentRegistry 读写（协商状态/分工写入/主导查询/发送记录/接管兜底）
5. 端到端流程模拟（协商 → 分工 → 主导发送 → 次要跳过 → 超时接管）

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\active_care\\verify_proactive_assignment.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

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


result = TestResult()


# ==================== 1. 时段判断 ====================

def test_time_slot():
    """测试 get_time_slot_from_hour 时段判断"""
    print("\n--- 测试1: 时段判断 ---")
    from core.services.active_care.storage.proactive_assignment_registry import (
        get_time_slot_from_hour,
        SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING, SLOT_NIGHT,
    )

    # 3时段边界
    cases = [
        (0, SLOT_NIGHT), (5, SLOT_NIGHT),
        (6, SLOT_MORNING), (11, SLOT_MORNING),
        (12, SLOT_AFTERNOON), (17, SLOT_AFTERNOON),
        (18, SLOT_EVENING), (23, SLOT_EVENING),
    ]
    for hour, expected in cases:
        got = get_time_slot_from_hour(hour)
        if got == expected:
            result.ok(f"hour={hour} -> {expected}")
        else:
            result.fail(f"hour={hour} -> {expected}", f"got {got}")


# ==================== 2. 解析器 ====================

def test_parser():
    """测试 parse_proactive_assignment_from_script"""
    print("\n--- 测试2: 解析器 ---")
    from core.services.active_care.peer_chat.proactive_assignment_parser import (
        parse_proactive_assignment_from_script,
    )

    # 正常标签
    text1 = (
        "Aveline: 上午我来发吧\n"
        "Ling: 好的，那下午我来\n"
        "<proactive_assignment>\n"
        '{"assignments": ['
        '{"time_slot": "morning", "lead": "aveline", "reason": "精神好"}, '
        '{"time_slot": "afternoon", "lead": "ling", "reason": "下午有空"}, '
        '{"time_slot": "evening", "lead": "aveline", "reason": "晚上陪主人"}'
        ']}'
        "\n</proactive_assignment>"
    )
    r1 = parse_proactive_assignment_from_script(text1)
    if len(r1) == 3 and r1[0]["lead"] == "aveline" and r1[1]["lead"] == "ling":
        result.ok("正常标签解析 3 条分工")
    else:
        result.fail("正常标签解析", str(r1))

    # 中文别名
    text2 = (
        "<proactive_assignment>"
        '{"assignments": ['
        '{"time_slot": "morning", "lead": "七濑 澪", "reason": "x"}, '
        '{"time_slot": "afternoon", "lead": "Ling", "reason": "y"}'
        ']}'
        "</proactive_assignment>"
    )
    r2 = parse_proactive_assignment_from_script(text2)
    if len(r2) == 2 and r2[0]["lead"] == "aveline" and r2[1]["lead"] == "ling":
        result.ok("中文别名解析")
    else:
        result.fail("中文别名解析", str(r2))

    # 空文本
    r3 = parse_proactive_assignment_from_script("")
    if r3 == []:
        result.ok("空文本返回空列表")
    else:
        result.fail("空文本返回空列表", str(r3))

    # 非法 JSON
    text4 = "<proactive_assignment>{bad json}</proactive_assignment>"
    r4 = parse_proactive_assignment_from_script(text4)
    if r4 == []:
        result.ok("非法 JSON 返回空列表")
    else:
        result.fail("非法 JSON 返回空列表", str(r4))


# ==================== 3. Prompt 构建 ====================

def test_prompt_builder():
    """测试 build_proactive_assignment_negotiation_suffix"""
    print("\n--- 测试3: Prompt 构建 ---")
    from core.services.active_care.prompt.proactive_assignment_prompts import (
        build_proactive_assignment_negotiation_suffix,
    )

    suffix = build_proactive_assignment_negotiation_suffix(
        aveline_state="精力充沛",
        ling_state="有点累",
    )
    if "主动关怀时段分工协商" in suffix and "morning" in suffix and "proactive_assignment" in suffix:
        result.ok("prompt 包含关键段")
    else:
        result.fail("prompt 缺少关键段", suffix[:200])

    if "七濑 澪（Aveline）：精力充沛" in suffix and "Ling（Ling）：有点累" in suffix:
        result.ok("prompt 注入角色状态")
    else:
        result.fail("prompt 未注入角色状态", suffix[:300])

    # 空状态
    suffix2 = build_proactive_assignment_negotiation_suffix()
    if "今日各自状态参考" not in suffix2:
        result.ok("空状态时不输出状态段")
    else:
        result.fail("空状态时仍输出状态段")


# ==================== 4. Registry 读写 ====================

async def test_registry():
    """测试 ProactiveAssignmentRegistry 读写"""
    print("\n--- 测试4: Registry 读写 ---")
    from core.services.active_care.storage.proactive_assignment_registry import (
        ProactiveAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "proactive_assignment_today.json"

        with patch(
            "core.services.active_care.storage.proactive_assignment_registry.get_proactive_assignment_path",
            return_value=fake_path,
        ):
            reg = ProactiveAssignmentRegistry()

            # 初始状态：needs_negotiation == True
            if await reg.needs_negotiation():
                result.ok("初始 needs_negotiation=True")
            else:
                result.fail("初始 needs_negotiation 应为 True")

            # 写入分工
            await reg.set_assignments([
                {"time_slot": "morning", "lead": "aveline", "reason": "上午精神好"},
                {"time_slot": "afternoon", "lead": "ling", "reason": "下午有空"},
                {"time_slot": "evening", "lead": "aveline", "reason": "晚上陪主人"},
            ])

            # 协商完成后 needs_negotiation == False
            if not await reg.needs_negotiation():
                result.ok("分工后 needs_negotiation=False")
            else:
                result.fail("分工后 needs_negotiation 应为 False")

            # 查询主导
            lead_morning = await reg.get_lead_for_slot("morning")
            if lead_morning == "aveline":
                result.ok("morning lead=aveline")
            else:
                result.fail("morning lead 应为 aveline", lead_morning)

            lead_afternoon = await reg.get_lead_for_slot("afternoon")
            if lead_afternoon == "ling":
                result.ok("afternoon lead=ling")
            else:
                result.fail("afternoon lead 应为 ling", lead_afternoon)

            # night 时段返回空
            lead_night = await reg.get_lead_for_slot("night")
            if lead_night == "":
                result.ok("night lead=空")
            else:
                result.fail("night lead 应为空", lead_night)


# ==================== 5. 接管兜底 ====================

async def test_take_over():
    """测试 can_take_over 兜底机制"""
    print("\n--- 测试5: 接管兜底 ---")
    from core.services.active_care.storage.proactive_assignment_registry import (
        ProactiveAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "proactive_assignment_today.json"

        with patch(
            "core.services.active_care.storage.proactive_assignment_registry.get_proactive_assignment_path",
            return_value=fake_path,
        ):
            reg = ProactiveAssignmentRegistry()
            await reg.set_assignments([
                {"time_slot": "morning", "lead": "aveline", "reason": "x"},
            ])

            # 主导角色可以发
            can = await reg.can_take_over("aveline", time_slot="morning")
            if can:
                result.ok("主导 aveline 可以发")
            else:
                result.fail("主导 aveline 应可以发")

            # 次要角色未超时不能发（negotiated_at 刚写入，elapsed < 1.5h）
            can2 = await reg.can_take_over("ling", time_slot="morning", timeout_seconds=5400.0)
            if not can2:
                result.ok("次要 ling 未超时不能发")
            else:
                result.fail("次要 ling 未超时应不能发")

            # 模拟主导已发送（record_send）
            await reg.record_send("aveline", time_slot="morning")
            # 次要角色仍然不能发（刚发过）
            can3 = await reg.can_take_over("ling", time_slot="morning", timeout_seconds=5400.0)
            if not can3:
                result.ok("主导刚发过，次要不能发")
            else:
                result.fail("主导刚发过，次要应不能发")

            # 模拟超时：用极小的 timeout
            can4 = await reg.can_take_over("ling", time_slot="morning", timeout_seconds=0.0)
            if can4:
                result.ok("主导超时后，次要可以接管")
            else:
                result.fail("主导超时后，次要应可以接管")

            # night 时段始终允许
            can5 = await reg.can_take_over("ling", time_slot="night")
            if can5:
                result.ok("night 时段允许发")
            else:
                result.fail("night 时段应允许发")


# ==================== 6. 协商失败兜底 ====================

async def test_negotiation_failed():
    """测试协商失败标记"""
    print("\n--- 测试6: 协商失败兜底 ---")
    from core.services.active_care.storage.proactive_assignment_registry import (
        ProactiveAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "proactive_assignment_today.json"

        with patch(
            "core.services.active_care.storage.proactive_assignment_registry.get_proactive_assignment_path",
            return_value=fake_path,
        ):
            reg = ProactiveAssignmentRegistry()
            # 模拟协商失败
            await reg.mark_negotiation_status("failed", reason="剧本生成失败")
            # failed 后 needs_negotiation == False（不再重试）
            if not await reg.needs_negotiation():
                result.ok("协商失败后 needs_negotiation=False")
            else:
                result.fail("协商失败后 needs_negotiation 应为 False")

            # 协商失败后仍必须稳定选出唯一主导，不能两边都发。
            effective_lead = await reg.get_effective_lead_for_slot("morning")
            can_aveline = await reg.can_take_over(
                "aveline", time_slot="morning", timeout_seconds=5400.0
            )
            can_ling = await reg.can_take_over(
                "ling", time_slot="morning", timeout_seconds=5400.0
            )
            if effective_lead in {"aveline", "ling"} and (can_aveline != can_ling):
                result.ok("协商失败时仅兜底主导角色可以发")
            else:
                result.fail(
                    "协商失败时应仅允许一个角色发",
                    f"lead={effective_lead}, aveline={can_aveline}, ling={can_ling}",
                )


# ==================== 7. 日期滚动 ====================

async def test_date_rollover():
    """测试日期滚动"""
    print("\n--- 测试7: 日期滚动 ---")
    from core.services.active_care.storage.proactive_assignment_registry import (
        ProactiveAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "proactive_assignment_today.json"
        # 先写入昨天的数据
        fake_path.parent.mkdir(parents=True, exist_ok=True)
        yesterday_data = {
            "date": "2020-01-01",
            "negotiation_status": "completed",
            "negotiated_at": 1.0,
            "assignments": [{"time_slot": "morning", "lead": "aveline", "reason": "old"}],
            "last_send_ts": {},
        }
        with open(fake_path, "w", encoding="utf-8") as f:
            json.dump(yesterday_data, f)

        with patch(
            "core.services.active_care.storage.proactive_assignment_registry.get_proactive_assignment_path",
            return_value=fake_path,
        ):
            reg = ProactiveAssignmentRegistry()
            # 读取时自动滚动
            data = await reg._load()
            if str(data.get("date")) != "2020-01-01":
                result.ok("过期数据自动滚动")
            else:
                result.fail("过期数据未滚动")

            if data.get("negotiation_status") == "pending":
                result.ok("滚动后状态重置为 pending")
            else:
                result.fail("滚动后状态应重置为 pending", str(data.get("negotiation_status")))


# ==================== 主入口 ====================

async def main():
    print("=" * 60)
    print("主动关怀时段分工机制验证")
    print("=" * 60)

    test_time_slot()
    test_parser()
    test_prompt_builder()
    await test_registry()
    await test_take_over()
    await test_negotiation_failed()
    await test_date_rollover()

    return result.summary()


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
