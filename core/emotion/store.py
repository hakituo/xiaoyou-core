import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)

class EmotionStore:
    """
    负责情绪数据的持久化存储（历史记录等）
    """
    def __init__(self, data_dir: str = "data/emotions"):
        self.data_dir = Path(data_dir)
        self._ensure_dir()
        # 内存缓存，每个用户最近 N 条
        self._history_cache: Dict[str, deque] = {}
        self._max_history = 100

    def _ensure_dir(self):
        if not self.data_dir.exists():
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create emotion data dir: {e}")

    def add_record(self, user_id: str, record: Dict[str, Any]):
        """
        添加一条情绪记录
        """
        if user_id not in self._history_cache:
            self._history_cache[user_id] = deque(maxlen=self._max_history)
        
        self._history_cache[user_id].append(record)
        # TODO: 异步写入磁盘以避免IO阻塞
        # 暂时简单实现：每10条写一次，或者定期写
        # 这里为了 MVP，暂时只在内存，或者追加到文件
        self._append_to_file(user_id, record)

    def get_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        if user_id in self._history_cache:
            return list(self._history_cache[user_id])[-limit:]
        
        # 尝试从文件加载最近的 (简化版，暂不实现全量加载)
        return []

    def _append_to_file(self, user_id: str, record: Dict[str, Any]):
        file_path = self.data_dir / f"{user_id}_history.jsonl"
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write emotion record: {e}")
