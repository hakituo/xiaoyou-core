"""角色日常计划查看工具。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.services.character_daily.plan_view import (
    format_plan_for_tool,
    get_peer_role_id,
    get_role_display_name,
)
from core.services.character_daily.state import DailyStateStore
from core.tools.base import BaseTool
from core.utils.data_paths import _resolve_scope_from_active_persona
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("CharacterDailyPlanTool")

_VALID_TARGETS = {"self", "peer", "both", "aveline", "ling"}


class GetCharacterDailyPlanInput(BaseModel):
    target: str = Field(
        default="self",
        description=(
            "要查看谁的计划：self（自己）/ peer（同伴）/ both（两人都看）"
            "/ aveline / ling。默认 self。"
        ),
    )
    date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD。默认当前已生成的日期；当前通常只保留今天的计划。",
    )
    detail_level: str = Field(
        default="summary",
        description="返回粒度：summary（当前+接下来）或 full（完整时间线）。",
    )


class GetCharacterDailyPlanTool(BaseTool):
    name = "get_character_daily_plan"
    description = (
        "查看角色日常系统里已经生成的每日计划。"
        "可以看自己今天要做什么、同伴今天安排了什么，"
        "也可以一次查看两个人的计划。"
        "当用户问“你今天打算干嘛”“Ling今天安排是什么”“你们俩今天都在做什么”时优先使用。"
    )
    short_description = "查看自己/同伴的角色日常计划"
    category = "daily"
    args_schema = GetCharacterDailyPlanInput
    enabled_by_default = True

    async def _run(
        self,
        target: str = "self",
        date: Optional[str] = None,
        detail_level: str = "summary",
    ) -> str:
        normalized_target = str(target or "self").strip().lower()
        if normalized_target not in _VALID_TARGETS:
            return (
                f"无效的 target={target}。"
                "可选值：self / peer / both / aveline / ling。"
            )

        normalized_detail = str(detail_level or "summary").strip().lower()
        if normalized_detail not in {"summary", "full"}:
            return "detail_level 只能是 summary 或 full。"

        current_role = _resolve_scope_from_active_persona()
        roles = self._resolve_target_roles(normalized_target, current_role)
        state = self._load_state()
        if not state or not state.date:
            return "角色日常系统当前还没有已生成的计划。"

        target_date = date or state.date
        if target_date != state.date:
            return (
                f"角色日常系统当前仅保留 {state.date} 的已生成计划，"
                f"暂时没有 {target_date} 的角色计划。"
            )

        now = get_current_time()
        reports = []
        for role_id in roles:
            plan = state.get_plan(role_id)
            reports.append(
                format_plan_for_tool(
                    plan,
                    role_id=role_id,
                    detail_level=normalized_detail,
                    now=now,
                )
            )

        role_names = "、".join(get_role_display_name(role_id) for role_id in roles)
        header = (
            f"已获取 {role_names} 在 {target_date} 的角色日常计划"
            f"（查看视角：{get_role_display_name(current_role)}）。"
        )
        return header + "\n\n" + "\n\n".join(reports)

    @staticmethod
    def _resolve_target_roles(target: str, current_role: str) -> list[str]:
        if target == "self":
            return [current_role]
        if target == "peer":
            return [get_peer_role_id(current_role)]
        if target == "both":
            peer_role = get_peer_role_id(current_role)
            return [current_role, peer_role]
        return [target]

    @staticmethod
    def _load_state():
        try:
            from core.services.character_daily.engine import get_character_daily_engine

            engine = get_character_daily_engine()
            if engine and getattr(engine, "state", None) and engine.state.date:
                return engine.state
        except Exception as exc:
            logger.debug("读取 CharacterDailyEngine 内存态失败，回退磁盘状态: %s", exc)

        try:
            return DailyStateStore().load()
        except Exception as exc:
            logger.warning("读取角色日常状态失败: %s", exc)
            return None
