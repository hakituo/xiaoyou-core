"""
跨 persona 提醒分工机制验证脚本

验证内容：
1. ReminderAssignmentRegistry 基本功能（写入、读取、日期滚动、先到先得）
2. NegotiationParser 解析（正常 JSON、缺失标签、非法 JSON）
3. 端到端流程模拟（协商 → 分配 → 检查 → 跳过）
4. prompt_builder 注入"另一角色已发提醒"

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\active_care\\verify_reminder_assignment.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
# 路径层级：parents[0]=active_care, [1]=scripts, [2]=tests, [3]=项目根
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
        print(f"\n========== 验证结果 ==========")
        print(f"通过: {self.passed}/{total}")
        print(f"失败: {self.failed}/{total}")
        if self.failed == 0:
            print("全部通过！")
        else:
            print("有失败项，请检查")
        return self.failed == 0


result = TestResult()


# ==================== 测试 1: ReminderAssignmentRegistry 基本功能 ====================

async def test_registry_basic():
    """测试 ReminderAssignmentRegistry 的基本读写功能"""
    print("\n--- 测试 1: ReminderAssignmentRegistry 基本功能 ---")

    from core.services.active_care.storage.reminder_assignment_registry import (
        ReminderAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "reminder_assignment_today.json"

        with patch(
            "core.services.active_care.storage.reminder_assignment_registry."
            "get_dual_role_reminder_assignment_path",
            return_value=tmp_path,
        ):
            registry = ReminderAssignmentRegistry()

            # 1. 初始状态：needs_negotiation 应返回 True
            if await registry.needs_negotiation():
                result.ok("初始 needs_negotiation=True")
            else:
                result.fail("初始 needs_negotiation", "应为 True")

            # 2. 写入一个分配
            await registry.mark_assigned(
                reminder_id="study:review_due",
                title="学习复习提醒",
                persona="aveline",
                reason="Aveline 学科背景更适合",
            )
            result.ok("mark_assigned 写入成功")

            # 3. 检查是否分配给对方
            is_other = await registry.is_assigned_to_other("study:review_due", "ling")
            if is_other:
                result.ok("is_assigned_to_other(ling 视角) = True")
            else:
                result.fail("is_assigned_to_other", "ling 视角应为 True")

            # 4. 检查是否分配给自己
            is_self = await registry.is_assigned_to_self("study:review_due", "aveline")
            if is_self:
                result.ok("is_assigned_to_self(aveline 视角) = True")
            else:
                result.fail("is_assigned_to_self", "aveline 视角应为 True")

            # 5. 获取对方已认领的提醒（ling 视角）
            other_list = await registry.get_other_persona_assigned("ling")
            if len(other_list) == 1 and other_list[0]["title"] == "学习复习提醒":
                result.ok("get_other_persona_assigned(ling) 返回 aveline 的提醒")
            else:
                result.fail("get_other_persona_assigned", f"返回: {other_list}")

            # 6. 先到先得：ling 尝试认领已被 aveline 认领的提醒
            await registry.mark_assigned(
                reminder_id="study:review_due",
                title="学习复习提醒",
                persona="ling",
                reason="ling 想认领",
            )
            # 应该还是 aveline 认领
            is_other = await registry.is_assigned_to_other("study:review_due", "ling")
            if is_other:
                result.ok("先到先得：ling 无法覆盖 aveline 的认领")
            else:
                result.fail("先到先得", "ling 不应能覆盖 aveline 的认领")

            # 7. 标记协商完成
            await registry.mark_negotiation_status("completed")
            if not await registry.needs_negotiation():
                result.ok("协商完成后 needs_negotiation=False")
            else:
                result.fail("协商完成", "needs_negotiation 应为 False")

            # 8. 文件确实写入了
            if tmp_path.exists():
                result.ok("共享文件已写入磁盘")
            else:
                result.fail("文件写入", "文件不存在")


# ==================== 测试 2: 日期滚动 ====================

async def test_registry_date_rollover():
    """测试日期变更时自动重置"""
    print("\n--- 测试 2: 日期滚动 ---")

    from core.services.active_care.storage.reminder_assignment_registry import (
        ReminderAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "reminder_assignment_today.json"

        # 写入昨天的数据
        yesterday_data = {
            "date": "2020-01-01",  # 过期日期
            "negotiation_status": "completed",
            "negotiated_at": 1577836800.0,
            "assignments": [
                {"reminder_id": "old:xxx", "title": "旧提醒", "assigned_to": "aveline"}
            ],
            "pending": [],
        }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(yesterday_data, f, ensure_ascii=False)

        with patch(
            "core.services.active_care.storage.reminder_assignment_registry."
            "get_dual_role_reminder_assignment_path",
            return_value=tmp_path,
        ):
            registry = ReminderAssignmentRegistry()

            # 加载时应该检测到日期过期，自动重置
            needs = await registry.needs_negotiation()
            if needs:
                result.ok("过期数据被重置，needs_negotiation=True")
            else:
                result.fail("日期滚动", "过期数据应被重置为 pending")

            # 旧分配应该被清空
            other_list = await registry.get_other_persona_assigned("ling")
            if len(other_list) == 0:
                result.ok("旧分配已清空")
            else:
                result.fail("日期滚动", f"旧分配未清空: {other_list}")


# ==================== 测试 3: NegotiationParser 解析 ====================

def test_negotiation_parser():
    """测试 NegotiationParser 的解析能力"""
    print("\n--- 测试 3: NegotiationParser 解析 ---")

    from core.services.active_care.peer_chat.negotiation_parser import (
        parse_assignments_from_script,
        build_reminder_list_text,
    )

    # 1. 正常 <assignment> 块
    raw1 = """
    aveline: 今天那个学习复习提醒，我来发吧
    ling: 好，那我发喝水的
    <assignment>
    {"assignments": [
        {"reminder_id": "study:review_due", "assigned_to": "aveline", "reason": "学科背景"},
        {"reminder_id": "user_health_reminder:water", "assigned_to": "ling", "reason": "我来发"}
    ]}
    </assignment>
    """
    assignments1 = parse_assignments_from_script(raw1)
    if len(assignments1) == 2:
        result.ok("正常 <assignment> 块解析 2 条分工")
    else:
        result.fail("正常解析", f"期望 2 条，得到 {len(assignments1)}")

    # 2. 无标签的裸 JSON
    raw2 = '{"assignments": [{"reminder_id": "study:xxx", "assigned_to": "ling", "reason": "test"}]}'
    assignments2 = parse_assignments_from_script(raw2)
    if len(assignments2) == 1:
        result.ok("裸 JSON 块解析 1 条分工")
    else:
        result.fail("裸 JSON", f"期望 1 条，得到 {len(assignments2)}")

    # 3. 中文 persona 名规范化
    raw3 = '<assignment>{"assignments": [{"reminder_id": "test:1", "assigned_to": "七濑 澪", "reason": ""}]}</assignment>'
    assignments3 = parse_assignments_from_script(raw3)
    if len(assignments3) == 1 and assignments3[0]["assigned_to"] == "aveline":
        result.ok("中文 persona 名「七濑 澪」规范化为 aveline")
    else:
        result.fail("persona 规范化", f"得到: {assignments3}")

    raw4 = '<assignment>{"assignments": [{"reminder_id": "test:2", "assigned_to": "Ling", "reason": ""}]}</assignment>'
    assignments4 = parse_assignments_from_script(raw4)
    if len(assignments4) == 1 and assignments4[0]["assigned_to"] == "ling":
        result.ok("中文 persona 名「Ling」规范化为 ling")
    else:
        result.fail("persona 规范化", f"得到: {assignments4}")

    # 4. 无效 JSON
    raw5 = "<assignment>{invalid json}</assignment>"
    assignments5 = parse_assignments_from_script(raw5)
    if len(assignments5) == 0:
        result.ok("无效 JSON 返回空列表")
    else:
        result.fail("无效 JSON", f"应返回空，得到 {len(assignments5)}")

    # 5. 无分工块
    raw6 = "这是一段普通对话，没有分工信息"
    assignments6 = parse_assignments_from_script(raw6)
    if len(assignments6) == 0:
        result.ok("无分工块时返回空列表")
    else:
        result.fail("无分工块", f"应返回空，得到 {len(assignments6)}")

    # 6. build_reminder_list_text
    reminders = [
        {"reminder_id": "study:review_due", "title": "学习复习提醒：3个知识点到期"},
        {"reminder_id": "task:xxx", "title": "跟进任务：xxx"},
    ]
    text = build_reminder_list_text(reminders)
    if "study:review_due" in text and "学习复习提醒" in text:
        result.ok("build_reminder_list_text 生成正确")
    else:
        result.fail("build_reminder_list_text", f"文本: {text}")

    # 7. 空列表
    empty_text = build_reminder_list_text([])
    if "暂无" in empty_text:
        result.ok("空提醒列表有默认提示")
    else:
        result.fail("空列表", f"文本: {empty_text}")


# ==================== 测试 4: 端到端流程模拟 ====================

async def test_end_to_end_flow():
    """模拟完整的协商 → 分配 → 检查 → 跳过流程"""
    print("\n--- 测试 4: 端到端流程模拟 ---")

    from core.services.active_care.storage.reminder_assignment_registry import (
        ReminderAssignmentRegistry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "reminder_assignment_today.json"

        with patch(
            "core.services.active_care.storage.reminder_assignment_registry."
            "get_dual_role_reminder_assignment_path",
            return_value=tmp_path,
        ):
            registry = ReminderAssignmentRegistry()

            # Step 1: 模拟协商完成，写入分工结果
            await registry.mark_assigned(
                reminder_id="study:review_due",
                title="学习复习提醒：3个知识点到期",
                persona="aveline",
                reason="Aveline 学科背景更适合",
            )
            await registry.mark_assigned(
                reminder_id="user_health_reminder:water",
                title="喝水提醒",
                persona="ling",
                reason="Ling 来发喝水提醒",
            )
            await registry.mark_negotiation_status("completed")
            result.ok("Step 1: 协商完成，写入 2 条分配")

            # Step 2: 模拟 ling 触发 active_care，检查 study:review_due
            is_other = await registry.is_assigned_to_other("study:review_due", "ling")
            if is_other:
                result.ok("Step 2: ling 检查 study:review_due → 已分配给 aveline，应跳过")
            else:
                result.fail("Step 2", "ling 应检测到 study:review_due 已分配给 aveline")

            # Step 3: 模拟 aveline 触发 active_care，检查 user_health_reminder:water
            is_other = await registry.is_assigned_to_other("user_health_reminder:water", "aveline")
            if is_other:
                result.ok("Step 3: aveline 检查 water → 已分配给 ling，应跳过")
            else:
                result.fail("Step 3", "aveline 应检测到 water 已分配给 ling")

            # Step 4: 模拟 aveline 触发 active_care，检查 study:review_due（自己认领的）
            is_self = await registry.is_assigned_to_self("study:review_due", "aveline")
            if is_self:
                result.ok("Step 4: aveline 检查 study:review_due → 已分配给自己，应发送")
            else:
                result.fail("Step 4", "aveline 应能发送自己认领的提醒")

            # Step 5: 兜底场景 - 协商失败，先到先得
            await registry.mark_negotiation_status("failed", reason="测试兜底")
            # failed 状态下 needs_negotiation 应返回 False（不再协商）
            needs = await registry.needs_negotiation()
            if not needs:
                result.ok("Step 5: 协商失败后不再重复协商")
            else:
                result.fail("Step 5", "failed 状态下 needs_negotiation 应为 False")


# ==================== 测试 5: prompt_builder 注入 ====================

def test_prompt_builder_injection():
    """测试 prompt_builder 的"另一角色已发提醒"注入"""
    print("\n--- 测试 5: prompt_builder 注入 ---")

    from core.services.active_care.prompt.prompt_builder import (
        _build_other_persona_reminders_text,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "reminder_assignment_today.json"

        # 写入测试数据
        today = _get_today_str()
        test_data = {
            "date": today,
            "negotiation_status": "completed",
            "negotiated_at": 0.0,
            "assignments": [
                {"reminder_id": "study:review_due", "title": "学习复习提醒", "assigned_to": "aveline"},
                {"reminder_id": "task:xxx", "title": "跟进任务", "assigned_to": "aveline"},
            ],
            "pending": [],
        }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(test_data, f, ensure_ascii=False)

        with patch(
            "core.utils.data_paths.get_dual_role_reminder_assignment_path",
            return_value=tmp_path,
        ):
            # 1. ling 视角：应该看到 aveline 已发的提醒
            text = _build_other_persona_reminders_text("qq/Ling_QQ_Master.json")
            if "七濑 澪" in text and "学习复习提醒" in text and "跟进任务" in text:
                result.ok("ling 视角：看到 aveline 已发的 2 条提醒")
            else:
                result.fail("ling 视角注入", f"文本: {text[:100]}")

            # 2. aveline 视角：对方没发提醒，应该返回空
            text2 = _build_other_persona_reminders_text("qq/Aveline_QQ_Master.json")
            if not text2:
                result.ok("aveline 视角：对方无提醒，返回空")
            else:
                result.fail("aveline 视角", "对方无提醒时应返回空")

            # 3. 文件不存在时返回空
            with patch(
                "core.utils.data_paths.get_dual_role_reminder_assignment_path",
                return_value=Path(tmpdir) / "nonexistent.json",
            ):
                text3 = _build_other_persona_reminders_text("qq/Ling_QQ_Master.json")
                if not text3:
                    result.ok("文件不存在时返回空")
                else:
                    result.fail("文件不存在", "应返回空")


def _get_today_str() -> str:
    """获取今日日期字符串（同步）"""
    from core.utils.time_utils import get_current_time
    return get_current_time().strftime("%Y-%m-%d")


# ==================== 主入口 ====================

async def main():
    print("=" * 50)
    print("跨 persona 提醒分工机制验证")
    print("=" * 50)

    await test_registry_basic()
    await test_registry_date_rollover()
    test_negotiation_parser()
    await test_end_to_end_flow()
    test_prompt_builder_injection()

    return result.summary()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
