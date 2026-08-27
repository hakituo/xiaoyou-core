"""明日学习生活计划工具集

让 AI 可以：
1. 生成明日学习生活计划（高考备考：语数英 / 物化生）
2. 查询某日计划
3. 增删改查计划项
4. 标记计划项状态

设计原则：
- 工具直接调用 JournalService，不经过 WorkspaceService 桥接（计划是日记模块的扩展）
- 有具体时间的计划项自动同步到 WorkspaceReminderService，由 Active Care 自动触发提醒
- AI 调整计划时自动维护提醒（删旧建新）
"""
from __future__ import annotations

from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.services.journal.service import get_journal_service


# ── 1. 生成明日计划 ────────────────────────────────────────────
class GenerateTomorrowPlanInput(BaseModel):
    force: bool = Field(
        default=False,
        description=(
            "是否强制重新生成（会先清理旧计划的提醒）。"
            "默认 False：已存在则直接返回。"
        ),
    )


class GenerateTomorrowPlanTool(BaseTool):
    name = "generate_tomorrow_plan"
    description = (
        "生成明天的学习生活日常计划。会参考昨日学习记录、昨日日记总结、今日状态，"
        "为明天制定一份劳逸结合的高考备考计划（语数英/物化生）。"
        "有具体时间的计划项会自动创建定时提醒，到点由主动关怀系统提醒主人。"
        "默认情况下如果明日计划已存在则直接返回，不重新生成；"
        "如需重新生成请设 force=true。"
    )
    short_description = "生成明日学习生活计划"
    category = "daily"
    args_schema = GenerateTomorrowPlanInput

    async def _run(self, force: bool = False) -> str:
        try:
            from core.utils.data_paths import _resolve_scope_from_active_persona
            if _resolve_scope_from_active_persona() == "ling":
                return "计划是澪姐管的，我不能改啦~"
        except Exception:
            pass
        try:
            svc = get_journal_service()
            plan = await svc.generate_tomorrow_plan(force=force)
            text = svc.format_plan_for_injection(plan)
            timed_count = sum(1 for it in plan.items if it.time)
            return (
                f"明日计划已生成（{plan.date}，共 {len(plan.items)} 项，"
                f"其中 {timed_count} 项已创建定时提醒）：\n\n{text}"
            )
        except Exception as e:
            return f"生成明日计划失败: {e}"


# ── 1b. 生成今日计划 ───────────────────────────────────────────
class GenerateTodayPlanInput(BaseModel):
    force: bool = Field(
        default=False,
        description=(
            "是否强制重新生成（会先清理旧计划的提醒）。"
            "默认 False：今日计划已存在则直接返回。"
            "当主人说\"今天的计划是空的""重新排一下今天\"时设 true。"
        ),
    )


class GenerateTodayPlanTool(BaseTool):
    name = "generate_today_plan"
    description = (
        "生成今天的学习生活日常计划。"
        "夜间任务只自动生成明日计划，今日计划需要主动调用本工具生成。"
        "当主人问起今天要做什么、发现今天计划为空、或需要重新排今天剩余时间时使用。"
        "会参考昨日学习记录、今日状态，为今天制定劳逸结合的高考备考计划。"
        "有具体时间的计划项会自动创建定时提醒。"
        "默认如果今日计划已存在则直接返回；如需重新生成请设 force=true。"
    )
    short_description = "生成今日学习生活计划"
    category = "daily"
    args_schema = GenerateTodayPlanInput

    async def _run(self, force: bool = False) -> str:
        try:
            from core.utils.data_paths import _resolve_scope_from_active_persona
            if _resolve_scope_from_active_persona() == "ling":
                return "计划是澪姐管的，我不能改啦~"
        except Exception:
            pass
        try:
            svc = get_journal_service()
            plan = await svc.generate_today_plan(force=force)
            text = svc.format_plan_for_injection(plan)
            timed_count = sum(1 for it in plan.items if it.time)
            if not plan.items:
                return (
                    f"今日计划生成失败（{plan.date}），"
                    f"原因：{plan.notes or '未知'}。可以稍后重试或手动添加计划项。"
                )
            return (
                f"今日计划已生成（{plan.date}，共 {len(plan.items)} 项，"
                f"其中 {timed_count} 项已创建定时提醒）：\n\n{text}"
            )
        except Exception as e:
            return f"生成今日计划失败: {e}"


# ── 2. 查询计划 ────────────────────────────────────────────────
class GetPlanInput(BaseModel):
    date: Optional[str] = Field(
        default=None,
        description="要查询的日期 YYYY-MM-DD。留空默认查询今日计划。",
    )


