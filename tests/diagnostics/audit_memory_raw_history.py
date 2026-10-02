import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


DEFAULT_RECORDS: List[Dict[str, Any]] = [
    {
        "kind": "chat",
        "role": "user",
        "source": "user",
        "content": "明天下午两点要和客户开项目复盘会，提醒我提前准备汇报。",
    },
    {
        "kind": "chat",
        "role": "assistant",
        "source": "assistant",
        "content": "好的，我记住了，明天下午两点有客户项目复盘会。",
    },
    {
        "kind": "diary",
        "role": "journal",
        "source": "journal",
        "category": "diary",
        "content": "今天上午整理完了发布计划，下午状态不错，晚上想早点休息。",
        "metadata": {"entry_type": "daily_diary"},
    },
    {
        "kind": "backend_role",
        "role": "system_profile",
        "source": "system_profile",
        "category": "profile",
        "content": "用户当前处于工作模式，偏好直接、简洁的提醒方式。",
    },
    {
        "kind": "active_care",
        "role": "assistant",
        "source": "active_care",
        "content": "已经很晚了，你今天忙了一天，记得早点休息哦。",
        "metadata": {"is_proactive": True, "original_source": "active_care"},
    },
]


def _patch_memory_dirs(module, history_root: Path):
    import memory.core.manager_init_ops as manager_init_ops

    original = {
        "HISTORY_DIR": module.HISTORY_DIR,
        "DEFAULT_HISTORY_DIR": module.DEFAULT_HISTORY_DIR,
        "LONG_TERM_DIR": module.LONG_TERM_DIR,
        "WEIGHTED_MEMORY_DIR": module.WEIGHTED_MEMORY_DIR,
        "SHORT_TERM_DIR": module.SHORT_TERM_DIR,
        "SENSITIVE_DIR": module.SENSITIVE_DIR,
        "READABLE_DIR": module.READABLE_DIR,
        "get_memories_dir_for_conversation": manager_init_ops.get_memories_dir_for_conversation,
    }
    module.HISTORY_DIR = history_root
    module.DEFAULT_HISTORY_DIR = history_root.resolve()
    module.LONG_TERM_DIR = history_root / "long_term"
    module.WEIGHTED_MEMORY_DIR = history_root / "weighted"
    module.SHORT_TERM_DIR = history_root / "short_term"
    module.SENSITIVE_DIR = history_root / "sensitive"
    module.READABLE_DIR = history_root / "readable"
    manager_init_ops.get_memories_dir_for_conversation = lambda _conversation_id: str(history_root)
    return original


def _restore_memory_dirs(module, original: dict):
    import memory.core.manager_init_ops as manager_init_ops

    for key, value in original.items():
        if key == "get_memories_dir_for_conversation":
            manager_init_ops.get_memories_dir_for_conversation = value
            continue
        setattr(module, key, value)


