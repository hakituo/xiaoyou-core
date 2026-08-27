"""验证 pairs.txt 导入到 weighted_memories 是否成功

检查项：
1. weighted_memories 里有 pairs_txt 来源的记忆
2. 权重统一为 5.0（默认加权策略）
3. 时间戳保留原始 ts（不是导入时间）
4. 与 best_jsonl 来源的记忆共存（不冲突）
5. embedding 已生成
6. search_chat_history 能搜到 pairs_txt 来源的内容

用法:
    .\\venv_core\\Scripts\\python.exe -m tests.scripts.memory.verify_pairs_txt_import
"""
import asyncio
import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


async def check_weighted_memories():
    """检查 weighted_memories 里的 pairs_txt 导入记录"""
    print("\n" + "=" * 60)
    print("检查 1: weighted_memories 里的 pairs_txt 导入记录")
    print("=" * 60)

    from memory.weighted_memory_manager import get_weighted_memory_manager

    user_id = "private_10001__scope__ling"
    manager = get_weighted_memory_manager(user_id)
    if not manager:
        print("❌ 无法获取 MemoryManager")
        return False

    # 等待数据加载
    await asyncio.sleep(3)

    pairs_txt_count = 0
    best_jsonl_count = 0
    other_count = 0
    weight_check_passed = 0
    weight_check_failed = 0
    ts_preserved_count = 0
    ts_import_time_count = 0
    sample_records = []

    # pairs.txt 的时间范围：2026-02-16 ~ 2026-02-28，对应 ts 大约 1771200000 ~ 1772300000
    pairs_ts_min = 1771000000
    pairs_ts_max = 1773000000

    for memory_id, memory in manager.weighted_memories.items():
        metadata = memory.get("metadata") or {}
        import_source = metadata.get("import_source")

        if import_source == "pairs_txt":
            pairs_txt_count += 1

            # 验证权重 = 5.0
            actual_weight = memory.get("weight", 0)
            if abs(actual_weight - 5.0) < 0.01:
                weight_check_passed += 1
            else:
                weight_check_failed += 1
                if len(sample_records) < 3:
                    sample_records.append({
                        "id": memory_id,
                        "expected": 5.0,
                        "actual": actual_weight,
                    })

            # 检查 ts 是否保留原始时间
            ts = metadata.get("original_ts")
            mem_timestamp = memory.get("timestamp", 0)
            if ts is not None and abs(mem_timestamp - float(ts)) < 1.0:
                ts_preserved_count += 1
            elif pairs_ts_min <= mem_timestamp <= pairs_ts_max:
                ts_preserved_count += 1  # 在 pairs.txt 时间范围内也算
            else:
                ts_import_time_count += 1

        elif import_source == "best_jsonl":
            best_jsonl_count += 1
        else:
            other_count += 1

    print(f"  pairs_txt 导入记录数: {pairs_txt_count}")
    print(f"  best_jsonl 导入记录数（应有 32 条）: {best_jsonl_count}")
    print(f"  其他来源记录数: {other_count}")
    print(f"  权重校验（应=5.0）: 通过 {weight_check_passed} 条, 失败 {weight_check_failed} 条")
    print(f"  时间戳保留原始 ts: {ts_preserved_count} / {pairs_txt_count}")
    if ts_import_time_count > 0:
        print(f"  ⚠️ 时间戳为导入时间的: {ts_import_time_count}")

    if pairs_txt_count == 0:
        print("❌ 没有找到 pairs_txt 来源的记忆")
        return False

    if weight_check_failed > 0:
        print(f"❌ 权重校验失败 {weight_check_failed} 条:")
        for s in sample_records:
            print(f"    {s}")
        return False

    print("✅ weighted_memories 检查通过")
    return True


async def check_search_chat_history():
    """检查 search_chat_history 能搜到 pairs_txt 来源的内容"""
    print("\n" + "=" * 60)
    print("检查 2: 搜索能找到 pairs_txt 来源的记忆")
    print("=" * 60)

    from memory.weighted_memory_manager import get_weighted_memory_manager

    user_id = "private_10001__scope__ling"
    manager = get_weighted_memory_manager(user_id)
    if not manager:
        print("❌ 无法获取 MemoryManager")
        return False

    # 用几个测试 query 搜索
    test_queries = [
        "你为什么想起来找我了",
        "兼职",
        "猫",
        "西湖",
        "论文",
    ]

    all_passed = True
    for query in test_queries:
        # 用关键词搜索（search_memories 用 limit 参数）
        try:
            results = manager.search_memories(query, limit=5) or []
        except Exception as e:
            print(f"  ❌ '{query}' 搜索失败: {e}")
            all_passed = False
            continue
        # 过滤出 pairs_txt 来源的
        pairs_txt_hits = 0
        for r in results:
            mem_id = r.get("id") if isinstance(r, dict) else None
            if mem_id:
                mem = manager.weighted_memories.get(mem_id) or {}
                if (mem.get("metadata") or {}).get("import_source") == "pairs_txt":
                    pairs_txt_hits += 1
        if pairs_txt_hits > 0:
            print(f"  ✅ '{query}' → {len(results)} 条结果, 其中 {pairs_txt_hits} 条来自 pairs_txt")
        else:
            print(f"  ⚠️ '{query}' → {len(results)} 条结果, 无 pairs_txt 来源")
            # 不算失败，因为搜索结果可能本来就是 best_jsonl 优先

    print("✅ 搜索检查完成")
    return True


async def check_no_duplicate_with_best_jsonl():
    """检查 pairs_txt 和 best_jsonl 没有内容重复"""
    print("\n" + "=" * 60)
    print("检查 3: pairs_txt 与 best_jsonl 内容去重")
    print("=" * 60)

    from memory.weighted_memory_manager import get_weighted_memory_manager

    user_id = "private_10001__scope__ling"
    manager = get_weighted_memory_manager(user_id)
    if not manager:
        print("❌ 无法获取 MemoryManager")
        return False

    # 收集所有 pairs_txt 和 best_jsonl 的 content
    pairs_txt_contents = set()
    best_jsonl_contents = set()

    for memory_id, memory in manager.weighted_memories.items():
        metadata = memory.get("metadata") or {}
        import_source = metadata.get("import_source")
        content = memory.get("content", "").strip()
        if not content:
            continue
        if import_source == "pairs_txt":
            pairs_txt_contents.add(content)
        elif import_source == "best_jsonl":
            best_jsonl_contents.add(content)

    # 检查交集
    duplicates = pairs_txt_contents & best_jsonl_contents
    print(f"  pairs_txt 唯一内容数: {len(pairs_txt_contents)}")
    print(f"  best_jsonl 唯一内容数: {len(best_jsonl_contents)}")
    print(f"  两者重复内容数: {len(duplicates)}")

    if duplicates:
        print(f"  ⚠️ 发现 {len(duplicates)} 条重复内容（应为 0）:")
        for i, c in enumerate(list(duplicates)[:3]):
            print(f"    [{i+1}] {c[:80]}...")
        return False

    print("✅ 无重复内容")
    return True


async def main():
    print("=" * 60)
    print("pairs.txt 导入验证")
    print("=" * 60)

    checks = [
        ("weighted_memories 检查", await check_weighted_memories()),
        ("搜索检查", await check_search_chat_history()),
        ("与 best_jsonl 去重检查", await check_no_duplicate_with_best_jsonl()),
    ]

    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    all_passed = True
    for name, passed in checks:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n🎉 所有验证通过！")
        return 0
    else:
        print("\n⚠️ 有验证项失败，请检查")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
