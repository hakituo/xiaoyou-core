"""日程提醒的共享策略。"""

MIN_END_REMINDER_DURATION_MINUTES = 30


def should_schedule_end_reminder(duration_minutes: int | float | None) -> bool:
    """短计划只保留开始提醒，避免开始后很快再次打扰用户。"""
    try:
        return float(duration_minutes or 0) >= MIN_END_REMINDER_DURATION_MINUTES
    except (TypeError, ValueError):
        return False
