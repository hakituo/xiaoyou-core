#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 WeightedMemory 关系图检索行为。"""

import threading

from memory.core.relation_graph import rerank_with_relation_graph


class _Manager:
    def __init__(self, memories):
        self.weighted_memories = memories
        self.lock = threading.RLock()
        self._use_rw_lock = False


def _memory(memory_id, content, timestamp, role="user", topics=None, metadata=None):
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


def main() -> None:
    manager = _Manager(
        {
            "seed": _memory(
                "seed",
                "讨论 WeightedMemory 搜索准确率",
                100.0,
                topics=["memory", "search"],
                metadata={"turn_id": "turn-memory-1"},
            ),
            "context": _memory(
                "context",
                "决定让相关记忆按关系簇一起召回",
                101.0,
                role="assistant",
                topics=["memory", "search"],
                metadata={"turn_id": "turn-memory-1"},
            ),
            "noise": _memory(
                "noise",
                "无关天气内容",
                9000.0,
                topics=["weather"],
            ),
            "alternate": _memory(
                "alternate",
                "平行重新生成版本",
                102.0,
                metadata={"variant_of": "seed"},
            ),
        }
    )

    results = rerank_with_relation_graph(
        manager,
        [{**manager.weighted_memories["seed"], "hybrid_score": 0.9}],
        limit=4,
        scope="sfw",
    )
    ids = [item["id"] for item in results]

    assert ids[:2] == ["seed", "context"], ids
    assert "noise" not in ids, ids
    assert "alternate" not in ids, ids
    assert results[1].get("relation_expanded") is True
    assert float(results[1].get("relation_score") or 0.0) > 0.0

    print("PASS: WeightedMemory 关系图可扩展强关联上下文，并抑制无关/平行版本污染")


if __name__ == "__main__":
    main()
