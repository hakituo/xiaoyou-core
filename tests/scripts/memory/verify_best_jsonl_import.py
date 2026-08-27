"""
验证 best.jsonl 导入到 weighted_memories 和 StyleRetriever 接入是否成功

检查项：
1. weighted_memories 里有 best_jsonl_import 来源的记忆
2. 权重按 confidence 加权（3.0 + confidence * 4.0）
3. StyleRetriever 能从 best.jsonl 检索到相关对话
4. select_real_chat_examples 走 StyleRetriever 路径能返回结果
5. 用几条测试 query 验证检索质量

用法:
    .\\venv_core\\Scripts\\python.exe -m tests.scripts.memory.verify_best_jsonl_import
"""
import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


async def check_weighted_memories():
    """检查 weighted_memories 里是否有 best_jsonl_import 来源的记忆"""
    print("\n" + "=" * 60)
    print("检查 1: weighted_memories 里的导入记录")
    print("=" * 60)

    from memory.weighted_memory_manager import get_weighted_memory_manager

    user_id = "private_10001__scope__ling"
    manager = get_weighted_memory_manager(user_id)
    if not manager:
        print("❌ 无法获取 MemoryManager")
        return False

    # 等待数据加载
    await asyncio.sleep(2)

    imported_count = 0
    weight_check_passed = 0
    weight_check_failed = 0
    categories = {}
    sample_records = []

    for memory_id, memory in manager.weighted_memories.items():
        metadata = memory.get("metadata") or {}
        if metadata.get("import_source") == "best_jsonl":
            imported_count += 1

            # 统计分类
            cat = memory.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

            # 验证权重 = 3.0 + confidence * 4.0
            confidence = metadata.get("confidence", 0)
            expected_weight = round(3.0 + max(0.0, min(1.0, confidence)) * 4.0, 4)
            actual_weight = memory.get("weight", 0)
            if abs(actual_weight - expected_weight) < 0.01:
                weight_check_passed += 1
            else:
                weight_check_failed += 1
                if len(sample_records) < 3:
                    sample_records.append({
                        "id": memory_id,
                        "confidence": confidence,
                        "expected": expected_weight,
                        "actual": actual_weight,
                    })

            # 检查 embedding 是否生成
            has_embedding = bool(memory.get("embedding"))

    print(f"  导入记录数: {imported_count}")
    print(f"  分类分布: {categories}")
    print(f"  权重校验: 通过 {weight_check_passed} 条, 失败 {weight_check_failed} 条")

    if imported_count == 0:
        print("❌ 没有找到 best_jsonl_import 来源的记忆")
        return False

    if weight_check_failed > 0:
        print(f"⚠️ 权重校验失败 {weight_check_failed} 条:")
        for s in sample_records:
            print(f"    {s}")
        return False

    print("✅ weighted_memories 检查通过")
    return True


def check_style_retriever():
    """检查 StyleRetriever 能正常检索"""
    print("\n" + "=" * 60)
    print("检查 2: StyleRetriever 检索")
    print("=" * 60)

    from core.utils.style_retriever import StyleRetriever

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    memory_path = os.path.join(project_root, "data", "character", "ling", "best", "私聊_玲🍀.best.jsonl")
    static_path = os.path.join(project_root, "data", "character", "ling", "curated", "ling_style_manual_selected.txt")

    if not os.path.exists(memory_path):
        print(f"❌ best.jsonl 不存在: {memory_path}")
        return False

    retriever = StyleRetriever(memory_path, static_path if os.path.exists(static_path) else None)
    print(f"  加载对话数: {len(retriever.conversations)}")
    print(f"  静态示例数: {len(retriever.static_examples)}")

    if not retriever.conversations:
        print("❌ StyleRetriever 没加载到任何对话")
        return False

    # 测试几个 query
    test_queries = [
        "你英语背到哪了",
        "你在玩什么游戏",
        "我想你了",
        "你今天去哪里玩",
        "你生病了吗",
    ]

    all_passed = True
    for query in test_queries:
        results = retriever.retrieve(query, k=3, threshold=0.02)
        if results:
            first = results[0]
            chain_text = str(first.get("chain_text") or "").strip()[:80]
            print(f"  ✅ '{query}' → {len(results)} 条, 首条: {chain_text}...")
        else:
            print(f"  ❌ '{query}' → 无结果")
            all_passed = False

    return all_passed


def check_select_real_chat_examples():
    """检查 select_real_chat_examples 走 StyleRetriever 路径"""
    print("\n" + "=" * 60)
    print("检查 3: select_real_chat_examples 走 StyleRetriever 路径")
    print("=" * 60)

    from core.agents.chat_agent_components.persona_system.prompt.dialogue_examples import (
        select_real_chat_examples,
        _get_style_retriever,
    )

    # 确认 StyleRetriever 能初始化
    retriever = _get_style_retriever("Ling")
    if retriever is None:
        print("❌ StyleRetriever 初始化失败")
        return False
    print(f"  ✅ StyleRetriever 已初始化: {type(retriever).__name__}")

    # 测试几个 query
    test_queries = [
        "你英语背到哪了",
        "你最近忙什么呢",
        "你今天吃饭了吗",
    ]

    all_passed = True
    for query in test_queries:
        results = select_real_chat_examples(query, persona_name="Ling", top_k=3)
        if results:
            first = str(results[0]).strip()[:80]
            print(f"  ✅ '{query}' → {len(results)} 条, 首条: {first}...")
        else:
            print(f"  ❌ '{query}' → 无结果")
            all_passed = False

    return all_passed


async def main():
    print("=" * 60)
    print("best.jsonl 导入和 StyleRetriever 接入验证")
    print("=" * 60)

    checks = [
        ("weighted_memories 检查", await check_weighted_memories()),
        ("StyleRetriever 检索检查", check_style_retriever()),
        ("select_real_chat_examples 检查", check_select_real_chat_examples()),
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
