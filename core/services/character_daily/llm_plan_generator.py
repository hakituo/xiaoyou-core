"""LLM 每日计划生成器

用 LLM（deepseek qqbot1 v4-pro）为角色生成每日活动计划。
失败时回退到模板生成（DailyPlanGenerator）。

参考 auto_eat.py 的 LLM 调用模式：通过 scheduler.submit_llm_task 走 CloudRouter。
"""

from core.utils.logger import get_logger
import json

import re
from datetime import datetime, timedelta
from typing import Optional

from core.utils.time_utils import get_current_time

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    CHAT_ELIGIBLE_ACTIVITIES,
    DailyPlan,
    DailyState,
)
from core.services.character_daily.config import RoleScheduleTemplate
from core.services.character_daily.daily_plan import DailyPlanGenerator, _parse_hhmm
from core.agents.chat_agent_components.persona_system.prompt.components.character_schedule_prompts import (
    CHARACTER_SCHEDULE_SYSTEM_PROMPT,
    CHARACTER_SCHEDULE_USER_PROMPT_TEMPLATE,
    build_role_personality_section,
    build_rest_day_guidance,
    build_template_summary,
    build_user_plan_context,
    build_yesterday_summary,
)

logger = get_logger(__name__)

_ROLE_NAMES = {"aveline": "七濑澪", "ling": "Ling"}

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class LLMPlanGenerator:
    """LLM 每日计划生成器

    用 LLM 生成明日活动计划，失败时回退到模板生成。
    """

    def __init__(
        self,
        templates: dict,
        model_path: str,
        fallback_generator: Optional[DailyPlanGenerator] = None,
    ):
        """
        Args:
            templates: {role_id: RoleScheduleTemplate} 字典
            model_path: LLM 模型路径，如 cloud:deepseek:qqbot1:deepseek-v4-pro
            fallback_generator: LLM 失败时用的回退生成器，None 时自动创建
        """
        self._templates = templates
        self._model_path = model_path
        self._fallback = fallback_generator or DailyPlanGenerator(templates)

    async def generate(
        self,
        role_id: str,
        date_str: str,
        yesterday_state: Optional[DailyState] = None,
    ) -> Optional[DailyPlan]:
        """为指定角色生成指定日期的活动计划

        Args:
            role_id: 角色 ID
            date_str: 日期 "2026-06-27"
            yesterday_state: 昨日状态（用于上下文）

        Returns:
            DailyPlan，失败时回退到模板生成
        """
        template = self._templates.get(role_id)
        if not template:
            logger.warning("LLMPlanGenerator: 未找到 %s 的模板，回退", role_id)
            return self._fallback.generate(role_id, date_str)

        try:
            raw = await self._call_llm(role_id, date_str, template, yesterday_state)
            plan = self._parse_llm_output(raw, role_id, date_str, template)
            if plan:
                logger.info(
                    "LLMPlanGenerator: 为 %s 生成 %s 的 LLM 计划，共 %d 个槽位",
                    role_id, date_str, len(plan.slots),
                )
                return plan
            logger.warning("LLMPlanGenerator: LLM 输出解析失败，回退到模板")
        except Exception as e:
            logger.error("LLMPlanGenerator: LLM 生成失败，回退到模板: %s", e, exc_info=True)

        return self._fallback.generate(role_id, date_str)

    async def _call_llm(
        self,
        role_id: str,
        date_str: str,
        template: RoleScheduleTemplate,
        yesterday_state: Optional[DailyState],
    ) -> str:
        """调用 LLM 生成计划，返回原始文本"""
        from core.services.scheduler import get_global_scheduler

        scheduler = get_global_scheduler()
        if scheduler is None:
            raise RuntimeError("scheduler 未初始化")

        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        weekday_cn = _WEEKDAY_CN[date_obj.weekday()]
        role_name = _ROLE_NAMES.get(role_id, role_id)

        # 构建近期状态摘要
        recent_status = self._build_recent_status(role_id, yesterday_state)

        # 构建角色性格 + 活动偏好段落（让两个角色计划差异化）
        role_personality = build_role_personality_section(role_id)

        # 构建用户当日计划软参考（让角色作息与用户节奏自然贴合）
        user_plan_context = await self._load_user_plan_context(date_str)

        user_prompt = CHARACTER_SCHEDULE_USER_PROMPT_TEMPLATE.format(
            role_name=role_name,
            role_id=role_id,
            plan_date_str=date_str,
            weekday_cn=weekday_cn,
            rest_day_guidance=build_rest_day_guidance(date_obj),
            wake_time=template.wake_time,
            sleep_time=template.sleep_time,
            role_personality=role_personality,
            template_summary=build_template_summary(template),
            yesterday_summary=build_yesterday_summary(yesterday_state),
            recent_status=recent_status,
            user_plan_context=user_plan_context,
        )

        messages = [
            {"role": "system", "content": CHARACTER_SCHEDULE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        raw = ""
        async for chunk in scheduler.submit_llm_task(
            messages,
            max_tokens=1500,
            temperature=0.8,
            model_path=self._model_path,
        ):
            if isinstance(chunk, str):
                raw += chunk
            elif isinstance(chunk, dict) and chunk.get("content"):
                raw += str(chunk.get("content") or "")

        return raw

    def _build_recent_status(self, role_id: str, yesterday_state: Optional[DailyState]) -> str:
        """构建近期状态摘要"""
        if not yesterday_state:
            return "（无近期记录，按常规作息安排）"
        plan = yesterday_state.get_plan(role_id)
        if not plan:
            return "（无近期记录，按常规作息安排）"
        parts = []
        if plan.today_peer_chat_count > 0:
            parts.append(f"昨日和同伴聊过 {plan.today_peer_chat_count} 次")
        parts.append(f"昨日最后活动：{plan.current_activity.value}")
        return "；".join(parts) if parts else "（无特殊状态）"

    async def _load_user_plan_context(self, date_str: str) -> str:
        """加载用户当日计划，格式化为软参考文本（注入角色日程 prompt）

        通过 JournalService.get_plan(date_str) 读取用户对应日期的计划。
        如果不存在则返回空字符串（不阻塞角色计划生成）。

        设计：软参考——角色计划仍按自身作息和偏好生成，只是参考用户节奏。
        失败容错：任何异常都返回空字符串，保证角色计划生成不被阻塞。

        Args:
            date_str: 角色计划日期 "2026-06-27"

        Returns:
            格式化的用户计划文本，或空字符串
        """
        try:
            from core.services.journal.service import get_journal_service
            js = get_journal_service()
            if js is None:
                return ""
            user_plan = await js.get_plan(date_str)
            context = build_user_plan_context(user_plan)
            if context:
                logger.info(
                    "LLMPlanGenerator: 加载用户 %s 计划作为软参考（%d 项）",
                    date_str,
                    len(getattr(user_plan, "items", []) or []),
                )
            return context
        except Exception as e:
            logger.debug("LLMPlanGenerator: 加载用户计划失败（软参考，跳过）: %s", e)
            return ""

    def _parse_llm_output(
        self,
        raw: str,
        role_id: str,
        date_str: str,
        template: RoleScheduleTemplate,
    ) -> Optional[DailyPlan]:
        """解析 LLM 输出为 DailyPlan

        包含校验和修补：时间不连续处填 idle，自动补 chat_eligible，自动补 sleeping 段。
        """
        data = self._extract_json(raw)
        if not data or not isinstance(data, dict):
            return None

        slots_raw = data.get("slots")
        if not isinstance(slots_raw, list) or not slots_raw:
            return None

        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        slots: list = []
        prev_end: Optional[datetime] = None

        for item in slots_raw:
            if not isinstance(item, dict):
                continue
            activity_str = str(item.get("activity") or "").strip().lower()
            start_str = str(item.get("start") or "").strip()
            end_str = str(item.get("end") or "").strip()
            if not activity_str or not start_str or not end_str:
                continue

            activity = ActivityType.from_str(activity_str)
            if activity == ActivityType.SLEEPING:
                # sleeping 由代码自动补，跳过 LLM 给的
                continue

            start_dt = self._parse_hhmm_to_datetime(start_str, date_obj)
            end_dt = self._parse_hhmm_to_datetime(end_str, date_obj)
            if not start_dt or not end_dt:
                continue
            # 处理跨天（end < start）
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

            # 时间不连续：用 idle 填补
            if prev_end and start_dt > prev_end:
                gap_activity = ActivityType.IDLE
                slots.append(
                    ActivitySlot(
                        activity=gap_activity,
                        planned_start=prev_end,
                        planned_end=start_dt,
                        flexible=True,
                        chat_eligible=gap_activity in CHAT_ELIGIBLE_ACTIVITIES,
                    )
                )

            chat_eligible = activity in CHAT_ELIGIBLE_ACTIVITIES
            slots.append(
                ActivitySlot(
                    activity=activity,
                    planned_start=start_dt,
                    planned_end=end_dt,
                    flexible=activity not in (ActivityType.BREAKFAST, ActivityType.LUNCH, ActivityType.DINNER),
                    chat_eligible=chat_eligible,
                )
            )
            prev_end = end_dt

        if not slots:
            return None

        # 自动补 sleeping 跨天段
        sleep_h, sleep_m = _parse_hhmm(template.sleep_time)
        wake_h, wake_m = _parse_hhmm(template.wake_time)
        sleep_start = datetime(date_obj.year, date_obj.month, date_obj.day, sleep_h, sleep_m)
        if (sleep_h, sleep_m) < (wake_h, wake_m):
            sleep_end = sleep_start + timedelta(days=1)
        else:
            sleep_end = sleep_start + timedelta(days=1)
        sleep_end = sleep_end.replace(hour=wake_h, minute=wake_m, second=0, microsecond=0)

        slots.append(
            ActivitySlot(
                activity=ActivityType.SLEEPING,
                planned_start=sleep_start,
                planned_end=sleep_end,
                flexible=False,
                chat_eligible=False,
            )
        )

        slots.sort(key=lambda s: s.planned_start)

        plan = DailyPlan(
            role_id=role_id,
            date=date_str,
            generated_at=get_current_time().timestamp(),
            slots=slots,
        )
        return plan

    def _extract_json(self, raw: str) -> Optional[dict]:
        """从 LLM 输出中提取 JSON（兼容 ```json 包裹和裸 JSON）"""
        if not raw:
            return None
        text = raw.strip()
        # 去 ```json 包裹
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        else:
            # 找第一个 { 到最后一个 }
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("LLMPlanGenerator: JSON 解析失败: %s, raw=%s", e, raw[:200])
            return None

    @staticmethod
    def _parse_hhmm_to_datetime(hhmm: str, date_obj) -> Optional[datetime]:
        """HH:MM → 当天 datetime"""
        try:
            h, m = _parse_hhmm(hhmm)
            return datetime(date_obj.year, date_obj.month, date_obj.day, h, m)
        except Exception:
            return None
