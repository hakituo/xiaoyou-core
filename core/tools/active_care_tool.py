from __future__ import annotations

import time
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

from core.tools.base import BaseTool


class AdjustFrequencyInput(BaseModel):
    action: Literal["increase", "decrease", "set"] = Field(
        description="调整方式：increase=增加频率(缩短间隔)，decrease=减少频率(延长间隔)，set=直接设定间隔"
    )
    minutes: Optional[float] = Field(
        default=None,
        description="间隔分钟数。action=set时必填，表示设定的间隔；action=increase/decrease时可选，表示调整的幅度（默认30分钟）"
    )


class PauseActiveCareInput(BaseModel):
    duration_minutes: float = Field(
        description="暂停时长（分钟），例如60表示暂停1小时，120表示暂停2小时"
    )


class ScheduleCareMessageInput(BaseModel):
    delay_minutes: float = Field(
        description="延迟多少分钟后发送主动关怀消息，例如120表示2小时后"
    )
    topic_hint: Optional[str] = Field(
        default="",
        description="话题提示，例如'提醒喝水'、'问问学习进度'，留空则由AI自行决定内容"
    )


class ToggleActiveCareInput(BaseModel):
    enabled: bool = Field(
        description="true=开启主动关怀，false=关闭主动关怀"
    )


class GetActiveCareStatusInput(BaseModel):
    pass


class AdjustActiveCareFrequencyTool(BaseTool):
    name = "adjust_active_care_frequency"
    description = (
        "调整主动关怀（active care）的消息发送频率。"
        "当用户说'少发一点'、'发频繁一点'、'每隔X分钟发一次'、'别那么频繁'等涉及关怀频率的话时调用此工具。"
        "action=increase表示增加频率（缩短间隔），action=decrease表示减少频率（延长间隔），action=set表示直接设定间隔分钟数。"
    )
    short_description = "调整主动关怀消息频率"
    category = "active_care"
    args_schema = AdjustFrequencyInput

    async def _run(self, action: str, minutes: Optional[float] = None) -> str:
        try:
            from config.integrated_config import get_settings
            settings = get_settings()
            current_gap = settings.life_simulation.active_care_min_gap_seconds
            current_minutes = current_gap / 60.0

            if action == "set":
                if minutes is None or minutes <= 0:
                    return "错误：设定间隔时必须提供正数的分钟数"
                new_gap = max(60, int(minutes * 60))
                settings.life_simulation.active_care_min_gap_seconds = new_gap
                new_minutes = new_gap / 60.0
                return (
                    f"已将主动关怀间隔设定为 {new_minutes:.0f} 分钟"
                    f"（原间隔 {current_minutes:.0f} 分钟）。"
                )

            delta_minutes = minutes if minutes and minutes > 0 else 30
            delta_seconds = int(delta_minutes * 60)

            if action == "increase":
                new_gap = max(60, current_gap - delta_seconds)
                settings.life_simulation.active_care_min_gap_seconds = new_gap
                new_minutes = new_gap / 60.0
                return (
                    f"已增加主动关怀频率，间隔从 {current_minutes:.0f} 分钟"
                    f"缩短到 {new_minutes:.0f} 分钟。"
                )

            if action == "decrease":
                new_gap = min(7200, current_gap + delta_seconds)
                settings.life_simulation.active_care_min_gap_seconds = new_gap
                new_minutes = new_gap / 60.0
                return (
                    f"已减少主动关怀频率，间隔从 {current_minutes:.0f} 分钟"
                    f"延长到 {new_minutes:.0f} 分钟。"
                )

            return f"未知的调整方式: {action}"
        except Exception as e:
            return f"调整频率失败: {str(e)}"


class PauseActiveCareTool(BaseTool):
    name = "pause_active_care"
    description = (
        "暂停主动关怀（active care）一段时间。"
        "当用户说'暂时别来烦我'、'安静一会儿'、'先别发消息'、'休息X小时'等要求暂停关怀的话时调用此工具。"
        "暂停期间不会主动发送关怀消息，到期后自动恢复。"
    )
    short_description = "暂停主动关怀一段时间"
    category = "active_care"
    args_schema = PauseActiveCareInput

    async def _run(self, duration_minutes: float) -> str:
        if duration_minutes <= 0:
            return "错误：暂停时长必须大于0分钟"

        try:
            from core.services.active_care.core.service import get_active_care_service
            svc = get_active_care_service()
            duration_seconds = int(duration_minutes * 60)
            success = await svc.pause(duration_seconds=duration_seconds)
            if success:
                hours = duration_minutes / 60.0
                if hours >= 1:
                    time_desc = f"{hours:.1f} 小时"
                else:
                    time_desc = f"{duration_minutes:.0f} 分钟"
                return f"已暂停主动关怀 {time_desc}，到期后自动恢复。"
            return "暂停主动关怀失败，服务可能未启动。"
        except Exception as e:
            return f"暂停主动关怀失败: {str(e)}"


