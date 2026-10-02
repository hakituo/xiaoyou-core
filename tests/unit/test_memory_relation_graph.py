import threading

from memory.core.relation_graph import (
    ensure_relation_graph,
    get_relation_cluster,
    rerank_with_relation_graph,
)


class _Manager:
    def __init__(self, memories):
        self.weighted_memories = memories
        self.lock = threading.RLock()
        self._use_rw_lock = False


def _memory(
    memory_id: str,
    content: str,
    *,
    timestamp: float,
    role: str = "user",
    topics=None,
    metadata=None,
):
    return {
        "id": memory_id,
        "content": content,
        "timestamp": timestamp,
        "last_access_time": timestamp,
        "weight": 5.0,
        "topics": list(topics or []),
        "source": role,
        "role": role,
        "category": "event",
        "memory_type": "dialogue",
        "status": "active",
        "scopes": ["sfw", "local", "cloud"],
        "metadata": dict(metadata or {}),
    }


def test_relation_graph_expands_same_turn_context():
    manager = _Manager(
        {
            "a": _memory(
                "a",
                "用户准备去修电脑",
                timestamp=100.0,
                topics=["电脑维修"],
                metadata={"turn_id": "turn-1"},
            ),
            "b": _memory(
                "b",
                "已经确认需要更换风扇",
                timestamp=101.0,
                role="assistant",
                topics=["电脑维修"],
                metadata={"turn_id": "turn-1"},
            ),
            "c": _memory(
                "c",
                "完全无关的晚餐记录",
                timestamp=5000.0,
                topics=["饮食"],
            ),
        }
    )

    ranked = rerank_with_relation_graph(
        manager,
        [{**manager.weighted_memories["a"], "hybrid_score": 0.92}],
        limit=3,
        scope="sfw",
    )

    assert [item["id"] for item in ranked[:2]] == ["a", "b"]
    assert ranked[1]["relation_expanded"] is True
    assert ranked[1]["relation_context"]["relation"] in {
        "turn",
        "topic",
        "continuation",
    }


def test_alternate_variant_is_not_promoted_as_current_context():
    manager = _Manager(
        {
            "active": _memory(
                "active",
                "当前采用的回复",
                timestamp=100.0,
                metadata={"turn_id": "active-turn"},
            ),
            "alternate": _memory(
                "alternate",
                "另一个重新生成版本",
                timestamp=101.0,
                metadata={"variant_of": "active"},
            ),
        }
    )

    ranked = rerank_with_relation_graph(
        manager,
        [{**manager.weighted_memories["active"], "hybrid_score": 0.9}],
        limit=2,
    )

    assert [item["id"] for item in ranked] == ["active"]


def test_variant_does_not_weaken_active_branch_context():
    manager = _Manager(
        {
            "user": _memory(
                "user",
                "用户问了一个问题",
                timestamp=99.0,
                topics=["分支测试"],
                metadata={"turn_id": "turn-active"},
            ),
            "active": _memory(
                "active",
                "当前采用的回复",
                timestamp=100.0,
                role="assistant",
                topics=["分支测试"],
                metadata={"turn_id": "turn-active"},
            ),
            "alternate": _memory(
                "alternate",
                "另一个重新生成版本",
                timestamp=101.0,
                role="assistant",
                topics=["分支测试"],
                metadata={"variant_of": "active"},
            ),
        }
    )

    ranked = rerank_with_relation_graph(
        manager,
        [{**manager.weighted_memories["active"], "hybrid_score": 0.9}],
        limit=3,
    )

    assert [item["id"] for item in ranked[:2]] == ["active", "user"]
    assert "alternate" not in [item["id"] for item in ranked]


def test_android_client_parent_id_resolves_to_weighted_memory_uuid():
    manager = _Manager(
        {
            "wm-user": _memory(
                "wm-user",
                "Android 用户消息",
                timestamp=100.0,
                metadata={"client_message_id": "android-user-1"},
            ),
            "wm-ai": _memory(
                "wm-ai",
                "Android AI 回复",
                timestamp=101.0,
                role="assistant",
                metadata={
                    "client_message_id": "android-ai-1",
                    "parent_id": "android-user-1",
                },
            ),
        }
    )

    graph = ensure_relation_graph(manager)
    assert any(
        edge.target_id == "wm-user"
        and edge.relation == "parent"
        and edge.strength == 1.0
        for edge in graph["wm-ai"]
    )


def test_android_parallel_descendants_do_not_cross_worldlines():
    manager = _Manager(
        {
            "root": _memory(
                "root",
                "共同父消息",
                timestamp=100.0,
                topics=["世界线测试"],
                metadata={"client_message_id": "android-root"},
            ),
            "v2": _memory(
                "v2",
                "旧回复 v2",
                timestamp=101.0,
                role="assistant",
                topics=["世界线测试"],
                metadata={
                    "client_message_id": "android-v2",
                    "parent_id": "android-root",
                },
            ),
            "v3": _memory(
                "v3",
                "重新生成回复 v3",
                timestamp=102.0,
                role="assistant",
                topics=["世界线测试"],
                metadata={
                    "client_message_id": "android-v3",
                    "parent_id": "android-root",
                    "variant_of": "android-v2",
                },
            ),
            "v2-child": _memory(
                "v2-child",
                "v2 世界线后续",
                timestamp=103.0,
                topics=["世界线测试"],
                metadata={
                    "client_message_id": "android-v2-child",
                    "parent_id": "android-v2",
                },
            ),
            "v3-child": _memory(
                "v3-child",
                "v3 世界线后续",
                timestamp=104.0,
                topics=["世界线测试"],
                metadata={
                    "client_message_id": "android-v3-child",
                    "parent_id": "android-v3",
                },
            ),
        }
    )

    ranked = rerank_with_relation_graph(
        manager,
        [{**manager.weighted_memories["v3-child"], "hybrid_score": 0.95}],
        limit=5,
        max_depth=3,
    )
    ids = [item["id"] for item in ranked]

    assert "v3" in ids
    assert "root" in ids
    assert "v2" not in ids
    assert "v2-child" not in ids
    assert manager._memory_relation_lineages["v2-child"] != (
        manager._memory_relation_lineages["v3-child"]
    )


def test_relation_graph_cache_rebuilds_when_memory_set_changes():
    manager = _Manager(
        {
            "a": _memory("a", "第一条", timestamp=100.0, topics=["项目"]),
        }
    )
    first = ensure_relation_graph(manager)
    assert set(first) == {"a"}

    manager.weighted_memories["b"] = _memory(
        "b", "第二条", timestamp=101.0, topics=["项目"]
    )
    second = ensure_relation_graph(manager)
    assert set(second) == {"a", "b"}
    assert any(edge.target_id == "b" for edge in second["a"])


def test_get_relation_cluster_returns_local_graph_neighborhood():
    manager = _Manager(
        {
            "a": _memory("a", "第一轮", timestamp=100.0, topics=["记忆系统"]),
            "b": _memory(
                "b",
                "第二轮",
                timestamp=101.0,
                role="assistant",
                topics=["记忆系统"],
            ),
            "c": _memory("c", "第三轮", timestamp=102.0, topics=["记忆系统"]),
        }
    )

    cluster = get_relation_cluster(manager, "b", limit=3, max_depth=1)
    assert cluster[0]["id"] == "b"
    assert {item["id"] for item in cluster} == {"a", "b", "c"}
