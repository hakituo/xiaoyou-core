from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.services.workspace.service import get_workspace_service
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("ReminderTool")


def _parse_time_of_day(time_str: str) -> Optional[tuple]:
    """解析 HH:MM 格式时间，失败返回 None。"""
    if not time_str:
        return None
    try:
        parts = str(time_str).strip().split(":")
        if len(parts) != 2:
            return None
        hh = int(parts[0])
        mm = int(parts[1])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return (hh, mm)
    except (ValueError, IndexError):
        pass
    return None


def _parse_weekdays(weekdays_str: str) -> List[int]:
    """解析星期字符串，返回 [1..7] 列表（1=周一, 7=周日）。

    支持格式：
    - "1,3,5" → [1, 3, 5]
    - "周一,周三,周五" → [1, 3, 5]
    - "mon,wed,fri" → [1, 3, 5]
    - "每天" / "daily" → [1,2,3,4,5,6,7]
    - "工作日" / "weekdays" → [1,2,3,4,5]
    - "周末" / "weekend" → [6,7]
    """
    if not weekdays_str:
        return []
    s = str(weekdays_str).strip().lower()

    # 中文/英文快捷词
    quick_map = {
        "每天": [1, 2, 3, 4, 5, 6, 7],
        "daily": [1, 2, 3, 4, 5, 6, 7],
        "工作日": [1, 2, 3, 4, 5],
        "weekdays": [1, 2, 3, 4, 5],
        "weekday": [1, 2, 3, 4, 5],
        "周末": [6, 7],
        "weekend": [6, 7],
    }
    if s in quick_map:
        return quick_map[s]

    # 单个数字/中文
    cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
    en_map = {
        "mon": 1, "monday": 1,
        "tue": 2, "tuesday": 2,
        "wed": 3, "wednesday": 3,
        "thu": 4, "thursday": 4,
        "fri": 5, "friday": 5,
        "sat": 6, "saturday": 6,
        "sun": 7, "sunday": 7,
    }

    result = set()
    # 按逗号/空格分割
    for part in s.replace(",", " ").replace("、", " ").split():
        part = part.strip()
        if not part:
            continue
        # 纯数字
        if part.isdigit():
            n = int(part)
            if 1 <= n <= 7:
                result.add(n)
            continue
        # 中文星期（"周一"或"一"）
        if part.startswith("周") or part.startswith("星期"):
            cn_char = part[-1]
            if cn_char in cn_map:
                result.add(cn_map[cn_char])
            continue
        # 单个中文
        if part in cn_map:
            result.add(cn_map[part])
            continue
        # 英文
        if part in en_map:
            result.add(en_map[part])
            continue

    return sorted(result)


def _compute_first_trigger_ts(
    time_of_day: str,
    weekdays: Optional[List[int]] = None,
    base_dt: Optional[datetime] = None,
) -> float:
    """计算首次触发时间戳。

    - time_of_day: HH:MM 格式
    - weekdays: None 或空 → 每天；非空 → 下一个匹配的周X
    - base_dt: 基准时间（默认当前时间）

    返回首次触发时间戳。如果今天的指定时间还没过，则今天触发；
    否则找下一个匹配日。
    """
    now_dt = base_dt or get_current_time()
    hh_mm = _parse_time_of_day(time_of_day)
    if hh_mm is None:
        # 无 time_of_day，5 分钟后触发（兜底）
        return (now_dt + timedelta(minutes=5)).timestamp()

    hh, mm = hh_mm
    target_days = sorted({d for d in (weekdays or []) if 1 <= d <= 7})

    # 不指定 weekdays → 每天
    if not target_days:
        target_days = [1, 2, 3, 4, 5, 6, 7]

    # 从今天开始往后找（最多 7 天）
    for offset in range(0, 8):
        candidate = now_dt + timedelta(days=offset)
        candidate = candidate.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # 今天的指定时间必须还没过
        if offset == 0 and candidate <= now_dt:
            continue
        if candidate.isoweekday() in target_days:
            return candidate.timestamp()

    # 理论上不会走到这里
    return (now_dt + timedelta(days=1)).timestamp()


class ReminderInput(BaseModel):
    minutes: float = Field(
        default=0,
        description=(
            "几分钟后提醒（支持小数）。与 at_time 二选一："
            "用 minutes 做相对时间提醒（如 30=30分钟后）；用 at_time 做绝对时间提醒。"
        ),
    )
    at_time: str = Field(
        default="",
        description=(
            "绝对时间触发，格式 'HH:MM'（如 '14:30'）或 'YYYY-MM-DD HH:MM'。"
            "留空则使用 minutes 做相对时间提醒。"
        ),
    )
    message: str = Field(description="提醒内容")
    recurrence: str = Field(
        default="none",
        description=(
            "重复类型。none=单次（默认），daily=每天，weekly=每周（需配合 weekdays），monthly=每月。"
        ),
    )
    weekdays: str = Field(
        default="",
        description=(
            "weekly 模式下生效。支持 '1,3,5' / '周一,周三,周五' / '工作日' / '周末' / '每天'。"
            "1=周一 ... 7=周日。"
        ),
    )


