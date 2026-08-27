import asyncio
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


async def _delete_user_diary_entries() -> dict:
    from core.services.journal.storage import JournalStorage
    from core.services.journal.models import JournalEntry

    storage = JournalStorage()
    user_daily_root = storage._get_scope_base_dir("user") / "daily"
    deleted_files = []
    removed_memory_ids = []

    if user_daily_root.exists():
        for file_path in user_daily_root.rglob("*.json"):
            if file_path.name == "diary_summary.json":
                continue
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
                entry = JournalEntry.model_validate(payload)
            except Exception:
                continue
            if (
                str(entry.source or "").strip().lower() == "system"
                and str(entry.type or "").strip().lower() == "daily_summary"
                and str(entry.thought or "").strip().lower() == "auto_generated_daily_summary"
            ):
                try:
                    file_path.unlink()
                    deleted_files.append(str(file_path))
                except Exception:
                    continue

    from memory.weighted_memory_manager import get_weighted_memory_manager

    manager = await asyncio.to_thread(get_weighted_memory_manager, "default_user")
    if manager is not None:
        for memory_id, memory in list(manager.weighted_memories.items()):
            metadata = memory.get("metadata") if isinstance(memory, dict) else {}
            if (
                str(memory.get("source") or "").strip().lower() == "journal"
                and str(memory.get("category") or "").strip().lower() == "diary"
                and isinstance(metadata, dict)
                and str(metadata.get("source") or "").strip().lower() == "system"
                and str(metadata.get("entry_type") or "").strip().lower() == "daily_summary"
                and str(metadata.get("thought") or "").strip().lower() == "auto_generated_daily_summary"
            ):
                deleted = await asyncio.to_thread(manager.delete_memory, memory_id)
                if deleted:
                    removed_memory_ids.append(memory_id)
        if removed_memory_ids:
            await asyncio.to_thread(manager.sync_save_memory)
        await asyncio.to_thread(manager.shutdown)

    return {
        "deleted_diary_files": deleted_files,
        "deleted_diary_file_count": len(deleted_files),
        "removed_memory_ids": removed_memory_ids,
        "removed_memory_count": len(removed_memory_ids),
    }


def main() -> int:
    result = asyncio.run(_delete_user_diary_entries())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("OK: 已清理 AI 自动生成的用户日记与对应记忆残留")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