def _load_records(input_path: str | None) -> List[Dict[str, Any]]:
    if not input_path:
        return list(DEFAULT_RECORDS)
    target = Path(input_path)
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if target.suffix.lower() == ".jsonl":
        records: List[Dict[str, Any]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            records.append(json.loads(raw))
        return records
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return payload["records"]
    raise ValueError("输入文件必须是 JSON 数组、包含 records 的 JSON 对象，或 JSONL")


def _prepare_memory_record(record: Dict[str, Any]) -> Dict[str, Any]:
    prepared = dict(record)
    prepared["kind"] = str(prepared.get("kind") or "chat").strip() or "chat"
    prepared["role"] = str(prepared.get("role") or "user").strip() or "user"
    prepared["source"] = str(prepared.get("source") or prepared["role"]).strip() or prepared["role"]
    prepared["content"] = str(prepared.get("content") or "").strip()
    prepared["category"] = str(prepared.get("category") or "").strip() or None
    metadata = prepared.get("metadata")
    prepared["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
    if prepared["kind"] == "active_care":
        prepared["metadata"].setdefault("is_proactive", True)
        prepared["metadata"].setdefault("original_source", "active_care")
    if prepared["kind"] == "diary":
        prepared["category"] = prepared["category"] or "diary"
        prepared["metadata"].setdefault("entry_type", "diary")
    if prepared["kind"] == "backend_role" and prepared["source"] == "system_profile":
        prepared["category"] = prepared["category"] or "profile"
    prepared["metadata"]["defer_analysis"] = True
    return prepared


def _inspect_readable_dir(readable_dir: Path) -> Dict[str, Any]:
    files = [
        "short_term.json",
        "weighted_all.json",
        "weighted_by_type.json",
        "weighted_by_topic.json",
        "weighted_timeline.json",
        "weighted_summary.json",
    ]
    result: Dict[str, Any] = {"directory": str(readable_dir), "files": {}}
    for name in files:
        target = readable_dir / name
        info: Dict[str, Any] = {"exists": target.exists()}
        if target.exists():
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
                info["parseable"] = True
                if isinstance(payload, list):
                    info["item_count"] = len(payload)
                elif isinstance(payload, dict):
                    if isinstance(payload.get("items"), list):
                        info["item_count"] = len(payload.get("items") or [])
                    elif isinstance(payload.get("weighted_memories"), list):
                        info["item_count"] = len(payload.get("weighted_memories") or [])
                    elif isinstance(payload.get("groups"), list):
                        info["item_count"] = len(payload.get("groups") or [])
                    elif isinstance(payload.get("groups"), dict):
                        info["item_count"] = len(payload.get("groups") or {})
                    else:
                        info["item_count"] = len(payload)
                else:
                    info["item_count"] = 0
            except Exception as e:
                info["parseable"] = False
                info["error"] = str(e)
        result["files"][name] = info
    return result


async def _build_report(manager: Any, query: str, memory_ids: List[str], records: List[Dict[str, Any]]):
    recall_bundle = await manager.build_recall_bundle(
        query=query,
        limit=8,
        history_limit=20,
        conversation_id=manager.user_id,
    )
    weighted_snapshot = {item.get("id"): item for item in manager.get_weighted_memories(limit=256)}
    by_category = Counter()
    by_memory_type = Counter()
    by_source = Counter()
    detailed_items = []
    for memory_id, raw in zip(memory_ids, records):
        memory = weighted_snapshot.get(memory_id) or manager.weighted_memories.get(memory_id) or {}
        by_category[str(memory.get("category") or "uncategorized")] += 1
        by_memory_type[str(memory.get("memory_type") or "dialogue")] += 1
        by_source[str(memory.get("source") or raw.get("source") or "unknown")] += 1
        metadata = memory.get("metadata") or {}
        detailed_items.append(
            {
                "input_kind": raw.get("kind"),
                "input_role": raw.get("role"),
                "input_source": raw.get("source"),
                "memory_id": memory_id,
                "memory_type": memory.get("memory_type"),
                "category": memory.get("category"),
                "topics": list(memory.get("topics") or []),
                "readable_title": memory.get("readable_title"),
                "readable_summary": memory.get("readable_summary"),
                "source_ref": memory.get("source_ref"),
                "bert_shadow": ((metadata.get("analysis_meta") or {}).get("bert_shadow") or {}),
                "decision_trace": metadata.get("decision_trace") or {},
            }
        )

    special_sources = defaultdict(int)
    for item in detailed_items:
        source = str(item.get("input_source") or "")
        if source in {"journal", "active_care", "system_profile", "workspace"}:
            special_sources[source] += 1

    readable_report = _inspect_readable_dir(manager._get_readable_history_dir())
    return {
        "query": query,
        "input_count": len(records),
        "classification_summary": {
            "by_category": dict(by_category),
            "by_memory_type": dict(by_memory_type),
            "by_source": dict(by_source),
            "special_sources": dict(special_sources),
        },
        "detailed_items": detailed_items,
        "recall_bundle": recall_bundle,
        "readable_report": readable_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--user-id", default="raw_history_audit")
    parser.add_argument("--query", default="项目 休息 提醒")
    parser.add_argument("--output")
    args = parser.parse_args()

    import core.services.chat_history_store as chat_history_module
    import memory.weighted_memory_manager as memory_module

    records = [_prepare_memory_record(item) for item in _load_records(args.input)]
    if not records:
        print("FAIL: 没有可处理的原始历史记录")
        return 2

    with tempfile.TemporaryDirectory() as tmpdir:
        history_root = Path(tmpdir) / "memories"
        history_root.mkdir(parents=True, exist_ok=True)
        chat_history_root = Path(tmpdir) / "chat_history"
        chat_history_root.mkdir(parents=True, exist_ok=True)
        original_dirs = _patch_memory_dirs(memory_module, history_root)
        original_store = getattr(chat_history_module, "_INSTANCE", None)
        manager = None
        try:
            chat_history_module._INSTANCE = chat_history_module.ChatHistoryStore(base_dir=chat_history_root)
            manager = memory_module.WeightedMemoryManager(
                user_id=args.user_id,
                auto_save_interval=0,
                skip_auto_reclassify=True,
            )
            manager.enable_readable_history_mirror = True
            manager.clear_memory(mode="all")

            memory_ids: List[str] = []
            event_store = chat_history_module.get_chat_history_store()
            for index, record in enumerate(records):
                metadata = dict(record.get("metadata") or {})
                if record["kind"] in {"chat", "backend_role", "active_care"}:
                    event_ref = event_store.append_event(
                        conversation_id=args.user_id,
                        role=record["role"],
                        content=record["content"],
                        message_id=f"raw_{index}",
                        event_type=record["kind"],
                        metadata={
                            "source": record["source"],
                            "kind": record["kind"],
                        },
                    )
                    metadata["event_ref"] = event_ref
                memory_id = manager.add_memory(
                    content=record["content"],
                    source=record["source"],
                    category=record.get("category"),
                    metadata=metadata,
                )
                memory_ids.append(memory_id)

            processed = manager.process_pending_analysis(limit=max(32, len(records) + 4))
            fused = manager.apply_ai_shadow_adjudication(
                limit=max(32, len(records) + 4),
                allow_override=False,
            )
            manager.sync_save_memory()

            report = asyncio.run(_build_report(manager, args.query, memory_ids, records))
            report["processed"] = processed
            report["fused"] = fused

            output_path = Path(args.output) if args.output else Path(tmpdir) / "raw_history_audit_report.json"
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"OK: 原始历史记录审计完成，报告已生成: {output_path}")
            return 0
        finally:
            if manager is not None:
                manager.shutdown()
            chat_history_module._INSTANCE = original_store
            _restore_memory_dirs(memory_module, original_dirs)


if __name__ == "__main__":
    raise SystemExit(main())
