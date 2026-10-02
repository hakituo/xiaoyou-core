"""持久化与 IO Mixin
负责记忆数据的持久化和 IO 操作
"""
import time
from pathlib import Path
from typing import Any

from memory.core.persistence import safe_json_dump
from memory.core.io_ops import (
    load_weighted_data as load_weighted_data_impl,
    load_important_prompts as load_important_prompts_impl,
    get_important_prompts_file as get_important_prompts_file_impl,
    get_project_root as get_project_root_impl,
    get_output_conversation_file as get_output_conversation_file_impl,
    save_weighted_data_locked as save_weighted_data_locked_impl,
    save_important_prompts_locked as save_important_prompts_locked_impl,
    clear_weighted_memories as clear_weighted_memories_impl,
)


class PersistenceMixin:
    """持久化与 IO 操作 Mixin"""

    def _load_weighted_data(self):
        load_weighted_data_impl(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            default_encoding=self._default_encoding if hasattr(self, '_default_encoding') else "utf-8",
            logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
        )

    def _load_important_prompts(self):
        load_important_prompts_impl(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            default_encoding=self._default_encoding if hasattr(self, '_default_encoding') else "utf-8",
            logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
        )

    def _get_important_prompts_file(self) -> Path:
        return get_important_prompts_file_impl(
            self, weighted_memory_dir=self.weighted_memory_dir
        )

    def _get_project_root(self) -> Path:
        return get_project_root_impl()

    def _get_output_conversation_file(self) -> Path:
        return get_output_conversation_file_impl(self)

    def _save_weighted_data_locked(self):
        save_weighted_data_locked_impl(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
            time_module=time,
        )

    def _safe_json_dump_atomic(self, data: Any, file_path: Path):
        safe_json_dump(data, file_path, self._default_encoding if hasattr(self, '_default_encoding') else "utf-8")

    def _save_important_prompts_locked(self):
        save_important_prompts_locked_impl(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            default_encoding=self._default_encoding if hasattr(self, '_default_encoding') else "utf-8",
            logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
        )

    def _save_weighted_data(self):
        """保存权重相关数据 (对外接口)"""
        self._save_weighted_data_locked()

    async def async_save_weighted_data(self):
        """异步保存权重相关数据，不阻塞事件循环"""
        from memory.core.async_persistence import async_safe_json_dump

        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats['rw_lock_reads'] += 1
            weighted_data = {
                "weighted_memories": list(self.weighted_memories.values()),
                "topic_weights": dict(self.topic_weights),
                "emotion_memory_map": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in self.emotion_memory_map.items()
                },
            }
            important_data = list(self.important_prompts)

        weighted_file = self.weighted_memory_dir / f"{self.user_id}_weighted.json"
        await async_safe_json_dump(weighted_data, weighted_file, self._default_encoding if hasattr(self, '_default_encoding') else "utf-8")

        if important_data:
            prompts_file = self.weighted_memory_dir / f"{self.user_id}_important_prompts.json"
            await async_safe_json_dump(important_data, prompts_file, self._default_encoding if hasattr(self, '_default_encoding') else "utf-8")

    def clear_weighted_memories(self) -> int:
        return clear_weighted_memories_impl(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            default_encoding=self._default_encoding if hasattr(self, '_default_encoding') else "utf-8",
            logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
        )

    def _safe_json_dump(self, data: Any, file_path: str):
        safe_json_dump(data, file_path, self._default_encoding if hasattr(self, '_default_encoding') else "utf-8")
