# -*- coding: utf-8 -*-
"""验证日志按板块分流并生成重要摘要。"""

import logging
import shutil
import tempfile
from pathlib import Path

from core.utils.logging.registry import (
    ImportantLogFilter,
    LogSectionFilter,
    _create_routed_file_handler,
    _write_daily_log_index,
    classify_log_section,
)


def _record(name: str, level: int, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, message, (), None)


def main() -> int:
    expected_sections = {
        "ACTIVE_CARE_EXECUTOR": "active_care",
        "AVELINE_SERVICE": "conversation",
        "HealthWakeup": "health_daily",
        "DAILY_MANAGER": "health_daily",
        "LLM.STREAM_GENERATOR": "llm_media",
        "core.interfaces.websocket.heartbeat_service": "scheduler_runtime",
        "QQ_ADAPTER": "integrations",
        "unmapped_component": "other",
    }
    for logger_name, expected in expected_sections.items():
        actual = classify_log_section(logger_name)
        assert actual == expected, (logger_name, actual, expected)

    active_record = _record("ACTIVE_CARE_EXECUTOR", logging.INFO, "普通决策")
    assert LogSectionFilter("active_care").filter(active_record)
    assert not LogSectionFilter("conversation").filter(active_record)

    important_filter = ImportantLogFilter()
    assert important_filter.filter(
        _record("HealthWakeup", logging.INFO, "手表检测到起床")
    )
    assert important_filter.filter(
        _record("anything", logging.WARNING, "需要关注")
    )
    assert not important_filter.filter(
        _record("heartbeat", logging.INFO, "WebSocket Statistics")
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="sectioned_logging_"))
    try:
        daily_dir = temp_dir / "2026" / "8" / "18"
        daily_dir.mkdir(parents=True)
        _write_daily_log_index(str(daily_dir))
        index = (daily_dir / "README.md").read_text(encoding="utf-8")
        assert "important.log" in index
        assert "sections/01_active_care.log" in index
        assert "sections/07_other.log" in index
        assert "xiaoyou_main.log" in index

        config = {
            "log_dir": str(daily_dir),
            "rotation_type": "size",
            "max_bytes": 1024,
            "backup_count": 1,
            "use_json": False,
        }
        handler = _create_routed_file_handler(
            str(daily_dir / "sections" / "01_active_care.log"), config
        )
        try:
            handler.addFilter(LogSectionFilter("active_care"))
            handler.handle(active_record)
            today_path = Path(handler._today_log_dir())
            assert today_path.parent.name == "sections"
            assert today_path.name == "01_active_care.log"
            assert today_path.parents[4] == temp_dir
            assert "普通决策" in today_path.read_text(encoding="utf-8")
        finally:
            handler.close()

        important_path = daily_dir / "important.log"
        important_handler = _create_routed_file_handler(
            str(important_path), config
        )
        try:
            important_handler.addFilter(ImportantLogFilter())
            important_handler.handle(
                _record("anything", logging.WARNING, "需要关注")
            )
            important_handler.handle(
                _record("heartbeat", logging.INFO, "WebSocket Statistics")
            )
            important_text = important_path.read_text(encoding="utf-8")
            assert "需要关注" in important_text
            assert "WebSocket Statistics" not in important_text
        finally:
            important_handler.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("[OK] logger 会且只会进入一个功能板块")
    print("[OK] important.log 仅保留警告/错误和关键事件")
    print("[OK] 当日 README.md 提供板块导航")
    print("[OK] 板块子目录跨天后仍写入正确日期目录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