class ScheduleCareMessageTool(BaseTool):
    name = "schedule_active_care_message"
    description = (
        "安排一个延迟的主动关怀消息。"
        "当用户说'X小时后提醒我/找我/给我发消息'、'过一会儿再来'、'晚点再聊'等指定时间发送关怀的话时调用此工具。"
        "可以指定话题提示，也可以让AI自行决定内容。"
    )
    short_description = "定时发送主动关怀消息"
    category = "active_care"
    args_schema = ScheduleCareMessageInput

    async def _run(self, delay_minutes: float, topic_hint: str = "") -> str:
        if delay_minutes <= 0:
            return "错误：延迟时间必须大于0分钟"

        try:
            from core.services.active_care.scheduling.delayed_scheduler import get_delayed_scheduler
            scheduler = get_delayed_scheduler()

            delay_seconds = delay_minutes * 60
            trigger_time = datetime.fromtimestamp(time.time() + delay_seconds)
            time_str = trigger_time.strftime("%H:%M")

            scheduler.schedule_task(
                delay_seconds=delay_seconds,
                task_type="user_requested_follow_up",
                context={
                    "topic_hint": topic_hint,
                    "source": "user_tool_call",
                },
                priority=5,
                source_message=f"用户请求在{delay_minutes:.0f}分钟后发送关怀消息",
                action_hint=topic_hint or "用户请求的定时关怀",
            )

            hours = delay_minutes / 60.0
            if hours >= 1:
                time_desc = f"{hours:.1f} 小时后（{time_str}）"
            else:
                time_desc = f"{delay_minutes:.0f} 分钟后（{time_str}）"

            hint_text = f"，话题：{topic_hint}" if topic_hint else ""
            return f"已安排在 {time_desc} 发送主动关怀消息{hint_text}。"
        except Exception as e:
            return f"安排定时关怀失败: {str(e)}"


class ToggleActiveCareTool(BaseTool):
    name = "toggle_active_care"
    description = (
        "开启或关闭主动关怀（active care）功能。"
        "当用户明确说'开启/关闭主动关怀'、'以后别主动找我了'、'重新开始主动关怀'等彻底开关关怀的话时调用此工具。"
        "注意：如果只是暂时不想被打扰，应该用 pause_active_care 而非关闭。"
    )
    short_description = "开关主动关怀功能"
    category = "active_care"
    args_schema = ToggleActiveCareInput

    async def _run(self, enabled: bool) -> str:
        try:
            from core.managers.preference_manager import get_preference_manager
            prefs = get_preference_manager()
            await prefs.set_active_care(enabled)
            if enabled:
                return "主动关怀已开启，我会适时找你聊天。"
            return "主动关怀已关闭，没有你的允许我不会主动打扰你。"
        except Exception as e:
            return f"切换主动关怀失败: {str(e)}"


class GetActiveCareStatusTool(BaseTool):
    name = "get_active_care_status"
    description = (
        "获取主动关怀（active care）的当前状态，包括是否开启、当前频率间隔、暂停状态、待执行的延迟任务等。"
        "当用户问'当前关怀设置'、'主动关怀什么状态'、'多久发一次'等查询状态的话时调用此工具。"
    )
    short_description = "查询主动关怀当前状态"
    category = "active_care"
    args_schema = GetActiveCareStatusInput

    async def _run(self) -> str:
        try:
            from config.integrated_config import get_settings
            from core.managers.preference_manager import get_preference_manager

            settings = get_settings()
            prefs = get_preference_manager()

            enabled = prefs.is_active_care_enabled()
            min_gap_seconds = settings.life_simulation.active_care_min_gap_seconds
            min_gap_minutes = min_gap_seconds / 60.0
            daily_limit = settings.life_simulation.active_care_daily_limit

            status_parts = [
                f"主动关怀状态：{'开启' if enabled else '关闭'}",
                f"最小间隔：{min_gap_minutes:.0f} 分钟",
                f"每日上限：{daily_limit} 条",
            ]

            try:
                from core.services.active_care.core.service import get_active_care_service
                svc = get_active_care_service()
                runtime = svc.get_runtime_status()
                next_decision_in = runtime.get("next_decision_in_seconds", 0)
                if next_decision_in > 0:
                    next_minutes = next_decision_in / 60.0
                    status_parts.append(f"下次决策：{next_minutes:.0f} 分钟后")
                delayed_count = runtime.get("delayed_tasks_pending", 0)
                if delayed_count > 0:
                    status_parts.append(f"待执行延迟任务：{delayed_count} 个")
            except Exception:
                pass

            try:
                from core.services.active_care.scheduling.delayed_scheduler import get_delayed_scheduler
                scheduler = get_delayed_scheduler()
                pending = scheduler.get_pending_tasks()
                if pending:
                    for t in pending[:3]:
                        remaining = t.get("remaining_seconds", 0)
                        hint = t.get("action_hint", "")
                        remaining_min = remaining / 60.0
                        hint_text = f"（{hint}）" if hint else ""
                        status_parts.append(
                            f"  - 延迟任务：{remaining_min:.0f}分钟后触发{hint_text}"
                        )
            except Exception:
                pass

            return "\n".join(status_parts)
        except Exception as e:
            return f"获取状态失败: {str(e)}"
