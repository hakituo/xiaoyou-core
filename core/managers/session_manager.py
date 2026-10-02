from core.utils.logger import get_logger
import json
import os
import time
import uuid
import threading
from typing import List, Dict, Optional
from pathlib import Path
from config.integrated_config import get_settings
from core.utils.common import get_project_root
from core.utils.data_paths import (
    get_role_memories_dir,
    get_sessions_file_for_scope,
    resolve_data_scope_from_conversation_id,
)

logger = None
try:
    from core.utils.logger import get_logger

    logger = get_logger("SESSION_MANAGER")
except ImportError:

    logger = get_logger("SESSION_MANAGER")


class SessionManager:
    """
    会话管理器
    负责管理多会话列表 (ID, Title, Timestamp)
    """

    def __init__(self):
        self.settings = get_settings()
        self._session_file_map: Dict[str, Path] = {}
        self._ensure_dir()
        self.lock = threading.Lock()
        self.sessions = self._load_sessions()

    def _ensure_dir(self):
        for scope in ("aveline", "ling"):
            get_role_memories_dir(scope).mkdir(parents=True, exist_ok=True)

    def _get_session_files(self) -> List[Path]:
        files = [
            get_sessions_file_for_scope("aveline"),
            get_sessions_file_for_scope("ling"),
        ]
        deduped: List[Path] = []
        for path in files:
            resolved = path.resolve()
            if resolved not in deduped:
                deduped.append(resolved)
        return deduped

    def _read_sessions_file(self, file_path: Path) -> List[Dict]:
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"加载会话列表失败: {file_path} err={e}")
            return []

    def _resolve_session_file_for_id(self, session_id: str) -> Path:
        known = self._session_file_map.get(session_id)
        if isinstance(known, Path):
            return known
        scope = resolve_data_scope_from_conversation_id(session_id, default="aveline")
        return get_sessions_file_for_scope(scope)

    def _load_sessions(self) -> List[Dict]:
        merged: Dict[str, Dict] = {}
        self._session_file_map = {}
        try:
            with self.lock:
                for file_path in self._get_session_files():
                    for item in self._read_sessions_file(file_path):
                        if not isinstance(item, dict):
                            continue
                        sid = str(item.get("id") or "").strip()
                        if not sid:
                            continue
                        existing = merged.get(sid)
                        if existing is None or float(item.get("updated_at", 0) or 0) >= float(
                            existing.get("updated_at", 0) or 0
                        ):
                            merged[sid] = item
                            self._session_file_map[sid] = file_path
            return list(merged.values())
        except Exception as e:
            logger.error(f"加载会话列表失败: {e}")
            return []

    def _save_sessions(self):
        try:
            with self.lock:
                groups: Dict[Path, List[Dict]] = {}
                for session in self.sessions:
                    if not isinstance(session, dict):
                        continue
                    sid = str(session.get("id") or "").strip()
                    if not sid:
                        continue
                    file_path = self._resolve_session_file_for_id(sid)
                    self._session_file_map[sid] = file_path
                    groups.setdefault(file_path, []).append(session)

                # 只写入有会话数据的文件，空文件直接删除
                for file_path, payload in groups.items():
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    payload = sorted(
                        payload,
                        key=lambda x: x.get("updated_at", 0),
                        reverse=True,
                    )
                    temp_file = str(file_path) + ".tmp"
                    with open(temp_file, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    os.rename(temp_file, file_path)
        except Exception as e:
            logger.error(f"保存会话列表失败: {e}")

    def get_sessions(self) -> List[Dict]:
        # 按最后更新时间降序排序
        return sorted(self.sessions, key=lambda x: x.get("updated_at", 0), reverse=True)

    def create_session(self, title: str = None) -> str:
        self._cleanup_empty_sessions()

        if not title or title == "新话题":
            title = time.strftime("%m-%d %H:%M", time.localtime(time.time()))

        session_id = str(uuid.uuid4())
        now = time.time()
        new_session = {
            "id": session_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        self._session_file_map[session_id] = get_sessions_file_for_scope("aveline")
        self.sessions.insert(0, new_session)
        self._save_sessions()
        logger.info(f"创建新会话: {session_id} - {title}")
        return session_id

    def _cleanup_empty_sessions(self):
        """
        清理空会话（没有聊天记录或记录为空的会话）
        """
        project_root = self._get_project_root()
        history_dir = project_root / "output" / "memory" / "conversations"

        to_remove = []
        for session in self.sessions:
            sid = session.get("id")
            if not sid:
                continue

            # Check if history file exists and has content
            history_file = history_dir / f"{sid}.json"
            is_empty = True
            if history_file.exists():
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and len(data) > 0:
                            is_empty = False
                except Exception:
                    pass

            if is_empty:
                to_remove.append(sid)

        if to_remove:
            logger.info(f"自动清理空会话: {to_remove}")
            for sid in to_remove:
                self.delete_session(sid)

    def update_session(self, session_id: str, title: Optional[str] = None):
        for session in self.sessions:
            if session["id"] == session_id:
                session["updated_at"] = time.time()
                if title:
                    session["title"] = title
                self._save_sessions()
                return True
        # 如果不存在，可能是直接通过API调用的旧会话ID，自动创建
        logger.info(f"会话 {session_id} 不在列表中，自动添加")
        now = time.time()
        new_session = {
            "id": session_id,
            "title": title or "未命名话题",
            "created_at": now,
            "updated_at": now,
        }
        self._session_file_map[session_id] = self._resolve_session_file_for_id(session_id)
        self.sessions.insert(0, new_session)
        self._save_sessions()
        return True

    def delete_session(self, session_id: str):
        original_len = len(self.sessions)
        self.sessions = [s for s in self.sessions if s["id"] != session_id]
        self._session_file_map.pop(session_id, None)

        # Always attempt to delete files, even if session was not in the list (e.g. legacy or default files)
        files_deleted = self._delete_memory_files(session_id)

        if len(self.sessions) < original_len or files_deleted:
            self._save_sessions()
            logger.info(f"删除会话: {session_id}")
            return True
        return False

    def _get_project_root(self) -> Path:
        return get_project_root()

    def delete_kvswap_file(self, session_id: str) -> bool:
        try:
            s = str(session_id or "").strip()
            if not s:
                return False

            model_settings = getattr(self.settings, "model", None)
            kv_dir_cfg = (
                getattr(model_settings, "kv_swap_dir", None) if model_settings else None
            )
            if kv_dir_cfg:
                base_dir = Path(str(kv_dir_cfg))
                if not base_dir.is_absolute():
                    base_dir = Path(os.getcwd()) / base_dir
            else:
                cache_dir = (
                    str(getattr(model_settings, "cache_dir", "cache") or "cache")
                    if model_settings
                    else "cache"
                )
                base_dir = (self._get_project_root() / cache_dir / "kvswap").resolve()

            safe = s
            buf = []
            for c in safe:
                o = ord(c)
                if (
                    (48 <= o <= 57)
                    or (65 <= o <= 90)
                    or (97 <= o <= 122)
                    or c in {"-", "_"}
                ):
                    buf.append(c)
                else:
                    buf.append("_")
            safe = "".join(buf)

            p = base_dir / f"{safe}.kvswap"
            if p.exists() and p.is_file():
                p.unlink()
                logger.info(f"删除 KVSwap 文件: {p}")
                return True
        except Exception as e:
            logger.warning(f"删除 KVSwap 文件失败: {session_id} err={e}")
        return False

    def _delete_memory_files(self, session_id: str) -> bool:
        # 删除相关的记忆文件
        deleted = False
        try:
            candidates: List[Path] = []
            memory_roots = [
                get_role_memories_dir("aveline"),
                get_role_memories_dir("ling"),
            ]
            for root in memory_roots:
                candidates.append(root / f"{session_id}_short.json")
                candidates.append(root / f"{session_id}_long.json")
                candidates.append(root / f"{session_id}_weighted.json")
                candidates.append(root / "short_term" / f"{session_id}_short.json")
                candidates.append(root / "long_term" / f"{session_id}_long.json")
                candidates.append(root / "weighted" / f"{session_id}_weighted.json")
                candidates.append(
                    root / "weighted" / f"{session_id}_important_prompts.json"
                )
                candidates.append(
                    root / "sensitive" / f"{session_id}_sensitive.json"
                )
                weighted_dir = root / "weighted"
                if weighted_dir.exists():
                    for item in weighted_dir.iterdir():
                        if item.is_dir():
                            candidates.append(item / f"{session_id}_weighted.json")

            project_root = self._get_project_root()
            candidates.append(
                project_root
                / "output"
                / "memory"
                / "conversations"
                / f"{session_id}.json"
            )

            for p in candidates:
                try:
                    if p.exists() and p.is_file():
                        p.unlink()
                        logger.info(f"删除文件: {p}")
                        deleted = True
                except Exception as e:
                    logger.warning(f"删除文件失败: {p} err={e}")

            try:
                if self.delete_kvswap_file(session_id):
                    deleted = True
            except Exception:
                pass
            for root in memory_roots:
                weighted_dir = root / "weighted"
                if weighted_dir.exists():
                    for item in weighted_dir.iterdir():
                        try:
                            if item.is_dir() and not any(item.iterdir()):
                                item.rmdir()
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"删除会话文件失败: {e}")
        return deleted


# 全局实例
_session_manager = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
