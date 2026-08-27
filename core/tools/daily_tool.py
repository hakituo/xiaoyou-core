import asyncio
from typing import Optional, Type, Literal
from pydantic import BaseModel, Field
from core.tools.base import BaseTool
from core.services.daily.manager import get_daily_manager
from core.utils.logger import get_logger

logger = get_logger("DAILY_TOOL")


class RecordActivityInput(BaseModel):
    category: Literal["wakeup", "sleep", "meal", "study", "activity"] = Field(
        description="活动类别：wakeup(起床), sleep(睡觉), meal(吃饭), "
        "study(学习), activity(其他活动)"
    )
    content: Optional[str] = Field(
        default="",
        description="活动内容描述。对于 meal 是食物内容，对于 study 是科目，"
        "对于 activity 是具体事项。",
    )
    detail: Optional[str] = Field(
        default="",
        description="额外细节。例如 meal 的 'breakfast/lunch/dinner'，"
        "或 study 的具体内容。",
    )
    time_str: Optional[str] = Field(
        default=None,
        description="时间字符串(HH:MM格式)。用于指定活动发生的时间。"
        "对于sleep类别特别重要：凌晨0-9点的睡眠会自动归到前一天的记录。",
    )


class RecordActivityTool(BaseTool):
    name = "record_daily_activity"
    description = (
        "记录用户的每日生活细节，形成当日画像。"
        "当用户提到起床、吃饭、学习、玩游戏等日常行为时调用。\n"
        "【睡眠记录特殊规则】\n"
        "- 用户经常熬夜，凌晨0-9点睡觉会自动记录到\"前一天\"的记录中\n"
        "- 例如：凌晨2点睡觉会记录到昨天的daily_record.json，作为\"昨晚睡觉时间\"\n"
        "- 9点之后睡觉则认为是白天补觉，记录到当天\n"
        "- 如果用户提到具体睡觉时间，请通过time_str参数传递\n"
        "【起床记录特殊规则】\n"
        "- 凌晨0-5点不记录为正式起床（可能是半夜起来上厕所/喝水）\n"
        "- 只有5点之后才会记录为正式起床"
    )
    short_description = "记录用户日常活动（起床/吃饭/学习/睡觉）"
    category = "daily"
    args_schema: Type[BaseModel] = RecordActivityInput

    async def _run(
        self,
        category: str,
        content: str = "",
        detail: str = "",
        time_str: Optional[str] = None
    ) -> str:
        manager = get_daily_manager()

        # P1-4: manager 的 record_xxx 内部含文件 IO，统一放到线程池避免阻塞事件循环
        if category == "wakeup":
            result = await asyncio.to_thread(manager.record_wakeup, time_str)
            await self._sync_wakeup_to_active_care(time_str)
            return result

        elif category == "sleep":
            result = await asyncio.to_thread(manager.record_sleep, time_str)
            await self._sync_sleep_to_active_care(time_str)
            return result

        elif category == "meal":
            meal_type = (
                detail
                if detail in ["breakfast", "lunch", "dinner", "snack"]
                else "meal"
            )
            return await asyncio.to_thread(manager.record_meal, meal_type, content)

        elif category == "study":
            topic = content
            desc = detail
            return await asyncio.to_thread(manager.record_study, topic, desc)

        elif category == "activity":
            return await asyncio.to_thread(manager.record_activity, "misc", content)

        return "未知的活动类别"

    async def _sync_sleep_to_active_care(self, time_str: Optional[str] = None) -> None:
        """同步睡眠记录到 Active Care 状态（使用统一管理器）

        P1-4: 内部 sync_*_time_sync 是同步 IO，包装到线程池执行。
        """
        try:
            from core.services.active_care.state import get_sleep_state_manager
            manager = get_sleep_state_manager()
            await asyncio.to_thread(manager.sync_sleep_time_sync, time_str)
        except Exception as e:
            logger.warning(f"Failed to sync sleep to active care: {e}")

    async def _sync_wakeup_to_active_care(self, time_str: Optional[str] = None) -> None:
        """同步起床记录到 Active Care 状态（使用统一管理器）

        P1-4: 内部 sync_*_time_sync 是同步 IO，包装到线程池执行。
        """
        try:
            from core.services.active_care.state import get_sleep_state_manager
            manager = get_sleep_state_manager()
            await asyncio.to_thread(manager.sync_wakeup_time_sync, time_str)
        except Exception as e:
            logger.warning(f"Failed to sync wakeup to active care: {e}")


