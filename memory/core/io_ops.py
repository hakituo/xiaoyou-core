import gc
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from memory.core.vector_ops import decode_embedding_to_list
from memory.core.lock_utils import get_write_lock
from memory.core.record_ops import rebuild_memory_indexes_locked


def _normalize_content_signature(memory: Any) -> tuple[str, str, str]:
    content = " ".join(str((memory or {}).get("content", "")).strip().lower().split())
    source = str((memory or {}).get("source", "")).strip().lower()
    category = str((memory or {}).get("category", "uncategorized")).strip().lower() or "uncategorized"
    return content, source, category


def _is_invalid_profile_extraction(memory: Any) -> bool:
    if not isinstance(memory, dict):
        return False
    category = str(memory.get("category", "")).strip().lower()
    source = str(memory.get("source", "")).strip().lower()
    role = str(memory.get("role", "")).strip().lower()
    metadata = memory.get("metadata")
    extracted = bool(metadata.get("extracted")) if isinstance(metadata, dict) else False
    if category != "profile" and source != "system_profile" and role != "system_profile":
        return False
    if not extracted:
        return False
    content = str(memory.get("content", "")).strip()
    if not content.startswith("用户名字:"):
        return False
    value = content.split(":", 1)[1].strip() if ":" in content else ""
    if not value or len(value) > 8:
        return True
    banned_values = {
        "高考",
        "说我有点忧郁",
        "程序员",
        "学生",
        "北京",
        "上海",
        "深圳",
        "广州",
        "中国",
    }
    if value in banned_values:
        return True
    banned_fragments = ["说我", "有点", "忧郁", "喜欢", "不喜欢", "学习", "工作"]
    banned_fragments.extend(["主人", "干什么", "什么", "一下", "好的"])
    if any(frag in value for frag in banned_fragments):
        return True
    if any(ch.isspace() for ch in value):
        return True
    return False


def _merge_loaded_memory(base: dict, incoming: dict) -> dict:
    if float(incoming.get("weight", 0.0) or 0.0) > float(base.get("weight", 0.0) or 0.0):
        base["weight"] = incoming.get("weight", base.get("weight"))
    base["last_access_time"] = max(
        float(base.get("last_access_time", 0.0) or 0.0),
        float(incoming.get("last_access_time", 0.0) or 0.0),
    )
    base["is_important"] = bool(base.get("is_important", False) or incoming.get("is_important", False))
    base_topics = [str(t).strip() for t in (base.get("topics") or []) if str(t).strip()]
    for t in incoming.get("topics") or []:
        ts = str(t).strip()
        if ts and ts not in base_topics:
            base_topics.append(ts)
    base["topics"] = base_topics[:8]
    base_tags = [str(t).strip() for t in (base.get("display_tags") or []) if str(t).strip()]
    for t in (incoming.get("display_tags") or []) + base_topics:
        ts = str(t).strip()
        if ts and ts not in base_tags:
            base_tags.append(ts)
    base["display_tags"] = base_tags[:8]
    return base


