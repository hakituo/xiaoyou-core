"""WeightedMemoryManager 的构造与后台加载。"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from core.utils.data_paths import resolve_data_scope_from_conversation_id, resolve_memory_user_id
from memory.core.manager_init_ops import (
    build_memory_layout as build_memory_layout_impl,
    ensure_memory_layout_dirs as ensure_memory_layout_dirs_impl,
    initialize_manager_state as initialize_manager_state_impl,
)


def initialize_weighted_memory_manager(
    manager: Any,
    *,
    user_id: str,
    max_short_term: int,
    max_long_term: int,
    auto_save_interval: int,
    weight_config: dict[str, float] | None,
    skip_auto_reclassify: bool,
    trim_threshold: int,
    max_length_min: int,
    max_length_max: int,
    history_dir: Path,
    default_history_dir: Path,
    long_term_dir: Path,
    weighted_memory_dir: Path,
    short_term_dir: Path,
    sensitive_dir: Path,
    readable_dir: Path,
    settings: Any,
    logger: Any,
    vector_search_enabled: bool,
    embedding_generator: Any,
    default_encoding: str,
) -> None:
    """初始化管理器状态，并启动单一后台加载线程。"""
    manager.user_id = resolve_memory_user_id(str(user_id or "").strip() or "default")
    manager.max_short_term = max(max_length_min, min(max_short_term, max_length_max))
    manager.max_long_term = max(max_length_min, min(max_long_term, max_length_max))
    manager.trim_threshold = max(max_length_min, min(trim_threshold, manager.max_short_term))
    manager.auto_save_interval = max(0, int(auto_save_interval))
    manager.skip_auto_reclassify = skip_auto_reclassify
    manager.storage_scope = resolve_data_scope_from_conversation_id(
        manager.user_id, default="aveline"
    )
    manager._memory_layout = build_memory_layout_impl(
        manager.user_id,
        history_dir_root=history_dir,
        default_history_dir=default_history_dir,
        long_term_dir=long_term_dir,
        weighted_memory_dir=weighted_memory_dir,
        short_term_dir=short_term_dir,
        sensitive_dir=sensitive_dir,
        readable_dir=readable_dir,
    )
    ensure_memory_layout_dirs_impl(
        manager._memory_layout["history_dir"],
        logger_obj=logger,
        readable_enabled=bool(getattr(settings.memory, "readable_history_enabled", False)),
    )
    initialize_manager_state_impl(manager, weight_config=weight_config, settings=settings)

    manager._enable_optimizations = True
    from memory.core.unified_cache_manager import UnifiedCacheManager

    manager._unified_cache = UnifiedCacheManager(
        embedding_cache_size=getattr(manager, "_embedding_cache_max_items", 2048),
        query_cache_size=getattr(manager, "_query_embedding_cache_max_items", 256),
    )
    from memory.core.retrieval_ops_optimized import TopicWeightCache

    manager._topic_weight_cache = TopicWeightCache(ttl_seconds=30.0)
    from memory.core.concurrency_optimized import ReadWriteLock

    manager._rw_lock = ReadWriteLock()
    manager._use_rw_lock = True
    manager._perf_stats = {
        "topic_cache_hits": 0,
        "topic_cache_misses": 0,
        "rw_lock_reads": 0,
        "rw_lock_writes": 0,
    }
    manager._pending_analysis_count = 0
    manager._ai_shadow_count = 0
    manager._pending_embedding_backfill = 0
    manager._vector_indexer = None
    manager._vector_indexer_initialized = False
    manager._logger = logger
    manager._default_encoding = default_encoding
    manager._vector_search_enabled = vector_search_enabled
    manager._embedding_generator = embedding_generator if vector_search_enabled else None

    if manager.auto_save_interval > 0:
        manager._start_auto_save()
    manager._data_loaded_event = threading.Event()
    manager._save_pending_during_load = False
    threading.Thread(
        target=_load_manager_data,
        args=(manager, logger),
        daemon=True,
    ).start()


def _load_manager_data(manager: Any, logger: Any) -> None:
    """在后台串行加载、清理和迁移数据。"""
    from memory.core import startup_profile

    profile_start = time.perf_counter() if startup_profile.is_enabled() else None
    try:
        manager.load_memory()
        manager._load_weighted_data()
        manager._load_important_prompts()
        manager._migrate_legacy_data()
        manager.clean_memory_records(sync_save=False)
        if not manager.skip_auto_reclassify:
            manager.reclassify_all_memories()
        manager._data_loaded_event.set()
        logger.info("WeightedMemoryManager 后台数据加载完成 (user=%s)", manager.user_id)
        if manager._save_pending_during_load:
            manager._save_pending_during_load = False
            manager._schedule_save()
        if int(getattr(manager, "_pending_embedding_backfill", 0) or 0) > 0:
            threading.Thread(
                target=manager.run_pending_embedding_backfill,
                daemon=True,
                name="embedding-backfill",
            ).start()
    except Exception as exc:
        logger.warning("WeightedMemoryManager 后台数据加载失败: %s", exc)
        manager._data_loaded_event.set()
    finally:
        if profile_start is not None:
            startup_profile.accumulate(
                "TOTAL _deferred_load 全链路",
                time.perf_counter() - profile_start,
            )