class GetDailySummaryTool(BaseTool):
    name = "get_daily_summary"
    description = "获取用户今天的完整生活画像（作息、饮食、学习情况）。"
    short_description = "获取用户今日生活画像"
    category = "daily"

    async def _run(self) -> str:
        manager = get_daily_manager()
        # P1-4: get_today_summary 内部读 JSON 文件，放到线程池避免阻塞事件循环
        return await asyncio.to_thread(manager.get_today_summary)


class UpdateSleepRecordInput(BaseModel):
    sleep_time: Optional[str] = Field(
        default=None,
        description="睡觉时间(HH:MM格式，如 '07:30')。仅修正睡觉时间时填写，"
        "不修改则留空。凌晨0-9点的睡眠会自动归到前一天的记录。",
    )
    wakeup_time: Optional[str] = Field(
        default=None,
        description="起床时间(HH:MM格式，如 '17:00')。仅修正起床时间时填写，"
        "不修改则留空。",
    )
    target_date: Optional[str] = Field(
        default=None,
        description="指定修正的日期(YYYY-MM-DD格式，如 '2026-07-30')。"
        "不填则自动判断：若提供 sleep_time 按熬夜规则归到前一天/当天，否则默认今天。",
    )


class UpdateSleepRecordTool(BaseTool):
    name = "update_sleep_record"
    description = (
        "修正作息记录中的睡觉/起床时间。"
        "当用户指出系统记录的作息数据有误时调用此工具（例如用户说'我其实是7点睡的，不是19点'）。\n"
        "【适用场景】\n"
        "- 系统把聊天时间误识别成睡觉/起床时间\n"
        "- 用户明确指出记录的时间不对\n"
        "- 用户要求修改昨晚的作息数据\n"
        "【说明】\n"
        "- 此工具会绕过自动记录的保护逻辑，直接覆盖 sleep_cycle 字段\n"
        "- sleep_time 和 wakeup_time 至少提供一个，可同时提供\n"
        "- 修正后会自动重算睡眠时长，并同步到 Active Care 状态\n"
        "- 异常时长（<1h 或 >16h）会被置为 None，避免显示错误数据"
    )
    short_description = "修正作息记录（睡觉/起床时间）"
    category = "daily"
    args_schema: Type[BaseModel] = UpdateSleepRecordInput

    async def _run(
        self,
        sleep_time: Optional[str] = None,
        wakeup_time: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> str:
        manager = get_daily_manager()
        # update_sleep_cycle 内部含文件 IO，放到线程池避免阻塞事件循环
        result = await asyncio.to_thread(
            manager.update_sleep_cycle,
            sleep_time,
            wakeup_time,
            target_date,
        )

        # 同步到 Active Care 状态
        await self._sync_correction_to_active_care(
            sleep_time, wakeup_time, target_date
        )

        return result

    async def _sync_correction_to_active_care(
        self,
        sleep_time: Optional[str],
        wakeup_time: Optional[str],
        target_date: Optional[str],
    ) -> None:
        """将修正后的作息同步到 Active Care 状态

        P1-4: 内部 sync_*_time_sync 是同步 IO，包装到线程池执行。
        """
        try:
            from core.services.active_care.state import get_sleep_state_manager
            manager = get_sleep_state_manager()
            if sleep_time:
                await asyncio.to_thread(
                    manager.sync_sleep_time_sync, sleep_time, target_date
                )
            if wakeup_time:
                await asyncio.to_thread(manager.sync_wakeup_time_sync, wakeup_time)
        except Exception as e:
            logger.warning(f"Failed to sync sleep correction to active care: {e}")
