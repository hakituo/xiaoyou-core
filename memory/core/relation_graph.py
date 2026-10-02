from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from memory.core.lock_utils import get_read_lock


# 关系图是 WeightedMemory 的稀疏投影，不复制正文、不引入第二份记忆真源。
# 关系按需要从现有记录字段构建并缓存在 manager 上；旧数据无需迁移即可使用。
_GENERIC_TOPICS = frozenset(
    {
        "chat",
        "dialogue",
        "general",
        "other",
        "其他",
        "uncategorized",
        "event",
        "daily",
    }
)

_EXPLICIT_PARENT_FIELDS = (
    "parent_id",
    "parent_message_id",
    "reply_to",
    "reply_to_id",
)
_EXPLICIT_RELATED_FIELDS = (
    "related_memory_ids",
    "related_ids",
    "linked_memory_ids",
)
_EXPLICIT_ALTERNATE_FIELDS = (
    "variant_of",
    "supersedes_id",
    "superseded_by",
)
BranchLineage = Tuple[str, ...]


@dataclass(frozen=True)
class RelationEdge:
    target_id: str
    relation: str
    strength: float


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _iter_ids(value: Any) -> Iterable[str]:
    if isinstance(value, (list, tuple, set)):
        for item in value:
            item_id = _clean_id(item)
            if item_id:
                yield item_id
        return
    item_id = _clean_id(value)
    if item_id:
        yield item_id


def _metadata(memory: Dict[str, Any]) -> Dict[str, Any]:
    value = memory.get("metadata")
    return value if isinstance(value, dict) else {}


def _alternate_links(memory: Dict[str, Any]) -> List[Tuple[str, str]]:
    metadata = _metadata(memory)
    links: List[Tuple[str, str]] = []
    for field in _EXPLICIT_ALTERNATE_FIELDS:
        target = _clean_id(metadata.get(field) or memory.get(field))
        if target:
            links.append((field, target))
    return links


