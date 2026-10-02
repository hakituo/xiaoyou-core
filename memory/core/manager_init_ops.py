from collections import OrderedDict, defaultdict, deque
import threading
from pathlib import Path
import time
from typing import Any, Dict

from core.utils.data_paths import (
    get_memories_dir_for_conversation,
    resolve_data_scope_from_conversation_id,
)
from memory.core.cache_ops import LRUCache
from core.utils.config_accessor import get_config
from memory.core.weights import MemoryWeightCalculator
from memory.persistent_state import PersistentStateTracker


def ensure_memory_layout_dirs(
    history_dir: Path,
    *,
    logger_obj: Any,
    readable_enabled: bool = False,
) -> None:
    try:
        paths_to_create = [
            history_dir,
            history_dir / "weighted",
            history_dir / "short_term",
        ]
        if readable_enabled:
            paths_to_create.append(history_dir / "readable")
        for path in paths_to_create:
            path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger_obj.error(f"创建记忆布局目录时出错: {e}")


def build_memory_layout(
    user_id: str,
    *,
    history_dir_root: Path,
    default_history_dir: Path,
    long_term_dir: Path,
    weighted_memory_dir: Path,
    short_term_dir: Path,
    sensitive_dir: Path,
    readable_dir: Path,
) -> Dict[str, Any]:
    uid = str(user_id or "").strip() or "default"
    scope = resolve_data_scope_from_conversation_id(uid, default="aveline")
    current_history_dir = Path(history_dir_root).resolve()
    if current_history_dir != default_history_dir:
        history_dir = current_history_dir
    else:
        history_dir = Path(get_memories_dir_for_conversation(uid)).resolve()
    return {
        "scope": scope,
        "history_dir": history_dir,
        "long_term_dir": history_dir / "long_term",
        "weighted_dir": history_dir / "weighted",
        "short_term_dir": history_dir / "short_term",
        "sensitive_dir": history_dir / "sensitive",
        "readable_dir": history_dir / "readable",
        "legacy_history_dir": history_dir_root,
        "legacy_long_term_dir": long_term_dir,
        "legacy_weighted_dir": weighted_memory_dir,
        "legacy_short_term_dir": short_term_dir,
        "legacy_sensitive_dir": sensitive_dir,
        "legacy_readable_dir": readable_dir,
    }


def initialize_manager_state(
    manager: Any,
    *,
    weight_config: Dict[str, float] | None,
    settings: Any,
) -> None:
    manager.short_term_memory = []
    manager.topics = defaultdict(list)
    manager.user_preferences = {}
    manager.preference_index = {}
    manager.memory_dir = manager._memory_layout["history_dir"]
    manager.long_term_dir = manager._memory_layout["long_term_dir"]
    manager.weighted_memory_dir = manager._memory_layout["weighted_dir"]
    manager.short_term_dir = manager._memory_layout["short_term_dir"]
    manager.sensitive_dir = manager._memory_layout["sensitive_dir"]
    manager.readable_history_root = manager._memory_layout["readable_dir"]
    manager.legacy_history_dir = manager._memory_layout["legacy_history_dir"]
    manager.legacy_long_term_dir = manager._memory_layout["legacy_long_term_dir"]
    manager.legacy_weighted_dir = manager._memory_layout["legacy_weighted_dir"]
    manager.legacy_short_term_dir = manager._memory_layout["legacy_short_term_dir"]
    manager.legacy_sensitive_dir = manager._memory_layout["legacy_sensitive_dir"]
    manager.legacy_readable_dir = manager._memory_layout["legacy_readable_dir"]
    manager.last_modified_time = time.time()
    manager.last_save_time = 0
    manager.last_access_time = time.time()
    manager.lock = threading.RLock()
    manager._stop_event = threading.Event()
    manager.weight_calculator = MemoryWeightCalculator(weight_config)
    manager.weighted_memories = {}
    manager.category_index = defaultdict(list)
    manager.content_dedupe_index: Dict[str, str] = {}
    manager.important_prompts = []
    manager.sensitive_memories = []
    manager.topic_weights = defaultdict(float)
    manager.emotion_memory_map = defaultdict(list)
    manager.state_tracker = PersistentStateTracker(
        storage_dir=str(manager.memory_dir),
        user_id=manager.user_id,
    )
    manager.enable_readable_history_mirror = bool(
        getattr(settings.memory, "readable_history_enabled", False)
    )

    l1_size = getattr(settings.memory, 'l1_cache_size', 20)
    l2_size = getattr(settings.memory, 'l2_cache_size', 50)
    manager._cache = {
        "l1": LRUCache(l1_size),
        "l2": LRUCache(l2_size),
        "access_count": {},
    }

    manager._save_queue = deque(maxlen=1000)
    manager._save_thread = None
    manager._save_event = threading.Event()
    manager._save_batch_size = 10
    manager._save_delay = 5.0
    manager._is_saving = False

    manager._trim_scheduled = False
    manager._trim_delay = 30.0
    manager._trim_timer = None
    manager._distillation_thread = None

    manager._keyword_index = defaultdict(list)
    manager._keyword_graph = defaultdict(dict)
    manager._index_updated = False
    manager._keyword_force_rebuild = False
    manager._keyword_dirty_ids = set()
    manager._memory_keyword_sets = {}
    manager._memory_keyword_pairs = {}

    embedding_cache_max_items = 2048
    query_embedding_cache_max_items = 256
    try:
        rag = get_config("chat.rag", default=None, settings=settings)
        if rag is not None:
            embedding_cache_max_items = int(
                getattr(rag, "embedding_cache_max_items", embedding_cache_max_items)
            )
            query_embedding_cache_max_items = int(
                getattr(
                    rag,
                    "query_embedding_cache_max_items",
                    query_embedding_cache_max_items,
                )
            )
    except Exception:
        pass

    manager._embedding_cache_max_items = max(0, int(embedding_cache_max_items))
    manager._query_embedding_cache_max_items = max(0, int(query_embedding_cache_max_items))
    manager._embedding_cache = OrderedDict()
    manager._query_embedding_cache = OrderedDict()

    try:
        from core.cache.async_cache_manager import AsyncCacheManager

        manager.search_cache = AsyncCacheManager()
    except ImportError:
        manager.search_cache = None