class ReminderTool(BaseTool):
    name = "set_reminder"
    description = (
        "设置提醒，支持相对时间、绝对时间和周期性重复。"
        "示例："
        "'3分钟后提醒我喝水'（minutes=3）；"
        "'每天 14:30 提醒我午休'（at_time=14:30, recurrence=daily）；"
        "'每周一三五 09:00 提醒我早会'（at_time=09:00, recurrence=weekly, weekdays=1,3,5）；"
        "'每月 1 号 10:00 提醒我写月报'（at_time=10:00, recurrence=monthly，首次触发选最近一天）。"
    )
    short_description = "设置提醒（支持绝对时间+周期重复）"
    category = "utility"
    args_schema = ReminderInput

    async def _run(
        self,
        message: str,
        minutes: float = 0,
        at_time: str = "",
        recurrence: str = "none",
        weekdays: str = "",
    ) -> str:
        if not message or not message.strip():
            return "Error: 提醒内容不能为空"

        # 规整 recurrence
        recurrence = (recurrence or "none").strip().lower()
        if recurrence not in ("none", "daily", "weekly", "monthly"):
            return f"Error: 不支持的重复类型 '{recurrence}'，可选: none/daily/weekly/monthly"

        # 解析 weekdays
        weekday_list: List[int] = []
        if recurrence == "weekly":
            weekday_list = _parse_weekdays(weekdays)
            if not weekday_list:
                return (
                    "Error: weekly 模式需要指定 weekdays，"
                    "如 '1,3,5' 或 '周一,周三,周五' 或 '工作日'"
                )

        try:
            ws = get_workspace_service()

            # 模式1: 绝对时间 + 周期
            if at_time and at_time.strip():
                at_time_str = at_time.strip()

                # 处理 "YYYY-MM-DD HH:MM" 完整日期格式（仅单次）
                if " " in at_time_str and "-" in at_time_str:
                    try:
                        dt = datetime.strptime(at_time_str, "%Y-%m-%d %H:%M")
                        trigger_ts = dt.timestamp()
                        # 完整日期格式不支持周期，强制单次
                        if recurrence != "none":
                            return "Error: 指定完整日期时仅支持单次提醒（recurrence=none）"
                        msg_id = await ws.schedule_message(
                            message=message,
                            trigger_ts=trigger_ts,
                        )
                        return (
                            f"成功设置提醒：'{message}'，"
                            f"将在 {at_time_str} 触发 (ID: {msg_id})。"
                        )
                    except ValueError:
                        return f"Error: 时间格式错误，应为 'YYYY-MM-DD HH:MM'，收到 '{at_time_str}'"

                # 处理 "HH:MM" 格式
                hh_mm = _parse_time_of_day(at_time_str)
                if hh_mm is None:
                    return f"Error: 时间格式错误，应为 'HH:MM'（如 '14:30'），收到 '{at_time_str}'"

                # 计算首次触发时间
                trigger_ts = _compute_first_trigger_ts(
                    time_of_day=at_time_str,
                    weekdays=weekday_list if recurrence == "weekly" else None,
                )

                trigger_dt = datetime.fromtimestamp(trigger_ts)
                trigger_str = trigger_dt.strftime("%Y-%m-%d %H:%M")

                if recurrence == "none":
                    msg_id = await ws.schedule_message(
                        message=message,
                        trigger_ts=trigger_ts,
                    )
                    return (
                        f"成功设置提醒：'{message}'，"
                        f"将在 {trigger_str} 触发 (ID: {msg_id})。"
                    )
                else:
                    msg_id = await ws.schedule_recurring_message(
                        message=message,
                        first_trigger_ts=trigger_ts,
                        recurrence=recurrence,
                        time_of_day=at_time_str,
                        weekdays=weekday_list,
                    )
                    desc = self._format_recurrence_desc(recurrence, weekday_list, at_time_str)
                    return (
                        f"成功设置周期提醒：'{message}'，"
                        f"首次触发 {trigger_str}，{desc} (ID: {msg_id})。"
                    )

            # 模式2: 相对时间（minutes）
            if minutes <= 0:
                return (
                    "Error: 必须提供 minutes（相对分钟数）或 at_time（绝对时间 HH:MM）"
                )

            trigger_ts = time.time() + (minutes * 60)

            # 相对时间 + 周期：以触发时间为基准，按 time_of_day 滚动
            if recurrence != "none":
                # 用触发时刻作为 time_of_day
                trigger_dt = datetime.fromtimestamp(trigger_ts)
                time_of_day_str = trigger_dt.strftime("%H:%M")
                msg_id = await ws.schedule_recurring_message(
                    message=message,
                    first_trigger_ts=trigger_ts,
                    recurrence=recurrence,
                    time_of_day=time_of_day_str,
                    weekdays=weekday_list,
                )
                desc = self._format_recurrence_desc(
                    recurrence, weekday_list, time_of_day_str
                )
                trigger_str = trigger_dt.strftime("%Y-%m-%d %H:%M")
                return (
                    f"成功设置周期提醒：'{message}'，"
                    f"首次触发 {trigger_str}（{minutes}分钟后），{desc} (ID: {msg_id})。"
                )

            # 单次相对时间提醒
            msg_id = await ws.schedule_message(
                message=message,
                trigger_ts=trigger_ts,
            )
            return (
                f"成功设置提醒：'{message}'，将在 {minutes} 分钟后触发 (ID: {msg_id})。"
            )

        except Exception as e:
            logger.warning(f"设置提醒失败: {e}", exc_info=True)
            return f"设置提醒失败: {str(e)}"

    @staticmethod
    def _format_recurrence_desc(
        recurrence: str, weekdays: List[int], time_of_day: str
    ) -> str:
        """格式化重复描述。"""
        if recurrence == "daily":
            return f"每天 {time_of_day} 重复"
        if recurrence == "weekly":
            day_names = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}
            days_str = "、".join(f"周{day_names[d]}" for d in weekdays)
            return f"每{days_str} {time_of_day} 重复"
        if recurrence == "monthly":
            return f"每月同一日 {time_of_day} 重复"
        return ""
