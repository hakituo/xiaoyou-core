from typing import Any, Dict, List, Optional
import logging

from memory.core.lock_utils import get_write_lock

logger = logging.getLogger(__name__)


def decode_embedding_to_list(
    embedding_val: Any,
    base64_to_embedding_fn: Optional[Any] = None,
) -> List[float]:
    """将记忆记录中的 embedding 字段解码为 float 列表

    支持三种输入格式：base64 字符串、Python 列表、numpy 数组。
    此函数消除了 weighted_memory_manager.py 和 io_ops.py 中的重复解码逻辑。
    """
    if embedding_val is None:
        return []
    if isinstance(embedding_val, list):
        return embedding_val
    if isinstance(embedding_val, str) and base64_to_embedding_fn is not None:
        try:
            embedding_np = base64_to_embedding_fn(embedding_val)
            return embedding_np.tolist()
        except Exception:
            logger.warning("base64嵌入解码失败，返回空列表")
            return []
    if hasattr(embedding_val, "tolist"):
        try:
            return embedding_val.tolist()
        except Exception:
            logger.warning("嵌入tolist转换失败，返回空列表")
            return []
    return []


def update_memory_distillation(
    manager: Any,
    memory_id: str,
    summary: str,
    keywords: List[str],
    distillation_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    need_save = False
    with get_write_lock(manager):
        memory = None
        in_weighted = False
        if memory_id in manager.weighted_memories:
            memory = manager.weighted_memories[memory_id]
            in_weighted = True
        else:
            for m in manager.short_term_memory:
                if m.get("id") == memory_id:
                    memory = m
                    break

        if memory:
            memory["summary"] = summary
            merged = list(
                (memory.get("search_keywords", []) or [])
                + (memory.get("keywords", []) or [])
                + (keywords or [])
            )
            normalized: List[str] = []
            for k in merged:
                if not isinstance(k, str):
                    continue
                kk = k.strip().lower()
                if kk:
                    normalized.append(kk)
            deduped = list(set(normalized))
            memory["search_keywords"] = deduped
            memory["keywords"] = deduped
            display_tags: List[str] = []
            for t in (memory.get("topics") or []):
                ts = str(t or "").strip()
                if ts and ts not in display_tags:
                    display_tags.append(ts)
            for kw in deduped:
                if kw and kw not in display_tags:
                    display_tags.append(kw)
            memory["display_tags"] = display_tags[:8]
            memory["is_distilled"] = True
            if distillation_metadata is not None:
                memory["distillation_metadata"] = dict(distillation_metadata)
            if in_weighted:
                manager._mark_keyword_index_dirty_locked(memory_id)
            need_save = True
    if need_save:
        manager._schedule_save()
        return True
    return False


def generate_missing_embeddings(
    manager: Any,
    *,
    vector_search_enabled: bool,
    embedding_generator: Any,
    logger: Any,
) -> int:
    if not vector_search_enabled:
        logger.warning("向量搜索功能未启用，无法生成嵌入")
        return 0

    count = 0
    with get_write_lock(manager):
        for memory_id, memory in manager.weighted_memories.items():
            if "embedding" not in memory or not memory["embedding"]:
                try:
                    content = memory.get("content", "")
                    if content:
                        embedding = embedding_generator.generate_embedding(content)
                        memory["embedding"] = embedding_generator.embedding_to_base64(
                            embedding
                        )
                        count += 1
                except Exception as e:
                    logger.error(f"为记忆 {memory_id} 生成嵌入失败: {e}")

        if count > 0:
            logger.info(f"为用户 {manager.user_id} 生成了 {count} 个缺失的向量嵌入")

    if count > 0:
        manager._save_weighted_data()

    return count


def update_weight_config(
    manager: Any, new_config: Dict[str, float], *, logger: Any, time_module: Any
) -> None:
    with get_write_lock(manager):
        manager.weight_calculator.update_config(new_config)
        for memory_id, memory in manager.weighted_memories.items():
            base_weight = manager.weight_calculator.calculate_initial_weight(
                memory["content"],
                memory.get("is_important", False),
                memory.get("topics", []),
                memory.get("emotions", []),
            )
            memory["weight"] = manager.weight_calculator.apply_time_decay(
                base_weight, memory["timestamp"]
            )
        manager.last_modified_time = time_module.time()
        logger.info(f"已更新用户 {manager.user_id} 的权重配置")
