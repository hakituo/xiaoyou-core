#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time Utility Functions
Handles timezone-aware time operations.
"""

from datetime import datetime, timedelta
import pytz
from config.integrated_config import get_settings


def get_current_time() -> datetime:
    """
    获取配置时区的当前时间
    """
    settings = get_settings()
    tz_str = settings.system.timezone
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        # 降级到北京时间
        tz = pytz.timezone("Asia/Shanghai")

    return datetime.now(tz)


def get_current_time_str(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    获取配置时区的当前时间字符串
    """
    return get_current_time().strftime(format_str)


def format_timestamp(ts: float, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    将时间戳转换为配置时区的字符串
    """
    settings = get_settings()
    tz_str = settings.system.timezone
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("Asia/Shanghai")

    dt = datetime.fromtimestamp(ts, tz)
    return dt.strftime(format_str)


def get_time_period() -> str:
    """
    获取当前时间段（早上、中午、下午、晚上、深夜）
    """
    hour = get_current_time().hour
    if 5 <= hour < 11:
        return "早上"
    elif 11 <= hour < 13:
        return "中午"
    elif 13 <= hour < 18:
        return "下午"
    elif 18 <= hour < 23:
        return "晚上"
    else:
        return "深夜"


def get_diary_target_date(now: datetime | None = None, *, early_morning_threshold: int = 12) -> datetime:
    """获取日记/每日总结的目标日期。

    凌晨（默认 00:00 ~ 11:59）仍属于前一天的延续，应归到前一天。
    夜间任务在"一天结束后"运行，凌晨触发时前一天已完整结束，
    必须回顾前一天而非正在进行的当天（否则会写出 chat_turn_count=0 的空日记）。
    所有日记/摘要的日期归属必须走这个函数，禁止各自独立计算。

    Args:
        now: 当前时间，为 None 时自动获取配置时区时间。
        early_morning_threshold: 凌晨阈值小时数，默认 12（即 0~11 点算凌晨）。

    Returns:
        归属日的 datetime（仅日期部分有意义）。
    """
    if now is None:
        now = get_current_time()
    if now.hour < early_morning_threshold:
        return now - timedelta(days=1)
    return now


def get_diary_target_date_str(now: datetime | None = None, **kwargs) -> str:
    """get_diary_target_date 的字符串快捷方式，返回 YYYY-MM-DD。"""
    return get_diary_target_date(now, **kwargs).strftime("%Y-%m-%d")


def parse_hhmm(value: str) -> int | None:
    """将 HH:MM 格式的时间字符串转换为分钟数

    Args:
        value: 时间字符串，如 "09:30"

    Returns:
        从午夜开始的分钟数，如 570；解析失败返回 None
    """
    if not value:
        return None
    text = str(value).strip()
    if ":" not in text:
        return None
    try:
        hour_str, minute_str = text.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def now_iso() -> str:
    """获取配置时区当前时间的 ISO 字符串（带时区信息）。

    P2-4: 统一替代散落各处的 `datetime.now().isoformat()`。
    """
    return get_current_time().isoformat()


def now_str(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """获取配置时区当前时间的格式化字符串。"""
    return get_current_time().strftime(format_str)


def today_str() -> str:
    """获取配置时区当前日期字符串（YYYY-MM-DD）。

    注意：如果需要凌晨归属前一天的逻辑，请使用 `get_diary_target_date_str()`。
    """
    return get_current_time().strftime("%Y-%m-%d")


def from_timestamp(ts: float) -> datetime:
    """将时间戳转换为配置时区的 datetime。

    P2-4: 统一替代散落各处的 `datetime.fromtimestamp(ts)`（naive 转换）。
    """
    settings = get_settings()
    tz_str = settings.system.timezone
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("Asia/Shanghai")
    return datetime.fromtimestamp(ts, tz)


def ts_to_str(ts: float, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """将时间戳格式化为配置时区字符串（format_timestamp 的别名，更短）。"""
    return format_timestamp(ts, format_str)


def ts_to_iso(ts: float) -> str:
    """将时间戳转换为配置时区的 ISO 字符串。"""
    return from_timestamp(ts).isoformat()


def current_hour() -> int:
    """获取配置时区当前小时数（0-23）。

    P2-4: 统一替代散落各处的 `datetime.fromtimestamp(now).hour` 或
    `datetime.now().hour`。
    """
    return get_current_time().hour


def current_timestamp() -> float:
    """获取配置时区当前时间的时间戳。

    P2-4: 统一替代散落各处的 `datetime.now().timestamp()`。
    """
    return get_current_time().timestamp()
