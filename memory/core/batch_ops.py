"""
批量操作 API

减少锁获取次数，提升批量操作性能。

性能提升:
- 批量添加: 单次锁获取，N 次添加只需 1 次锁
- 批量删除: 单次锁获取，N 次删除只需 1 次锁
- 批量搜索: 单次快照，N 次查询只需 1 次快照
"""

import time as _time
from typing import Any, Dict, List, Optional, Tuple

from memory.core.lock_utils import get_write_lock


def batch_add_memories(
    manager: Any,
    items: List[Dict[str, Any]],
) -> List[str]:
    """
    批量添加记忆

    Args:
        manager: 记忆管理器
        items: 记忆列表，每项包含 add_memory 的参数

    Returns:
        添加成功的记忆 ID 列表

    性能: N 次添加只需 1 次锁获取
    """
    if not items:
        return []

    results = []
    need_save = False

    with get_write_lock(manager):
        for item in items:
            try:
                mid = manager.add_memory(**item)
                if mid:
                    need_save = True
                results.append(mid)
            except Exception:
                results.append(None)

    if need_save:
        manager._schedule_save()

    return results


def batch_delete_memories(
    manager: Any,
    memory_ids: List[str],
) -> List[bool]:
    """
    批量删除记忆
    
    Args:
        manager: 记忆管理器
        memory_ids: 要删除的记忆 ID 列表
        
    Returns:
        每个删除操作的结果列表
        
    性能: 单次锁获取完成所有删除
    """
    if not memory_ids:
        return []
    
    results = []
    need_save = False
    
    with get_write_lock(manager):
        for memory_id in memory_ids:
            try:
                mem = manager.weighted_memories.get(memory_id)
                if mem is None:
                    results.append(False)
                    continue
                
                if hasattr(manager, '_topic_weight_cache') and manager._enable_optimizations:
                    for topic in mem.get("topics", []):
                        manager._topic_weight_cache.remove_topic(
                            topic,
                            weight_delta=mem.get("weight", 0.0)
                        )
                
                del manager.weighted_memories[memory_id]
                
                if hasattr(manager, '_remove_memory_from_keyword_index_locked'):
                    manager._remove_memory_from_keyword_index_locked(memory_id, mem)
                
                if hasattr(manager, 'vector_indexer'):
                    try:
                        manager.vector_indexer.removeRecord(str(memory_id))
                    except Exception:
                        pass
                
                results.append(True)
            except Exception:
                results.append(False)
        
        if any(results):
            # category/topic/emotion 都是派生索引，批量删除后统一重建。
            from memory.core.record_ops import rebuild_memory_indexes_locked

            rebuild_memory_indexes_locked(manager)
            need_save = True
    
    if need_save:
        manager._schedule_save()
    
    return results


def batch_search_memories(
    manager: Any,
    queries: List[str],
    limit: int = 10,
    min_similarity: float = 0.3,
    category: Optional[str] = None,
) -> List[List[Dict[str, Any]]]:
    """
    批量搜索记忆
    
    Args:
        manager: 记忆管理器
        queries: 查询列表
        limit: 每个查询返回的最大结果数
        min_similarity: 最小相似度
        category: 可选分类过滤
        
    Returns:
        每个查询的结果列表
        
    性能: 单次快照减少锁竞争
    """
    if not queries:
        return []
    
    all_results = []
    for query in queries:
        try:
            results = manager.search_memories(
                query=query,
                limit=limit,
                min_similarity=min_similarity,
                category=category,
            )
            all_results.append(results)
        except Exception:
            all_results.append([])
    
    return all_results


def batch_update_weights(
    manager: Any,
    updates: List[Tuple[str, float]],
) -> List[bool]:
    """
    批量更新记忆权重
    
    Args:
        manager: 记忆管理器
        updates: (memory_id, weight_delta) 元组列表
        
    Returns:
        每个更新操作的结果列表
        
    性能: 单次锁获取完成所有更新
    """
    if not updates:
        return []
    
    results = []
    need_save = False
    
    with get_write_lock(manager):
        for memory_id, weight_delta in updates:
            try:
                memory = manager.weighted_memories.get(memory_id)
                if memory is None:
                    results.append(False)
                    continue
                
                memory["weight"] = max(0.0, memory.get("weight", 0.0) + weight_delta)
                memory["last_hit_time"] = _time.time()

                if hasattr(manager, '_topic_weight_cache') and manager._enable_optimizations:
                    for topic in memory.get("topics", []):
                        manager._topic_weight_cache.update_topic(
                            topic,
                            weight_delta=weight_delta,
                            timestamp=memory.get("last_hit_time", _time.time())
                        )
                
                results.append(True)
            except Exception:
                results.append(False)
        
        if any(results):
            need_save = True
    
    if need_save:
        manager._schedule_save()
    
    return results
