"""用户学习主计划服务。

从 core/services/journal/service.py 拆分而来，承担 JournalService 中
与"明日计划生成 / 查询 / 提醒同步 / 格式化"相关的职责。
计划项的增删改委托给 PlanCRUDService。JournalService 作为门面，把调用委托给本模块。

设计原则：
- 依赖注入：构造时接收 JournalService 实例，避免循环引用
- 计划项增删改委托给 PlanCRUDService
- 候选评分与容量排程复用 core.services.planning
- 保持外部 API 完全兼容（通过 JournalService 门面转发）
"""
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time
from core.utils.data_paths import get_study_daily_date_dir
from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.storage import JournalStorage
from core.services.journal.plan_crud import PlanCRUDService
from core.services.journal.plan_candidate_builder import (
    JournalPlanCandidateBuilder,
)
from core.services.journal.plan_policy import load_journal_plan_settings
from core.services.planning import (
    DeterministicPlanEngine,
    PlanPolicy,
    minutes_to_hhmm,
)

if TYPE_CHECKING:
    # 仅用于类型注解，避免运行时循环导入
    from core.services.journal.service import JournalService

logger = get_logger("JournalPlanService")


class JournalPlanService:
    """明日学习生活计划管理服务

    负责：
    - 使用真实学习事实确定性生成计划
    - 计划查询
    - 计划项与 WorkspaceReminderService 的提醒同步
    - 计划格式化（供 Active Care / ChatAgent 注入 prompt）
    - 计划项增删改委托给 PlanCRUDService
    """

    def __init__(self, service: "JournalService"):
        self.service = service
        self.storage: JournalStorage = service.storage
        self.settings = service.settings
        # 计划项增删改委托给 PlanCRUDService
        self._crud = PlanCRUDService(service)
        self._planning_settings = load_journal_plan_settings()
        self._candidate_builder = JournalPlanCandidateBuilder(
            self.storage,
            self._planning_settings,
        )
        self._planning_engine = DeterministicPlanEngine()

    # ── Study Daily 同步（markdown checkbox）────────────────────

    @staticmethod
    def _format_plan_as_markdown(plan: DailyPlan) -> str:
        """将计划格式化为带 markdown checkbox 的文本"""
        lines = [f"# {plan.date} 学习生活计划", ""]
        if plan.notes:
            lines.append(f"> {plan.notes}")
            lines.append("")
        sorted_items = sorted(
            plan.items, key=lambda x: (x.time or "99:99", x.category)
        )
        for it in sorted_items:
            time_str = it.time if it.time else "灵活"
            dur = f"（{it.estimated_duration_minutes}分钟）" if it.estimated_duration_minutes else ""
            if it.status == "completed":
                lines.append(f"- [x] {time_str} {it.title}{dur} ✅")
            elif it.status == "in_progress":
                lines.append(f"- [~] {time_str} {it.title}{dur} 🔄")
            elif it.status == "skipped":
                # skipped 不是 completed，不能用 [x] 让客户端显示为已完成。
                lines.append(f"- [ ] {time_str} {it.title}{dur} ⏭️")
            else:
                lines.append(f"- [ ] {time_str} {it.title}{dur}")
        lines.append("")
        return "\n".join(lines)

    async def _sync_plan_to_study_daily(
        self, plan: DailyPlan, plan_date: datetime
    ) -> None:
        """将计划同步到 D:\\AI\\Study\\Daily/YYYY/MM/DD/plan.md，并确俟 diary.md 存在"""
        try:
            target_dir = get_study_daily_date_dir(plan_date)
            await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)

            # 写入 plan.md
            plan_md_path = target_dir / "plan.md"
            md_content = self._format_plan_as_markdown(plan)
            await asyncio.to_thread(
                plan_md_path.write_text, md_content, "utf-8"
            )
            logger.info(f"计划已同步到 Study Daily: {plan_md_path}")

            # 确俟 diary.md 存在（不覆盖已有内容）
            diary_md_path = target_dir / "diary.md"
            if not diary_md_path.exists():
                date_str = plan_date.strftime("%Y-%m-%d")
                diary_header = f"# {date_str} 日记\n\n"
                await asyncio.to_thread(
                    diary_md_path.write_text, diary_header, "utf-8"
                )
                logger.info(f"已创建空日记文件: {diary_md_path}")
        except Exception as e:
            logger.warning(f"同步计划到 Study Daily 失败: {e}")

    async def _sync_plan_after_change(
        self, plan: DailyPlan, date: Optional[str] = None
    ) -> None:
        """计划变动后统一触发 Study Daily 同步"""
        try:
            if date:
                plan_date = datetime.strptime(date, "%Y-%m-%d")
            else:
                plan_date = datetime.strptime(plan.date, "%Y-%m-%d")
            await self._sync_plan_to_study_daily(plan, plan_date)
        except Exception as e:
            logger.warning(f"计划变动后同步失败: {e}")

    # ── 提醒同步 ─────────────────────────────────────────────

    async def _sync_plan_to_reminders(
        self, plan: DailyPlan, plan_date: datetime
    ) -> int:
        """把有具体时间的计划项同步到 WorkspaceReminderService，返回创建的提醒数

        - 只为 time 字段非空且 reminder_id 为空（未同步过）的项创建提醒
        - 开始提醒：在 time 时间点，消息如 "该开始「物理基础复习」了"
        - 结束提醒：仅为至少 30 分钟的计划创建，避免短计划连续打扰
        - 提醒 metadata 带 plan_item_id / plan_date / task_title / type(start/end)
        """
        synced = 0
        try:
            from core.services.workspace.service import get_workspace_service
            ws = get_workspace_service()
            # 检查 ws 是否有 schedule_message 方法
            if not hasattr(ws, "schedule_message"):
                logger.warning(
                    "WorkspaceService 无 schedule_message 方法，跳过提醒同步"
                )
                return 0
            now_ts = get_current_time().timestamp()
            for item in plan.items:
                if not item.time:
                    continue
                # 计算开始时间戳
                try:
                    h, m = item.time.split(":")
                    trigger_dt = plan_date.replace(
                        hour=int(h), minute=int(m), second=0, microsecond=0
                    )
                except Exception:
                    logger.warning(f"计划项 {item.id} 时间格式错误: {item.time}")
                    continue
                trigger_ts = trigger_dt.timestamp()
                title = item.title or "计划项"
                # 把计划项的描述/分类/科目一起塞进 metadata，供后续 reminder 触发时
                # 给 LLM 提供差异化素材（避免每次输出"该开始X了"的模板话）
                task_extra = {
                    "task_description": str(item.description or "").strip(),
                    "task_category": str(item.category or "").strip(),
                    "task_subject": str(item.subject or "").strip(),
                }

                # 开始提醒
                if not item.reminder_id and trigger_ts > now_ts:
                    msg_id = await ws.schedule_message(
                        message=f"该开始「{title}」了",
                        trigger_ts=trigger_ts,
                        type="text",
                        metadata={
                            "source": "daily_task",
                            "delivery_mode": "hard",
                            "type": "start",
                            "task_title": title,
                            "plan_item_id": item.id,
                            "plan_date": plan.date,
                            **task_extra,
                        },
                    )
                    item.reminder_id = msg_id
                    synced += 1

                # 结束提醒
                if not item.end_reminder_id and trigger_ts > now_ts:
                    dur = item.estimated_duration_minutes or 0
                    from core.services.journal.reminder_policy import (
                        should_schedule_end_reminder,
                    )
                    if should_schedule_end_reminder(dur):
                        from datetime import timedelta as td
                        end_dt = trigger_dt + td(minutes=dur)
                        end_ts = end_dt.timestamp()
                        if end_ts > now_ts:
                            end_msg_id = await ws.schedule_message(
                                message=f"「{title}」时间到了，休息一下吧~",
                                trigger_ts=end_ts,
                                type="text",
                                metadata={
                                    "source": "daily_task",
                                    "delivery_mode": "hard",
                                    "type": "end",
                                    "task_title": title,
                                    "plan_item_id": item.id,
                                    "plan_date": plan.date,
                                    **task_extra,
                                },
                            )
                            item.end_reminder_id = end_msg_id
                            synced += 1
            return synced
        except Exception as e:
            logger.warning(f"同步计划到提醒失败: {e}")
            return synced

    async def _cleanup_plan_reminders(
        self,
        plan: DailyPlan,
        *,
        preserve_manual: bool = False,
    ) -> int:
        """删除计划关联提醒；force 重生时可保留手动项及其提醒。"""
        removed = 0
        try:
            from core.services.workspace.service import get_workspace_service
            ws = get_workspace_service()
            if not hasattr(ws, "delete_message"):
                return 0
            for item in plan.items:
                if preserve_manual and self._is_manual_item(item):
                    continue
                # 清理开始提醒
                if item.reminder_id:
                    try:
                        ok = await ws.delete_message(item.reminder_id)
                        if ok:
                            removed += 1
                    except Exception:
                        pass
                    item.reminder_id = None
                # 清理结束提醒
                if item.end_reminder_id:
                    try:
                        ok = await ws.delete_message(item.end_reminder_id)
                        if ok:
                            removed += 1
                    except Exception:
                        pass
                    item.end_reminder_id = None
            return removed
        except Exception as e:
            logger.warning(f"清理计划提醒失败: {e}")
            return removed

    # ── 计划生成与查询 ───────────────────────────────────────

    async def generate_tomorrow_plan(
        self, force: bool = False
    ) -> DailyPlan:
        """生成明天的学习生活计划

        Args:
            force: True 时强制重新生成（会先清理旧计划的提醒）
        """
        now = get_current_time()
        tomorrow = now + timedelta(days=1)
        return await self._generate_plan_for_date(tomorrow, force=force)

    async def generate_today_plan(
        self, force: bool = False
    ) -> DailyPlan:
        """生成今天的学习生活计划

        用于今日计划缺失或需要重新排时的场景。
        夜间任务只生成明日计划；今日计划需要由 AI 工具主动触发。

        Args:
            force: True 时强制重新生成（会先清理旧计划的提醒）
        """
        now = get_current_time()
        return await self._generate_plan_for_date(now, force=force)

    async def generate_plan_for_date(
        self, date_str: str, force: bool = False
    ) -> DailyPlan:
        """为指定日期生成学习生活计划（按精确日期调用）

        供 nightly 等场景使用：凌晨运行时 target_date=昨天（凌晨归属逻辑），
        应生成 target_date+1=今天的计划。不能用 generate_tomorrow_plan()，
        因为它基于 now+1，凌晨运行时 now=今天会错误生成"后天"计划，
        且 _generate_plan_for_date 的 yesterday 上下文会取到空数据的今天。

        Args:
            date_str: 目标日期 YYYY-MM-DD
            force: True 时强制重新生成（会先清理旧计划的提醒）
        """
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        return await self._generate_plan_for_date(target_date, force=force)

    async def _generate_plan_for_date(
        self, target_date: datetime, force: bool = False
    ) -> DailyPlan:
        """按真实学习事实确定性生成指定日期主计划。"""
        now = get_current_time()
        plan_date_str = target_date.strftime("%Y-%m-%d")

        # 检查是否已存在
        existing = await self.storage.get_plan(target_date, scope="user")
        if existing and not force:
            logger.info(f"计划已存在（{plan_date_str}），跳过生成")
            return existing

        manual_items = (
            [
                item.model_copy(deep=True)
                for item in existing.items
                if self._is_manual_item(item)
                or (existing.source == "manual" and not item.source_key)
            ]
            if existing and force
            else []
        )
        if existing and force:
            await self._cleanup_plan_reminders(existing, preserve_manual=True)

        facts = await self._candidate_builder.load_facts(target_date)
        bundle = self._candidate_builder.build(target_date, facts)
        active_manual_minutes = sum(
            max(0, int(item.estimated_duration_minutes or 0))
            for item in manual_items
            if item.status in {"pending", "in_progress"}
        )
        occupied = [
            interval
            for item in manual_items
            if item.status in {"pending", "in_progress"}
            for interval in [self._item_interval(item)]
            if interval is not None
        ]
        history_counts = self._build_history_counts(facts.previous_plan)
        schedule_result = self._planning_engine.schedule(
            plan_key=f"user|{plan_date_str}",
            candidates=bundle.candidates,
            windows=bundle.policy.windows,
            policy=PlanPolicy(
                max_items=max(0, bundle.policy.max_items - len(manual_items)),
                capacity_minutes=max(
                    0,
                    bundle.policy.capacity_minutes - active_manual_minutes,
                ),
                buffer_minutes=10,
                repeat_penalty=7.0,
                duration_penalty_per_hour=1.5,
            ),
            history_counts=history_counts,
            occupied=occupied,
        )
        algorithm_items = self._scheduled_to_plan_items(
            plan_key=f"user|{plan_date_str}",
            scheduled=schedule_result.scheduled,
            now_ts=now.timestamp(),
        )
        items = sorted(
            manual_items + algorithm_items,
            key=lambda item: (item.time or "99:99", item.id),
        )
        fact_note = "真实学习记录" if bundle.has_learning_facts else "少量保底学习块"
        plan = DailyPlan(
            date=plan_date_str,
            items=items,
            notes=(
                f"{bundle.policy.name} 策略：最多 {bundle.policy.max_items} 项、"
                f"{bundle.policy.capacity_minutes} 分钟；基于{fact_note}确定性排程。"
            ),
            source="algorithm_generated",
            generated_at=now.timestamp(),
            updated_at=now.timestamp(),
        )

        # 自动计划只作为 Active Care MDP 素材，不批量注册 Workspace 硬提醒。
        # 用户明确新增或修改的定时项仍由 PlanCRUDService 维持原提醒行为。
        logger.info("算法自动计划不创建 Workspace 硬提醒，由 Active Care MDP 决定是否跟进")

        # 保存
        await self.storage.save_plan(plan, target_date, scope="user")

        # 同步到 Study Daily（markdown checkbox + diary.md）
        try:
            await self._sync_plan_to_study_daily(plan, target_date)
        except Exception as e:
            logger.warning(f"同步到 Study Daily 失败: {e}")

        logger.info(f"计划已生成：{plan_date_str}，共 {len(plan.items)} 项")
        return plan

    def _scheduled_to_plan_items(
        self,
        *,
        plan_key: str,
        scheduled: Any,
        now_ts: float,
    ) -> list[PlanItem]:
        """把共享引擎结果转换成向后兼容的 PlanItem。"""
        items: list[PlanItem] = []
        for entry in scheduled:
            candidate = entry.candidate
            metadata = candidate.metadata
            digest = hashlib.blake2b(
                f"{plan_key}|{candidate.key}".encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            items.append(
                PlanItem(
                    id=f"plan_{digest}",
                    time=minutes_to_hhmm(entry.start_minute),
                    title=candidate.title,
                    description=metadata.get("description"),
                    category=candidate.category,
                    subject=metadata.get("subject"),
                    priority=candidate.priority,
                    estimated_duration_minutes=candidate.duration_minutes,
                    status="pending",
                    source_key=candidate.key,
                    source_type=str(metadata.get("source_type") or "algorithm"),
                    score=round(float(entry.score), 4),
                    carryover_count=int(metadata.get("carryover_count") or 0),
                    deferred_from_date=metadata.get("deferred_from_date"),
                    settlement_reason=metadata.get("settlement_reason"),
                    created_at=now_ts,
                    updated_at=now_ts,
                )
            )
        return items

    @staticmethod
    def _is_manual_item(item: PlanItem) -> bool:
        """识别新旧格式的手动项；旧格式用提醒关联作为保守兜底。"""
        return bool(
            item.source_type == "manual"
            or item.reminder_id
            or item.end_reminder_id
        )

    @staticmethod
    def _item_interval(item: PlanItem) -> Optional[tuple[int, int]]:
        if not item.time:
            return None
        try:
            hour, minute = (int(value) for value in item.time.split(":", 1))
        except (TypeError, ValueError):
            return None
        start = hour * 60 + minute
        return start, start + max(1, int(item.estimated_duration_minutes or 0))

    @staticmethod
    def _build_history_counts(previous_plan: Optional[DailyPlan]) -> dict[str, int]:
        counts: dict[str, int] = {}
        if previous_plan is None:
            return counts
        for item in previous_plan.items:
            key = item.source_key or item.title
            counts[key] = counts.get(key, 0) + 1
        return counts

    async def get_plan(self, date: Optional[str] = None) -> Optional[DailyPlan]:
        """读取某日计划；未指定日期时读取今日计划。如果 Study Daily 里缺少 plan.md 则自动回填"""
        dt = self.service._parse_date(date)
        plan = await self.storage.get_plan(dt, scope="user")
        # 延迟回填：如果计划存在但 Study Daily 里没有 plan.md，自动同步
        if plan:
            try:
                target_dir = get_study_daily_date_dir(dt)
                plan_md = target_dir / "plan.md"
                if not plan_md.exists():
                    logger.info("Study Daily 缺少 plan.md，自动回填同步")
                    await self._sync_plan_to_study_daily(plan, dt)
            except Exception as e:
                logger.debug(f"检查/回填 Study Daily plan.md 失败: {e}")
        return plan

    async def get_tomorrow_plan(self) -> Optional[DailyPlan]:
        """读取明日计划。如果 Study Daily 里缺少 plan.md 则自动回填"""
        tomorrow = get_current_time() + timedelta(days=1)
        plan = await self.storage.get_plan(tomorrow, scope="user")
        if plan:
            try:
                target_dir = get_study_daily_date_dir(tomorrow)
                plan_md = target_dir / "plan.md"
                if not plan_md.exists():
                    logger.info("Study Daily 缺少明日 plan.md，自动回填同步")
                    await self._sync_plan_to_study_daily(plan, tomorrow)
            except Exception as e:
                logger.debug(f"检查/回填明日 Study Daily plan.md 失败: {e}")
        return plan

    # ── 计划项增删改：委托给 PlanCRUDService ─────────────────

    async def add_plan_item(
        self, date: Optional[str], item_dict: Dict[str, Any]
    ) -> Optional[DailyPlan]:
        plan = await self._crud.add_plan_item(date, item_dict)
        if plan:
            await self._sync_plan_after_change(plan, date)
        return plan

    async def update_plan_item(
        self, date: Optional[str], item_id: str, updates: Dict[str, Any]
    ) -> Optional[DailyPlan]:
        plan = await self._crud.update_plan_item(date, item_id, updates)
        if plan:
            await self._sync_plan_after_change(plan, date)
        return plan

    async def remove_plan_item(
        self, date: Optional[str], item_id: str
    ) -> Optional[DailyPlan]:
        plan = await self._crud.remove_plan_item(date, item_id)
        if plan:
            await self._sync_plan_after_change(plan, date)
        return plan

    async def mark_plan_item_status(
        self, date: Optional[str], item_id: str, status: str
    ) -> Optional[DailyPlan]:
        plan = await self._crud.mark_plan_item_status(date, item_id, status)
        if plan:
            await self._sync_plan_after_change(plan, date)
        return plan

    # ── 格式化输出 ───────────────────────────────────────────

    def format_plan_for_injection(self, plan: Optional[DailyPlan]) -> str:
        """把计划格式化为注入 prompt 的文本（供 Active Care / ChatAgent 使用）"""
        if not plan or not plan.items:
            return ""
        lines = [f"📅 {plan.date} 计划："]
        if plan.notes:
            lines.append(f"（{plan.notes}）")
        # 按 time 排序，无 time 的放后面
        sorted_items = sorted(
            plan.items,
            key=lambda x: (x.time or "99:99", x.category),
        )
        for it in sorted_items:
            time_prefix = f"[{it.time}]" if it.time else "[灵活]"
            status_icon = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "skipped": "⏭️",
            }.get(it.status, "⏳")
            subject_suffix = f"（{it.subject}）" if it.subject else ""
            dur_suffix = (
                f" {it.estimated_duration_minutes}分钟"
                if it.estimated_duration_minutes else ""
            )
            lines.append(
                f"  {status_icon} {time_prefix} {it.title}{subject_suffix}{dur_suffix}"
            )
            if it.description:
                lines.append(f"      └ {it.description[:80]}")
        return "\n".join(lines)