def _build_client_id_aliases(
    memories: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """把 Android/客户端消息 ID 映射回 WeightedMemory UUID。"""
    aliases: Dict[str, str] = {}
    for memory_id, memory in memories.items():
        if not isinstance(memory, dict):
            continue
        mid = _clean_id(memory_id or memory.get("id"))
        client_id = _clean_id(_metadata(memory).get("client_message_id"))
        if mid and client_id:
            aliases[client_id] = mid
    return aliases


def _resolve_memory_id(
    value: Any,
    memories: Dict[str, Dict[str, Any]],
    client_aliases: Dict[str, str],
) -> str:
    target = _clean_id(value)
    if not target:
        return ""
    if target in memories:
        return target
    return _clean_id(client_aliases.get(target))


def _add_edge(
    graph: Dict[str, Dict[str, RelationEdge]],
    left: str,
    right: str,
    relation: str,
    strength: float,
) -> None:
    if not left or not right or left == right:
        return
    strength = max(0.0, min(float(strength), 1.0))
    current = graph[left].get(right)
    if current is None or strength > current.strength:
        graph[left][right] = RelationEdge(right, relation, strength)
    current = graph[right].get(left)
    if current is None or strength > current.strength:
        graph[right][left] = RelationEdge(left, relation, strength)


def _set_edge(
    graph: Dict[str, Dict[str, RelationEdge]],
    left: str,
    right: str,
    relation: str,
    strength: float,
) -> None:
    """强制写入双向边，用于让显式平行版本覆盖误推断出的强关系。"""
    if not left or not right or left == right:
        return
    strength = max(0.0, min(float(strength), 1.0))
    graph[left][right] = RelationEdge(right, relation, strength)
    graph[right][left] = RelationEdge(left, relation, strength)


def _event_key(memory: Dict[str, Any]) -> Optional[str]:
    source_ref = memory.get("source_ref")
    if isinstance(source_ref, dict):
        if source_ref.get("kind") == "event" and source_ref.get("event_id"):
            return f"event:{source_ref['event_id']}"

    metadata = _metadata(memory)
    event_ref = metadata.get("event_ref")
    if isinstance(event_ref, dict):
        event_id = event_ref.get("event_id") or event_ref.get("id")
        if event_id:
            return f"event:{event_id}"
        path = _clean_id(event_ref.get("path") or event_ref.get("file"))
        offset = event_ref.get("offset")
        if path and offset is not None:
            return f"event_ref:{path}:{offset}"
    return None


def _turn_keys(memory: Dict[str, Any]) -> List[str]:
    metadata = _metadata(memory)
    keys: List[str] = []
    for field in (
        "turn_id",
        "conversation_turn_id",
        "request_id",
        "message_id",
        "interaction_id",
        "thread_id",
    ):
        value = _clean_id(metadata.get(field) or memory.get(field))
        if value:
            keys.append(f"{field}:{value}")
    return keys


def _topic_keys(memory: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    for topic in memory.get("topics") or []:
        text = str(topic or "").strip()
        if not text or text.lower() in _GENERIC_TOPICS:
            continue
        keys.append(f"topic:{text.lower()}")
    return keys[:8]


def _graph_signature(memories: Dict[str, Dict[str, Any]]) -> Tuple[int, str, int]:
    if not memories:
        return (0, "", 0)
    try:
        last_id = next(reversed(memories))
    except Exception:
        last_id = next(iter(memories), "")
    last = memories.get(last_id) or {}
    last_ts = int(float(last.get("timestamp") or 0.0) * 1000)
    return (len(memories), str(last_id), last_ts)


def _build_parent_map_and_split_roots(
    memories: Dict[str, Dict[str, Any]],
    client_aliases: Dict[str, str],
) -> Tuple[Dict[str, str], set[str]]:
    """恢复客户端父链，并把每一对平行版本的两端都视为分叉根。"""
    parent_map: Dict[str, str] = {}
    split_roots: set[str] = set()
    for memory_id, memory in memories.items():
        if not isinstance(memory, dict):
            continue
        mid = _clean_id(memory_id or memory.get("id"))
        if not mid:
            continue
        metadata = _metadata(memory)
        for field in _EXPLICIT_PARENT_FIELDS:
            target = _resolve_memory_id(
                metadata.get(field) or memory.get(field), memories, client_aliases
            )
            if target and target != mid:
                parent_map[mid] = target
                break
        for _, raw_target in _alternate_links(memory):
            target = _resolve_memory_id(raw_target, memories, client_aliases)
            if target and target != mid:
                # old/new 两个版本各自代表一条世界线；共同父节点仍属于共享历史。
                split_roots.add(mid)
                split_roots.add(target)
    return parent_map, split_roots


def _build_branch_lineages(
    memories: Dict[str, Dict[str, Any]],
    client_aliases: Dict[str, str],
) -> Dict[str, BranchLineage]:
    parent_map, split_roots = _build_parent_map_and_split_roots(
        memories, client_aliases
    )
    cache: Dict[str, BranchLineage] = {}

    def resolve(memory_id: str, visiting: set[str]) -> BranchLineage:
        if memory_id in cache:
            return cache[memory_id]
        if memory_id in visiting:
            return ()
        next_visiting = set(visiting)
        next_visiting.add(memory_id)
        parent_id = parent_map.get(memory_id)
        lineage = resolve(parent_id, next_visiting) if parent_id else ()
        if memory_id in split_roots:
            lineage = lineage + (memory_id,)
        cache[memory_id] = lineage
        return lineage

    for memory_id in memories:
        resolve(_clean_id(memory_id), set())
    return cache


def _lineages_compatible(left: BranchLineage, right: BranchLineage) -> bool:
    """同一路径或祖先/后代路径兼容；同一分叉下的兄弟世界线不兼容。"""
    if not left or not right:
        return True
    common = min(len(left), len(right))
    return left[:common] == right[:common]


def _build_relation_graph(
    memories: Dict[str, Dict[str, Any]],
    *,
    client_aliases: Optional[Dict[str, str]] = None,
    branch_lineages: Optional[Dict[str, BranchLineage]] = None,
) -> Dict[str, Tuple[RelationEdge, ...]]:
    graph: Dict[str, Dict[str, RelationEdge]] = defaultdict(dict)
    grouped: Dict[str, List[str]] = defaultdict(list)
    timestamps: Dict[str, float] = {}
    dialogue_ids: List[str] = []
    isolated_variant_nodes: set[str] = set()
    alternate_pairs: set[Tuple[str, str]] = set()
    aliases = client_aliases or _build_client_id_aliases(memories)
    lineages = branch_lineages or _build_branch_lineages(memories, aliases)

    for memory_id, memory in memories.items():
        mid = _clean_id(memory_id or memory.get("id"))
        if not mid or not isinstance(memory, dict):
            continue
        timestamps[mid] = float(memory.get("timestamp") or 0.0)
        graph.setdefault(mid, {})

        event_key = _event_key(memory)
        if event_key:
            grouped[event_key].append(mid)
        for key in _turn_keys(memory):
            grouped[key].append(mid)
        for key in _topic_keys(memory):
            grouped[key].append(mid)

        metadata = _metadata(memory)
        for field in _EXPLICIT_PARENT_FIELDS:
            target = _resolve_memory_id(
                metadata.get(field) or memory.get(field), memories, aliases
            )
            if target:
                _add_edge(graph, mid, target, "parent", 1.0)
        for field in _EXPLICIT_RELATED_FIELDS:
            value = metadata.get(field, memory.get(field))
            for raw_target in _iter_ids(value):
                target = _resolve_memory_id(raw_target, memories, aliases)
                if target:
                    _add_edge(graph, mid, target, "related", 0.9)
        for field, raw_target in _alternate_links(memory):
            target = _resolve_memory_id(raw_target, memories, aliases)
            if not target:
                continue
            alternate_pairs.add(tuple(sorted((mid, target))))
            if field == "variant_of":
                # 当前节点是另一个回复的平行版本；只隔离当前节点，不能削弱基准版本。
                isolated_variant_nodes.add(mid)
            elif field == "supersedes_id":
                isolated_variant_nodes.add(target)
            elif field == "superseded_by":
                isolated_variant_nodes.add(mid)
            _add_edge(graph, mid, target, "alternate", 0.18)

        role = str(memory.get("role") or memory.get("source") or "").strip().lower()
        memory_type = str(memory.get("memory_type") or "dialogue").strip().lower()
        if role in {"user", "assistant"} and memory_type == "dialogue":
            dialogue_ids.append(mid)

    # 同一事件/turn 是强关系；同主题只连时间上相邻的节点，避免大主题形成 O(N²) 完全图。
    # 如果两条记录已经能从 Android parent/variant 链证明属于兄弟世界线，则完全不建立
    # 自动推断边；共同祖先 lineage 是前缀，仍可以正常连接和召回。
    for key, ids in grouped.items():
        unique_ids = sorted(
            set(ids), key=lambda item: (timestamps.get(item, 0.0), item)
        )
        if len(unique_ids) < 2:
            continue
        if key.startswith("topic:"):
            relation, strength = "topic", 0.48
        elif key.startswith("event"):
            relation, strength = "event", 0.96
        else:
            relation, strength = "turn", 0.94
        for left, right in zip(unique_ids, unique_ids[1:]):
            if not _lineages_compatible(
                lineages.get(left, ()), lineages.get(right, ())
            ):
                continue
            inferred_strength = strength
            if left in isolated_variant_nodes or right in isolated_variant_nodes:
                inferred_strength = min(inferred_strength, 0.18)
            _add_edge(graph, left, right, relation, inferred_strength)

    # 对话天然具有顺序关系。仅连接 10 分钟内相邻轮次，避免跨场景硬串。
    dialogue_ids.sort(key=lambda item: (timestamps.get(item, 0.0), item))
    for left, right in zip(dialogue_ids, dialogue_ids[1:]):
        delta = timestamps.get(right, 0.0) - timestamps.get(left, 0.0)
        if delta < 0 or delta > 600:
            continue
        if not _lineages_compatible(
            lineages.get(left, ()), lineages.get(right, ())
        ):
            continue
        left_mem = memories.get(left) or {}
        right_mem = memories.get(right) or {}
        left_role = str(left_mem.get("role") or left_mem.get("source") or "").lower()
        right_role = str(right_mem.get("role") or right_mem.get("source") or "").lower()
        strength = 0.82 if left_role != right_role else 0.62
        if left in isolated_variant_nodes or right in isolated_variant_nodes:
            strength = min(strength, 0.18)
        _add_edge(graph, left, right, "continuation", strength)

    # 显式 alternate 是更强的语义约束：即使前面因 parent/event 等字段推断出强边，
    # 这里也最终把这“一对版本”降级；不会影响基准版本与自己正常上下文的其它强边。
    for left, right in alternate_pairs:
        _set_edge(graph, left, right, "alternate", 0.18)

    return {
        memory_id: tuple(
            sorted(edges.values(), key=lambda edge: edge.strength, reverse=True)
        )
        for memory_id, edges in graph.items()
    }


def ensure_relation_graph(
    manager: Any,
    *,
    force: bool = False,
) -> Dict[str, Tuple[RelationEdge, ...]]:
    """获取当前 WeightedMemory 的稀疏关系图；记录集合变化时自动重建。"""
    with get_read_lock(manager):
        memories = manager.weighted_memories
        signature = _graph_signature(memories)
        cached_signature = getattr(manager, "_memory_relation_signature", None)
        cached_graph = getattr(manager, "_memory_relation_graph", None)
        cached_lineages = getattr(manager, "_memory_relation_lineages", None)
        if (
            not force
            and cached_signature == signature
            and isinstance(cached_graph, dict)
            and isinstance(cached_lineages, dict)
        ):
            return cached_graph
        snapshot = {mid: dict(memory) for mid, memory in memories.items()}

    from memory.core import startup_profile

    with startup_profile.phase("M11 relation graph 懒构建"):
        aliases = _build_client_id_aliases(snapshot)
        lineages = _build_branch_lineages(snapshot, aliases)
        graph = _build_relation_graph(
            snapshot, client_aliases=aliases, branch_lineages=lineages
        )
    manager._memory_relation_graph = graph
    manager._memory_relation_lineages = lineages
    manager._memory_relation_signature = signature
    return graph


def _is_allowed(
    memory: Dict[str, Any],
    *,
    scope: Optional[str],
    exclude_categories: Optional[List[str]],
) -> bool:
    if not isinstance(memory, dict):
        return False
    status = str(memory.get("status") or "active").strip().lower()
    if status == "superseded":
        return False
    if memory.get("memory_type") == "preference" and status != "active":
        return False
    category = str(memory.get("category") or "").strip().lower()
    excluded = {str(item).strip().lower() for item in (exclude_categories or [])}
    if category in excluded:
        return False
    if scope:
        scopes = memory.get("scopes")
        if isinstance(scopes, list) and scopes and scope not in scopes:
            return False
    return True


def _result_score(result: Dict[str, Any]) -> float:
    for field in ("hybrid_score", "weighted_score", "similarity_score", "similarity"):
        value = result.get(field)
        if isinstance(value, (int, float)):
            return max(0.0, float(value))
    return 0.0


def rerank_with_relation_graph(
    manager: Any,
    results: List[Dict[str, Any]],
    *,
    limit: int,
    scope: Optional[str] = None,
    exclude_categories: Optional[List[str]] = None,
    seed_count: int = 3,
    max_depth: int = 2,
) -> List[Dict[str, Any]]:
    """用关系簇扩展并重排语义/BM25 候选。

    高相关结果仍由原检索器决定；关系图只做二阶段 rerank。强事件/父子/连续关系
    可以补回同簇上下文；Android 明确分叉后的兄弟 lineage 不互相扩散。
    """
    if limit <= 0 or not results:
        return []

    graph = ensure_relation_graph(manager)
    if not graph:
        return results[:limit]

    with get_read_lock(manager):
        memories = {mid: dict(memory) for mid, memory in manager.weighted_memories.items()}
    lineages = getattr(manager, "_memory_relation_lineages", {})
    if not isinstance(lineages, dict):
        lineages = {}

    by_id: Dict[str, Dict[str, Any]] = {}
    base_scores: Dict[str, float] = {}
    for result in results:
        mid = _clean_id(result.get("id"))
        if not mid:
            continue
        copied = dict(result)
        by_id[mid] = copied
        base_scores[mid] = _result_score(copied)

    seeds = sorted(
        by_id.items(), key=lambda item: base_scores.get(item[0], 0.0), reverse=True
    )[: max(1, int(seed_count))]
    relation_scores: Dict[str, float] = defaultdict(float)
    relation_meta: Dict[str, Dict[str, Any]] = {}

    for seed_id, _ in seeds:
        seed_score = max(base_scores.get(seed_id, 0.0), 0.35)
        seed_lineage = tuple(lineages.get(seed_id, ()))
        queue = deque([(seed_id, 0, 1.0)])
        visited = {seed_id}
        while queue:
            current_id, depth, path_strength = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in graph.get(current_id, ()):  # type: ignore[arg-type]
                target = edge.target_id
                if target in visited:
                    continue
                target_lineage = tuple(lineages.get(target, ()))
                if not _lineages_compatible(seed_lineage, target_lineage):
                    continue
                visited.add(target)
                next_strength = path_strength * edge.strength * (0.72 ** depth)
                support = seed_score * next_strength
                if support > relation_scores[target]:
                    relation_scores[target] = support
                    relation_meta[target] = {
                        "seed_id": seed_id,
                        "relation": edge.relation,
                        "graph_distance": depth + 1,
                        "path_strength": round(next_strength, 4),
                        "branch_lineage": list(target_lineage),
                    }
                if edge.strength >= 0.45:
                    queue.append((target, depth + 1, next_strength))

    # 强关系可补入原始 Top-K 外的同簇节点；平行世界线已在 lineage gate 被隔离。
    for mid, support in relation_scores.items():
        if mid in by_id or support < 0.34:
            continue
        memory = memories.get(mid)
        if not memory or not _is_allowed(
            memory, scope=scope, exclude_categories=exclude_categories
        ):
            continue
        candidate = dict(memory)
        candidate["relation_expanded"] = True
        by_id[mid] = candidate
        base_scores[mid] = 0.0

    ranked: List[Dict[str, Any]] = []
    for mid, result in by_id.items():
        relation_score = min(relation_scores.get(mid, 0.0), 1.0)
        base = base_scores.get(mid, 0.0)
        if base > 0:
            adjusted = base + relation_score * 0.22
        else:
            adjusted = relation_score * 0.68
        result["base_hybrid_score"] = base
        result["relation_score"] = relation_score
        result["relation_adjusted_score"] = adjusted
        if "hybrid_score" in result or adjusted > 0:
            result["hybrid_score"] = adjusted
        if mid in relation_meta:
            result["relation_context"] = relation_meta[mid]
        ranked.append(result)

    ranked.sort(
        key=lambda item: (
            float(item.get("relation_adjusted_score") or 0.0),
            float(item.get("timestamp") or 0.0),
        ),
        reverse=True,
    )
    return ranked[:limit]


def get_relation_cluster(
    manager: Any,
    memory_id: str,
    *,
    limit: int = 12,
    max_depth: int = 2,
) -> List[Dict[str, Any]]:
    """返回某条记忆附近的同世界线关系簇，供搜索工具/调试接口直接使用。"""
    root = _clean_id(memory_id)
    if not root or limit <= 0:
        return []
    graph = ensure_relation_graph(manager)
    with get_read_lock(manager):
        memories = {mid: dict(memory) for mid, memory in manager.weighted_memories.items()}
    if root not in memories:
        return []
    lineages = getattr(manager, "_memory_relation_lineages", {})
    if not isinstance(lineages, dict):
        lineages = {}
    root_lineage = tuple(lineages.get(root, ()))

    output: List[Dict[str, Any]] = []
    queue = deque([(root, 0, "self", 1.0)])
    visited = set()
    while queue and len(output) < limit:
        current, depth, relation, strength = queue.popleft()
        if current in visited:
            continue
        current_lineage = tuple(lineages.get(current, ()))
        if not _lineages_compatible(root_lineage, current_lineage):
            continue
        visited.add(current)
        memory = memories.get(current)
        if memory:
            item = dict(memory)
            item["relation_context"] = {
                "root_id": root,
                "relation": relation,
                "graph_distance": depth,
                "path_strength": strength,
                "branch_lineage": list(current_lineage),
            }
            output.append(item)
        if depth >= max_depth:
            continue
        for edge in graph.get(current, ()):  # type: ignore[arg-type]
            if edge.target_id not in visited and edge.strength >= 0.35:
                target_lineage = tuple(lineages.get(edge.target_id, ()))
                if not _lineages_compatible(root_lineage, target_lineage):
                    continue
                queue.append(
                    (
                        edge.target_id,
                        depth + 1,
                        edge.relation,
                        round(strength * edge.strength, 4),
                    )
                )
    return output
