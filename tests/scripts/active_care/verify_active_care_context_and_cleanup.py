"""验证 Active Care 日期、提醒目标、日志路由与脏数据清理修复。"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.chat_agent_components.persona_system.prompt.special_days import (  # noqa: E402
    correct_relative_holiday_claims,
    get_authoritative_calendar_prompt,
    remove_invalid_relative_holiday_clauses,
)
from core.services.active_care.core.reminder_handler import ReminderHandler  # noqa: E402
from core.services.journal.reminder_policy import (  # noqa: E402
    should_schedule_end_reminder,
)
from core.utils.logging.registry import ModuleLoggerNameFilter  # noqa: E402
from scripts.cleanup.clean_active_care_dirty_records import _load_and_clean  # noqa: E402


def verify_calendar_anchor() -> None:
    prompt = get_authoritative_calendar_prompt(date(2026, 8, 17), days_ahead=7)
    assert "七夕节：2026-08-19（2天后）" in prompt
    assert "不要主动提节日" in prompt
    corrected = correct_relative_holiday_claims(
        "洗完澡突然想到明天七夕——你有什么安排？[VOICE]",
        date(2026, 8, 17),
    )
    assert corrected == "洗完澡突然想到后天是七夕节——你有什么安排？[VOICE]"
    sanitized = remove_invalid_relative_holiday_clauses(
        "洗完澡准备护肤了，突然想到明天七夕——你这周末有什么安排没？[VOICE]",
        date(2026, 8, 17),
    )
    assert sanitized == "洗完澡准备护肤了，你这周末有什么安排没？[VOICE]"


def verify_reminder_target_guard() -> None:
    handler = ReminderHandler()
    reminder = "任务「物理复习」到时间该开始了；计划内容：完成错题整理"
    kept = handler.enforce_reminder_target("物理复习该开始啦。", reminder)
    assert kept == "物理复习该开始啦。"
    fallback = handler.enforce_reminder_target("明天七夕，你想怎么过？", reminder)
    assert "物理复习" in fallback
    assert "七夕" not in fallback
    natural = handler.enforce_reminder_target(
        "emmmm 你那个复盘写了吗 [VOICE]",
        "任务「睡前复盘与明日计划」结束时间到了，该告一段落",
    )
    assert natural == "emmmm 你那个复盘写了吗 [VOICE]"
    gentle = handler.enforce_reminder_target(
        "emmmm 你还在吗 [VOICE]",
        "任务「睡前复盘与明日计划」到时间该开始了",
    )
    assert gentle == "睡前复盘与明日计划要开始啦，要不要先弄一点？"
    assert not should_schedule_end_reminder(15)
    assert should_schedule_end_reminder(30)


def verify_module_log_filter() -> None:
    module_filter = ModuleLoggerNameFilter(["ACTIVE_CARE_MSG"])
    active_record = logging.LogRecord(
        "ACTIVE_CARE_MSG", logging.INFO, __file__, 1, "ok", (), None
    )
    unrelated_record = logging.LogRecord(
        "ChatAgent", logging.INFO, __file__, 1, "noise", (), None
    )
    assert module_filter.filter(active_record)
    assert not module_filter.filter(unrelated_record)
    module_filter.add_logger_name("ACTIVE_CARE_EXECUTOR")
    executor_record = logging.LogRecord(
        "ACTIVE_CARE_EXECUTOR", logging.INFO, __file__, 1, "ok", (), None
    )
    assert module_filter.filter(executor_record)


def verify_cleanup_rules() -> None:
    records = [
        {
            "role": "assistant",
            "source": "active_care",
            "content": "明天七夕，你想干嘛？",
            "created_at": "2026-08-17 18:00:00",
        },
        {
            "role": "user",
            "source": "user",
            "content": "你怎么老是说明天七夕，日期不对",
            "created_at": "2026-08-17 18:01:00",
        },
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "2026" / "08" / "17" / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
            encoding="utf-8",
        )
        findings = []
        cleaned, changed, is_jsonl = _load_and_clean(path, findings, [])
    assert changed and is_jsonl
    assert len(cleaned) == 1
    assert cleaned[0]["role"] == "user", "用户的纠正消息不得被误删"
    assert any("权威农历日期冲突" in item.reason for item in findings)


def main() -> int:
    verify_calendar_anchor()
    verify_reminder_target_guard()
    verify_module_log_filter()
    verify_cleanup_rules()
    print("PASS: Active Care 日期、提醒目标、日志路由与脏数据清理验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