def load_weighted_data(
    manager: Any,
    *,
    weighted_memory_dir: Path,
    default_encoding: str,
    logger: Any,
) -> None:
    try:
        manager.weighted_memories = {}
        manager.category_index = defaultdict(list)
        manager.content_dedupe_index = {}
        signature_to_id: dict[tuple[str, str, str], str] = {}
        candidate_dirs = [weighted_memory_dir]
        legacy_weighted_dir = getattr(manager, "legacy_weighted_dir", None)
        if isinstance(legacy_weighted_dir, Path) and legacy_weighted_dir not in candidate_dirs:
            candidate_dirs.append(legacy_weighted_dir)

        # 获取 embedding 解码函数
        base64_to_embedding = None
        try:
            from memory.embedding_generator import embedding_generator
            base64_to_embedding = getattr(embedding_generator, "base64_to_embedding", None)
        except Exception:
            pass

        def process_data(data: Any, default_category: Optional[str] = None) -> None:
            if "weighted_memories" in data:
                for memory in data["weighted_memories"]:
                    if hasattr(manager, "_hydrate_weighted_memory_record"):
                        memory = manager._hydrate_weighted_memory_record(memory)
                    if "category" not in memory and default_category:
                        memory["category"] = default_category
                    elif "category" not in memory:
                        memory["category"] = "uncategorized"
                    # 注意：保留 embedding 字段，不要删除

                    legacy_keywords = memory.get("keywords")
                    search_keywords = memory.get("search_keywords")
                    if isinstance(search_keywords, list):
                        normalized_search = []
                        for kw in search_keywords:
                            if not isinstance(kw, str):
                                continue
                            k = kw.strip().lower()
                            if k:
                                normalized_search.append(k)
                        search_keywords = list(set(normalized_search))
                    elif isinstance(legacy_keywords, list):
                        normalized_search = []
                        for kw in legacy_keywords:
                            if not isinstance(kw, str):
                                continue
                            k = kw.strip().lower()
                            if k:
                                normalized_search.append(k)
                        search_keywords = list(set(normalized_search))
                    else:
                        search_keywords = []
                    memory["search_keywords"] = search_keywords
                    memory["keywords"] = list(search_keywords)

                    display_tags = memory.get("display_tags")
                    if isinstance(display_tags, list):
                        normalized_tags = []
                        for t in display_tags:
                            ts = str(t or "").strip()
                            if ts and ts not in normalized_tags:
                                normalized_tags.append(ts)
                        display_tags = normalized_tags
                    else:
                        display_tags = []
                    for t in (memory.get("topics") or []):
                        ts = str(t or "").strip()
                        if ts and ts not in display_tags:
                            display_tags.append(ts)
                    memory["display_tags"] = display_tags[:8]
                    if hasattr(manager, "_normalize_memory_record"):
                        memory, _ = manager._normalize_memory_record(memory)

                    if _is_invalid_profile_extraction(memory):
                        continue

                    mid = str(memory.get("id") or "").strip()
                    if not mid:
                        continue

                    existing = manager.weighted_memories.get(mid)
                    if isinstance(existing, dict):
                        manager.weighted_memories[mid] = _merge_loaded_memory(existing, memory)
                        signature_to_id[_normalize_content_signature(manager.weighted_memories[mid])] = mid
                        continue

                    signature = _normalize_content_signature(memory)
                    duplicate_mid = signature_to_id.get(signature)
                    if duplicate_mid and duplicate_mid in manager.weighted_memories:
                        target = manager.weighted_memories[duplicate_mid]
                        manager.weighted_memories[duplicate_mid] = _merge_loaded_memory(target, memory)
                        continue

                    manager.weighted_memories[mid] = memory
                    signature_to_id[signature] = mid

            if "topic_weights" in data:
                if not manager.topic_weights:
                    manager.topic_weights = defaultdict(float, data["topic_weights"])

            # emotion_memory_map 是派生索引，旧文件可能保留大量已删除记忆 ID。
            # 所有分片加载完成后统一从有效 weighted_memories 重建。

        for current_dir in candidate_dirs:
            weighted_file = current_dir / f"{manager.user_id}_weighted.json"
            if weighted_file.exists():
                with open(weighted_file, "r", encoding=default_encoding) as f:
                    data = json.load(f)
                    process_data(data, default_category="uncategorized")
                    if "important_prompts" in data and not manager.important_prompts:
                        manager.important_prompts = data["important_prompts"]
                        logger.info(
                            f"已从 weighted.json 迁移 {len(manager.important_prompts)} 条重要Prompt"
                        )

            if current_dir.exists():
                for item in current_dir.iterdir():
                    if item.is_dir() and item.name not in ["short_term", "long_term"]:
                        cat_file = item / f"{manager.user_id}_weighted.json"
                        if cat_file.exists():
                            try:
                                with open(cat_file, "r", encoding=default_encoding) as f:
                                    data = json.load(f)
                                    process_data(data, default_category=item.name)
                            except Exception as e:
                                logger.error(f"Failed to load category file {cat_file}: {e}")

        for mid, mem in manager.weighted_memories.items():
            cat = mem.get("category", "uncategorized")
            manager.category_index[cat].append(mid)

            if hasattr(manager, "content_dedupe_index"):
                norm_content = " ".join(str(mem.get("content", "")).strip().lower().split())
                src_key = str(mem.get("source", "")).strip().lower()
                cat_key = str(mem.get("category", "uncategorized")).strip().lower() or "uncategorized"
                dedupe_key = f"{norm_content}\x00{src_key}\x00{cat_key}"
                manager.content_dedupe_index[dedupe_key] = mid

            # 将加载的记忆同步到 C++ VectorIndexer
            if hasattr(manager, "vector_indexer"):
                try:
                    embedding_list = decode_embedding_to_list(
                        mem.get("embedding"),
                        base64_to_embedding,
                    )
                    manager.vector_indexer.addRecord(
                        str(mid),
                        embedding_list,
                        float(mem.get("weight") or 0.0),
                        float(mem.get("timestamp") or 0.0),
                        str(mem.get("source") or ""),
                        [str(t) for t in (mem.get("topics") or [])]
                    )
                except Exception as e:
                    logger.warning(f"无法将记忆 {mid} 同步到 C++ VectorIndexer: {e}")

        rebuild_memory_indexes_locked(manager)

        logger.info(
            f"已加载用户 {manager.user_id} 的权重数据，共 {len(manager.weighted_memories)} 条"
        )

        # 初始化 O(1) 计数器
        pending_count = 0
        shadow_count = 0
        for mem in manager.weighted_memories.values():
            metadata = mem.get("metadata")
            if isinstance(metadata, dict):
                if bool(metadata.get("analysis_pending", False)):
                    pending_count += 1
                if isinstance(metadata.get("ai_shadow"), dict):
                    shadow_count += 1
        manager._pending_analysis_count = pending_count
        manager._ai_shadow_count = shadow_count

        gc.collect()
    except Exception as e:
        logger.error(f"加载权重数据时出错: {e}")


