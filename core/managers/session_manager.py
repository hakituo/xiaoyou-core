import json
import os
import time
import uuid
import threading
from typing import List, Dict, Optional
from pathlib import Path
from config.integrated_config import get_settings

logger = None
try:
    from core.utils.logger import get_logger
    logger = get_logger("SESSION_MANAGER")
except ImportError:
    import logging
    logger = logging.getLogger("SESSION_MANAGER")

class SessionManager:
    """
    会话管理器
    负责管理多会话列表 (ID, Title, Timestamp)
    """
    def __init__(self):
        self.settings = get_settings()
        self.memory_dir = Path(self.settings.memory.history_dir)
        if not self.memory_dir.is_absolute():
            self.memory_dir = Path(os.getcwd()) / self.memory_dir
        
        self.sessions_file = self.memory_dir / "sessions.json"
        self._ensure_dir()
        self.lock = threading.Lock()
        self.sessions = self._load_sessions()

    def _ensure_dir(self):
        if not self.memory_dir.exists():
            self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _load_sessions(self) -> List[Dict]:
        if not self.sessions_file.exists():
            return []
        try:
            with self.lock:
                with open(self.sessions_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载会话列表失败: {e}")
            return []

    def _save_sessions(self):
        try:
            temp_file = str(self.sessions_file) + ".tmp"
            with self.lock:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.sessions, f, ensure_ascii=False, indent=2)
                
                if os.path.exists(self.sessions_file):
                    os.remove(self.sessions_file)
                os.rename(temp_file, self.sessions_file)
        except Exception as e:
            logger.error(f"保存会话列表失败: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def get_sessions(self) -> List[Dict]:
        # 按最后更新时间降序排序
        return sorted(self.sessions, key=lambda x: x.get('updated_at', 0), reverse=True)

    def create_session(self, title: str = "新话题") -> str:
        session_id = str(uuid.uuid4())
        now = time.time()
        new_session = {
            "id": session_id,
            "title": title,
            "created_at": now,
            "updated_at": now
        }
        self.sessions.insert(0, new_session)
        self._save_sessions()
        logger.info(f"创建新会话: {session_id} - {title}")
        return session_id

    def update_session(self, session_id: str, title: Optional[str] = None):
        for session in self.sessions:
            if session['id'] == session_id:
                session['updated_at'] = time.time()
                if title:
                    session['title'] = title
                self._save_sessions()
                return True
        # 如果不存在，可能是直接通过API调用的旧会话ID，自动创建
        logger.info(f"会话 {session_id} 不在列表中，自动添加")
        now = time.time()
        new_session = {
            "id": session_id,
            "title": title or "未命名话题",
            "created_at": now,
            "updated_at": now
        }
        self.sessions.insert(0, new_session)
        self._save_sessions()
        return True

    def delete_session(self, session_id: str):
        original_len = len(self.sessions)
        self.sessions = [s for s in self.sessions if s['id'] != session_id]
        
        # Always attempt to delete files, even if session was not in the list (e.g. legacy or default files)
        files_deleted = self._delete_memory_files(session_id)
        
        if len(self.sessions) < original_len or files_deleted:
            self._save_sessions()
            logger.info(f"删除会话: {session_id}")
            return True
        return False

    def _delete_memory_files(self, session_id: str) -> bool:
        # 删除相关的记忆文件
        deleted = False
        try:
            files_to_delete = [
                self.memory_dir / f"{session_id}_short.json",
                self.memory_dir / "long_term" / f"{session_id}_long.json",
                self.memory_dir / "weighted" / f"{session_id}_weighted.json"
            ]
            for p in files_to_delete:
                if p.exists():
                    os.remove(p)
                    logger.info(f"删除文件: {p}")
                    deleted = True
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
