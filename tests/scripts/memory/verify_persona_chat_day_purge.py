"""验证按角色自然日清理会话时不会误删同日其它数据。"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.maintenance import purge_persona_chat_day as purge_mod  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="persona-chat-day-purge-") as temp_dir:
        companion = Path(temp_dir) / "companion_data"
        role_root = companion / "ling_data"
        target_cid = "shared__persona__ling_love"
        other_cid = "shared__persona__core_ling"
        history_file = (
            role_root
            / "chat_history"
            / "2026"
            / "09"
            / "01"
            / "主线对话"
            / f"{target_cid}.jsonl"
        )
        other_file = history_file.with_name(f"{other_cid}.jsonl")
        _write_jsonl(
            history_file,
            [{"event_id": "target-event", "conversation_id": target_cid}],
        )
        _write_jsonl(
            other_file,
            [{"event_id": "other-event", "conversation_id": other_cid}],
        )
        action_file = (
            role_root
            / "daily"
            / "2026"
            / "09"
            / "01"
            / "events"
            / "chat_actions.jsonl"
        )
        _write_jsonl(
            action_file,
            [
                {"conversation_id": target_cid, "history_event_refs": {"event_id": "target-event"}},
                {"conversation_id": other_cid, "history_event_refs": {"event_id": "other-event"}},
            ],
        )
        weighted_file = (
            role_root
            / "memories"
            / "weighted"
            / "sensitive"
            / "shared__scope__ling_weighted.json"
        )
        weighted_file.parent.mkdir(parents=True, exist_ok=True)
        weighted_file.write_text(
            json.dumps(
                {
                    "weighted_memories": [
                        {"id": "target-memory", "metadata": {"event_ref": {"event_id": "target-event"}}},
                        {"id": "other-memory", "metadata": {"event_ref": {"event_id": "other-event"}}},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        original_companion = purge_mod.COMPANION_DATA
        purge_mod.COMPANION_DATA = companion
        try:
            preview = purge_mod.purge_chat_day(
                role_root=role_root,
                target_date=date(2026, 9, 1),
                conversation_ids={target_cid},
                apply=False,
            )
            assert preview["history_events_removed"] == 1
            assert preview["daily_events_removed"] == 1
            assert preview["memory_records_removed"] == 1
            assert history_file.exists(), "dry-run 不得改文件"

            applied = purge_mod.purge_chat_day(
                role_root=role_root,
                target_date=date(2026, 9, 1),
                conversation_ids={target_cid},
                apply=True,
            )
            assert applied["history_events_removed"] == 1
            assert not history_file.exists()
            assert other_file.exists()
            assert len(action_file.read_text(encoding="utf-8").splitlines()) == 1
            memories = json.loads(weighted_file.read_text(encoding="utf-8"))["weighted_memories"]
            assert [item["id"] for item in memories] == ["other-memory"]
        finally:
            purge_mod.COMPANION_DATA = original_companion

    print("PASS: 目标会话的历史、daily 引用和 weighted 记忆已删除，同日其它会话保留")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
