#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""带权重记忆管理器的兼容门面与单例生命周期。"""
# ruff: noqa: F401

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict

from config.integrated_config import get_settings
from core.utils.data_paths import (
    get_user_weighted_history_dir,
    resolve_data_scope_from_conversation_id,
    resolve_memory_user_id,
)
from core.utils.logger import get_logger
from memory.core.distillation import trim_short_term_memory
from memory.core.history_ops import (
    get_event_history as get_event_history_impl,
    get_recent_history as get_recent_history_impl,
)
from memory.core.lifecycle_ops import (
    clear_memory as clear_memory_impl,
    load_memory as load_memory_impl,
    migrate_legacy_data as migrate_legacy_data_impl,
    shutdown_manager as shutdown_manager_impl,
)
from memory.core.maintenance_ops import reclassify_all_memories as reclassify_all_memories_impl
from memory.core.manager_init_ops import (
    build_memory_layout as build_memory_layout_impl,
    ensure_memory_layout_dirs as ensure_memory_layout_dirs_impl,
    initialize_manager_state as initialize_manager_state_impl,
)
from memory.core.mutation_ops import (
    access_memory as access_memory_impl,
    clear_all_memories as clear_all_memories_impl,
    delete_memory as delete_memory_impl,
    delete_message as delete_message_impl,
    set_memory_important as set_memory_important_impl,
    update_memory_weight as update_memory_weight_impl,
)
from memory.core.preferences import extract_preference_updates, upsert_preference_locked
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
from memory.core.storage import MemoryContext, _add_memory_core
from memory.core.utils import (
    classify_category,
    detect_topics,
    extract_keywords,
    extract_user_preferences,
)
from memory.core.vector_ops import (
    decode_embedding_to_list,
    generate_missing_embeddings as generate_missing_embeddings_impl,
    update_memory_distillation as update_memory_distillation_impl,
    update_weight_config as update_weight_config_impl,
)
from memory.keyword_index_mixin import KeywordIndexMixin
from memory.persistence_mixin import PersistenceMixin
from memory.save_scheduler_mixin import SaveSchedulerMixin
from memory.search_mixin import SearchMixin
from memory.shadow_analysis_mixin import ShadowAnalysisMixin
from memory.weighted_manager.initialization import initialize_weighted_memory_manager
from memory.weighted_manager.lifecycle import WeightedManagerLifecycleMixin
from memory.weighted_manager.preferences import WeightedManagerPreferenceMixin
from memory.weighted_manager.queries import WeightedManagerQueryMixin
from memory.weighted_manager.support import WeightedManagerSupportMixin
from memory.weighted_manager.writing import WeightedManagerWriteMixin

try:
    from .embedding_generator import embedding_generator

    VECTOR_SEARCH_ENABLED = True
except ImportError:
    get_logger(__name__).warning("未找到向量嵌入生成模块，向量搜索功能将被禁用")
    embedding_generator = None
    VECTOR_SEARCH_ENABLED = False

logger = get_logger(__name__)
settings = get_settings()
HISTORY_DIR = get_user_weighted_history_dir()
DEFAULT_HISTORY_DIR = HISTORY_DIR
DEFAULT_MAX_SHORT_TERM = getattr(settings.memory, "short_term_capacity", 60) or 60
DEFAULT_MAX_LONG_TERM = getattr(settings.memory, "long_term_capacity", 100000) or 100000
DEFAULT_TRIM_THRESHOLD = getattr(settings.memory, "trim_threshold", 60) or 60
DEFAULT_AUTO_SAVE_INTERVAL = getattr(settings.memory, "auto_save_interval", 300) or 300
MAX_LENGTH_MIN = 1
MAX_LENGTH_MAX = 10000
DEFAULT_ENCODING = "utf-8"
LONG_TERM_DIR = HISTORY_DIR / "long_term"
WEIGHTED_MEMORY_DIR = HISTORY_DIR / "weighted"
SHORT_TERM_DIR = HISTORY_DIR / "short_term"
SENSITIVE_DIR = HISTORY_DIR / "sensitive"
READABLE_DIR = HISTORY_DIR / "readable"
_FALLBACK_EMOTION_KEYWORDS = {
    "happy": ("开心", "高兴", "喜欢", "棒", "不错", "哈哈", "谢谢"),
    "sad": ("难过", "伤心", "讨厌", "糟糕", "烦", "失望", "痛苦"),
    "angry": ("生气", "愤怒", "火大", "滚"),
    "anxious": ("焦虑", "担心", "害怕"),
}


