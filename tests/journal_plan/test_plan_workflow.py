"""明日学习生活计划功能验证脚本

验证内容：
1. 数据模型 PlanItem / DailyPlan 序列化/反序列化
2. JournalStorage.save_plan / get_plan 存取
3. JournalService 计划增删改查方法
4. format_plan_for_injection 格式化
5. 工具注册到 registry
6. _normalize_plan_item_dict 规范化
7. Active Care prompt 注入今日计划

运行方式（在 venv_core 环境）：
    python -m pytest tests/journal_plan/test_plan_workflow.py -v
或直接：
    python tests/journal_plan/test_plan_workflow.py
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _print_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _print_fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def test_models_serialization() -> bool:
    """测试 1: 数据模型序列化/反序列化"""
    print("\n[测试 1] 数据模型 PlanItem / DailyPlan 序列化")
    try:
        from core.services.journal.models import PlanItem, DailyPlan

        # 创建计划项
        item = PlanItem(
            time="08:00",
            title="数学专项训练",
            description="导数应用题",
            category="study",
            subject="数学",
            priority="high",
            estimated_duration_minutes=120,
        )
        assert item.id.startswith("plan_"), f"id 前缀错误: {item.id}"
        assert item.status == "pending", f"默认状态错误: {item.status}"

        # 序列化
        item_json = item.model_dump_json()
        item_dict = json.loads(item_json)
        assert item_dict["time"] == "08:00"
        assert item_dict["subject"] == "数学"

        # 反序列化
        item2 = PlanItem.model_validate_json(item_json)
        assert item2.title == item.title
        assert item2.time == item.time

        # 创建 DailyPlan
        plan = DailyPlan(
            date="2025-06-21",
            items=[item],
            notes="周末适当休息",
            source="ai_generated",
        )
        plan_json = plan.model_dump_json(indent=2)
        plan2 = DailyPlan.model_validate_json(plan_json)
        assert len(plan2.items) == 1
        assert plan2.items[0].title == "数学专项训练"

        _print_ok("PlanItem / DailyPlan 序列化反序列化正常")
        return True
    except Exception as e:
        _print_fail(f"数据模型测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_normalize_plan_item() -> bool:
    """测试 2: _normalize_plan_item_dict 规范化"""
    print("\n[测试 2] _normalize_plan_item_dict 规范化")
    try:
        from core.services.journal.service import JournalService

        svc = JournalService()

        # 测试无效 category 被修正
        clean = svc._normalize_plan_item_dict({
            "title": "测试",
            "category": "invalid_category",
            "priority": "invalid_priority",
            "time": "25:99",  # 无效时间
        })
        assert clean["category"] == "study", f"无效 category 应回退为 study: {clean['category']}"
        assert clean["priority"] == "normal", f"无效 priority 应回退为 normal: {clean['priority']}"
        assert clean["time"] is None, f"无效 time 应置空: {clean['time']}"

        # 测试非 study 类别清空 subject
        clean2 = svc._normalize_plan_item_dict({
            "title": "吃早餐",
            "category": "life",
            "subject": "数学",  # 应被清空
        })
        assert clean2["subject"] is None, f"life 类别应清空 subject: {clean2['subject']}"

        # 测试有效输入保持不变
        clean3 = svc._normalize_plan_item_dict({
            "time": "14:30",
            "title": "英语阅读",
            "category": "study",
            "subject": "英语",
            "priority": "high",
            "estimated_duration_minutes": 45,
        })
        assert clean3["time"] == "14:30"
        assert clean3["subject"] == "英语"

        _print_ok("规范化逻辑正确（无效值回退、非 study 清空 subject）")
        return True
    except Exception as e:
        _print_fail(f"规范化测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_format_plan_for_injection() -> bool:
    """测试 3: format_plan_for_injection 格式化"""
    print("\n[测试 3] format_plan_for_injection 格式化")
    try:
        from core.services.journal.service import JournalService
        from core.services.journal.models import PlanItem, DailyPlan

        svc = JournalService()

        # 空计划
        assert svc.format_plan_for_injection(None) == ""
        assert svc.format_plan_for_injection(DailyPlan(date="2025-06-21", items=[])) == ""

        # 有计划
        plan = DailyPlan(
            date="2025-06-21",
            items=[
                PlanItem(time="08:00", title="数学训练", category="study", subject="数学", estimated_duration_minutes=120),
                PlanItem(time=None, title="英语阅读", category="study", subject="英语", estimated_duration_minutes=40, status="completed"),
            ],
            notes="周末计划",
        )
        text = svc.format_plan_for_injection(plan)
        assert "2025-06-21" in text, "应包含日期"
        assert "数学训练" in text, "应包含标题"
        assert "英语阅读" in text
        assert "周末计划" in text, "应包含 notes"
        assert "120分钟" in text, "应包含时长"
        # 有时间的排前面
        math_idx = text.find("数学训练")
        english_idx = text.find("英语阅读")
        assert math_idx < english_idx, "有时间的项应排在前面"

        _print_ok("格式化输出包含日期/标题/notes/时长，按时间排序正确")
        return True
    except Exception as e:
        _print_fail(f"格式化测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def _test_storage_roundtrip() -> bool:
    """测试 4: JournalStorage.save_plan / get_plan 存取"""
    print("\n[测试 4] JournalStorage 存取计划")
    try:
        from core.services.journal.storage import JournalStorage
        from core.services.journal.models import PlanItem, DailyPlan

        storage = JournalStorage()
        # 用未来日期避免干扰现有数据
        future_date = datetime(2099, 12, 31)
        plan = DailyPlan(
            date=future_date.strftime("%Y-%m-%d"),
            items=[
                PlanItem(time="08:00", title="测试项1", category="study", subject="数学"),
                PlanItem(time=None, title="测试项2", category="life"),
            ],
            notes="测试计划",
        )
        # 保存
        path = await storage.save_plan(plan, future_date, scope="user")
        assert Path(path).exists(), f"文件未创建: {path}"

        # 读取
        loaded = await storage.get_plan(future_date, scope="user")
        assert loaded is not None, "读取失败"
        assert loaded.date == plan.date
        assert len(loaded.items) == 2
        assert loaded.items[0].title == "测试项1"
        assert loaded.items[1].title == "测试项2"
        assert loaded.notes == "测试计划"

        # 清理测试文件
        Path(path).unlink(missing_ok=True)

        _print_ok("save_plan / get_plan 存取正常")
        return True
    except Exception as e:
        _print_fail(f"存储测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def _test_service_crud() -> bool:
    """测试 5: JournalService 计划增删改查"""
    print("\n[测试 5] JournalService 计划增删改查")
    try:
        from core.services.journal.service import JournalService

        svc = JournalService()
        future_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")

        # 1. 新增计划项
        plan = await svc.add_plan_item(future_date, {
            "time": "08:00",
            "title": "验证脚本-数学",
            "category": "study",
            "subject": "数学",
            "priority": "high",
            "estimated_duration_minutes": 90,
        })
        assert plan is not None, "add_plan_item 返回 None"
        assert len(plan.items) == 1
        item_id = plan.items[0].id
        assert plan.items[0].title == "验证脚本-数学"

        # 2. 查询
        loaded = await svc.get_plan(future_date)
        assert loaded is not None, "get_plan 返回 None"
        assert len(loaded.items) == 1

        # 3. 更新
        updated = await svc.update_plan_item(future_date, item_id, {
            "title": "验证脚本-数学-已更新",
            "status": "in_progress",
        })
        assert updated is not None, "update_plan_item 返回 None"
        assert updated.items[0].title == "验证脚本-数学-已更新"
        assert updated.items[0].status == "in_progress"

        # 4. 标记状态
        marked = await svc.mark_plan_item_status(future_date, item_id, "completed")
        assert marked is not None
        assert marked.items[0].status == "completed"

        # 5. 再加一项
        plan2 = await svc.add_plan_item(future_date, {
            "title": "验证脚本-英语",
            "category": "study",
            "subject": "英语",
        })
        assert len(plan2.items) == 2

        # 6. 删除第一项
        removed = await svc.remove_plan_item(future_date, item_id)
        assert removed is not None
        assert len(removed.items) == 1
        assert removed.items[0].title == "验证脚本-英语"

        # 7. 清理测试数据
        remaining_id = removed.items[0].id
        await svc.remove_plan_item(future_date, remaining_id)
        final_plan = await svc.get_plan(future_date)
        if final_plan and not final_plan.items:
            # 删除空计划文件
            from core.utils.data_paths import get_user_data_dir
            dt = datetime.strptime(future_date, "%Y-%m-%d")
            plan_path = (
                get_user_data_dir() / "daily"
                / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d")
                / "plan.json"
            )
            plan_path.unlink(missing_ok=True)

        _print_ok("add/get/update/mark_status/remove 全流程正常")
        return True
    except Exception as e:
        _print_fail(f"CRUD 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_registry() -> bool:
    """测试 6: 工具注册到 registry"""
    print("\n[测试 6] 工具注册到 ToolRegistry")
    try:
        from core.tools.registry import ToolRegistry, register_all_tools

        registry = ToolRegistry()
        register_all_tools(registry)

        expected_tools = [
            "generate_tomorrow_plan",
            "get_plan",
            "add_plan_item",
            "update_plan_item",
            "remove_plan_item",
            "mark_plan_item_status",
        ]
        for name in expected_tools:
            tool = registry.get_tool(name)
            assert tool is not None, f"工具未注册: {name}"
            assert hasattr(tool, "_run"), f"工具缺少 _run 方法: {name}"

        # 验证工具描述包含关键词
        gen_tool = registry.get_tool("generate_tomorrow_plan")
        assert "高考" in gen_tool.description or "学习" in gen_tool.description, \
            f"generate_tomorrow_plan 描述应包含高考/学习: {gen_tool.description}"

        _print_ok(f"6 个计划工具全部注册成功：{', '.join(expected_tools)}")
        return True
    except Exception as e:
        _print_fail(f"工具注册测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_active_care_prompt_injection() -> bool:
    """测试 7: Active Care prompt 注入今日计划"""
    print("\n[测试 7] Active Care prompt 注入今日计划")
    try:
        # 验证 _build_today_plan_text 函数存在且可调用
        from core.services.active_care.prompt.prompt_context_builders import _build_today_plan_text
        text = _build_today_plan_text()
        # 没有计划时应返回空字符串，不报错
        assert isinstance(text, str), f"返回类型错误: {type(text)}"

        # 验证 TODAY_PLAN_TEMPLATE 存在
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import TODAY_PLAN_TEMPLATE
        assert "{plan_text}" in TODAY_PLAN_TEMPLATE, "TODAY_PLAN_TEMPLATE 应包含 {plan_text} 占位符"

        # 验证 prompt_builder 导入了 _build_today_plan_text
        from core.services.active_care.prompt.prompt_builder import _build_today_plan_text as _bpt
        assert _bpt is not None

        _print_ok("_build_today_plan_text 可调用，TODAY_PLAN_TEMPLATE 模板正确，prompt_builder 已导入")
        return True
    except Exception as e:
        _print_fail(f"Active Care 注入测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_prompt_templates() -> bool:
    """测试 8: Prompt 模板完整性"""
    print("\n[测试 8] Prompt 模板完整性")
    try:
        from core.agents.chat_agent_components.persona_system.prompt.components import (
            PLAN_GENERATION_SYSTEM_PROMPT,
            PLAN_GENERATION_USER_PROMPT_TEMPLATE,
        )

        # 系统提示应包含高考科目
        assert "语文" in PLAN_GENERATION_SYSTEM_PROMPT, "应包含语文"
        assert "数学" in PLAN_GENERATION_SYSTEM_PROMPT, "应包含数学"
        assert "英语" in PLAN_GENERATION_SYSTEM_PROMPT, "应包含英语"
        assert "物理" in PLAN_GENERATION_SYSTEM_PROMPT, "应包含物理"
        assert "化学" in PLAN_GENERATION_SYSTEM_PROMPT, "应包含化学"
        assert "生物" in PLAN_GENERATION_SYSTEM_PROMPT, "应包含生物"
        assert "JSON" in PLAN_GENERATION_SYSTEM_PROMPT, "应要求 JSON 输出"

        # 用户模板应包含必要占位符
        assert "{now_str}" in PLAN_GENERATION_USER_PROMPT_TEMPLATE
        assert "{plan_date_str}" in PLAN_GENERATION_USER_PROMPT_TEMPLATE
        assert "{yesterday_study}" in PLAN_GENERATION_USER_PROMPT_TEMPLATE
        assert "{weekday_cn}" in PLAN_GENERATION_USER_PROMPT_TEMPLATE

        # 测试模板格式化
        formatted = PLAN_GENERATION_USER_PROMPT_TEMPLATE.format(
            now_str="2025-06-20 22:00 Friday",
            plan_date_str="2025-06-21",
            weekday_cn="周六",
            yesterday_study="昨日学习数学 60 分钟",
            yesterday_diary="日记摘要",
            today_status="状态良好",
            subject_distribution="数学: 60 分钟",
        )
        assert "2025-06-21" in formatted
        assert "周六" in formatted

        _print_ok("Prompt 模板包含高考科目、JSON 输出要求、必要占位符")
        return True
    except Exception as e:
        _print_fail(f"Prompt 模板测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_priority_integration() -> bool:
    """测试 9: 计划项与 priority 系统集成"""
    print("\n[测试 9] 计划项与 priority 系统集成")
    try:
        from core.services.active_care.decision.daily_push_priority import (
            build_daily_push_priority_candidates,
        )

        # 构造一个假的 workspace_snapshot 和 priority_focus
        workspace_snapshot = {
            "daily_tasks": {
                "focus": {
                    "timed_overdue": [],
                    "timed_due_soon": [],
                },
            },
        }
        priority_focus = {
            "task_probe": None,
            "portrait_priority": [],
        }
        urgent_needs = []

        # 先在没有计划的情况下调用，确保不报错
        candidates = build_daily_push_priority_candidates(
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            urgent_needs=urgent_needs,
        )
        assert isinstance(candidates, list), "应返回列表"

        # 现在写入一个今日计划，再调用
        from core.services.journal.models import DailyPlan, PlanItem
        from core.utils.time_utils import get_current_time
        from core.utils.data_paths import get_user_data_dir

        now = get_current_time()
        today_str = now.strftime("%Y-%m-%d")

        # 构造一个高优先级 + 接近当前时间的计划项
        # 时间设为当前时间 + 10 分钟，确保在 30 分钟窗口内
        plan_time = (now + timedelta(minutes=10)).strftime("%H:%M")
        plan = DailyPlan(
            date=today_str,
            items=[
                PlanItem(
                    time=plan_time,
                    title="priority集成测试-数学",
                    category="study",
                    subject="数学",
                    priority="high",
                    estimated_duration_minutes=60,
                ),
                PlanItem(
                    title="priority集成测试-已完成",
                    category="study",
                    subject="英语",
                    status="completed",  # 已完成，不应出现在候选中
                ),
            ],
            notes="集成测试",
        )

        # 同步写文件
        plan_path = (
            get_user_data_dir() / "daily"
            / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
            / "plan.json"
        )
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        original_content = None
        if plan_path.exists():
            original_content = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        try:
            candidates = build_daily_push_priority_candidates(
                workspace_snapshot=workspace_snapshot,
                priority_focus=priority_focus,
                urgent_needs=urgent_needs,
            )
            # 应该有 plan: 前缀的候选
            plan_candidates = [c for c in candidates if c["id"].startswith("plan:")]
            assert len(plan_candidates) >= 1, f"应有至少 1 个计划项候选，实际: {len(plan_candidates)}"

            # 验证候选字段
            pc = plan_candidates[0]
            assert pc["reason"] == "plan_item", f"reason 应为 plan_item: {pc['reason']}"
            assert pc["suggested_intent"] == "planned_topic", \
                f"suggested_intent 应为 planned_topic: {pc['suggested_intent']}"
            # high 优先级 + 30 分钟内 = 85 + 10 = 95
            assert pc["base_score"] == 95, f"base_score 应为 95（85+10）: {pc['base_score']}"
            assert "priority集成测试-数学" in pc["title"], f"title 应包含计划项标题: {pc['title']}"

            # 验证已完成的项不出现
            completed_candidates = [
                c for c in candidates if "priority集成测试-已完成" in c.get("title", "")
            ]
            assert len(completed_candidates) == 0, "已完成的项不应出现在候选中"

            _print_ok(
                f"计划项注入 priority 候选成功：高优先级+临近时间 → base_score={pc['base_score']}，"
                f"已完成项被正确过滤"
            )
            return True
        finally:
            # 恢复或清理测试文件
            if original_content is not None:
                plan_path.write_text(original_content, encoding="utf-8")
            else:
                plan_path.unlink(missing_ok=True)
    except Exception as e:
        _print_fail(f"priority 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main() -> int:
    """主入口：运行所有验证测试"""
    print("=" * 70)
    print("明日学习生活计划功能验证")
    print("=" * 70)

    results = []

    # 同步测试
    results.append(("数据模型序列化", test_models_serialization()))
    results.append(("规范化逻辑", test_normalize_plan_item()))
    results.append(("格式化输出", test_format_plan_for_injection()))
    results.append(("工具注册", test_tool_registry()))
    results.append(("Active Care 注入", test_active_care_prompt_injection()))
    results.append(("Prompt 模板", test_prompt_templates()))
    results.append(("priority 集成", test_priority_integration()))

    # 异步测试
    results.append(("存储存取", await _test_storage_roundtrip()))
    results.append(("CRUD 全流程", await _test_service_crud()))

    # 汇总
    print("\n" + "=" * 70)
    print("验证结果汇总")
    print("=" * 70)
    passed = 0
    failed = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n总计: {passed} 通过, {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