def get_important_prompts_file(manager: Any, *, weighted_memory_dir: Path) -> Path:
    return weighted_memory_dir / f"{manager.user_id}_important_prompts.json"


def get_project_root() -> Path:
    """获取项目根目录（委托给 core.utils.common）"""
    from core.utils.common import get_project_root as _get_root
    return _get_root()


def get_output_conversation_file(manager: Any) -> Path:
    return get_project_root() / "output" / "memory" / "conversations" / f"{manager.user_id}.json"


def load_important_prompts(
    manager: Any,
    *,
    weighted_memory_dir: Path,
    default_encoding: str,
    logger: Any,
) -> None:
    try:
        prompts_file = get_important_prompts_file(
            manager, weighted_memory_dir=weighted_memory_dir
        )
        manager.important_prompts = []
        candidate_files = [prompts_file]
        legacy_weighted_dir = getattr(manager, "legacy_weighted_dir", None)
        if isinstance(legacy_weighted_dir, Path):
            candidate_files.append(
                get_important_prompts_file(
                    manager, weighted_memory_dir=legacy_weighted_dir
                )
            )
        for current_file in candidate_files:
            if current_file.exists():
                with open(current_file, "r", encoding=default_encoding) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logger.info(
                            "检测到旧重要Prompt副本文件 %s，已跳过正文装载，后续会从主记忆仓动态推导",
                            str(current_file),
                        )
                    elif isinstance(data, dict) and "important_prompts" in data:
                        logger.info(
                            "检测到旧重要Prompt副本文件 %s，已跳过正文装载，后续会从主记忆仓动态推导",
                            str(current_file),
                        )
                return
        legacy_file = weighted_memory_dir / "important_prompts.json"
        if manager.user_id == "default" and legacy_file.exists():
            logger.info(
                "检测到旧 important_prompts.json 副本文件，后续会从主记忆仓动态推导"
            )
    except Exception as e:
        logger.error(f"加载重要Prompt数据失败: {e}")
        manager.important_prompts = []


