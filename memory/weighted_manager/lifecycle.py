"""WeightedMemoryManager 的生命周期和记录规范化能力。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from memory.core.distillation import trim_short_term_memory
from memory.core.lifecycle_ops import (
    clear_memory as clear_memory_impl,
    load_memory as load_memory_impl,
    migrate_legacy_data as migrate_legacy_data_impl,
    shutdown_manager as shutdown_manager_impl,
)
from memory.core.readable_ops import (
    build_short_term_disk_records as build_short_term_disk_records_impl,
    compact_weighted_memory_record as compact_weighted_memory_record_impl,
    get_readable_history_dir as get_readable_history_dir_impl,
    hydrate_short_term_records as hydrate_short_term_records_impl,
    hydrate_weighted_memory_record as hydrate_weighted_memory_record_impl,
    write_readable_history_mirror as write_readable_history_mirror_impl,
)
from memory.core.record_ops import (
    build_weighted_readable_views as build_weighted_readable_views_impl,
    clean_memory_records as clean_memory_records_impl,
    get_memory_field_policy as get_memory_field_policy_impl,
    merge_tags as merge_tags_impl,
    normalize_memory_record as normalize_memory_record_impl,
)
from memory.core.runtime_ops import (
    trim_short_term_memory as trim_short_term_memory_impl,
    update_topic_index as update_topic_index_impl,
    update_topic_index_incremental as update_topic_index_incremental_impl,
)
from memory.core.utils import classify_category, detect_topics, extract_user_preferences

_FALLBACK_EMOTION_KEYWORDS = {
    "happy": ("开心", "高兴", "喜欢", "棒", "不错", "哈哈", "谢谢"),
    "sad": ("难过", "伤心", "讨厌", "糟糕", "烦", "失望", "痛苦"),
    "angry": ("生气", "愤怒", "火大", "滚"),
    "anxious": ("焦虑", "担心", "害怕"),
}


class WeightedManagerLifecycleMixin:
    """数据加载、索引器、序列化与关闭职责。"""

    def ensure_data_loaded(self, timeout: float = 30.0) -> bool:
        if self._data_loaded_event.is_set():
            return True
        loaded = self._data_loaded_event.wait(timeout=timeout)
        if not loaded:
            self._logger.warning(
                "WeightedMemoryManager(user=%s) ensure_data_loaded 超时 (%.1fs)，继续执行",
                self.user_id,
                timeout,
            )
        return loaded

    def _lazy_init_vector_indexer(self) -> None:
        if self._vector_indexer_initialized:
            return
        try:
            import memory_index_py

            self._vector_indexer = memory_index_py.VectorIndexer()
            self._logger.info("成功初始化 C++ VectorIndexer (memory_index_py) [延迟初始化]")
        except ImportError as exc:
            self._logger.warning("未能导入 memory_index_py，将回退到原生 Python 检索: %s", exc)
        finally:
            self._vector_indexer_initialized = True

    @property
    def vector_indexer(self):
        if not self._vector_indexer_initialized:
            self._lazy_init_vector_indexer()
        return self._vector_indexer

    def _get_readable_history_dir(self) -> Path:
        return get_readable_history_dir_impl(self)

    def _write_readable_history_mirror(self) -> None:
        write_readable_history_mirror_impl(self)

    def _detect_topics(self, content: str) -> List[str]:
        return detect_topics(content)

    def _extract_user_preferences(self, content: str) -> None:
        extract_user_preferences(content, self.user_preferences)

    def _migrate_legacy_data(self) -> None:
        migrate_legacy_data_impl(self, encoding=self._default_encoding)

    def _trim_short_term_memory(self) -> None:
        trim_short_term_memory_impl(
            self,
            trim_short_term_memory_fn=trim_short_term_memory,
            logger=self._logger,
        )

    def _update_topic_index(self) -> None:
        update_topic_index_impl(self)

    def _update_topic_index_incremental(self, memory: Dict[str, Any]) -> None:
        update_topic_index_incremental_impl(self, memory)

    def _build_short_term_disk_records(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return build_short_term_disk_records_impl(self, messages)

    def _hydrate_short_term_records(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return hydrate_short_term_records_impl(self, messages)

    def get_memory_field_policy(self) -> Dict[str, List[str]]:
        return get_memory_field_policy_impl()

    def _merge_tags(self, base: List[str], incoming: List[str], limit: int = 8) -> List[str]:
        return merge_tags_impl(base, incoming, limit=limit)

    def clean_memory_records(
        self,
        *,
        sync_save: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return clean_memory_records_impl(self, sync_save=sync_save, dry_run=dry_run)

    def _normalize_memory_record(
        self, memory: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool]:
        return normalize_memory_record_impl(self, memory)

    def _build_weighted_readable_views(self) -> Dict[str, Any]:
        return build_weighted_readable_views_impl(self)

    def _compact_weighted_memory_record(
        self, memory: Dict[str, Any], *, keep_embedding: bool = False
    ) -> Dict[str, Any]:
        return compact_weighted_memory_record_impl(self, memory, keep_embedding=keep_embedding)

    def _hydrate_weighted_memory_record(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        return hydrate_weighted_memory_record_impl(self, memory)

    def load_memory(self) -> None:
        load_memory_impl(self, encoding=self._default_encoding)

    def clear_memory(self, mode: str = "all") -> None:
        clear_memory_impl(self, mode=mode)

    def shutdown(self) -> None:
        shutdown_manager_impl(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.shutdown()
        return False

    def _detect_emotion(self, content: str) -> str:
        try:
            from core.emotion import get_emotion_manager

            manager = get_emotion_manager()
            if manager.detector is not None:
                state = manager.detector.detect(content)
                if state and state.primary_emotion:
                    return state.primary_emotion.value
        except Exception:  # noqa: BLE001
            pass
        content_lower = content.lower()
        for emotion, keywords in _FALLBACK_EMOTION_KEYWORDS.items():
            if any(keyword in content_lower for keyword in keywords):
                return emotion
        return "neutral"

    def _classify_category(self, content: str) -> str:
        return classify_category(content)
