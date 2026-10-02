"""用户计划中途复盘与重排服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from core.services.journal.models import DailyPlan, PlanItem
from core.services.planning import (
    PlanCandidate,
    PlanPolicy,
    PlanWindow,
    hhmm_to_minutes,
    minutes_to_hhmm,
)
from core.utils.common import get_project_root
from core.utils.logger import get_logger
from core.utils.time_utils import from_timestamp, get_current_time

if TYPE_CHECKING:
    from core.services.journal.service import JournalService

logger = get_logger("PlanCheckpointService")


@dataclass(slots=True)
class PlanCheckpointConfig:
    """计划检查点配置。"""

    enabled: bool = True
    noon_hour: int = 12
    evening_hour: int = 18
    overdue_grace_minutes: int = 20
    remaining_load_ratio_threshold: float = 1.15
    max_replanned_items: int = 6


@dataclass(slots=True)
class PlanCheckpoint:
    """当前命中的检查点。"""

    name: str
    label: str
    hour: int

    def key(self, date_str: str) -> str:
        return f"{date_str}:{self.name}"


class PlanCheckpointService:
    """负责中午/傍晚对今日计划做一次自动复盘与重排。"""

    def __init__(self, service: "JournalService"):
        self.service = service
        self.storage = service.storage
        self._config = self._load_config()

    async def maybe_reassess_today_plan(
        self,
        now: Optional[datetime] = None,
    ) -> Optional[DailyPlan]:
        """在 12 点和 18 点检查今日计划是否需要自动重排。"""
        if not self._config.enabled:
            return None

        current_dt = now or get_current_time()
        plan = await self.service.get_plan(current_dt.strftime("%Y-%m-%d"))
        if not plan or not plan.items:
            return plan

        checkpoint = self._resolve_checkpoint(plan, current_dt)
        if checkpoint is None:
            return plan

        evaluation = self._evaluate_plan(plan, current_dt, checkpoint)
        review_key = checkpoint.key(plan.date)
        now_ts = current_dt.timestamp()

        if not evaluation["should_replan"]:
            plan.checkpoint_reviews[review_key] = now_ts
            plan.updated_at = now_ts
            await self.storage.save_plan(plan, current_dt, scope="user")
            logger.info(
                "Plan checkpoint review skipped: date=%s checkpoint=%s summary=%s",
                plan.date,
                checkpoint.name,
                evaluation["summary"],
            )
            return plan

        replanned = self._replan_remaining_items(
            plan=plan,
            now=current_dt,
            max_items=self._config.max_replanned_items,
        )
        if not replanned["items"] and not replanned["deferred"]:
            plan.checkpoint_reviews[review_key] = now_ts
            plan.updated_at = now_ts
            await self.storage.save_plan(plan, current_dt, scope="user")
            logger.warning(
                "Plan checkpoint algorithm returned empty items: date=%s checkpoint=%s",
                plan.date,
                checkpoint.name,
            )
            return plan

        await self.service._plan_service._cleanup_plan_reminders(
            plan,
            preserve_manual=True,
        )
        preserved_items = [
            item.model_copy(deep=True)
            for item in plan.items
            if item.status in {"completed", "skipped"}
        ]
        plan.items = sorted(
            preserved_items + replanned["items"] + replanned["deferred"],
            key=lambda item: (item.time or "99:99", item.id),
        )
        plan.notes = self._compose_notes(
            current_note=plan.notes,
            replan_note=replanned["notes"],
            checkpoint=checkpoint,
            evaluation=evaluation,
        )
        plan.source = "algorithm_adjusted"
        plan.revision_count = int(plan.revision_count or 0) + 1
        plan.checkpoint_reviews[review_key] = now_ts
        plan.updated_at = now_ts

        # 自动重排后的计划继续作为 MDP 决策素材，不重新创建整批硬提醒。
        synced = 0
        await self.storage.save_plan(plan, current_dt, scope="user")
        await self.service._plan_service._sync_plan_to_study_daily(plan, current_dt)
        logger.info(
            "Plan checkpoint replan applied: date=%s checkpoint=%s items=%d synced=%d summary=%s",
            plan.date,
            checkpoint.name,
            len(plan.items),
            synced,
            evaluation["summary"],
        )
        return plan

    def _load_config(self) -> PlanCheckpointConfig:
        """从 app.yaml 读取计划检查点配置。"""
        try:
            from config.yaml_loader import load_resolved_yaml_config_from_disk

            yaml_path = get_project_root() / "config" / "yaml" / "app.yaml"
            if yaml_path.exists():
                full, _, _ = load_resolved_yaml_config_from_disk(yaml_path)
                payload = (
                    (full.get("journal_plan") or {}).get("checkpoint_reassessment") or {}
                )
                return PlanCheckpointConfig(
                    enabled=bool(payload.get("enabled", True)),
                    noon_hour=int(payload.get("checkpoint_hours", [12, 18])[0]),
                    evening_hour=int(payload.get("checkpoint_hours", [12, 18])[-1]),
                    overdue_grace_minutes=int(payload.get("overdue_grace_minutes", 20)),
                    remaining_load_ratio_threshold=float(
                        payload.get("remaining_load_ratio_threshold", 1.15)
                    ),
                    max_replanned_items=int(payload.get("max_replanned_items", 6)),
                )
        except Exception as exc:
            logger.debug("加载计划检查点配置失败，回退默认值: %s", exc)
        return PlanCheckpointConfig()

    def _resolve_checkpoint(
        self,
        plan: DailyPlan,
        now: datetime,
    ) -> Optional[PlanCheckpoint]:
        reviews = plan.checkpoint_reviews or {}
        evening = PlanCheckpoint("evening", "傍晚 18 点复盘", self._config.evening_hour)
        noon = PlanCheckpoint("noon", "中午 12 点复盘", self._config.noon_hour)
        if now.hour >= evening.hour and evening.key(plan.date) not in reviews:
            return evening
        if now.hour >= noon.hour and noon.key(plan.date) not in reviews:
            return noon
        return None

    def _evaluate_plan(
        self,
        plan: DailyPlan,
        now: datetime,
        checkpoint: PlanCheckpoint,
    ) -> dict[str, Any]:
        grace_seconds = self._config.overdue_grace_minutes * 60
        completed = [item for item in plan.items if item.status == "completed"]
        skipped = [item for item in plan.items if item.status == "skipped"]
        in_progress = [item for item in plan.items if item.status == "in_progress"]
        pending = [item for item in plan.items if item.status == "pending"]
        active_items = [item for item in plan.items if item.status in {"pending", "in_progress"}]

        overdue_items = [
            item
            for item in active_items
            if self._item_time_in_past(item, now, grace_seconds=grace_seconds)
        ]
        pending_minutes = sum(
            max(0, int(item.estimated_duration_minutes or 0)) for item in active_items
        )
        day_end = now.replace(hour=23, minute=30, second=0, microsecond=0)
        if day_end <= now:
            remaining_minutes = 0
        else:
            remaining_minutes = int((day_end - now).total_seconds() / 60)
        overload = (
            remaining_minutes > 0
            and pending_minutes > remaining_minutes * self._config.remaining_load_ratio_threshold
        )
        none_done = len(completed) == 0

        reasons: list[str] = []
        if overdue_items:
            reasons.append(f"已有 {len(overdue_items)} 项计划明显超时未完成")
        if overload:
            reasons.append(
                f"剩余事项预计 {pending_minutes} 分钟，超过剩余可用 {remaining_minutes} 分钟"
            )
        if checkpoint.name == "evening" and none_done and active_items:
            reasons.append("到傍晚仍然没有任何计划完成，需要切换到保底方案")
        elif checkpoint.name == "noon" and overdue_items:
            reasons.append("上午的计划已经堆积到中午，需要重排下午")

        should_replan = bool(reasons) and bool(active_items)
        summary = (
            f"completed={len(completed)}, in_progress={len(in_progress)}, pending={len(pending)}, "
            f"skipped={len(skipped)}, overdue={len(overdue_items)}, remaining_minutes={remaining_minutes}"
        )
        return {
            "should_replan": should_replan,
            "summary": summary,
            "reasons": reasons or ["当前执行节奏正常，不需要重排"],
            "remaining_minutes": remaining_minutes,
            "progress_summary": self._build_progress_summary(
                completed=completed,
                in_progress=in_progress,
                pending=pending,
                skipped=skipped,
                overdue_items=overdue_items,
                pending_minutes=pending_minutes,
                remaining_minutes=remaining_minutes,
            ),
        }

    def _build_progress_summary(
        self,
        *,
        completed: list[PlanItem],
        in_progress: list[PlanItem],
        pending: list[PlanItem],
        skipped: list[PlanItem],
        overdue_items: list[PlanItem],
        pending_minutes: int,
        remaining_minutes: int,
    ) -> str:
        lines = [
            f"- 已完成: {len(completed)} 项",
            f"- 进行中: {len(in_progress)} 项",
            f"- 待处理: {len(pending)} 项",
            f"- 已跳过: {len(skipped)} 项",
            f"- 明显超时未完成: {len(overdue_items)} 项",
            f"- 剩余待处理预计时长: {pending_minutes} 分钟",
            f"- 今天剩余可用时间: {remaining_minutes} 分钟",
        ]
        return "\n".join(lines)

    def _replan_remaining_items(
        self,
        *,
        plan: DailyPlan,
        now: datetime,
        max_items: int,
    ) -> dict[str, Any]:
        """用共享引擎压缩并重排 pending/in_progress，绝不伪造完成。"""
        active_items = [
            item
            for item in plan.items
            if item.status in {"pending", "in_progress"}
        ]
        day_policy = self.service._plan_service._planning_settings.policy_for(
            now.date()
        )
        current_minute = now.hour * 60 + now.minute
        windows = [
            PlanWindow(
                key=window.key,
                start_minute=max(window.start_minute, current_minute),
                end_minute=window.end_minute,
            )
            for window in day_policy.windows
            if window.end_minute > current_minute
            and window.end_minute > max(window.start_minute, current_minute)
        ]
        configured_keys = tuple(window.key for window in windows)
        window_map = {window.key: window for window in windows}
        candidates: list[PlanCandidate] = []
        for item in active_items:
            fixed_start: Optional[int] = None
            window_keys = configured_keys
            if item.status == "in_progress":
                key = f"in_progress:{item.id}"
                duration = max(10, int(item.estimated_duration_minutes or 0))
                window_map[key] = PlanWindow(
                    key=key,
                    start_minute=current_minute,
                    end_minute=min(23 * 60 + 30, current_minute + duration),
                )
                fixed_start = current_minute
                window_keys = (key,)
            elif self.service._plan_service._is_manual_item(item) and item.time:
                try:
                    manual_start = hhmm_to_minutes(item.time)
                except ValueError:
                    manual_start = -1
                if manual_start >= current_minute:
                    duration = max(10, int(item.estimated_duration_minutes or 0))
                    matching = next(
                        (
                            window.key
                            for window in windows
                            if window.start_minute <= manual_start
                            and manual_start + duration <= window.end_minute
                        ),
                        "",
                    )
                    if not matching:
                        matching = f"manual:{item.id}"
                        window_map[matching] = PlanWindow(
                            key=matching,
                            start_minute=manual_start,
                            end_minute=manual_start + duration,
                        )
                    fixed_start = manual_start
                    window_keys = (matching,)

            source = (
                "manual"
                if self.service._plan_service._is_manual_item(item)
                else "carryover"
                if item.source_type == "carryover"
                else "template"
            )
            candidates.append(
                PlanCandidate(
                    key=f"checkpoint:{item.id}",
                    title=item.title,
                    duration_minutes=max(
                        10,
                        int(item.estimated_duration_minutes or 0),
                    ),
                    base_score=float(item.score or 0.0),
                    category=item.category,
                    source=source,
                    priority=item.priority,
                    repeat_key=item.source_key or item.id,
                    window_keys=window_keys,
                    fixed_start_minute=fixed_start,
                    score_factors={
                        "in_progress": 60.0
                        if item.status == "in_progress"
                        else 0.0,
                    },
                    metadata={"item": item.model_copy(deep=True)},
                )
            )

        usable_windows = tuple(window_map.values())
        available_minutes = sum(
            max(0, window.end_minute - window.start_minute)
            for window in windows
        )
        result = self.service._plan_service._planning_engine.schedule(
            plan_key=f"user|{plan.date}|checkpoint|{now.strftime('%H:%M')}",
            candidates=candidates,
            windows=usable_windows,
            policy=PlanPolicy(
                max_items=min(max(0, max_items), day_policy.max_items),
                capacity_minutes=min(
                    day_policy.capacity_minutes,
                    available_minutes,
                ),
                buffer_minutes=10,
                repeat_penalty=0.0,
                duration_penalty_per_hour=1.5,
            ),
        )

        scheduled_items: list[PlanItem] = []
        scheduled_ids: set[str] = set()
        now_ts = now.timestamp()
        for entry in result.scheduled:
            copied: PlanItem = entry.candidate.metadata["item"]
            old_time = copied.time
            copied.time = minutes_to_hhmm(entry.start_minute)
            copied.score = round(float(entry.score), 4)
            copied.updated_at = now_ts
            copied.settlement_reason = None
            if old_time != copied.time:
                copied.reminder_id = None
                copied.end_reminder_id = None
            scheduled_items.append(copied)
            scheduled_ids.add(copied.id)

        deferred: list[PlanItem] = []
        for item in active_items:
            if item.id in scheduled_ids:
                continue
            copied = item.model_copy(deep=True)
            copied.updated_at = now_ts
            copied.reminder_id = None
            copied.end_reminder_id = None
            if copied.status == "in_progress":
                # 极端容量/窗口异常时也不能把进行中事项误结算掉。
                scheduled_items.append(copied)
                continue
            # 当前窗口塞不下不等于用户主动跳过；保留 pending，清除已失效
            # 的旧时间。若随后睡眠结算，会统一标记 sleep 并允许次日滚动。
            copied.time = None
            copied.settlement_reason = "checkpoint_capacity"
            deferred.append(copied)

        return {
            "notes": "已用同一确定性算法压缩并重排剩余事项。",
            "items": scheduled_items,
            "deferred": deferred,
        }

    def _item_time_in_past(
        self,
        item: PlanItem,
        now: datetime,
        *,
        grace_seconds: int,
    ) -> bool:
        if not item.time:
            return False
        try:
            hour, minute = int(item.time.split(":")[0]), int(item.time.split(":")[1])
            planned = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except Exception:
            return False
        return planned.timestamp() < now.timestamp() - grace_seconds

    def _compose_notes(
        self,
        *,
        current_note: Optional[str],
        replan_note: str,
        checkpoint: PlanCheckpoint,
        evaluation: dict[str, Any],
    ) -> str:
        base_note = replan_note or "已根据当前执行情况重新压缩剩余计划。"
        reason_text = "；".join(evaluation["reasons"][:2])
        prefix = f"{checkpoint.label}自动重排"
        if reason_text:
            prefix += f"：{reason_text}"
        if current_note:
            return f"{prefix}。{base_note} 原计划备注：{current_note}"
        return f"{prefix}。{base_note}"

    # ============================================================
    # 睡眠结算：用户发「晚安」进入 goodnight 模式时调用
    # 此时用户已准备睡觉，今日剩余 pending / in_progress 项都无法再完成，
    # 统一标记为 skipped，并同步到 Study Daily。
    # 与定时检查点（中午/傍晚）不同，这里不依赖 LLM，只按「已就寝」事实结算。
    # ============================================================
    async def settle_today_plan_on_sleep(
        self,
        *,
        sleep_ts: Optional[float] = None,
    ) -> dict[str, Any]:
        """按本次睡眠信号结算当日计划。

        结算日期和可修改范围都以 ``sleep_ts`` 为准。尤其禁止旧晚安信号
        修改在该信号之后才生成的新计划，避免夜间任务生成计划后被下一轮
        Active Care 检查整批标记为 skipped。
        """
        try:
            now = get_current_time()
            signal_ts = float(sleep_ts or now.timestamp())
            plan_date = from_timestamp(signal_ts)
            date_str = plan_date.strftime("%Y-%m-%d")
            plan = await self.storage.get_plan(plan_date, scope="user")
            if plan is None:
                return {"settled": False, "reason": "no_plan"}
            if not plan.items:
                return {"settled": False, "reason": "empty_plan"}

            # 计划晚于睡眠信号生成，说明它属于睡醒后的新一天，不能被旧信号结算。
            if plan.generated_at > signal_ts + 1.0:
                logger.info(
                    "跳过睡眠结算：计划生成晚于睡眠信号 "
                    "(date=%s, plan_generated_at=%.0f, sleep_ts=%.0f)",
                    date_str,
                    plan.generated_at,
                    signal_ts,
                )
                return {
                    "settled": False,
                    "reason": "plan_generated_after_sleep_signal",
                    "date": date_str,
                }

            now_ts = now.timestamp()
            settled: list[dict[str, Any]] = []
            modified = False
            for item in plan.items:
                if item.status in ("pending", "in_progress"):
                    item.status = "skipped"
                    item.settlement_reason = "sleep"
                    item.updated_at = now_ts
                    settled.append({"id": item.id, "title": item.title})
                    modified = True

            if not modified:
                return {"settled": False, "reason": "nothing_to_settle"}

            # 仅保留已完成/已跳过项，清空到点提醒，避免睡眠后仍被打扰
            preserved_items = [
                it for it in plan.items if it.status in ("completed", "skipped")
            ]
            await self.service._plan_service._cleanup_plan_reminders(plan)
            plan.items = preserved_items
            plan.source = "algorithm_adjusted"
            plan.updated_at = now_ts
            await self.storage.save_plan(plan, plan_date, scope="user")
            await self.service._plan_service._sync_plan_to_study_daily(
                plan, plan_date
            )

            logger.info(
                "睡眠结算完成：%d 项标记为 skipped (%s)", len(settled), date_str
            )
            return {
                "settled": True,
                "date": date_str,
                "skipped_count": len(settled),
                "items": settled,
            }
        except Exception as exc:  # pragma: no cover - 防御：结算失败不应影响晚安流程
            logger.error("睡眠结算失败：%s", exc, exc_info=True)
            return {"settled": False, "error": str(exc)}