def save_weighted_data_locked(
    manager: Any,
    *,
    weighted_memory_dir: Path,
    logger: Any,
    time_module: Any,
) -> None:
    try:
        grouped_memories = defaultdict(list)
        # 快照迭代：safe_save_all 在锁外被调用，期间其他线程可能向 weighted_memories
        # 插入新条目（如 _preserve_removed_to_weighted），直接迭代 dict views 会触发
        # "dictionary changed size during iteration"。这里取 list 快照保证遍历稳定。
        for memory in list(manager.weighted_memories.values()):
            category = memory.get("category") or "uncategorized"
            compact_memory = (
                manager._compact_weighted_memory_record(memory)
                if hasattr(manager, "_compact_weighted_memory_record")
                else memory
            )
            grouped_memories[category].append(compact_memory)

        common_data = {
            "topic_weights": dict(manager.topic_weights),
            "emotion_memory_map": dict(manager.emotion_memory_map),
            "last_updated": time_module.time(),
        }

        uncategorized_memories = grouped_memories.pop("uncategorized", [])
        weighted_file = weighted_memory_dir / f"{manager.user_id}_weighted.json"
        data = {"weighted_memories": uncategorized_memories, **common_data}
        manager._safe_json_dump_atomic(data, weighted_file)

        active_category_dirs = set()
        for category, memories in grouped_memories.items():
            safe_category = manager._normalize_category_dir(category)
            active_category_dirs.add(safe_category)
            category_dir = weighted_memory_dir / safe_category
            if not category_dir.exists():
                category_dir.mkdir(parents=True, exist_ok=True)
            cat_file = category_dir / f"{manager.user_id}_weighted.json"
            cat_data = {
                "weighted_memories": memories,
                "category": category,
                "last_updated": time_module.time(),
            }
            manager._safe_json_dump_atomic(cat_data, cat_file)

        if weighted_memory_dir.exists():
            for item in weighted_memory_dir.iterdir():
                if not item.is_dir():
                    continue
                if item.name in ["short_term", "long_term"]:
                    continue
                if item.name in active_category_dirs:
                    continue
                stale_file = item / f"{manager.user_id}_weighted.json"
                if stale_file.exists():
                    try:
                        stale_file.unlink()
                    except Exception:
                        pass
        logger.debug(
            f"已保存用户 {manager.user_id} 的权重数据 (分 {len(grouped_memories) + 1} 个类别)"
        )
    except Exception as e:
        logger.error(f"保存权重数据时出错: {e}")


def save_important_prompts_locked(
    manager: Any,
    *,
    weighted_memory_dir: Path,
    default_encoding: str,
    logger: Any,
) -> None:
    try:
        prompts_file = get_important_prompts_file(manager, weighted_memory_dir=weighted_memory_dir)
        try:
            os.remove(prompts_file)
        except FileNotFoundError:
            pass
    except Exception as e:
        logger.error(f"保存重要Prompt数据时出错: {e}")


def clear_weighted_memories(
    manager: Any,
    *,
    weighted_memory_dir: Path,
    default_encoding: str,
    logger: Any,
) -> int:
    with get_write_lock(manager):
        count = len(manager.weighted_memories)
        manager.weighted_memories.clear()
        if hasattr(manager, "content_dedupe_index"):
            manager.content_dedupe_index = {}
        manager.topic_weights.clear()
        manager.emotion_memory_map.clear()
        manager.category_index = defaultdict(list)
        manager._keyword_index.clear()
        manager._keyword_graph.clear()
        manager._memory_keyword_sets.clear()
        manager._memory_keyword_pairs.clear()
        manager._keyword_dirty_ids.clear()
        manager._keyword_force_rebuild = False
        manager._index_updated = False
        manager.preference_index.clear()
        try:
            weighted_file = weighted_memory_dir / f"{manager.user_id}_weighted.json"
            if weighted_file.exists():
                data = {
                    "weighted_memories": [],
                    "topic_weights": {},
                    "emotion_memory_map": {},
                }
                with open(weighted_file, "w", encoding=default_encoding) as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            if weighted_memory_dir.exists():
                for item in weighted_memory_dir.iterdir():
                    if item.is_dir() and item.name not in ["short_term", "long_term"]:
                        cat_file = item / f"{manager.user_id}_weighted.json"
                        if cat_file.exists():
                            try:
                                os.remove(cat_file)
                            except Exception:
                                pass
        except Exception as e:
            logger.error(f"清除加权记忆文件失败: {e}")
        logger.info(f"已清除所有加权记忆，共 {count} 条")
        return count
