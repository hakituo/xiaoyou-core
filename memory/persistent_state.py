import hashlib
import json
import logging
import re
import time
from typing import Dict, List, Any
from pathlib import Path

from memory.core.persistence import safe_json_dump

logger = logging.getLogger(__name__)

_SUFFIX_LIST = ("了", "了哦", "啦", "哈", "呀", "呢")
_PREFIX_LIST = ("今天", "现在", "刚才", "已经", "确实", "早就")
_NEGATION_WORDS = ("没", "不", "还没")
_NUMERIC_PATTERN = re.compile(r'\d+(\.\d+)?(kg|斤|点|分钟|小时|个|次)')
_EXTRACT_PATTERNS = [
    re.compile(r"(?:已经|早就|确实)\s*(.+?)\s*(?:了|啦|完毕|完成|齐了)"),
    re.compile(r"(.+?)\s*(?:完了|好了|齐了|完毕|完成)"),
    re.compile(r"(?:做了|吃了|喝了|买了|搞定|完成)\s*(.+)"),
]
_COMMON_ACTIONS = ("吃饭", "吃过饭", "吃完饭", "洗澡", "睡觉", "吃药", "服药", "打卡")


class PersistentStateTracker:

    def __init__(self, storage_dir: str, user_id: str = "default"):
        self.storage_dir = Path(storage_dir)
        self.user_id = user_id
        self.state_file = self.storage_dir / f"persistent_states_{user_id}.json"
        self.states: Dict[str, Dict[str, Any]] = {}
        self._load_states()

    def _load_states(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.states = json.load(f)
                self.cleanup_expired_states()
            except Exception as e:
                logger.error(f"Failed to load persistent states: {e}")
                self.states = {}
        else:
            self.states = {}

    def _save_states(self):
        try:
            # 空数据时跳过写入，已有文件则删除
            if not self.states:
                if self.state_file.exists():
                    self.state_file.unlink()
                return
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            safe_json_dump(self.states, str(self.state_file), "utf-8")
        except Exception as e:
            logger.error(f"Failed to save persistent states: {e}")

    def cleanup_expired_states(self):
        current_time = time.time()
        expired_keys = [
            key for key, state in self.states.items()
            if state.get("expiry") and current_time > state["expiry"]
        ]
        if expired_keys:
            for key in expired_keys:
                del self.states[key]
            self._save_states()
            logger.info(
                f"Cleaned up {len(expired_keys)} expired states for user {self.user_id}"
            )

    def _normalize_content(self, content: str) -> tuple[str, str]:
        normalized = content.strip().lower()
        for suffix in _SUFFIX_LIST:
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                normalized = normalized[: -len(suffix)]
                break
        core = normalized
        for prefix in _PREFIX_LIST:
            if core.startswith(prefix):
                core = core[len(prefix):].strip()
                break
        core = _NUMERIC_PATTERN.sub('', core).strip()
        if not core:
            core = normalized
        return normalized, core

    def add_state(
        self,
        content: str,
        status: str = "completed",
        ttl_hours: int = 24,
        metadata: Dict = None,
        _skip_save: bool = False,
    ):
        normalized_content, core_content = self._normalize_content(content)
        key = hashlib.sha256(core_content.encode("utf-8")).hexdigest()
        current_time = time.time()
        expiry = current_time + (ttl_hours * 3600) if ttl_hours else None
        self.states[key] = {
            "content": normalized_content,
            "display_content": content,
            "status": status,
            "created_at": current_time,
            "updated_at": current_time,
            "expiry": expiry,
            "metadata": metadata or {},
        }
        if not _skip_save:
            self._save_states()
        logger.info(f"Added persistent state: {normalized_content} ({status})")
        return key

    def extract_from_text(self, text: str) -> List[str]:
        if not text:
            return []
        found_states = []
        for pattern in _EXTRACT_PATTERNS:
            for match in pattern.finditer(text):
                state_content = match.group(1).strip()
                if 1 < len(state_content) < 20:
                    found_states.append(state_content)
        for action in _COMMON_ACTIONS:
            if action in text and action not in found_states:
                if not any(neg in text for neg in _NEGATION_WORDS):
                    found_states.append(action)
        return list(set(found_states))

    def auto_update_from_text(self, text: str):
        extracted = self.extract_from_text(text)
        if not extracted:
            return extracted
        for state in extracted:
            self.add_state(state, _skip_save=True)
        self._save_states()
        return extracted

    def get_active_states(self) -> List[Dict[str, Any]]:
        self.cleanup_expired_states()
        return sorted(self.states.values(), key=lambda x: x["created_at"])

    def get_context_string(self) -> str:
        states = self.get_active_states()
        if not states:
            return ""
        lines = ["[Persistent States / Daily Actions]"]
        for state in states[-15:]:
            lines.append(f"- {state['content']} [{state['status']}]")
        return "\n".join(lines)
