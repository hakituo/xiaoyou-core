#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版记忆管理器 - 带权重管理功能 (融合版)

该模块实现了记忆权重管理系统，能够对不同话题、事件和交互内容进行量化加权处理。
整合了原 EnhancedMemoryManager 的所有功能，作为统一的记忆管理入口。
"""

import time
import threading
import heapq
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path

from core.utils.data_paths import (
    resolve_data_scope_from_conversation_id,
    resolve_memory_user_id,
    get_user_weighted_history_dir,
)
# 使用项目统一日志通道：SafeQueueHandler → QueueListener → ErrorCollectorHandler
# 这样 ERROR 及以上级别日志才会被写入 errors_YYYYMMDD.json
from core.utils.logger import get_logger

# 导入向量嵌入生成模块
try:
    from .embedding_generator import embedding_generator

    VECTOR_SEARCH_ENABLED = True
except ImportError:
    get_logger(__name__).warning("未找到向量嵌入生成模块，向量搜索功能将被禁用")
    VECTOR_SEARCH_ENABLED = False

from config.integrated_config import get_settings

# 导入拆分后的模块
from memory.core.utils import (
    detect_topics,
    classify_category,
    extract_user_preferences,
    extract_keywords,
)
from memory.core.storage import (
    MemoryContext,
    _add_memory_core,
)
from memory.core.distillation import trim_short_term_memory
from memory.core.mutation_ops import (
    update_memory_weight as update_memory_weight_impl,
    delete_memory as delete_memory_impl,
    access_memory as access_memory_impl,
    clear_all_memories as clear_all_memories_impl,
    delete_message as delete_message_impl,
    set_memory_important as set_memory_important_impl,
)
from memory.core.maintenance_ops import (
    reclassify_all_memories as reclassify_all_memories_impl,
)
from memory.core.vector_ops import (
    update_memory_distillation as update_memory_distillation_impl,
    generate_missing_embeddings as generate_missing_embeddings_impl,
    update_weight_config as update_weight_config_impl,
    decode_embedding_to_list,
)
from memory.core.record_ops import (
    get_memory_field_policy as get_memory_field_policy_impl,
    merge_tags as merge_tags_impl,
    clean_memory_records as clean_memory_records_impl,
    normalize_memory_record as normalize_memory_record_impl,
    build_weighted_readable_views as build_weighted_readable_views_impl,
)
from memory.core.readable_ops import (
    get_readable_history_dir as get_readable_history_dir_impl,
    write_readable_history_mirror as write_readable_history_mirror_impl,
    build_short_term_disk_records as build_short_term_disk_records_impl,
    hydrate_short_term_records as hydrate_short_term_records_impl,
    compact_weighted_memory_record as compact_weighted_memory_record_impl,
    hydrate_weighted_memory_record as hydrate_weighted_memory_record_impl,
)
from memory.core.lifecycle_ops import (
    migrate_legacy_data as migrate_legacy_data_impl,
    load_memory as load_memory_impl,
    clear_memory as clear_memory_impl,
    shutdown_manager as shutdown_manager_impl,
)
from memory.core.manager_init_ops import (
    ensure_memory_layout_dirs as ensure_memory_layout_dirs_impl,
    build_memory_layout as build_memory_layout_impl,
    initialize_manager_state as initialize_manager_state_impl,
)
from memory.core.runtime_ops import (
    trim_short_term_memory as trim_short_term_memory_impl,
    update_topic_index as update_topic_index_impl,
    update_topic_index_incremental as update_topic_index_incremental_impl,
)
from memory.core.history_ops import (
    get_recent_history as get_recent_history_impl,
    get_event_history as get_event_history_impl,
)
from memory.core.preferences import (
    extract_preference_updates,
    upsert_preference_locked,
)

# 导入 Mixin
from memory.keyword_index_mixin import KeywordIndexMixin
from memory.search_mixin import SearchMixin
from memory.shadow_analysis_mixin import ShadowAnalysisMixin
from memory.persistence_mixin import PersistenceMixin
from memory.save_scheduler_mixin import SaveSchedulerMixin

logger = get_logger(__name__)

# 使用配置目录路径
settings = get_settings()
HISTORY_DIR = get_user_weighted_history_dir()
DEFAULT_HISTORY_DIR = HISTORY_DIR

# 默认配置常量（从配置文件读取）
DEFAULT_MAX_SHORT_TERM = getattr(settings.memory, 'short_term_capacity', 60) or 60
DEFAULT_MAX_LONG_TERM = getattr(settings.memory, 'long_term_capacity', 100000) or 100000
DEFAULT_TRIM_THRESHOLD = getattr(settings.memory, 'trim_threshold', 60) or 60
DEFAULT_AUTO_SAVE_INTERVAL = getattr(settings.memory, 'auto_save_interval', 300) or 300
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
    KeywordIndexMixin,
    SearchMixin,
    ShadowAnalysisMixin,
    PersistenceMixin,
    SaveSchedulerMixin,
):
    """
    带权重管理的增强版记忆管理器
    融合了原 EnhancedMemoryManager 的功能

    方法按职责拆分到各 Mixin：
    - KeywordIndexMixin: 关键词索引操作
    - SearchMixin: 搜索与检索操作
    - ShadowAnalysisMixin: AI 影子分析操作
    - PersistenceMixin: 持久化与 IO 操作
    - SaveSchedulerMixin: 自动保存与调度操作
    """

    def __init__(
        self,
        user_id: str = "default",
        max_short_term: int = DEFAULT_MAX_SHORT_TERM,
        max_long_term: int = DEFAULT_MAX_LONG_TERM,
        auto_save_interval: int = DEFAULT_AUTO_SAVE_INTERVAL,
        weight_config: Dict[str, float] = None,
        skip_auto_reclassify: bool = False,
        trim_threshold: int = DEFAULT_TRIM_THRESHOLD,
    ):
        """
        初始化带权重管理的记忆管理器

        Args:
            user_id: 用户ID，用于保存/加载记忆
            max_short_term: 短期记忆最大条数（存储上限）
            max_long_term: 长期记忆最大条数
            auto_save_interval: 自动保存间隔（秒）
            weight_config: 权重配置参数
            skip_auto_reclassify: 是否跳过自动重分类（用于只读模式）
            trim_threshold: 短期记忆修剪触发阈值，超过此数量触发修剪
        """
        # 参数验证
        # 直接构造和工厂构造都必须统一到 scope ID，避免同一角色同时写入
        # persona、裸 ID 和 scope 三套 short_term 文件。
        self.user_id = resolve_memory_user_id(str(user_id or "").strip() or "default")
        self.max_short_term = max(MAX_LENGTH_MIN, min(max_short_term, MAX_LENGTH_MAX))
        self.max_long_term = max(MAX_LENGTH_MIN, min(max_long_term, MAX_LENGTH_MAX))
        self.trim_threshold = max(MAX_LENGTH_MIN, min(trim_threshold, self.max_short_term))
        self.auto_save_interval = max(0, int(auto_save_interval))
        self.skip_auto_reclassify = skip_auto_reclassify
        self.storage_scope = resolve_data_scope_from_conversation_id(
            self.user_id, default="aveline"
        )
        self._memory_layout = build_memory_layout_impl(
            self.user_id,
            history_dir_root=HISTORY_DIR,
            default_history_dir=DEFAULT_HISTORY_DIR,
            long_term_dir=LONG_TERM_DIR,
            weighted_memory_dir=WEIGHTED_MEMORY_DIR,
            short_term_dir=SHORT_TERM_DIR,
            sensitive_dir=SENSITIVE_DIR,
            readable_dir=READABLE_DIR,
        )
        ensure_memory_layout_dirs_impl(
            self._memory_layout["history_dir"],
            logger_obj=logger,
            readable_enabled=bool(getattr(settings.memory, "readable_history_enabled", False)),
        )
        initialize_manager_state_impl(self, weight_config=weight_config, settings=settings)

        # [OPTIMIZATION] 初始化优化组件
        self._enable_optimizations = True

        # 初始化统一缓存管理器
        from memory.core.unified_cache_manager import UnifiedCacheManager
        self._unified_cache = UnifiedCacheManager(
            embedding_cache_size=getattr(self, '_embedding_cache_max_items', 2048),
            query_cache_size=getattr(self, '_query_embedding_cache_max_items', 256),
        )

        # 初始化增量主题权重缓存 (90x 性能提升)
        from memory.core.retrieval_ops_optimized import TopicWeightCache
        self._topic_weight_cache = TopicWeightCache(ttl_seconds=30.0)

        # 初始化读写锁 (5x 并发性能提升)
        from memory.core.concurrency_optimized import ReadWriteLock
        self._rw_lock = ReadWriteLock()
        self._use_rw_lock = True

        # 性能统计
        self._perf_stats = {
            'topic_cache_hits': 0,
            'topic_cache_misses': 0,
            'rw_lock_reads': 0,
            'rw_lock_writes': 0,
        }

        # O(1) 计数器 (避免 count_pending_analysis/count_ai_shadow_results 的 O(N) 遍历)
        self._pending_analysis_count: int = 0
        self._ai_shadow_count: int = 0

        # C++ 极速索引器 - 延迟初始化避免阻塞
        self._vector_indexer = None
        self._vector_indexer_initialized = False

        # Mixin 需要的属性引用
        self._logger = logger
        self._default_encoding = DEFAULT_ENCODING
        self._vector_search_enabled = VECTOR_SEARCH_ENABLED
        self._embedding_generator = embedding_generator if VECTOR_SEARCH_ENABLED else None

        # 启动自动保存线程
        if self.auto_save_interval > 0:
            self._start_auto_save()

        # 数据加载就绪标志（threading.Event 支持跨线程等待）
        self._data_loaded_event = threading.Event()

        # 将磁盘I/O密集操作移到后台线程，避免阻塞主线程
        def _deferred_load():
            try:
                self.load_memory()
                self._load_weighted_data()
                self._load_important_prompts()
                self._migrate_legacy_data()
                self.clean_memory_records(sync_save=False)
                self._data_loaded_event.set()
                logger.info("WeightedMemoryManager 后台数据加载完成 (user=%s)", self.user_id)
                # 启动时自动重分类（优化历史数据）
                # 在数据加载完成后执行，避免独立线程与 _deferred_load 并行导致的时序问题
                # 同时减少后台线程数量（从 3 个合并为 1 个），降低与 ChatAgent 创建的 GIL 竞争
                if not self.skip_auto_reclassify:
                    self.reclassify_all_memories()
            except Exception as e:
                logger.warning("WeightedMemoryManager 后台数据加载失败: %s", e)
                self._data_loaded_event.set()

        threading.Thread(target=_deferred_load, daemon=True).start()

        # 注：C++ VectorIndexer 通过 vector_indexer property 延迟获取，
        # 首次访问时自动初始化，无需后台预初始化线程。

        # 注：嵌入模型预加载已统一移至 ChatAgent.initialize() 末尾启动，
        # 避免与 ChatAgent 创建（register_all_tools + 大量 import）抢 GIL。

    # --- 数据加载同步 ---

    def ensure_data_loaded(self, timeout: float = 30.0) -> bool:
        """阻塞等待后台数据加载完成。

        在重启后首次访问记忆前调用，确保 short_term_memory 和
        weighted_memories 已从磁盘载入，避免上下文丢失。

        Args:
            timeout: 最大等待秒数，超时后仍返回（不抛异常）

        Returns:
            True 表示加载完成，False 表示超时
        """
        if self._data_loaded_event.is_set():
            return True
        loaded = self._data_loaded_event.wait(timeout=timeout)
        if not loaded:
            logger.warning(
                "WeightedMemoryManager(user=%s) ensure_data_loaded 超时 (%.1fs)，继续执行",
                self.user_id, timeout,
            )
        return loaded

    # --- 向量索引器 ---

    def _lazy_init_vector_indexer(self):
        """后台延迟初始化 C++ VectorIndexer，避免阻塞主线程"""
        if self._vector_indexer_initialized:
            return
        try:
            import memory_index_py
            self._vector_indexer = memory_index_py.VectorIndexer()
            self._vector_indexer_initialized = True
            logger.info("成功初始化 C++ VectorIndexer (memory_index_py) [延迟初始化]")
        except ImportError as e:
            self._vector_indexer_initialized = True
            logger.warning(f"未能导入 memory_index_py，将回退到原生 Python 检索: {e}")

    @property
    def vector_indexer(self):
        """延迟获取 C++ VectorIndexer，首次访问时初始化"""
        if not self._vector_indexer_initialized:
            self._lazy_init_vector_indexer()
        return self._vector_indexer

    # --- 可读历史镜像 ---

    def _get_readable_history_dir(self) -> Path:
        return get_readable_history_dir_impl(self)

    def _write_readable_history_mirror(self) -> None:
        write_readable_history_mirror_impl(self)

    # --- 主题与偏好检测 ---

    def _detect_topics(self, content: str) -> List[str]:
        """自动检测消息主题"""
        return detect_topics(content)

    def _extract_user_preferences(self, content: str):
        """从用户消息中提取偏好信息"""
        extract_user_preferences(content, self.user_preferences)

    # --- 数据迁移与修剪 ---

    def _migrate_legacy_data(self):
        migrate_legacy_data_impl(self, encoding=DEFAULT_ENCODING)

    def _trim_short_term_memory(self):
        trim_short_term_memory_impl(
            self,
            trim_short_term_memory_fn=trim_short_term_memory,
            logger=logger,
        )

    # --- 主题索引 ---

    def _update_topic_index(self):
        update_topic_index_impl(self)

    def _update_topic_index_incremental(self, memory: Dict[str, Any]):
        update_topic_index_incremental_impl(self, memory)

    # --- 记录序列化/反序列化 ---

    def _build_short_term_disk_records(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return build_short_term_disk_records_impl(self, messages)

    def _hydrate_short_term_records(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return hydrate_short_term_records_impl(self, messages)

    # --- 记录规范化与清洗 ---

    def get_memory_field_policy(self) -> Dict[str, List[str]]:
        return get_memory_field_policy_impl()

    def _merge_tags(
        self, base: List[str], incoming: List[str], limit: int = 8
    ) -> List[str]:
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

    def _compact_weighted_memory_record(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        return compact_weighted_memory_record_impl(self, memory)

    def _hydrate_weighted_memory_record(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        return hydrate_weighted_memory_record_impl(self, memory)

    # --- 生命周期 ---

    def load_memory(self):
        load_memory_impl(self, encoding=DEFAULT_ENCODING)

    def clear_memory(self, mode: str = "all"):
        clear_memory_impl(self, mode=mode)

    def get_sensitive_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取敏感记忆 (仅本地模型使用) [已优化 - 使用读写锁]"""
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats['rw_lock_reads'] += 1
            candidates = [
                m
                for m in self.weighted_memories.values()
                if str(m.get("category") or "").strip().lower() == "sensitive"
            ]
            return heapq.nlargest(limit, candidates, key=lambda x: x["timestamp"])

    def shutdown(self):
        shutdown_manager_impl(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.shutdown()
        return False

    # --- 情感检测 ---

    def _detect_emotion(self, content: str) -> str:
        """检测消息情感 (委托给 core.emotion)"""
        try:
            from core.emotion import get_emotion_manager

            manager = get_emotion_manager()
            if manager.detector is not None:
                state = manager.detector.detect(content)
                if state and state.primary_emotion:
                    return state.primary_emotion.value
        except Exception:
            pass

        content_lower = content.lower()
        for emotion, keywords in _FALLBACK_EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in content_lower:
                    return emotion
        return "neutral"

    def _classify_category(self, content: str) -> str:
        return classify_category(content)

    # --- 核心业务：添加与查询记忆 ---

    def add_memory(
        self,
        content: str = "",
        topics: List[str] = None,
        emotions: List[str] = None,
        is_important: bool = False,
        source: str = "chat",
        category: str = None,
        metadata: Dict[str, Any] = None,
        scopes: Optional[List[str]] = None,
        is_sensitive_mode: bool = False,
        *,
        input: Optional[Any] = None,
        **legacy_kwargs: Any,
    ) -> str:
        """添加带权重的记忆

        支持两种调用方式：
        1. 散装参数: add_memory("content", source="user")
        2. MemoryInput 对象: add_memory(input=MemoryInput(content="content", source="user"))
        """
        from memory.core.storage import MemoryInput

        # 优先使用 MemoryInput 对象
        if input is not None and isinstance(input, MemoryInput):
            inp = input
        else:
            inp = MemoryInput(
                content=content,
                topics=topics,
                emotions=emotions,
                is_important=is_important,
                source=source,
                category=category,
                metadata=metadata,
                scopes=scopes,
                user_id=self.user_id,
                is_sensitive_mode=is_sensitive_mode,
            )

        lock_context = self._rw_lock.write_lock() if self._use_rw_lock else self.lock

        need_save = False
        with lock_context:
            self._perf_stats['rw_lock_writes'] += 1

            generate_embedding = None
            embedding_to_base64 = None
            base64_to_embedding = None
            if VECTOR_SEARCH_ENABLED:
                generate_embedding = getattr(
                    embedding_generator, "generate_embedding", None
                )
                embedding_to_base64 = getattr(
                    embedding_generator, "embedding_to_base64", None
                )
                base64_to_embedding = getattr(
                    embedding_generator, "base64_to_embedding", None
                )

            ctx = MemoryContext(
                weighted_memories=self.weighted_memories,
                short_term_memory=self.short_term_memory,
                category_index=self.category_index,
                important_prompts=self.important_prompts,
                sensitive_memories=self.sensitive_memories,
                topic_weights=self.topic_weights,
                emotion_memory_map=self.emotion_memory_map,
                weight_calculator=self.weight_calculator,
                detect_topics_fn=self._detect_topics,
                detect_emotion_fn=self._detect_emotion,
                classify_category_fn=self._classify_category,
                extract_user_preferences_fn=self._extract_user_preferences,
                extract_preference_updates_fn=self._extract_preference_updates,
                upsert_preference_locked_fn=self._upsert_preference_locked,
                normalize_memory_record_fn=self._normalize_memory_record,
                mark_keyword_index_dirty_fn=self._mark_keyword_index_dirty_locked,
                schedule_save_fn=lambda: None,
                schedule_trim_fn=self._schedule_trim,
                update_topic_index_fn=self._update_topic_index,
                update_topic_index_incremental_fn=self._update_topic_index_incremental,
                vector_search_enabled=VECTOR_SEARCH_ENABLED,
                generate_embedding_fn=generate_embedding,
                embedding_to_base64_fn=embedding_to_base64,
                content_dedupe_index=self.content_dedupe_index,
            )
            mem_input = MemoryInput(
                content=inp.content,
                topics=inp.topics,
                emotions=inp.emotions,
                is_important=inp.is_important,
                source=inp.source,
                category=inp.category,
                metadata=inp.metadata,
                scopes=inp.scopes,
                user_id=inp.user_id,
                is_sensitive_mode=inp.is_sensitive_mode,
            )
            mid, need_save = _add_memory_core(ctx, mem_input, legacy_kwargs)

            if mid and self._enable_optimizations:
                mem = self.weighted_memories.get(mid)
                if mem:
                    for topic in mem.get("topics", []):
                        self._topic_weight_cache.update_topic(
                            topic,
                            weight_delta=mem.get("weight", 0.0),
                            timestamp=mem.get("timestamp", time.time())
                        )

            if mid and self.vector_indexer is not None:
                mem = self.weighted_memories.get(mid)
                if mem:
                    try:
                        embedding_list = decode_embedding_to_list(
                            mem.get("embedding"),
                            base64_to_embedding,
                        )
                        self.vector_indexer.addRecord(
                            str(mid),
                            embedding_list,
                            float(mem.get("weight") or 0.0),
                            float(mem.get("timestamp") or 0.0),
                            str(mem.get("source") or ""),
                            [str(t) for t in (mem.get("topics") or [])]
                        )
                    except Exception as e:
                        logger.warning(f"Failed to sync memory {mid} to C++ VectorIndexer: {e}")

        if need_save:
            self._schedule_save()

        return mid

    def get_memories_by_topic(
        self, topic: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        t = str(topic or "").strip()
        if not t or limit <= 0:
            return []

        candidates: List[Dict[str, Any]] = []
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats['rw_lock_reads'] += 1
            for m in reversed(self.short_term_memory):
                topics = m.get("topics")
                if isinstance(topics, list) and t in topics:
                    candidates.append(m.copy())
                    if len(candidates) >= limit:
                        return candidates

            for m in reversed(list(self.weighted_memories.values())):
                topics = m.get("topics")
                if isinstance(topics, list) and t in topics:
                    candidates.append(m.copy())
                    if len(candidates) >= limit:
                        return candidates

        return candidates

    def get_history(
        self,
        scope: Optional[str] = None,
        raw: bool = False,
        exclude_categories: Optional[List[str]] = None,
        exclude_sensitive: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        try:
            limit_value = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit_value = None

        if limit_value is not None and limit_value <= 0:
            return []

        def _apply_limit(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            if limit_value is None:
                return items
            if len(items) <= limit_value:
                return items
            return items[-limit_value:]

        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats['rw_lock_reads'] += 1
            if raw:
                if not scope and not exclude_categories and not exclude_sensitive:
                    return _apply_limit(list(self.short_term_memory))
                filtered_raw: List[Dict[str, Any]] = []
                for m in self.short_term_memory:
                    cat = m.get("category")
                    if exclude_categories and cat in exclude_categories:
                        continue
                    if exclude_sensitive and cat == "sensitive":
                        continue
                    scopes = m.get("scopes")
                    if not scope:
                        filtered_raw.append(m)
                    elif scopes is None or (
                        isinstance(scopes, list) and scope in scopes
                    ):
                        filtered_raw.append(m)
                return _apply_limit(filtered_raw)

            history: List[Dict[str, Any]] = []
            for m in self.short_term_memory:
                cat = m.get("category")
                if exclude_categories and cat in exclude_categories:
                    continue
                if exclude_sensitive and cat == "sensitive":
                    continue
                scopes = m.get("scopes")
                if scope and scopes and scope not in scopes:
                    continue
                role = m.get("role", m.get("source", "user"))
                if role not in ("system", "user", "assistant", "tool"):
                    role = "system"
                entry: Dict[str, Any] = {
                    "role": role,
                    "content": m.get("content", ""),
                    "timestamp": m.get("timestamp", 0),
                }
                # 保留 category 以便调用方过滤或标记（如 peer_chat 剧本）
                msg_category = m.get("category")
                if msg_category:
                    entry["category"] = msg_category
                # 平台标记对所有 role 都读取（user/assistant 都需要区分来源）
                _meta = m.get("metadata")
                if isinstance(_meta, dict):
                    _pf = _meta.get("platform")
                    if _pf:
                        entry["platform"] = str(_pf)
                if role == "assistant":
                    meta = m.get("metadata")
                    if isinstance(meta, dict):
                        if meta.get("reasoning_content"):
                            entry["reasoning_content"] = meta["reasoning_content"]
                        # 保留主动消息标记，让主 LLM 知道这是主动发起的
                        if meta.get("is_proactive"):
                            entry["is_proactive"] = True
                        # 保留剧本标记，供下游区分 AI 间私聊 vs 用户对话
                        if meta.get("is_peer_script"):
                            entry["is_peer_script"] = True
                    tool_calls = m.get("tool_calls")
                    if tool_calls:
                        entry["tool_calls"] = tool_calls
                if role == "tool":
                    meta = m.get("metadata")
                    if isinstance(meta, dict) and meta.get("tool_call_id"):
                        entry["tool_call_id"] = meta["tool_call_id"]
                history.append(entry)
            return _apply_limit(history)

    def get_weighted_memories(
        self,
        min_weight: float = None,
        topics: List[str] = None,
        limit: int = 10,
        category: str = None,
        emotion: str = None,
        exclude_categories: Optional[List[str]] = None,
        exclude_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """获取按权重排序的记忆列表 [已优化 - 使用读写锁]"""
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats['rw_lock_reads'] += 1
            if category:
                candidate_ids = self.category_index.get(category, [])
                memories_snapshot = [
                    self.weighted_memories[mid].copy()
                    for mid in candidate_ids
                    if mid in self.weighted_memories
                ]
            else:
                memories_snapshot = [m.copy() for m in self.weighted_memories.values()]

        filtered_memories = []
        for memory in memories_snapshot:
            content = memory.get("content", "")
            if content.startswith("SYSTEM_COMMAND:"):
                continue

            mem_cat = memory.get("category")
            if exclude_categories and mem_cat in exclude_categories:
                continue
            if exclude_sensitive and mem_cat == "sensitive":
                continue

            decayed_weight = self.weight_calculator.apply_time_decay(
                memory["weight"], memory["timestamp"], category=mem_cat
            )
            if min_weight is not None and decayed_weight < min_weight:
                continue
            if topics:
                if not any(topic in memory.get("topics", []) for topic in topics):
                    continue

            if category and memory.get("category") != category:
                continue

            updated_memory = memory.copy()
            updated_memory["weight"] = decayed_weight

            if emotion and emotion in memory.get("emotions", []):
                updated_memory["weight"] *= 1.2

            filtered_memories.append(updated_memory)

        filtered_memories.sort(key=lambda x: x.get("weight", 0), reverse=True)
        return filtered_memories[:limit]

    # --- 记忆变更操作 ---

    def update_memory_weight(self, memory_id: str, weight_delta: float) -> bool:
        return update_memory_weight_impl(
            self, memory_id, weight_delta, logger=logger, time_module=time
        )

    def set_memory_important(self, memory_id: str, important: bool) -> bool:
        """标记/取消标记记忆为重要。"""
        return set_memory_important_impl(
            self, memory_id, important, logger=logger, time_module=time
        )

    def delete_memory(self, memory_id: str) -> bool:
        if self._enable_optimizations:
            lock_ctx = self._rw_lock.write_lock() if self._use_rw_lock else self.lock
            with lock_ctx:
                self._perf_stats['rw_lock_writes'] += 1
                mem = self.weighted_memories.get(memory_id)
                if mem:
                    for topic in mem.get("topics", []):
                        self._topic_weight_cache.remove_topic(
                            topic,
                            weight_delta=mem.get("weight", 0.0)
                        )
        res = delete_memory_impl(self, memory_id, logger=logger, time_module=time)
        if res and self.vector_indexer is not None:
            try:
                self.vector_indexer.removeRecord(str(memory_id))
            except Exception as e:
                logger.warning(f"Failed to remove memory {memory_id} from C++ VectorIndexer: {e}")
        return res

    def access_memory(
        self, memory_id: str, importance: int = 1
    ) -> Optional[Dict[str, Any]]:
        return access_memory_impl(
            self, memory_id, importance=importance, logger=logger, time_module=time
        )

    def delete_message(self, message_id: str) -> bool:
        return delete_message_impl(self, message_id, logger=logger)

    def reclassify_all_memories(self):
        reclassify_all_memories_impl(self, logger=logger)

    def clear_all_memories(self):
        clear_all_memories_impl(self, logger=logger)
        if self.vector_indexer is not None:
            try:
                self.vector_indexer.clear()
            except Exception as e:
                logger.warning(f"Failed to clear C++ VectorIndexer: {e}")

    # --- 偏好管理 ---

    def _extract_keywords(self, content: str) -> Set[str]:
        """从内容中提取关键词"""
        return extract_keywords(content)

    def _extract_preference_updates(self, content: str) -> List[Dict[str, Any]]:
        return extract_preference_updates(content)

    def _upsert_preference_locked(
        self,
        key: str,
        polarity: bool,
        source_memory_id: str,
        timestamp: float,
    ) -> Optional[str]:
        generate_embedding = None
        embedding_to_base64 = None
        if VECTOR_SEARCH_ENABLED:
            generate_embedding = getattr(
                embedding_generator, "generate_embedding", None
            )
            embedding_to_base64 = getattr(
                embedding_generator, "embedding_to_base64", None
            )

        memory_id = upsert_preference_locked(
            key=key,
            polarity=polarity,
            source_memory_id=source_memory_id,
            timestamp=timestamp,
            weighted_memories=self.weighted_memories,
            category_index=self.category_index,
            preference_index=self.preference_index,
            calculate_initial_weight=self.weight_calculator.calculate_initial_weight,
            mark_keyword_index_dirty=self._mark_keyword_index_dirty_locked,
            normalize_memory_record=self._normalize_memory_record,
            vector_search_enabled=VECTOR_SEARCH_ENABLED,
            generate_embedding=generate_embedding,
            embedding_to_base64=embedding_to_base64,
        )
        if memory_id:
            self.last_modified_time = time.time()
        return memory_id

    # --- 重要 Prompt ---

    def get_important_prompts(self) -> List[Dict[str, Any]]:
        """获取重要Prompt层记忆 (Layer 3) [已优化 - 使用读写锁]"""
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats['rw_lock_reads'] += 1
            prompts = list(self.important_prompts)
            if prompts:
                return prompts
            derived: List[Dict[str, Any]] = []
            for mem in sorted(
                self.weighted_memories.values(),
                key=lambda x: float(x.get("timestamp") or 0.0),
                reverse=True,
            ):
                topics = [str(t).strip() for t in (mem.get("topics") or []) if str(t).strip()]
                if "user_instruction" in topics or bool(mem.get("is_important", False)):
                    derived.append(mem)
                if len(derived) >= 20:
                    break
            return derived

    # --- 缓存 ---

    def _update_cache(self, memory_id: str, memory: Dict[str, Any]):
        from memory.core.cache_ops import update_cache as update_cache_impl
        update_cache_impl(self, memory_id, memory)

    def _get_from_cache(self, memory_id: str) -> Optional[Dict[str, Any]]:
        from memory.core.cache_ops import get_from_cache as get_from_cache_impl
        return get_from_cache_impl(self, memory_id)

    # --- 异步历史查询 ---

    async def get_recent_history(
        self,
        session_id: str = None,
        limit: int = 100,
        allowed_categories: List[str] = None,
        before: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        return await get_recent_history_impl(
            self,
            session_id=session_id,
            limit=limit,
            allowed_categories=allowed_categories,
            before=before,
        )

    async def get_event_history(
        self,
        conversation_id: str = None,
        limit: int = 100,
        before: Optional[float] = None,
        query: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return await get_event_history_impl(
            self,
            conversation_id=conversation_id,
            limit=limit,
            before=before,
            query=query,
            roles=roles,
        )

    # --- 向量操作 ---

    def update_memory_distillation(
        self,
        memory_id: str,
        summary: str,
        keywords: List[str],
        distillation_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return update_memory_distillation_impl(
            self,
            memory_id,
            summary,
            keywords,
            distillation_metadata,
        )

    def generate_missing_embeddings(self) -> int:
        return generate_missing_embeddings_impl(
            self,
            vector_search_enabled=VECTOR_SEARCH_ENABLED,
            embedding_generator=embedding_generator,
            logger=logger,
        )

    def update_weight_config(self, new_config: Dict[str, float]):
        update_weight_config_impl(self, new_config, logger=logger, time_module=time)

    # --- 状态追踪 ---

    def update_state(
        self, content: str, status: str = "completed", ttl_hours: int = 24
    ) -> str:
        return self.state_tracker.add_state(content, status, ttl_hours)

    def get_active_states(self) -> List[Dict[str, Any]]:
        return self.state_tracker.get_active_states()

    def get_state_context(self) -> str:
        return self.state_tracker.get_context_string()

    # --- 性能监控 ---

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取所有缓存的统计信息"""
        stats = {}
        if hasattr(self, '_unified_cache'):
            stats.update(self._unified_cache.get_all_stats())
        if hasattr(self, '_topic_weight_cache'):
            cache = self._topic_weight_cache
            stats["topic_weights"] = {
                "size": len(cache.weights),
                "last_rebuild_time": cache._last_rebuild_time,
                "needs_rebuild": cache.needs_rebuild(),
            }
        return stats

    def get_lock_stats(self) -> Dict[str, Any]:
        """获取读写锁使用统计"""
        return dict(self._perf_stats)

    def get_optimization_stats(self) -> Dict[str, Any]:
        """获取优化组件的完整统计信息"""
        stats = {
            "enabled": self._enable_optimizations,
            "rw_lock_enabled": self._use_rw_lock,
            "perf_stats": dict(self._perf_stats),
            "caches": self.get_cache_stats(),
        }
        if self.vector_indexer is not None:
            stats["cpp_indexer"] = True
        return stats

    def clear_optimization_caches(self):
        """清除所有优化缓存"""
        if hasattr(self, '_unified_cache'):
            self._unified_cache.clear_all()
        if hasattr(self, '_topic_weight_cache'):
            self._topic_weight_cache.invalidate()

    # --- 批量操作 API ---

    def batch_delete_memories(self, memory_ids: List[str]) -> List[bool]:
        """批量删除记忆 (单次锁获取，N 次删除只需 1 次锁)"""
        from memory.core.batch_ops import batch_delete_memories as _batch_delete
        return _batch_delete(self, memory_ids)

    def batch_update_weights(
        self, updates: List[Tuple[str, float]]
    ) -> List[bool]:
        """批量更新权重 (单次锁获取，N 次更新只需 1 次锁)"""
        from memory.core.batch_ops import batch_update_weights as _batch_update
        return _batch_update(self, updates)

    def batch_search_memories(
        self,
        queries: List[str],
        limit: int = 10,
        min_similarity: float = 0.3,
        category: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        """批量搜索记忆 (单次快照减少锁竞争)"""
        from memory.core.batch_ops import batch_search_memories as _batch_search
        return _batch_search(self, queries, limit, min_similarity, category)


_instances: Dict[str, "WeightedMemoryManager"] = {}
_instances_lock = threading.Lock()


def get_weighted_memory_manager(user_id: str = "default") -> WeightedMemoryManager:
    """获取或创建用户的权重记忆管理器实例

    同一 scope（角色）下的不同 persona 共享记忆池。
    conversation_id 会被转换为 scope 级别的 user_id。

    重启后首次调用时，会阻塞等待后台数据加载完成（最多 30 秒），
    避免在 short_term_memory 未就绪时返回空上下文。
    """
    raw_uid = str(user_id or "").strip() or "default"

    # 转换失败必须显式暴露，不能静默退回 raw ID 后生成第二套记忆池。
    uid = resolve_memory_user_id(raw_uid)

    with _instances_lock:
        manager = _instances.get(uid)
        if manager is None:
            manager = WeightedMemoryManager(user_id=uid)
            _instances[uid] = manager
        # 更新最后访问时间，用于清理机制判断
        manager.last_access_time = time.time()

    # 等待后台数据加载完成（在锁外调用，避免阻塞其他线程获取实例）
    manager.ensure_data_loaded(timeout=30.0)
    return manager


# 默认空闲超时时间（秒），超过此时间未访问的实例将被清理
_DEFAULT_IDLE_TIMEOUT_SECONDS = 3600  # 1 小时


def cleanup_idle_weighted_memory_managers(
    idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> int:
    """清理长时间未访问的 WeightedMemoryManager 实例，防止内存泄漏

    Args:
        idle_timeout_seconds: 空闲超时时间（秒），默认 1 小时

    Returns:
        被清理的实例数量
    """
    now = time.time()
    removed = 0
    with _instances_lock:
        # 复制 key 列表，避免迭代时修改字典
        for uid in list(_instances.keys()):
            manager = _instances.get(uid)
            if manager is None:
                continue
            last_access = getattr(manager, "last_access_time", 0) or 0
            if now - last_access > idle_timeout_seconds:
                try:
                    manager.shutdown()
                except Exception:
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
    """关闭并清理所有 WeightedMemoryManager 实例（用于进程退出时调用）

    Returns:
        被清理的实例数量
    """
    removed = 0
    with _instances_lock:
        for uid in list(_instances.keys()):
            manager = _instances.pop(uid, None)
            if manager is not None:
                try:
                    manager.shutdown()
                except Exception:
                    pass
                removed += 1
    return removed
