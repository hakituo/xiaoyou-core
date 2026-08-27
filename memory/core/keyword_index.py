from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


def compute_memory_keywords(
    memory: Dict[str, Any],
    extract_keywords: Callable[[str], Set[str]],
) -> Set[str]:
    content = (memory.get("summary") or memory.get("content", "") or "").strip()
    extracted = set(extract_keywords(content) or []) if content else set()

    search_explicit = memory.get("search_keywords")
    if isinstance(search_explicit, list):
        for kw in search_explicit:
            if isinstance(kw, str) and kw.strip():
                extracted.add(kw.strip().lower())

    explicit = memory.get("keywords")
    if isinstance(explicit, list):
        for kw in explicit:
            if isinstance(kw, str) and kw.strip():
                extracted.add(kw.strip().lower())

    return {k.strip().lower() for k in extracted if isinstance(k, str) and k.strip()}


def build_pairs(keywords: Set[str]) -> List[Tuple[str, str]]:
    kw_list = sorted({k for k in keywords if isinstance(k, str) and k.strip()})
    if len(kw_list) < 2:
        return []
    pairs: List[Tuple[str, str]] = []
    for i in range(len(kw_list)):
        a = kw_list[i]
        for j in range(i + 1, len(kw_list)):
            pairs.append((a, kw_list[j]))
    return pairs


def rebuild_keyword_index(
    weighted_memories: Dict[str, Dict[str, Any]],
    extract_keywords: Callable[[str], Set[str]],
) -> Tuple[
    Dict[str, List[str]],
    Dict[str, Dict[str, int]],
    Dict[str, Set[str]],
    Dict[str, List[Tuple[str, str]]],
]:
    keyword_index: Dict[str, List[str]] = defaultdict(list)
    keyword_graph: Dict[str, Dict[str, int]] = defaultdict(dict)
    memory_keyword_sets: Dict[str, Set[str]] = {}
    memory_keyword_pairs: Dict[str, List[Tuple[str, str]]] = {}

    for memory_id, memory in weighted_memories.items():
        keywords = compute_memory_keywords(memory, extract_keywords)
        if not keywords:
            continue

        memory_keyword_sets[memory_id] = keywords
        for keyword in keywords:
            if memory_id not in keyword_index[keyword]:
                keyword_index[keyword].append(memory_id)

        pairs = build_pairs(keywords)
        if pairs:
            memory_keyword_pairs[memory_id] = pairs
            for a, b in pairs:
                keyword_graph.setdefault(a, {})
                keyword_graph.setdefault(b, {})
                keyword_graph[a][b] = int(keyword_graph[a].get(b, 0)) + 1
                keyword_graph[b][a] = int(keyword_graph[b].get(a, 0)) + 1

    return keyword_index, keyword_graph, memory_keyword_sets, memory_keyword_pairs


def remove_memory_from_keyword_index(
    memory_id: str,
    memory: Optional[Dict[str, Any]],
    keyword_index: Dict[str, List[str]],
    keyword_graph: Dict[str, Dict[str, int]],
    memory_keyword_sets: Dict[str, Set[str]],
    memory_keyword_pairs: Dict[str, List[Tuple[str, str]]],
    extract_keywords: Callable[[str], Set[str]],
):
    mid = str(memory_id or "").strip()
    if not mid:
        return

    old_keywords = memory_keyword_sets.pop(mid, None)
    if old_keywords is None and isinstance(memory, dict):
        old_keywords = compute_memory_keywords(memory, extract_keywords)

    if old_keywords:
        for kw in old_keywords:
            ids = keyword_index.get(kw)
            if not ids:
                continue
            try:
                while mid in ids:
                    ids.remove(mid)
            except ValueError:
                pass
            if not ids:
                keyword_index.pop(kw, None)

    old_pairs = memory_keyword_pairs.pop(mid, None)
    if old_pairs is None and old_keywords:
        old_pairs = build_pairs(old_keywords)

    if old_pairs:
        for a, b in old_pairs:
            rel_a = keyword_graph.get(a)
            rel_b = keyword_graph.get(b)
            if isinstance(rel_a, dict) and b in rel_a:
                rel_a[b] = int(rel_a.get(b, 0)) - 1
                if rel_a[b] <= 0:
                    rel_a.pop(b, None)
                if not rel_a:
                    keyword_graph.pop(a, None)
            if isinstance(rel_b, dict) and a in rel_b:
                rel_b[a] = int(rel_b.get(a, 0)) - 1
                if rel_b[a] <= 0:
                    rel_b.pop(a, None)
                if not rel_b:
                    keyword_graph.pop(b, None)


def expand_keywords(
    keywords: List[str], keyword_graph: Dict[str, Dict[str, int]], top_k: int = 3
) -> List[str]:
    """基于关键词图进行关键词联想扩展"""
    if not keywords or not keyword_graph:
        return list(keywords)

    expanded = set(keywords)
    for kw in keywords:
        if kw in keyword_graph:
            # 获取相关的关键词，按共现频率排序
            related = sorted(
                keyword_graph[kw].items(), key=lambda x: x[1], reverse=True
            )
            # 添加前 top_k 个相关关键词
            for rel_kw, freq in related[:top_k]:
                expanded.add(rel_kw)

    return list(expanded)


def upsert_memory_keywords(
    memory_id: str,
    memory: Dict[str, Any],
    keyword_index: Dict[str, List[str]],
    keyword_graph: Dict[str, Dict[str, int]],
    memory_keyword_sets: Dict[str, Set[str]],
    memory_keyword_pairs: Dict[str, List[Tuple[str, str]]],
    extract_keywords: Callable[[str], Set[str]],
):
    mid = str(memory_id or "").strip()
    if not mid:
        return

    new_keywords = compute_memory_keywords(memory, extract_keywords)
    old_keywords = memory_keyword_sets.get(mid, set())
    if old_keywords == new_keywords and mid in memory_keyword_pairs:
        return

    remove_memory_from_keyword_index(
        mid,
        None,
        keyword_index,
        keyword_graph,
        memory_keyword_sets,
        memory_keyword_pairs,
        extract_keywords,
    )

    if not new_keywords:
        return

    memory_keyword_sets[mid] = new_keywords
    for kw in new_keywords:
        if mid not in keyword_index.setdefault(kw, []):
            keyword_index[kw].append(mid)

    pairs = build_pairs(new_keywords)
    if pairs:
        memory_keyword_pairs[mid] = pairs
        for a, b in pairs:
            keyword_graph.setdefault(a, {})
            keyword_graph.setdefault(b, {})
            keyword_graph[a][b] = int(keyword_graph[a].get(b, 0)) + 1
            keyword_graph[b][a] = int(keyword_graph[b].get(a, 0)) + 1
