"""
每日计划生成器

每天为每个角色生成一份当天的活动计划。
计划基于角色日程模板，通过共享评分与容量算法稳定生成。
"""


from core.utils.logger import get_logger
import time
from datetime import datetime, timedelta
from typing import List, Optional

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    CHAT_ELIGIBLE_ACTIVITIES,
    DailyPlan,
)
from core.services.character_daily.config import (
    ActivityTemplate,
    RoleScheduleTemplate,
    TimeBlock,
    load_schedule_templates,
)
from core.services.planning import (
    DeterministicPlanEngine,
    PlanCandidate,
    PlanPolicy,
    PlanWindow,
    stable_int,
)

logger = get_logger(__name__)

_REST_DAY_RELAXED_ACTIVITIES = {
    "reading",
    "walking",
    "phone_scrolling",
    "gardening",
    "idle",
    "gaming",
    "creative_hobby",
    "shopping",
    "self_care",
}


def _parse_hhmm(hhmm: str) -> tuple:
    """解析 HH:MM 字符串为 (hour, minute)"""
    parts = hhmm.split(":")
    return int(parts[0]), int(parts[1])


class DailyPlanGenerator:
    """每日计划生成器

    为每个角色根据日程模板生成一天的活动计划。
    同一角色同一天结果稳定，不同日期可有适度变化。
    """

    def __init__(self, templates: dict = None):
        """
        Args:
            templates: {role_id: RoleScheduleTemplate} 字典。
                       为 None 时自动从 YAML 加载。
        """
        self._templates = templates if templates is not None else load_schedule_templates()

    def get_template(self, role_id: str) -> Optional[RoleScheduleTemplate]:
        return self._templates.get(role_id)

    @property
    def role_ids(self) -> tuple[str, ...]:
        """返回全部已加载模板角色，不维护独立角色白名单。"""
        return tuple(self._templates.keys())

    def generate(
        self,
        role_id: str,
        date_str: str,
        previous_plan: Optional[DailyPlan] = None,
    ) -> Optional[DailyPlan]:
        """为指定角色生成指定日期的活动计划

        Args:
            role_id: 任意已加载 YAML 模板的角色 ID
            date_str: 日期字符串 "2026-06-25"
            previous_plan: 同角色昨日计划；留空时保持旧调用兼容

        Returns:
            DailyPlan 实例，模板不存在时返回 None
        """
        template = self._templates.get(role_id)
        if not template:
            logger.warning("CharacterDaily: 未找到 %s 的日程模板", role_id)
            return None

        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        is_rest_day = date.weekday() >= 5
        plan_key = f"character|{role_id}|{date_str}"
        windows, candidates = self._build_candidates(
            role_id=role_id,
            date_str=date_str,
            template=template,
            is_rest_day=is_rest_day,
        )
        history_counts: dict[str, int] = {}
        if previous_plan is not None:
            for slot in previous_plan.slots:
                repeat_key = slot.activity.value
                history_counts[repeat_key] = history_counts.get(repeat_key, 0) + 1

        result = DeterministicPlanEngine().schedule(
            plan_key=plan_key,
            candidates=candidates,
            windows=windows,
            policy=PlanPolicy(
                max_items=len(candidates),
                capacity_minutes=sum(
                    max(0, window.end_minute - window.start_minute)
                    for window in windows
                ),
                buffer_minutes=0,
                repeat_penalty=6.0,
                duration_penalty_per_hour=1.0,
                source_bonuses={"fixed": 100.0, "template": 0.0},
            ),
            history_counts=history_counts,
        )

        midnight = datetime(date.year, date.month, date.day)
        slots: List[ActivitySlot] = []
        for scheduled in result.scheduled:
            candidate = scheduled.candidate
            activity = ActivityType.from_str(candidate.metadata.get("activity", "idle"))
            flexible = bool(candidate.metadata.get("flexible", True))
            slots.append(
                ActivitySlot(
                    activity=activity,
                    planned_start=midnight
                    + timedelta(minutes=scheduled.start_minute),
                    planned_end=midnight + timedelta(minutes=scheduled.end_minute),
                    flexible=flexible,
                    chat_eligible=activity in CHAT_ELIGIBLE_ACTIVITIES,
                )
            )

        # 生成 sleeping slot（跨天）
        sleep_h, sleep_m = _parse_hhmm(template.sleep_time)
        wake_h, wake_m = _parse_hhmm(template.wake_time)

        sleep_start = datetime(date.year, date.month, date.day, sleep_h, sleep_m)
        sleep_end = datetime(date.year, date.month, date.day, wake_h, wake_m) + timedelta(
            days=1
        )

        slots.append(
            ActivitySlot(
                activity=ActivityType.SLEEPING,
                planned_start=sleep_start,
                planned_end=sleep_end,
                flexible=False,
                chat_eligible=False,
            )
        )

        # 按时间排序
        slots.sort(key=lambda s: s.planned_start)

        plan = DailyPlan(
            role_id=role_id,
            date=date_str,
            generated_at=time.time(),
            slots=slots,
        )

        logger.info(
            "CharacterDaily: 为 %s 生成 %s 的计划，共 %d 个活动槽位",
            role_id,
            date_str,
            len(slots),
        )

        return plan

    def _build_candidates(
        self,
        *,
        role_id: str,
        date_str: str,
        template: RoleScheduleTemplate,
        is_rest_day: bool,
    ) -> tuple[List[PlanWindow], List[PlanCandidate]]:
        """把 YAML 中的 fixed/pool 模板转换成共享引擎候选。"""
        windows: List[PlanWindow] = []
        candidates: List[PlanCandidate] = []
        plan_key = f"character|{role_id}|{date_str}"
        for block_index, block in enumerate(template.time_blocks):
            window_key = f"{block_index}:{block.period or 'period'}"
            window = PlanWindow.from_hhmm(window_key, block.start, block.end)
            windows.append(window)
            fixed_cursor = window.start_minute
            for fixed_index, fixed in enumerate(block.fixed):
                duration = stable_int(
                    fixed.duration_min,
                    fixed.duration_max,
                    plan_key,
                    window_key,
                    "fixed",
                    fixed_index,
                    fixed.activity,
                )
                duration = min(duration, max(1, window.end_minute - fixed_cursor))
                candidates.append(
                    PlanCandidate(
                        key=f"{window_key}:fixed:{fixed_index}:{fixed.activity}",
                        title=fixed.activity,
                        duration_minutes=duration,
                        base_score=float(fixed.weight) * 5.0,
                        category=block.period,
                        source="fixed",
                        priority="high",
                        repeat_key=fixed.activity,
                        window_keys=(window_key,),
                        fixed_start_minute=fixed_cursor,
                        metadata={"activity": fixed.activity, "flexible": False},
                    )
                )
                fixed_cursor += duration

            effective_pool = self._build_effective_pool(
                role_id,
                block,
                is_rest_day=is_rest_day,
                rest_day_extras=template.rest_day_extras,
            )
            block_minutes = max(0, window.end_minute - fixed_cursor)
            for pool_index, item in enumerate(effective_pool):
                instance_count = max(
                    1,
                    min(3, block_minutes // max(1, int(item.duration_min))),
                )
                for instance_index in range(instance_count):
                    candidate_key = (
                        f"{window_key}:pool:{pool_index}:{item.activity}:{instance_index}"
                    )
                    duration = stable_int(
                        item.duration_min,
                        item.duration_max,
                        plan_key,
                        candidate_key,
                    )
                    candidates.append(
                        PlanCandidate(
                            key=candidate_key,
                            title=item.activity,
                            duration_minutes=duration,
                            base_score=float(item.weight) * 5.0,
                            category=block.period,
                            source="template",
                            priority="normal",
                            repeat_key=item.activity,
                            window_keys=(window_key,),
                            score_factors={
                                # 先覆盖同一时段内的不同活动，再考虑第二/第三实例，
                                # 避免高权重模板连续占满整段时间。
                                "instance_decay": -float(instance_index) * 20.0
                            },
                            metadata={"activity": item.activity, "flexible": True},
                        )
                    )
        return windows, candidates

    def _build_effective_pool(
        self,
        role_id: str,
        block: TimeBlock,
        *,
        is_rest_day: bool,
        rest_day_extras: Optional[dict[str, List[ActivityTemplate]]] = None,
    ) -> List[ActivityTemplate]:
        """构建实际用于采样的活动池。"""
        pool = [
            ActivityTemplate(
                activity=item.activity,
                duration_min=item.duration_min,
                duration_max=item.duration_max,
                weight=item.weight,
            )
            for item in block.pool
        ]
        if not is_rest_day:
            return pool

        period = str(block.period or "").strip().lower()
        adjusted_pool: List[ActivityTemplate] = []
        for item in pool:
            weight = item.weight
            if item.activity == "studying":
                if period in {"afternoon_activity", "evening", "bedtime"}:
                    weight *= 0.55
                else:
                    weight *= 0.75
            elif item.activity in _REST_DAY_RELAXED_ACTIVITIES:
                weight *= 1.25
            adjusted_pool.append(
                ActivityTemplate(
                    activity=item.activity,
                    duration_min=item.duration_min,
                    duration_max=item.duration_max,
                    weight=weight,
                )
            )

        if rest_day_extras is None:
            template = self._templates.get(role_id)
            rest_day_extras = template.rest_day_extras if template else {}
        extra_items = rest_day_extras.get(period, [])
        adjusted_pool.extend(
            ActivityTemplate(
                activity=item.activity,
                duration_min=item.duration_min,
                duration_max=item.duration_max,
                weight=item.weight,
            )
            for item in extra_items
        )
        return adjusted_pool
