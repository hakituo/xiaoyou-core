from core.utils.logger import get_logger
import atexit
import json

import queue
import threading
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class EmotionStore:
    """
    负责情绪数据的持久化存储（历史记录等）
    使用后台线程批量写入JSONL文件
    """

    def __init__(self, data_dir: str = "data/emotions"):
        self.data_dir = Path(data_dir)
        self._ensure_dir()
        self._history_cache: Dict[str, deque] = {}
        self._max_history = 100
        self._flush_interval = 1.0
        self._batch_size = 16
        self._closed = False
        self._close_lock = threading.Lock()
        self._write_queue: "queue.Queue[Any]" = queue.Queue()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="EmotionStoreWriter",
            daemon=True,
        )
        self._writer_thread.start()
        atexit.register(self.close)

    def _ensure_dir(self):
        if not self.data_dir.exists():
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create emotion data dir: {e}")

    def add_record(self, user_id: str, record: Dict[str, Any]):
        if user_id not in self._history_cache:
            self._history_cache[user_id] = deque(maxlen=self._max_history)

        self._history_cache[user_id].append(record)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        if self._closed:
            self._append_lines_to_file(user_id, [line])
            return
        self._write_queue.put((user_id, line))

    def get_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        if user_id in self._history_cache:
            return list(self._history_cache[user_id])[-limit:]
        return []

    def flush(self, timeout: Optional[float] = None) -> bool:
        if self._closed and self._write_queue.empty():
            return True
        completed = threading.Event()
        self._write_queue.put((None, completed))
        return completed.wait(timeout)

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.flush(timeout=5.0)
        self._write_queue.put(None)
        if self._writer_thread.is_alive():
            self._writer_thread.join(timeout=5.0)

    def _writer_loop(self):
        pending: Dict[str, List[str]] = {}
        pending_count = 0

        while True:
            try:
                item = self._write_queue.get(timeout=self._flush_interval)
            except queue.Empty:
                if pending_count:
                    self._flush_pending(pending)
                    pending.clear()
                    pending_count = 0
                if self._closed and self._write_queue.empty():
                    break
                continue

            try:
                if item is None:
                    if pending_count:
                        self._flush_pending(pending)
                        pending.clear()
                    break

                if item[0] is None:
                    if pending_count:
                        self._flush_pending(pending)
                        pending.clear()
                        pending_count = 0
                    item[1].set()
                    continue

                user_id, line = item
                pending.setdefault(user_id, []).append(line)
                pending_count += 1

                if pending_count >= self._batch_size:
                    self._flush_pending(pending)
                    pending.clear()
                    pending_count = 0
            finally:
                self._write_queue.task_done()

    def _flush_pending(self, pending: Dict[str, List[str]]):
        for user_id, lines in pending.items():
            if lines:
                self._append_lines_to_file(user_id, lines)

    def _append_lines_to_file(self, user_id: str, lines: List[str]):
        file_path = self.data_dir / f"{user_id}_history.jsonl"
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.error(f"Failed to write emotion record: {e}")
