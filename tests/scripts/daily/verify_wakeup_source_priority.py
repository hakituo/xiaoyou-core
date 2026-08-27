"""验证健康起床时间不再被聊天时间覆盖。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.daily.verify_wakeup_source_priority
"""

import json
import os
import shutil
import tempfile

from core.services.daily.extractor import ActivityExtractor
from core.services.daily.manager import get_daily_manager
from core.services.health_sync.wakeup import sync_wakeup_to_daily_record
from core.utils.singleton import SingletonFactory
from core.utils.time_utils import get_current_time
from memory.core.discourse import analyze_discourse, infer_state_event


def _write_legacy_wrong_record(root_dir: str, date_str: str) -> None:
    year, month, day = date_str.split("-")
    file_path = os.path.join(
        root_dir, str(int(year)), str(int(month)), str(int(day)), "daily_record.json"
    )
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(
            {
                "date": date_str,
                "sleep_cycle": {
                    "sleep": "01:12",
                    "wakeup": "13:56",
                    "duration": "12h44m",
                },
                "meals": [],
                "study": {"sessions": [], "summary": ""},
                "activities": [],
            },
            file,
            ensure_ascii=False,
        )


def main() -> None:
    temp_dir = tempfile.mkdtemp(prefix="wakeup_priority_")
    manager = get_daily_manager()
    original_root = manager.root_dir
    try:
        manager.root_dir = temp_dir
        now = get_current_time()
        date_str = now.strftime("%Y-%m-%d")
        _write_legacy_wrong_record(temp_dir, date_str)

        # 模拟 Samsung Health 上报北京时间 08:53。
        sleep_end = now.replace(hour=8, minute=53, second=0, microsecond=0)
        sync_result = sync_wakeup_to_daily_record(
            {"sleep_end": sleep_end.isoformat()}
        )
        assert sync_result["applied"] is True, sync_result

        record = manager.get_record(date_str)
        sleep_cycle = record["sleep_cycle"]
        assert sleep_cycle["wakeup"] == "08:53", sleep_cycle
        assert sleep_cycle["wakeup_source"] == "samsung_health", sleep_cycle

        # 用户讨论记录时，快速提取器不应把当前聊天时间当作起床时间。
        question = "撕，说什么呢，你好好看，跟我说这个记录的起床时间是多久"
        discourse = analyze_discourse(question)
        assert discourse["trigger_blocked"] is True, discourse
        assert infer_state_event(question, discourse) == "NONE"
        extractor = ActivityExtractor()
        assert extractor._apply_fast_record(question) is False

        # 即使后续某条聊天被误识别，低优先级来源也不能覆盖健康数据。
        manager.record_wakeup("13:56", source="chat_inferred")
        protected = manager.get_record(date_str)["sleep_cycle"]
        assert protected["wakeup"] == "08:53", protected
        assert "08:53" in manager.get_today_summary()
        assert "13:56" not in manager.get_today_summary()

        # 用户明确手动修正仍然拥有最高优先级。
        manager.update_sleep_cycle(wakeup_time="09:05", target_date=date_str)
        corrected = manager.get_record(date_str)["sleep_cycle"]
        assert corrected["wakeup"] == "09:05", corrected
        assert corrected["wakeup_source"] == "user_manual", corrected

        print("[OK] Samsung Health 08:53 覆盖历史错值 13:56")
        print("[OK] 讨论记录不触发起床写入")
        print("[OK] 聊天推断无法覆盖健康数据")
        print("[OK] 用户手动修正仍可覆盖健康数据")
    finally:
        manager.root_dir = original_root
        SingletonFactory._instances = {}
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
