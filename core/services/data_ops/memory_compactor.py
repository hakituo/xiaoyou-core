import hashlib
from collections import defaultdict
from typing import Any, Dict, List

from memory.weighted_memory_manager import get_weighted_memory_manager


class MemoryCompactor:
    def build_denoise_summary(
        self, *, user_id: str, min_weight: float = 1.0, max_items: int = 200
    ) -> Dict[str, Any]:
        manager = get_weighted_memory_manager(user_id)
        weighted_map = getattr(manager, "weighted_memories", {}) or {}
        all_memories = (
            list(weighted_map.values())
            if isinstance(weighted_map, dict)
            else []
        )
        memories = [
            m
            for m in all_memories
            if isinstance(m, dict) and str(m.get("category", "")) != "thinking"
        ]
        memories.sort(key=lambda x: float(x.get("weight") or 0), reverse=True)
        if max_items > 0:
            memories = memories[: int(max_items)]
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in memories:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            key = hashlib.sha256(
                " ".join(content.lower().split()).encode("utf-8")
            ).hexdigest()
            grouped[key].append(item)
        unique_memories: List[Dict[str, Any]] = []
        duplicate_count = 0
        for items in grouped.values():
            items.sort(key=lambda x: float(x.get("weight") or 0), reverse=True)
            unique_memories.append(items[0])
            if len(items) > 1:
                duplicate_count += len(items) - 1
        clean_memories = [
            m
            for m in unique_memories
            if float(m.get("weight") or 0.0) >= float(min_weight)
        ]
        clean_memories.sort(key=lambda x: float(x.get("weight") or 0), reverse=True)
        topic_stats: Dict[str, int] = defaultdict(int)
        category_stats: Dict[str, int] = defaultdict(int)
        for item in clean_memories:
            category_stats[str(item.get("category") or "uncategorized")] += 1
            for topic in item.get("topics") or []:
                topic_stats[str(topic)] += 1
        top_topics = sorted(topic_stats.items(), key=lambda x: x[1], reverse=True)[:6]
        highlights = []
        for item in clean_memories[:5]:
            text = str(item.get("content") or "").strip()
            display_tags = item.get("display_tags")
            if not isinstance(display_tags, list):
                display_tags = []
            normalized_tags = []
            for tag in display_tags:
                ts = str(tag or "").strip()
                if ts and ts not in normalized_tags:
                    normalized_tags.append(ts)
            if not normalized_tags:
                normalized_tags = [
                    str(t)
                    for t in (item.get("topics") or [])
                    if str(t).strip()
                ]
            highlights.append(
                {
                    "id": str(item.get("id") or item.get("message_id") or ""),
                    "content": text[:120],
                    "weight": float(item.get("weight") or 0.0),
                    "category": str(item.get("category") or "uncategorized"),
                    "topics": [str(t) for t in (item.get("topics") or [])[:4]],
                    "display_tags": normalized_tags[:6],
                }
            )
        summary = (
            f"共扫描 {len(memories)} 条候选记忆，去重后 {len(unique_memories)} 条，"
            f"移除重复 {duplicate_count} 条，保留高价值 {len(clean_memories)} 条。"
        )
        return {
            "summary": summary,
            "stats": {
                "scanned": len(memories),
                "unique": len(unique_memories),
                "duplicates_removed": duplicate_count,
                "retained": len(clean_memories),
                "min_weight": float(min_weight),
            },
            "top_topics": [{"topic": k, "count": v} for k, v in top_topics],
            "category_distribution": dict(category_stats),
            "highlights": highlights,
        }
