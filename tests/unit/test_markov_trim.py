"""短期记忆修剪（马尔科夫性质）测试

当前实现不再是"对话/元数据按角色分配名额"，而是：
1. 按 is_important 分桶，important 最多占 50% 配额，剩余名额让给普通消息
2. 桶内按评分（基础分 + 权重分 + 时间衰减分）降序保留
3. 最近的消息评分更高，体现马尔科夫性质

这里按上述现行契约重写，不再断言已被移除的角色配额。
"""

import os
import sys
import time

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from memory.core.distillation import trim_short_term_memory


def _noop_detect_topics(content):
    return []


def _make_messages(count, *, prefix="msg", start_offset, step=10.0, **extra):
    now = time.time()
    messages = []
    for i in range(count):
        message = {
            "id": f"{prefix}_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"{prefix} {i}",
            "timestamp": now - start_offset + i * step,
        }
        message.update(extra)
        messages.append(message)
    return messages


def test_no_trim_when_under_threshold():
    """未超过阈值时原样返回，且不产生被移除消息"""
    messages = _make_messages(10, prefix="m", start_offset=600, step=10.0)

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    assert len(trimmed) == 10
    assert removed == []


def test_trim_keeps_threshold_and_splits_removed():
    """超阈值后保留数量等于阈值，kept 与 removed 互补且无重复"""
    messages = _make_messages(100, prefix="m", start_offset=1800, step=10.0)

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    assert len(trimmed) == 60
    assert len(removed) == 40

    kept_ids = {m["id"] for m in trimmed}
    removed_ids = {m["id"] for m in removed}
    assert len(kept_ids) == 60, "保留列表不应出现重复 id"
    assert kept_ids.isdisjoint(removed_ids)
    assert kept_ids | removed_ids == {m["id"] for m in messages}


def test_trim_result_is_time_ordered():
    """修剪结果按时间升序返回，保证上下文顺序稳定"""
    messages = _make_messages(100, prefix="m", start_offset=1800, step=10.0)

    trimmed, _ = trim_short_term_memory(messages, 60, _noop_detect_topics)

    timestamps = [m["timestamp"] for m in trimmed]
    assert timestamps == sorted(timestamps)


def test_recent_messages_survive_older_ones():
    """马尔科夫性质：同等条件下最近的消息优先保留"""
    messages = _make_messages(100, prefix="m", start_offset=1800, step=10.0)

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    kept_timestamps = {m["timestamp"] for m in trimmed}
    removed_timestamps = {m["timestamp"] for m in removed}

    assert max(removed_timestamps) < min(kept_timestamps), "被移除的应全是更早的消息"
    # 最近 60 条（索引 40-99）应被保留
    assert kept_timestamps == {m["timestamp"] for m in messages[40:]}


def test_important_messages_are_kept_despite_being_old():
    """重要消息与配额独立：即使最旧也会优先保留"""
    important = _make_messages(
        10, prefix="imp", start_offset=86400 * 5, step=60.0, is_important=True
    )
    normal = _make_messages(100, prefix="norm", start_offset=1800, step=10.0)

    trimmed, _ = trim_short_term_memory(important + normal, 20, _noop_detect_topics)

    kept_important = [m for m in trimmed if m.get("is_important")]
    kept_normal = [m for m in trimmed if not m.get("is_important")]

    assert len(kept_important) == 10, "重要消息应全部保留"
    assert len(kept_normal) == 10, "剩余名额应让给普通消息"


def test_important_quota_is_capped_at_half():
    """全部标记为重要时仍会修剪，避免配额失效"""
    messages = _make_messages(
        100, prefix="imp", start_offset=86400 * 5, step=60.0, is_important=True
    )

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    assert len(trimmed) == 30, f"important 最多占一半配额，实际保留 {len(trimmed)} 条"
    assert len(removed) == 70


def test_higher_weight_survives_within_same_bucket():
    """同一分桶内权重更高的消息优先保留"""
    now = time.time()
    messages = []
    for i in range(100):
        messages.append(
            {
                "id": f"w_{i}",
                "role": "user",
                "content": f"weighted {i}",
                "timestamp": now - 1800 + i * 10,
                "weight": 0.0,
            }
        )
    # 给最旧的 10 条一个极高权重，抵消时间劣势
    for m in messages[:10]:
        m["weight"] = 100.0

    trimmed, _ = trim_short_term_memory(messages, 60, _noop_detect_topics)

    kept_ids = {m["id"] for m in trimmed}
    assert kept_ids.issuperset({m["id"] for m in messages[:10]}), "高权重消息应保留"
    assert len(kept_ids) == 60
