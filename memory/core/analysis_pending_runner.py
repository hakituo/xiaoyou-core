"""待分析记忆的批处理编排：读锁取件 → 锁外分析 → 写锁落库。

从 ``memory.core.analysis_ops`` 拆出，原样搬移 ``process_pending_analysis``。
拆分是纯搬家：未改逻辑、命名与断言。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from memory.core.analysis_pending import (
    _apply_pending_analysis_result,
    _prepare_pending_analysis,
)
from memory.core.analysis_shadow import _run_bert_shadow_analysis
from memory.core.lock_utils import get_read_lock, get_write_lock


def process_pending_analysis(manager: Any, limit: int = 32) -> Dict[str, Any]:
    max_items = max(1, int(limit))

    # 阶段1：读锁内收集待分析记忆的内容快照
    with get_read_lock(manager):
        pending_items: List[Tuple[float, str]] = []
        # 快照迭代：读锁只能挡住同样走读写锁的写者，后台加载等直接改字典的路径
        # 不受约束，Python 层迭代需要 list 快照兜底
        for memory_id, memory in list(manager.weighted_memories.items()):
            metadata = memory.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if not bool(metadata.get("analysis_pending", False)):
                continue
            pending_items.append((float(memory.get("timestamp") or 0.0), memory_id))
        pending_items.sort(key=lambda x: x[0])
        pending_ids = [mid for _, mid in pending_items[:max_items]]

        if not pending_ids:
            return {
                "processed": 0,
                "pending_before": 0,
                "pending_after": 0,
                "updated_ids": [],
            }

        # 快照待分析记忆的内容（仅复制必要字段）
        memory_snapshots: Dict[str, Dict[str, Any]] = {}
        for mid in pending_ids:
            mem = manager.weighted_memories.get(mid)
            if isinstance(mem, dict):
                memory_snapshots[mid] = {
                    "content": mem.get("content", ""),
                    "category": mem.get("category"),
                    "is_important": mem.get("is_important", False),
                    "metadata": mem.get("metadata"),
                }

    pending_before = len(pending_items)

    # 阶段2：锁外执行规则分析和BERT推理（耗时操作）
    prep_results: Dict[str, Dict[str, Any]] = {}
    bert_results: Dict[str, Dict[str, Any]] = {}
    for memory_id in pending_ids:
        snapshot = memory_snapshots.get(memory_id)
        if not isinstance(snapshot, dict):
            continue
        # 构造临时memory对象用于分析
        temp_memory = dict(snapshot)
        prep = _prepare_pending_analysis(manager, memory_id, temp_memory, time.time())
        prep_results[memory_id] = prep
        if not prep.get("skip") and not prep.get("empty_content"):
            # BERT推理在锁外执行
            bert_results[memory_id] = _run_bert_shadow_analysis(prep["bert_input_text"])

    # 阶段3：写锁内应用分析结果
    now_ts = time.time()
    updated_ids: List[str] = []
    with get_write_lock(manager):
        for memory_id in pending_ids:
            memory = manager.weighted_memories.get(memory_id)
            if not isinstance(memory, dict):
                continue
            prep = prep_results.get(memory_id)
            if not prep:
                continue
            bert_shadow = bert_results.get(memory_id, {})
            if _apply_pending_analysis_result(
                manager, memory_id, memory, prep, bert_shadow, now_ts
            ):
                updated_ids.append(memory_id)

        manager.last_modified_time = now_ts
        pending_after = max(0, pending_before - len(updated_ids))

    if updated_ids:
        manager._schedule_save()
    return {
        "processed": len(updated_ids),
        "pending_before": pending_before,
        "pending_after": pending_after,
        "updated_ids": updated_ids,
    }
