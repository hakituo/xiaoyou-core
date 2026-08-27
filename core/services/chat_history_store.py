import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.atomic_io import safe_json_dump
from core.utils.conversation_labels import _sanitize_segment, get_conversation_label_info
from core.utils.data_paths import (
    get_all_chat_history_dirs,
    get_chat_history_dir_for_conversation,
    normalize_data_scope,
)
from core.utils.time_utils import get_current_time


_LOCK = threading.Lock()
_INSTANCE = None


class ChatHistoryStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = Path(base_dir).resolve() if base_dir else None
        if self._base_dir is not None:
            self._base_dir.mkdir(parents=True, exist_ok=True)

    def _get_base_dir(self, conversation_id: Optional[str] = None) -> Path:
        if self._base_dir is not None:
            return self._base_dir
        base_dir = Path(get_chat_history_dir_for_conversation(conversation_id)).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    def append_event(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        message_id: str,
        event_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        now_dt=None,
    ) -> Dict[str, Any]:
        from core.utils.debug_markers import is_debug_context_message
        if is_debug_context_message(content):
            from core.utils.logger import get_logger
            logger = get_logger("ChatHistoryStore")
            logger.info(f"Filtered out debug/error message from chat history store: {content[:100]}")
            return {
                "event_id": "filtered",
                "relative_path": "",
                "mirror_relative_path": "",
                "timestamp": 0.0,
                "role": role,
                "conversation_id": conversation_id,
                "storage_scope": "filtered",
            }

        dt = now_dt or get_current_time()
        safe_cid = _sanitize_segment(conversation_id)
        label_info = get_conversation_label_info(conversation_id)
        base_dir = self._get_base_dir(conversation_id)
        storage_scope = normalize_data_scope(
            label_info.get("storage_scope"), default="aveline"
        )
        day_dir = base_dir / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        file_path = day_dir
        chat_segments = list(label_info.get("chat_segments") or [])
        if not chat_segments:
            chat_segments = [str(label_info.get("safe_lane") or "default_lane")]
        for segment in chat_segments:
            file_path = file_path / str(segment)
        file_path.mkdir(parents=True, exist_ok=True)
        file_path = file_path / f"{safe_cid}.jsonl"

        event_id = uuid.uuid4().hex
        rel_path = file_path.relative_to(base_dir).as_posix()
        payload = {
            "event_id": event_id,
            "conversation_id": str(conversation_id or "default"),
            "message_id": str(message_id or ""),
            "event_type": str(event_type or "message"),
            "role": str(role or "system"),
            "content": str(content or ""),
            "timestamp": float(dt.timestamp()),
            "created_at": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "readable_title": str(label_info.get("readable_title") or ""),
            "storage_scope": storage_scope,
        }

        line = json.dumps(payload, ensure_ascii=False)
        with _LOCK:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._write_day_index(day_dir, base_dir)

        return {
            "event_id": event_id,
            "relative_path": rel_path,
            "mirror_relative_path": rel_path,
            "timestamp": payload["timestamp"],
            "role": payload["role"],
            "conversation_id": payload["conversation_id"],
            "storage_scope": storage_scope,
        }

    def rebuild_readable_mirrors(self) -> Dict[str, int]:
        return {"copied": 0, "skipped": 0}

    def delete_conversation(self, conversation_id: str) -> Dict[str, int]:
        safe_cid = _sanitize_segment(conversation_id)
        removed = 0
        reindexed = 0
        candidate_roots = [self._get_base_dir(conversation_id)]
        for root in get_all_chat_history_dirs():
            if root not in candidate_roots:
                candidate_roots.append(root)
        with _LOCK:
            for base_dir in candidate_roots:
                if not base_dir.exists():
                    continue
                matched_days = set()
                for file_path in list(base_dir.rglob(f"{safe_cid}.jsonl")):
                    try:
                        rel_parts = file_path.relative_to(base_dir).parts
                    except Exception:
                        continue
                    if len(rel_parts) < 4:
                        continue
                    day_dir = base_dir / rel_parts[0] / rel_parts[1] / rel_parts[2]
                    try:
                        file_path.unlink()
                        removed += 1
                        matched_days.add(day_dir)
                    except Exception:
                        continue
                for day_dir in matched_days:
                    self._write_day_index(day_dir, base_dir)
                    reindexed += 1
        return {"removed_files": removed, "reindexed_days": reindexed}

    def _write_day_index(self, day_dir: Path, base_dir: Path) -> None:
        try:
            if not day_dir.exists():
                return
            items = []
            for path in sorted(day_dir.rglob("*.jsonl")):
                rel = path.relative_to(base_dir).as_posix()
                cid = str(path.stem or "").strip()
                label_info = get_conversation_label_info(cid)
                items.append(
                    {
                        "relative_path": rel,
                        "view": "readable",
                        "name": path.name,
                        "conversation_id": str(
                            label_info.get("conversation_id") or cid or "default"
                        ),
                        "readable_title": str(label_info.get("readable_title") or ""),
                    }
                )
            index_path = day_dir / "index.json"
            # P0-17: 用原子写入保存聊天历史索引，避免进程崩溃导致索引损坏
            safe_json_dump({"files": items}, index_path, encoding="utf-8")
        except Exception:
            return

    def get_event_content(self, event_ref: Dict[str, Any]) -> Optional[str]:
        if not isinstance(event_ref, dict):
            return None
        rel_path = str(event_ref.get("relative_path") or "").strip()
        event_id = str(event_ref.get("event_id") or "").strip()
        if not rel_path or not event_id:
            return None
        roots = []
        if self._base_dir is not None:
            roots = [self._base_dir]
        else:
            hinted_scope = normalize_data_scope(
                event_ref.get("storage_scope"), default="aveline"
            )
            scope_roots = [
                root
                for root in get_all_chat_history_dirs()
                if root.name == "chat_history"
            ]
            preferred = []
            fallback = []
            for root in scope_roots:
                root_text = str(root).lower()
                if hinted_scope == "aveline" and "aveline_data" in root_text:
                    preferred.append(root)
                elif hinted_scope == "ling" and "ling_data" in root_text:
                    preferred.append(root)
                elif hinted_scope == "user" and "user_data" in root_text:
                    preferred.append(root)
                else:
                    fallback.append(root)
            roots = preferred + fallback

        for root in roots:
            file_path = (root / rel_path).resolve()
            try:
                if not str(file_path).startswith(str(root)):
                    continue
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except Exception:
                            continue
                        if str(item.get("event_id") or "") == event_id:
                            return str(item.get("content") or "")
            except Exception:
                continue
        return None

    def list_conversation_events(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before: Optional[float] = None,
        query: Optional[str] = None,
        roles: Optional[list[str]] = None,
    ) -> list[Dict[str, Any]]:
        safe_cid = _sanitize_segment(conversation_id)
        primary_root = self._get_base_dir(conversation_id)
        candidate_roots = [primary_root]

        label_info = get_conversation_label_info(conversation_id)
        storage_scope = normalize_data_scope(
            label_info.get("storage_scope"), default="aveline"
        )
        has_explicit_scope = storage_scope in {"aveline", "ling", "dual_role", "user"}

        if has_explicit_scope:
            found_in_primary = False
            if primary_root.exists():
                for _ in primary_root.rglob(f"{safe_cid}.jsonl"):
                    found_in_primary = True
                    break
            if found_in_primary:
                candidate_roots = [primary_root]
            else:
                for root in get_all_chat_history_dirs():
                    if root not in candidate_roots:
                        candidate_roots.append(root)
        else:
            for root in get_all_chat_history_dirs():
                if root not in candidate_roots:
                    candidate_roots.append(root)

        normalized_query = str(query or "").strip().lower()
        query_tokens = [token for token in normalized_query.split() if token]
        if not query_tokens and normalized_query:
            query_tokens = [normalized_query]
        normalized_roles = {
            str(item).strip().lower() for item in (roles or []) if str(item).strip()
        }
        items: list[Dict[str, Any]] = []
        for base_dir in candidate_roots:
            if not base_dir.exists():
                continue
            for file_path in sorted(base_dir.rglob(f"{safe_cid}.jsonl")):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            raw = line.strip()
                            if not raw:
                                continue
                            try:
                                payload = json.loads(raw)
                            except Exception:
                                continue
                            role = str(payload.get("role") or "system").strip().lower()
                            if normalized_roles and role not in normalized_roles:
                                continue
                            timestamp = float(payload.get("timestamp") or 0.0)
                            if before is not None and timestamp >= float(before):
                                continue
                            content = str(payload.get("content") or "")
                            if query_tokens:
                                lowered_content = content.lower()
                                if not any(token in lowered_content for token in query_tokens):
                                    continue
                            items.append(payload)
                except Exception:
                    continue

        deduped: Dict[str, Dict[str, Any]] = {}
        for item in sorted(items, key=lambda entry: float(entry.get("timestamp") or 0.0)):
            event_id = str(item.get("event_id") or "").strip()
            if event_id:
                deduped[event_id] = item
        result = list(deduped.values())
        if limit > 0 and len(result) > int(limit):
            return result[-int(limit) :]
        return result


def get_chat_history_store() -> ChatHistoryStore:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ChatHistoryStore()
    return _INSTANCE
