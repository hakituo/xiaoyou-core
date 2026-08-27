"""验证 Aveline、Ling的 weighted memory 清理与索引修复。"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from memory.core.readable_ops import compact_weighted_memory_record  # noqa: E402
from memory.core.record_ops import (  # noqa: E402
    infer_memory_type,
    rebuild_memory_indexes_locked,
)


AVELINE_WEIGHTED = (
    PROJECT_ROOT / "companion_data" / "aveline_data" / "memories" / "weighted"
)
LING_WEIGHTED = (
    PROJECT_ROOT / "companion_data" / "ling_data" / "memories" / "weighted"
)
DUAL_WEIGHTED = (
    PROJECT_ROOT / "companion_data" / "dual_role" / "memories" / "weighted"
)
AVELINE_HISTORY = PROJECT_ROOT / "companion_data" / "aveline_data" / "chat_history"
LING_HISTORY = PROJECT_ROOT / "companion_data" / "ling_data" / "chat_history"

AVELINE_IDS = {
    "aveline",
    "private_123456789",
    "private_123456789__scope__aveline",
    "shared__scope__aveline",
}
LING_IDS = {
    "ling",
    "private_123456789__scope__ling",
    "shared__scope__ling",
}
DUAL_IDS = {
    "peer_3406280693__scope__dual_role",
    "peer_3795532329__scope__dual_role",
}
NON_PERSISTENT = {"thinking", "context_injection", "persona_prompt"}
DERIVED_FIELDS = {
    "source_ref",
    "readable_summary",
    "readable_title",
    "display_tags",
    "keywords",
    "last_hit_time",
    "embedding",
    "embedding_base64",
}
RUNTIME_METADATA_FIELDS = {
    "reply_content",
    "thought",
    "reasoning_content",
    "model_hint",
    "trace_id",
    "thought_source",
    "defer_analysis",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"顶层不是对象: {path}")
    return data


def manager_files(root: Path, user_id: str) -> list[Path]:
    name = f"{user_id}_weighted.json"
    return sorted(path for path in root.rglob(name) if path.is_file())


def manager_records(root: Path, user_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in manager_files(root, user_id):
        for record in payload(path).get("weighted_memories") or []:
            require(isinstance(record, dict), f"记忆记录不是对象: {path}")
            records.append(record)
    return records


def discover_ids(root: Path) -> set[str]:
    return {
        path.name.removesuffix("_weighted.json")
        for path in root.rglob("*_weighted.json")
        if path.is_file()
    }


def collect_event_ids(value: Any, target: set[str]) -> None:
    if isinstance(value, dict):
        event_id = value.get("event_id")
        if event_id:
            target.add(str(event_id))
        for nested in value.values():
            collect_event_ids(nested, target)
    elif isinstance(value, list):
        for nested in value:
            collect_event_ids(nested, target)


def history_event_ids(root: Path) -> set[str]:
    event_ids: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".jsonl":
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                collect_event_ids(json.loads(line), event_ids)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"聊天历史 JSONL 损坏: {path}:{line_number}") from exc
    return event_ids


def event_key(record: dict[str, Any]) -> tuple[str, str, str] | None:
    metadata = record.get("metadata")
    event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
    if not isinstance(event_ref, dict) or not event_ref.get("event_id"):
        return None
    return (
        str(event_ref["event_id"]),
        str(record.get("memory_type") or "dialogue").lower(),
        str(record.get("source") or "chat").lower(),
    )


def verify_manager(
    root: Path,
    user_id: str,
    *,
    known_history_events: set[str] | None = None,
) -> tuple[int, int]:
    files = manager_files(root, user_id)
    require(files, f"缺少 weighted manager: {root} / {user_id}")
    root_file = root / f"{user_id}_weighted.json"
    require(root_file in files, f"缺少根索引文件: {root_file}")
    records = manager_records(root, user_id)

    ids: set[str] = set()
    event_keys: set[tuple[str, str, str]] = set()
    event_ids: set[str] = set()
    for path in files:
        data = payload(path)
        expected_category = path.parent.name if path.parent != root else "uncategorized"
        for record in data.get("weighted_memories") or []:
            memory_id = str(record.get("id") or "").strip()
            require(memory_id, f"记录缺少 ID: {path}")
            require(memory_id not in ids, f"重复记忆 ID: {user_id} / {memory_id}")
            ids.add(memory_id)
            category = str(record.get("category") or "uncategorized").lower()
            require(category == expected_category, f"分类分片不匹配: {path} / {category}")
            require(category not in NON_PERSISTENT, f"非持久类别仍在磁盘: {category}")
            require(not DERIVED_FIELDS.intersection(record), f"派生字段未压缩: {memory_id}")
            metadata = record.get("metadata")
            if isinstance(metadata, dict):
                require(
                    not RUNTIME_METADATA_FIELDS.intersection(metadata),
                    f"运行时元数据未清理: {memory_id}",
                )
            key = event_key(record)
            if key is not None:
                require(key not in event_keys, f"重复事件记忆: {user_id} / {key}")
                event_keys.add(key)
                event_ids.add(key[0])
                require(not str(record.get("content") or "").strip(), f"事件正文未压缩: {memory_id}")
            if category == "diary":
                require(record.get("memory_type") == "event_summary", f"日记类型错误: {memory_id}")
            if category == "sensitive":
                require(record.get("memory_type") == "sensitive", f"敏感记忆类型错误: {memory_id}")

    root_data = payload(root_file)
    indexed_ids = {
        str(entry.get("memory_id") or "")
        for entries in (root_data.get("emotion_memory_map") or {}).values()
        for entry in entries
        if isinstance(entry, dict)
    }
    require(indexed_ids <= ids, f"emotion_memory_map 含失效 ID: {user_id}")
    topic_keys = list((root_data.get("topic_weights") or {}).keys())
    require(
        len({str(topic).lower() for topic in topic_keys}) == len(topic_keys),
        f"主题大小写重复: {user_id}",
    )
    if known_history_events is not None:
        missing = event_ids - known_history_events
        require(
            not missing,
            f"聊天历史缺少 {len(missing)} 个事件引用: {user_id} / {sorted(missing)[:5]}",
        )
    return len(files), len(records)


class FakeManager:
    def __init__(self) -> None:
        self.weighted_memories = {
            "m1": {
                "id": "m1",
                "content": "hello",
                "source": "chat",
                "category": "daily",
                "weight": 2.0,
                "topics": ["Chat"],
                "emotions": ["Joy"],
            }
        }
        self.category_index = defaultdict(list, {"stale": ["gone"]})
        self.topic_weights = defaultdict(float, {"Chat": 1.0, "chat": 1.0})
        self.topics = defaultdict(list)
        self.emotion_memory_map = defaultdict(
            list, {"joy": [{"memory_id": "gone", "relevance_score": 0.8}]}
        )
        self.content_dedupe_index = {"stale": "gone"}

    def _update_topic_index(self) -> None:
        return None

    def _rebuild_preference_index_locked(self) -> None:
        return None

    def _normalize_memory_record(self, memory: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return dict(memory), False


def verify_code_semantics() -> None:
    manager = FakeManager()
    rebuild_memory_indexes_locked(manager)
    require(dict(manager.category_index) == {"daily": ["m1"]}, "分类索引未重建")
    require(set(manager.topic_weights) == {"chat"}, "Chat/chat 未归一")
    require(
        manager.emotion_memory_map["joy"] == [
            {"memory_id": "m1", "relevance_score": 0.8}
        ],
        "情绪索引仍含失效引用",
    )
    compacted = compact_weighted_memory_record(
        manager,
        {
            "id": "m2",
            "content": "x",
            "source_ref": "derived",
            "readable_summary": "derived",
            "keywords": ["derived"],
            "embedding": [1.0],
        },
    )
    require(not DERIVED_FIELDS.intersection(compacted), "weighted 落盘压缩未移除派生字段")
    require(
        infer_memory_type(manager, {"category": "diary", "source": "journal"})
        == "event_summary",
        "日记未分类为 event_summary",
    )


def main() -> int:
    verify_code_semantics()
    require(discover_ids(AVELINE_WEIGHTED) == AVELINE_IDS, "Aveline 仍含旧 persona/TG/测试 manager")
    require(discover_ids(LING_WEIGHTED) == LING_IDS, "Ling仍含旧 persona/TG/测试 manager")
    aveline_history_ids = history_event_ids(AVELINE_HISTORY)
    ling_history_ids = history_event_ids(LING_HISTORY)

    report: dict[str, dict[str, int]] = {}
    for label, root, user_ids, history_ids in (
        ("aveline", AVELINE_WEIGHTED, AVELINE_IDS, aveline_history_ids),
        ("ling", LING_WEIGHTED, LING_IDS, ling_history_ids),
        ("dual_role", DUAL_WEIGHTED, DUAL_IDS, None),
    ):
        file_count = 0
        record_count = 0
        for user_id in sorted(user_ids):
            files, records = verify_manager(
                root,
                user_id,
                known_history_events=history_ids,
            )
            file_count += files
            record_count += records
        report[label] = {"files": file_count, "records": record_count}

    print(json.dumps({"status": "ok", "report": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