class GetPlanTool(BaseTool):
    name = "get_plan"
    description = (
        "查询某日的学习生活计划。留空 date 默认查询今日计划。"
        "返回计划的完整内容，包括每个计划项的时间、标题、学科、状态等。"
    )
    short_description = "查询学习生活计划"
    category = "daily"
    args_schema = GetPlanInput

    async def _run(self, date: Optional[str] = None) -> str:
        try:
            svc = get_journal_service()
            plan = await svc.get_plan(date)
            if not plan:
                target = date or "今日"
                return (
                    f"{target}暂无计划。"
                    "可以调用 generate_tomorrow_plan 生成明日计划。"
                )
            text = svc.format_plan_for_injection(plan)
            return f"查询到计划（{plan.date}，共 {len(plan.items)} 项）：\n\n{text}"
        except Exception as e:
            return f"查询计划失败: {e}"


# ── 3. 新增计划项 ──────────────────────────────────────────────
class AddPlanItemInput(BaseModel):
    title: str = Field(description="计划项标题，简短一句话")
    time: Optional[str] = Field(
        default=None,
        description=(
            "HH:MM 24小时制具体时间，如 14:00。"
            "留空表示无固定时间。有具体时间会自动创建定时提醒。"
        ),
    )
    description: Optional[str] = Field(default=None, description="详细说明/备注")
    category: str = Field(
        default="study",
        description="类别：study/life/rest/other。学习类请用 study。",
    )
    subject: Optional[str] = Field(
        default=None,
        description="学科（仅 study 类别）：语文/数学/英语/物理/化学/生物",
    )
    priority: str = Field(default="normal", description="优先级：high/normal/low")
    estimated_duration_minutes: int = Field(default=60, description="预计耗时（分钟）")
    date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD。留空默认明日。",
    )


class AddPlanItemTool(BaseTool):
    name = "add_plan_item"
    description = (
        "向某日计划添加新的计划项。date 留空默认添加到明日计划。"
        "如果该日期还没有计划，会自动创建一个空计划再添加。"
        "有具体时间的项会自动创建定时提醒。"
    )
    short_description = "添加计划项"
    category = "daily"
    args_schema = AddPlanItemInput

    async def _run(
        self,
        title: str,
        time: Optional[str] = None,
        description: Optional[str] = None,
        category: str = "study",
        subject: Optional[str] = None,
        priority: str = "normal",
        estimated_duration_minutes: int = 60,
        date: Optional[str] = None,
    ) -> str:
        try:
            from core.utils.data_paths import _resolve_scope_from_active_persona
            if _resolve_scope_from_active_persona() == "ling":
                return "计划是澪姐管的，我不能加东西啦~"
        except Exception:
            pass
        try:
            svc = get_journal_service()
            item_dict = {
                "title": title,
                "time": time,
                "description": description,
                "category": category,
                "subject": subject,
                "priority": priority,
                "estimated_duration_minutes": estimated_duration_minutes,
            }
            plan = await svc.add_plan_item(date, item_dict)
            if not plan:
                return "添加失败：计划不存在"
            text = svc.format_plan_for_injection(plan)
            return f"已添加计划项到 {plan.date} 计划：\n\n{text}"
        except Exception as e:
            return f"添加计划项失败: {e}"


# ── 4. 更新计划项 ──────────────────────────────────────────────
class UpdatePlanItemInput(BaseModel):
    item_id: str = Field(description="要更新的计划项 ID")
    date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD。留空默认明日。",
    )
    title: Optional[str] = Field(default=None, description="新标题")
    time: Optional[str] = Field(
        default=None,
        description=(
            "新时间 HH:MM。改为 null 表示取消固定时间。"
            "时间变更会自动同步提醒。"
        ),
    )
    description: Optional[str] = Field(default=None, description="新说明")
    category: Optional[str] = Field(default=None, description="新类别")
    subject: Optional[str] = Field(default=None, description="新学科")
    priority: Optional[str] = Field(default=None, description="新优先级")
    estimated_duration_minutes: Optional[int] = Field(
        default=None, description="新预计耗时"
    )
    status: Optional[str] = Field(
        default=None,
        description="新状态：pending/in_progress/completed/skipped",
    )


