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
    """补算缺失的向量嵌入。

    三段式，**不把写锁跨在模型加载/推理上**：

    1. 短锁收集待补算的 `(id, content)`；
    2. 锁外做模型加载 + 首次推理预热 + 逐条推理（实测这一步可能是几十秒：
       ORT 的 CUDA EP 上下文/内核初始化发生在第一次 `session.run()`）；
    3. 短锁回写，逐条复核（期间记录可能已被删或已被其它线程补上）。

    旧实现把整段包在 `get_write_lock` 里，实测写锁被持有 52s，期间所有记忆读写
    都被堵住；拆开后补算可以安全地放到数据就绪之后的背景线程里跑。
    """
    if not vector_search_enabled:
        logger.warning("向量搜索功能未启用，无法生成嵌入")
        return 0

    from memory.core import startup_profile

    with startup_profile.phase("M3 缺失 embedding 补算"):
        with get_write_lock(manager):
            pending = [
                (memory_id, str(memory.get("content") or ""))
                for memory_id, memory in manager.weighted_memories.items()
                if not memory.get("embedding") and str(memory.get("content") or "")
            ]

        if not pending:
            return 0

        # 把"模型懒加载""首次推理预热""逐条推理"分开计时：三者的优化手段完全不同
        # （模型加载是一次性固定成本、首次推理是 ORT/CUDA 上下文初始化、只有逐条推理
        # 才随缺失条数增长）。混在一起会被误读成"单条嵌入很慢"。
        with startup_profile.phase("M3a 模型加载（含在 M3 内）"):
            try:
                ensure_loaded = getattr(embedding_generator, "ensure_model_loaded", None)
                if callable(ensure_loaded):
                    ensure_loaded()
            except Exception as e:
                logger.warning(f"预加载嵌入模型失败(忽略): {e}")

        if startup_profile.is_enabled():
            # 只在埋点开启时量首次推理：ORT 第一次 run 会初始化 CUDA EP/内核与
            # 内存池（实测可达数十秒），提前跑一次 dummy 才能把它和逐条推理分开。
            with startup_profile.phase("M3a2 首次推理预热（含在 M3 内）"):
                try:
                    embedding_generator.generate_embedding("预热")
                except Exception as e:
                    logger.warning(f"嵌入预热失败(忽略): {e}")

        computed: List[tuple] = []
        with startup_profile.phase("M3b 逐条推理（含在 M3 内）"):
            for memory_id, content in pending:
                try:
                    embedding = embedding_generator.generate_embedding(content)
                    computed.append(
                        (memory_id, embedding_generator.embedding_to_base64(embedding))
                    )
                except Exception as e:
                    logger.error(f"为记忆 {memory_id} 生成嵌入失败: {e}")

        count = 0
        with get_write_lock(manager):
            for memory_id, encoded in computed:
                memory = manager.weighted_memories.get(memory_id)
                if not isinstance(memory, dict) or memory.get("embedding"):
                    continue
                memory["embedding"] = encoded
                count += 1
            if count > 0:
                logger.info(f"为用户 {manager.user_id} 生成了 {count} 个缺失的向量嵌入")

    if count > 0:
        # 补算结果必须落盘，否则重启后再次丢失；用调度保存避免加载路径上的额外同步 IO
        try:
            manager._schedule_save()
        except AttributeError:
            logger.warning("补算 embedding 后调度保存失败：manager 缺少 _schedule_save")

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