class WeightedMemoryManager(
    WeightedManagerLifecycleMixin,
    WeightedManagerWriteMixin,
    WeightedManagerQueryMixin,
    WeightedManagerPreferenceMixin,
    WeightedManagerSupportMixin,
    KeywordIndexMixin,
    SearchMixin,
    ShadowAnalysisMixin,
    PersistenceMixin,
    SaveSchedulerMixin,
):
    """统一记忆入口；具体职责由各 Mixin 和 ``memory.core`` 操作模块实现。"""

    def __init__(
        self,
        user_id: str = "default",
        max_short_term: int = DEFAULT_MAX_SHORT_TERM,
        max_long_term: int = DEFAULT_MAX_LONG_TERM,
        auto_save_interval: int = DEFAULT_AUTO_SAVE_INTERVAL,
        weight_config: Dict[str, float] = None,
        skip_auto_reclassify: bool = False,
        trim_threshold: int = DEFAULT_TRIM_THRESHOLD,
    ) -> None:
        initialize_weighted_memory_manager(
            self,
            user_id=user_id,
            max_short_term=max_short_term,
            max_long_term=max_long_term,
            auto_save_interval=auto_save_interval,
            weight_config=weight_config,
            skip_auto_reclassify=skip_auto_reclassify,
            trim_threshold=trim_threshold,
            max_length_min=MAX_LENGTH_MIN,
            max_length_max=MAX_LENGTH_MAX,
            history_dir=HISTORY_DIR,
            default_history_dir=DEFAULT_HISTORY_DIR,
            long_term_dir=LONG_TERM_DIR,
            weighted_memory_dir=WEIGHTED_MEMORY_DIR,
            short_term_dir=SHORT_TERM_DIR,
            sensitive_dir=SENSITIVE_DIR,
            readable_dir=READABLE_DIR,
            settings=settings,
            logger=logger,
            vector_search_enabled=VECTOR_SEARCH_ENABLED,
            embedding_generator=embedding_generator,
            default_encoding=DEFAULT_ENCODING,
        )


_instances: Dict[str, WeightedMemoryManager] = {}
_instances_lock = threading.Lock()
_DEFAULT_IDLE_TIMEOUT_SECONDS = 3600


def get_weighted_memory_manager(
    user_id: str = "default",
    ensure_loaded: bool = True,
) -> WeightedMemoryManager:
    """按角色 scope 获取唯一管理器实例。"""
    raw_uid = str(user_id or "").strip() or "default"
    uid = resolve_memory_user_id(raw_uid)
    with _instances_lock:
        manager = _instances.get(uid)
        if manager is None:
            manager = WeightedMemoryManager(user_id=uid)
            _instances[uid] = manager
        manager.last_access_time = time.time()
    if ensure_loaded:
        manager.ensure_data_loaded(timeout=30.0)
    return manager


def cleanup_idle_weighted_memory_managers(
    idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> int:
    """关闭并移除超过空闲阈值的管理器。"""
    now = time.time()
    removed = 0
    with _instances_lock:
        for uid in list(_instances):
            manager = _instances.get(uid)
            if manager is None:
                continue
            last_access = getattr(manager, "last_access_time", 0) or 0
            if now - last_access <= idle_timeout_seconds:
                continue
            try:
                manager.shutdown()
            except Exception:  # noqa: BLE001
                pass
            _instances.pop(uid, None)
            removed += 1
            logger.info(
                "清理空闲 WeightedMemoryManager 实例: %s (空闲 %.0fs)",
                uid,
                now - last_access,
            )
    return removed


def shutdown_all_weighted_memory_managers() -> int:
    """关闭并清理全部管理器实例。"""
    removed = 0
    with _instances_lock:
        for uid in list(_instances):
            manager = _instances.pop(uid, None)
            if manager is None:
                continue
            try:
                manager.shutdown()
            except Exception:  # noqa: BLE001
                pass
            removed += 1
    return removed
