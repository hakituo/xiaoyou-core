"""计划项增删改服务

从 core/services/journal/plan_service.py 拆分而来，承担 JournalPlanService 中
与"计划项增删改查"相关的职责。JournalPlanService 作为门面，把调用委托给本模块。

设计原则：
- 依赖注入：构造时接收 JournalService 实例，避免循环引用
- 复用 journal_helpers 中的共享工具函数，不重复造轮子
- 保持外部 API 完全兼容（通过 JournalService/JournalPlanService 门面转发）
"""
from typing import TYPE_CHECKING, Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time
from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.storage import JournalStorage
from core.services.journal.journal_helpers import (
    VALID_CATEGORIES,
    VALID_PRIORITIES,
    VALID_STATUSES,
    normalize_plan_item_dict,
)
from core.services.journal.reminder_policy import should_schedule_end_reminder

if TYPE_CHECKING:
    # 仅用于类型注解，避免运行时循环导入
    from core.services.journal.service import JournalService

logger = get_logger("PlanCRUDService")


class PlanCRUDService:
    """计划项增删改服务

    负责对 DailyPlan 中的 PlanItem 进行添加、更新、删除、状态标记。
    时间变更时会自动同步提醒（创建/删除）。
    """

    def __init__(self, service: "JournalService"):
        self.service = service
        self.storage: JournalStorage = service.storage

    async def add_plan_item(
        self, date: Optional[str], item_dict: Dict[str, Any]
    ) -> Optional[DailyPlan]:
        """向某日计划添加新项；date 为 None 时默认明日"""
        now = get_current_time()
        dt = self.service._parse_date(date) if date else now + self._tomorrow_delta()
        plan = await self.storage.get_plan(dt, scope="user")
        if not plan:
            plan = DailyPlan(
                date=dt.strftime("%Y-%m-%d"),
                items=[],
                notes=None,
                source="manual",
                generated_at=now.timestamp(),
                updated_at=now.timestamp(),
            )
        clean = normalize_plan_item_dict(item_dict)
        clean["source_type"] = "manual"
        clean["source_key"] = str(item_dict.get("source_key") or "")
        clean["score"] = 0.0
        new_item = PlanItem(**clean)
        plan.items.append(new_item)
        plan.source = "manual"
        plan.updated_at = now.timestamp()
        # 如果有具体时间，创建提醒（开始 + 结束）
        if new_item.time:
            try:
                from core.services.workspace.service import get_workspace_service
                ws = get_workspace_service()
                if hasattr(ws, "schedule_message"):
                    h, m = new_item.time.split(":")
                    trigger_dt = dt.replace(
                        hour=int(h), minute=int(m),
                        second=0, microsecond=0,
                    )
                    trigger_ts = trigger_dt.timestamp()
                    if trigger_ts > now.timestamp():
                        # 开始提醒
                        msg_id = await ws.schedule_message(
                            message=f"该开始「{new_item.title}」了",
                            trigger_ts=trigger_ts,
                            type="text",
                            metadata={
                                "source": "daily_task",
                                "delivery_mode": "hard",
                                "type": "start",
                                "task_title": new_item.title,
                                "plan_item_id": new_item.id,
                                "plan_date": plan.date,
                            },
                        )
                        new_item.reminder_id = msg_id
                        # 结束提醒
                        dur = new_item.estimated_duration_minutes or 0
                        if should_schedule_end_reminder(dur):
                            from datetime import timedelta as td
                            end_dt = trigger_dt + td(minutes=dur)
                            end_ts = end_dt.timestamp()
                            if end_ts > now.timestamp():
                                end_msg_id = await ws.schedule_message(
                                    message=f"「{new_item.title}」时间到了，休息一下吧~",
                                    trigger_ts=end_ts,
                                    type="text",
                                    metadata={
                                        "source": "daily_task",
                                        "delivery_mode": "hard",
                                        "type": "end",
                                        "task_title": new_item.title,
                                        "plan_item_id": new_item.id,
                                        "plan_date": plan.date,
                                    },
                                )
                                new_item.end_reminder_id = end_msg_id
            except Exception as e:
                logger.warning(f"新增计划项创建提醒失败: {e}")
        await self.storage.save_plan(plan, dt, scope="user")
        return plan

    async def update_plan_item(
        self, date: Optional[str], item_id: str, updates: Dict[str, Any]
    ) -> Optional[DailyPlan]:
        """更新某日计划的指定项；date 为 None 时默认明日"""
        now = get_current_time()
        dt = self.service._parse_date(date) if date else now + self._tomorrow_delta()
        plan = await self.storage.get_plan(dt, scope="user")
        if not plan:
            return None
        target: Optional[PlanItem] = None
        for it in plan.items:
            if it.id == item_id:
                target = it
                break
        if not target:
            return None
        # 应用更新（只允许白名单字段）
        allowed = {
            "time", "title", "description", "category",
            "subject", "priority", "estimated_duration_minutes", "status",
        }
        old_time = target.time
        old_reminder_id = target.reminder_id
        old_end_reminder_id = target.end_reminder_id
        for k, v in updates.items():
            if k in allowed:
                setattr(target, k, v)
        # 规范化关键字段
        if "time" in updates:
            t = str(updates.get("time") or "").strip() or None
            if t:
                try:
                    h, m = t.split(":")
                    if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                        raise ValueError
                except Exception:
                    t = None
            target.time = t
        if "category" in updates and target.category not in VALID_CATEGORIES:
            target.category = "study"
        if "priority" in updates and target.priority not in VALID_PRIORITIES:
            target.priority = "normal"
        if "status" in updates and target.status not in VALID_STATUSES:
            target.status = "pending"
        if target.category != "study":
            target.subject = None
        target.updated_at = now.timestamp()
        target.source_type = "manual"
        target.score = 0.0
        plan.updated_at = now.timestamp()
        plan.source = "manual"

        # 时间变更：清理旧提醒（开始 + 结束），创建新提醒
        if old_time != target.time:
            # 删旧开始提醒
            if old_reminder_id:
                try:
                    from core.services.workspace.service import get_workspace_service
                    ws = get_workspace_service()
                    if hasattr(ws, "delete_message"):
                        await ws.delete_message(old_reminder_id)
                except Exception:
                    pass
                target.reminder_id = None
            # 删旧结束提醒
            if old_end_reminder_id:
                try:
                    from core.services.workspace.service import get_workspace_service
                    ws = get_workspace_service()
                    if hasattr(ws, "delete_message"):
                        await ws.delete_message(old_end_reminder_id)
                except Exception:
                    pass
                target.end_reminder_id = None
            # 建新提醒
            if target.time:
                try:
                    from core.services.workspace.service import get_workspace_service
                    ws = get_workspace_service()
                    if hasattr(ws, "schedule_message"):
                        h, m = target.time.split(":")
                        trigger_dt = dt.replace(
                            hour=int(h), minute=int(m),
                            second=0, microsecond=0,
                        )
                        trigger_ts = trigger_dt.timestamp()
                        if trigger_ts > now.timestamp():
                            # 开始提醒
                            msg_id = await ws.schedule_message(
                                message=f"该开始「{target.title}」了",
                                trigger_ts=trigger_ts,
                                type="text",
                                metadata={
                                    "source": "daily_task",
                                    "delivery_mode": "hard",
                                    "type": "start",
                                    "task_title": target.title,
                                    "plan_item_id": target.id,
                                    "plan_date": plan.date,
                                },
                            )
                            target.reminder_id = msg_id
                            # 结束提醒
                            dur = target.estimated_duration_minutes or 0
                            if should_schedule_end_reminder(dur):
                                from datetime import timedelta as td
                                end_dt = trigger_dt + td(minutes=dur)
                                end_ts = end_dt.timestamp()
                                if end_ts > now.timestamp():
                                    end_msg_id = await ws.schedule_message(
                                        message=f"「{target.title}」时间到了，休息一下吧~",
                                        trigger_ts=end_ts,
                                        type="text",
                                        metadata={
                                            "source": "daily_task",
                                            "delivery_mode": "hard",
                                            "type": "end",
                                            "task_title": target.title,
                                            "plan_item_id": target.id,
                                            "plan_date": plan.date,
                                        },
                                    )
                                    target.end_reminder_id = end_msg_id
                except Exception as e:
                    logger.warning(f"更新计划项创建提醒失败: {e}")

        await self.storage.save_plan(plan, dt, scope="user")
        return plan

    async def remove_plan_item(
        self, date: Optional[str], item_id: str
    ) -> Optional[DailyPlan]:
        """删除某日计划的指定项；date 为 None 时默认明日"""
        now = get_current_time()
        dt = self.service._parse_date(date) if date else now + self._tomorrow_delta()
        plan = await self.storage.get_plan(dt, scope="user")
        if not plan:
            return None
        target: Optional[PlanItem] = None
        for it in plan.items:
            if it.id == item_id:
                target = it
                break
        if not target:
            return None
        # 删除关联提醒（开始 + 结束）
        if target.reminder_id:
            try:
                from core.services.workspace.service import get_workspace_service
                ws = get_workspace_service()
                if hasattr(ws, "delete_message"):
                    await ws.delete_message(target.reminder_id)
            except Exception:
                pass
        if target.end_reminder_id:
            try:
                from core.services.workspace.service import get_workspace_service
                ws = get_workspace_service()
                if hasattr(ws, "delete_message"):
                    await ws.delete_message(target.end_reminder_id)
            except Exception:
                pass
        plan.items = [it for it in plan.items if it.id != item_id]
        plan.updated_at = now.timestamp()
        plan.source = "manual"
        await self.storage.save_plan(plan, dt, scope="user")
        return plan

    async def mark_plan_item_status(
        self, date: Optional[str], item_id: str, status: str
    ) -> Optional[DailyPlan]:
        """标记某日计划项的状态；date 为 None 时默认明日"""
        if status not in VALID_STATUSES:
            logger.warning(f"无效的计划项状态: {status}")
            return None
        return await self.update_plan_item(date, item_id, {"status": status})

    @staticmethod
    def _tomorrow_delta():
        """返回一日的 timedelta（避免重复 import timedelta）"""
        from datetime import timedelta
        return timedelta(days=1)
