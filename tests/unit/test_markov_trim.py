import sys
import os
import time
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from memory.core.distillation import trim_short_term_memory


def _noop_detect_topics(content):
    return []


def test_dialogue_priority_over_meta():
    print("=== 测试1：对话优先于元数据 ===")

    now = time.time()
    messages = []

    for i in range(30):
        messages.append({
            "id": f"old_system_{i}",
            "role": "system",
            "content": f"旧thinking {i}",
            "timestamp": now - 86400 * 3 + i * 60,
        })

    for i in range(30):
        messages.append({
            "id": f"recent_dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"最近对话 {i}",
            "timestamp": now - 3600 + i * 60,
        })

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    dialogue_in_trimmed = sum(1 for m in trimmed if m["role"] in ("user", "assistant"))
    meta_in_trimmed = sum(1 for m in trimmed if m["role"] == "system")

    print(f"  修剪后: {len(trimmed)} 条 (对话={dialogue_in_trimmed}, 元数据={meta_in_trimmed})")
    print(f"  移除: {len(removed)} 条")

    assert dialogue_in_trimmed == 30, f"所有30条对话应保留，实际: {dialogue_in_trimmed}"
    assert meta_in_trimmed == 30, f"元数据应保留30条，实际: {meta_in_trimmed}"

    print("  ✅ 对话全部保留，元数据按名额保留")


def test_recent_dialogue_over_old():
    print("\n=== 测试2：最近对话优先于旧对话 ===")

    now = time.time()
    messages = []

    for i in range(50):
        messages.append({
            "id": f"old_dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"旧对话 {i}",
            "timestamp": now - 86400 * 5 + i * 60,
        })

    for i in range(20):
        messages.append({
            "id": f"recent_dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"最近对话 {i}",
            "timestamp": now - 1800 + i * 30,
        })

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    dialogue_quota = int(60 * 0.7)
    dialogue_in_trimmed = sum(1 for m in trimmed if m["role"] in ("user", "assistant"))

    recent_kept = sum(1 for m in trimmed if m["id"].startswith("recent_dialogue_"))
    old_kept = sum(1 for m in trimmed if m["id"].startswith("old_dialogue_"))

    print(f"  修剪后: {len(trimmed)} 条 (对话={dialogue_in_trimmed})")
    print(f"  最近对话保留: {recent_kept}/20, 旧对话保留: {old_kept}/50")

    assert recent_kept == 20, f"所有20条最近对话应保留，实际: {recent_kept}"
    assert old_kept == dialogue_quota - 20, f"旧对话应保留剩余名额，实际: {old_kept}"

    print("  ✅ 最近对话全部保留，旧对话按名额保留")


def test_meta_does_not_displace_dialogue():
    print("\n=== 测试3：元数据不挤占对话名额 ===")

    now = time.time()
    messages = []

    for i in range(100):
        messages.append({
            "id": f"system_{i}",
            "role": "system",
            "content": f"thinking {i}",
            "timestamp": now - 86400 + i * 600,
        })

    for i in range(20):
        messages.append({
            "id": f"dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"对话 {i}",
            "timestamp": now - 3600 + i * 120,
        })

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    dialogue_in_trimmed = sum(1 for m in trimmed if m["role"] in ("user", "assistant"))
    meta_in_trimmed = sum(1 for m in trimmed if m["role"] == "system")

    print(f"  修剪后: {len(trimmed)} 条 (对话={dialogue_in_trimmed}, 元数据={meta_in_trimmed})")

    assert dialogue_in_trimmed == 20, f"所有20条对话应保留，实际: {dialogue_in_trimmed}"
    meta_quota = int(60 * 0.3)
    assert meta_in_trimmed == meta_quota, f"元数据应占{meta_quota}条，实际: {meta_in_trimmed}"

    print("  ✅ 对话全部保留，元数据不挤占对话名额")


def test_real_scenario():
    print("\n=== 测试4：复现真实场景 ===")

    now = time.time()
    messages = []

    for i in range(20):
        messages.append({
            "id": f"0503_system_{i}",
            "role": "system",
            "content": f"05-03 thinking {i}",
            "timestamp": now - 86400 * 8 + i * 60,
        })

    for i in range(18):
        messages.append({
            "id": f"0507_system_{i}",
            "role": "system",
            "content": f"05-07 thinking {i}",
            "timestamp": now - 86400 * 4 + i * 60,
        })

    for i in range(6):
        messages.append({
            "id": f"0508_system_{i}",
            "role": "system",
            "content": f"05-08 thinking {i}",
            "timestamp": now - 86400 * 3 + i * 60,
        })

    for i in range(30):
        messages.append({
            "id": f"0509_dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"05-09 对话 {i}",
            "timestamp": now - 86400 * 2 + i * 120,
        })

    for i in range(20):
        messages.append({
            "id": f"0510_dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"05-10 对话 {i}",
            "timestamp": now - 86400 + i * 120,
        })

    for i in range(10):
        messages.append({
            "id": f"0511_dialogue_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"05-11 对话 {i}",
            "timestamp": now - 1800 + i * 180,
        })

    print(f"  修剪前: {len(messages)} 条")

    trimmed, removed = trim_short_term_memory(messages, 60, _noop_detect_topics)

    dialogue_by_date = {}
    for m in trimmed:
        if m["role"] in ("user", "assistant"):
            ts = m["timestamp"]
            dt = datetime.fromtimestamp(ts).strftime('%m-%d')
            dialogue_by_date[dt] = dialogue_by_date.get(dt, 0) + 1

    meta_by_date = {}
    for m in trimmed:
        if m["role"] == "system":
            ts = m["timestamp"]
            dt = datetime.fromtimestamp(ts).strftime('%m-%d')
            meta_by_date[dt] = meta_by_date.get(dt, 0) + 1

    print(f"  修剪后: {len(trimmed)} 条")
    print(f"  对话分布: {dialogue_by_date}")
    print(f"  元数据分布: {meta_by_date}")

    has_0509 = "05-09" in dialogue_by_date or any(
        m["id"].startswith("0509_dialogue_") for m in trimmed
    )
    has_0510 = "05-10" in dialogue_by_date or any(
        m["id"].startswith("0510_dialogue_") for m in trimmed
    )
    has_0511 = "05-11" in dialogue_by_date or any(
        m["id"].startswith("0511_dialogue_") for m in trimmed
    )

    assert has_0510, "05-10对话应保留"
    assert has_0511, "05-11对话应保留"

    print("  ✅ 最近对话优先保留")


if __name__ == "__main__":
    print("=" * 60)
    print("短期记忆修剪逻辑测试（马尔科夫性质）")
    print("=" * 60)

    test_dialogue_priority_over_meta()
    test_recent_dialogue_over_old()
    test_meta_does_not_displace_dialogue()
    test_real_scenario()

    print("\n" + "=" * 60)
    print("🎉 所有测试通过！修剪逻辑已按马尔科夫性质优化")
    print("=" * 60)
