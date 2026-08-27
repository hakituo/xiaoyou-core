"""验证 short_term 写入边界、紧凑落盘和现有数据清理结果。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.data_paths import resolve_memory_user_id  # noqa: E402
from memory.core.readable_ops import (  # noqa: E402
    SHORT_TERM_DISK_MAX_BYTES,
    build_short_term_disk_records,
)
from memory.core.storage import is_short_term_dialogue  # noqa: E402


class FakeManager:
    @staticmethod
    def _normalize_memory_record(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return record, False


def dialogue(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "memory-id",
        "content": "正常对话",
        "timestamp": 1.0,
        "created_at": "2026-08-24T00:00:00+08:00",
        "source": "user",
        "role": "user",
        "category": "daily",
        "memory_type": "dialogue",
        "is_important": False,
        "weight": 2.0,
        "topics": ["daily"],
        "emotions": ["neutral"],
        "emotion": "neutral",
        "scopes": ["local", "cloud"],
        "readable_title": "不应落盘",
        "readable_summary": "不应落盘",
        "display_tags": ["不应落盘"],
        "embedding": [0.1, 0.2],
        "metadata": {
            "event_ref": {"event_id": "event-1"},
            "message_id": "message-1",
            "thought": "不应落盘",
            "reply_content": "不应落盘",
        },
    }
    record.update(overrides)
    return record


def verify_code_boundaries() -> None:
    assert is_short_term_dialogue(dialogue())
    assert is_short_term_dialogue(dialogue(source="active_care", role="assistant"))
    assert not is_short_term_dialogue(dialogue(memory_type="event_summary"))
    assert not is_short_term_dialogue(dialogue(source="system_summary", role="system"))
    assert not is_short_term_dialogue(dialogue(category="thinking", role="system"))
    assert not is_short_term_dialogue(dialogue(category="sensitive"))

    records = [
        dialogue(id=f"id-{index}", timestamp=float(index), content="内容" * 1200)
        for index in range(60)
    ]
    compact = build_short_term_disk_records(FakeManager(), records)
    payload = json.dumps(compact, ensure_ascii=False, indent=2).encode("utf-8")
    assert len(payload) <= SHORT_TERM_DISK_MAX_BYTES
    assert compact[-1]["id"] == "id-59"
    assert "readable_title" not in compact[-1]
    assert "embedding" not in compact[-1]
    assert "thought" not in compact[-1].get("metadata", {})
    assert "reply_content" not in compact[-1].get("metadata", {})

    assert resolve_memory_user_id("shared__persona__aveline_qq_master") == "shared__scope__aveline"
    assert (
        resolve_memory_user_id("private_123456789__persona__ling_qq_master")
        == "private_123456789__scope__ling"
    )


def verify_existing_data() -> tuple[int, int, int]:
    data_root = PROJECT_ROOT / "companion_data"
    files = sorted(
        path
        for path in data_root.rglob("*_short.json")
        if path.is_file()
        and path.parent.name == "short_term"
        and "backups" not in path.relative_to(data_root).parts
    )
    total_records = 0
    total_bytes = 0
    for path in files:
        user_id = path.name.removesuffix("_short.json").lower()
        assert not user_id.startswith("tg_"), f"Telegram 文件仍存在: {path}"
        records = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(records, list), f"顶层不是数组: {path}"
        assert len(records) <= 60, f"记录数超过 60: {path}"
        assert all(is_short_term_dialogue(record) for record in records), f"存在非对话记录: {path}"
        assert path.stat().st_size <= SHORT_TERM_DISK_MAX_BYTES, f"文件超过 64 KiB: {path}"
        total_records += len(records)
        total_bytes += path.stat().st_size
    return len(files), total_records, total_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-data", action="store_true", help="同时检查 companion_data 现有文件")
    args = parser.parse_args()

    verify_code_boundaries()
    print("代码边界验证通过")
    if args.check_data:
        file_count, record_count, byte_count = verify_existing_data()
        print(
            f"现有数据验证通过: {file_count} 个文件, {record_count} 条, "
            f"{byte_count / 1024:.1f} KiB"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
