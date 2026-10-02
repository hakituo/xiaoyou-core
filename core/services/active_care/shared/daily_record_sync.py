"""
睡眠区间回写 Daily Record

从原 `shared/constants.py` 拆出：本模块是 shared/ 中唯一带 IO 副作用的部分
（会实例化 DailyActivityManager 并写盘），单独成模块后，只用常量/纯函数的
调用方不会再间接依赖 Daily 模块，降低循环导入风险。
"""


def sync_sleep_to_daily_record(
    sleep_start_ts: float,
    wakeup_ts: float,
    min_duration_seconds: float = 1800,
) -> bool:
    """把一次达到最短时长的睡眠区间写入 Daily Record。

    Args:
        sleep_start_ts: 入睡时间戳
        wakeup_ts: 起床时间戳
        min_duration_seconds: 最短有效睡眠时长，默认 30 分钟

    Returns:
        bool: 是否成功写入
    """
    if sleep_start_ts <= 0:
        return False
    duration_seconds = wakeup_ts - sleep_start_ts
    if duration_seconds < min_duration_seconds:
        return False
    try:
        from datetime import datetime

        from core.services.daily.manager import DailyActivityManager

        sleep_dt = datetime.fromtimestamp(sleep_start_ts)
        wakeup_dt = datetime.fromtimestamp(wakeup_ts)
        sleep_hhmm = sleep_dt.strftime("%H:%M")
        wakeup_hhmm = wakeup_dt.strftime("%H:%M")
        daily_mgr = DailyActivityManager()
        daily_mgr.record_sleep(sleep_hhmm)
        daily_mgr.record_wakeup(wakeup_hhmm, source="active_care_session")
        return True
    except Exception:
        return False


__all__ = ["sync_sleep_to_daily_record"]