class UpdatePlanItemTool(BaseTool):
    name = "update_plan_item"
    description = (
        "更新某日计划的指定计划项。可以修改标题、时间、说明、学科、优先级、状态等字段。"
        "如果修改了 time 字段，会自动同步提醒（删旧建新）。"
        "date 留空默认操作明日计划。"
    )
    short_description = "更新计划项"
    category = "daily"
    args_schema = UpdatePlanItemInput

    async def _run(
        self,
        item_id: str,
        date: Optional[str] = None,
        title: Optional[str] = None,
        time: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        subject: Optional[str] = None,
        priority: Optional[str] = None,
        estimated_duration_minutes: Optional[int] = None,
        status: Optional[str] = None,
    ) -> str:
        try:
            from core.utils.data_paths import _resolve_scope_from_active_persona
            if _resolve_scope_from_active_persona() == "ling":
                return "计划是澪姐管的，我不能改啦~"
        except Exception:
            pass
        try:
            # 构造 updates，只包含实际传入的字段
            updates: Dict[str, Any] = {}
            if title is not None:
                updates["title"] = title
            if time is not None:
                updates["time"] = time
            if description is not None:
                updates["description"] = description
            if category is not None:
                updates["category"] = category
            if subject is not None:
                updates["subject"] = subject
            if priority is not None:
                updates["priority"] = priority
            if estimated_duration_minutes is not None:
                updates["estimated_duration_minutes"] = estimated_duration_minutes
            if status is not None:
                updates["status"] = status
            if not updates:
                return "未提供任何更新字段"
            svc = get_journal_service()
            plan = await svc.update_plan_item(date, item_id, updates)
            if not plan:
                return "更新失败：计划或计划项不存在"
            text = svc.format_plan_for_injection(plan)
            return f"已更新计划项 {item_id}：\n\n{text}"
        except Exception as e:
            return f"更新计划项失败: {e}"


# ── 5. 删除计划项 ──────────────────────────────────────────────
class RemovePlanItemInput(BaseModel):
    item_id: str = Field(description="要删除的计划项 ID")
    date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD。留空默认明日。",
    )


class RemovePlanItemTool(BaseTool):
    name = "remove_plan_item"
    description = (
        "从某日计划删除指定计划项。会自动删除关联的定时提醒。"
        "date 留空默认操作明日计划。"
    )
    short_description = "删除计划项"
    category = "daily"
    args_schema = RemovePlanItemInput

    async def _run(self, item_id: str, date: Optional[str] = None) -> str:
        try:
            from core.utils.data_paths import _resolve_scope_from_active_persona
            if _resolve_scope_from_active_persona() == "ling":
                return "计划是澪姐管的，我不能删东西啦~"
        except Exception:
            pass
        try:
            svc = get_journal_service()
            plan = await svc.remove_plan_item(date, item_id)
            if not plan:
                return "删除失败：计划或计划项不存在"
            text = svc.format_plan_for_injection(plan)
            return f"已删除计划项 {item_id}。剩余计划：\n\n{text}"
        except Exception as e:
            return f"删除计划项失败: {e}"


# ── 6. 标记计划项状态 ──────────────────────────────────────────
class MarkPlanItemStatusInput(BaseModel):
    item_id: str = Field(description="要标记的计划项 ID")
    status: str = Field(
        description=(
            "新状态：pending（待开始）/ in_progress（进行中）"
            " / completed（已完成）/ skipped（已跳过）"
        ),
    )
    date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD。留空默认今日（执行中的计划）。",
    )


class MarkPlanItemStatusTool(BaseTool):
    name = "mark_plan_item_status"
    description = (
        "标记某日计划项的执行状态——这是 TODO 清单的勾选动作。"
        "当主人提到做完了某项计划（如\"数学写完了\"\"刚背完单词\"\"那项搞定了\"），"
        "应立即调用此工具把对应项标记为 completed，不需要每次都问要不要勾。"
        "主人开始做某项时可标记为 in_progress，明确跳过时标记为 skipped。"
        "date 留空默认操作今日计划。"
    )
    short_description = "勾选计划项状态（TODO 勾选）"
    category = "daily"
    args_schema = MarkPlanItemStatusInput

    async def _run(self, item_id: str, status: str, date: Optional[str] = None) -> str:
        try:
            svc = get_journal_service()
            plan = await svc.mark_plan_item_status(date, item_id, status)
            if not plan:
                return "标记失败：计划或计划项不存在，或状态值无效"
            text = svc.format_plan_for_injection(plan)
            return f"已将计划项 {item_id} 标记为 {status}：\n\n{text}"
        except Exception as e:
            return f"标记计划项状态失败: {e}"
