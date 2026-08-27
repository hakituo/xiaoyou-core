"""搜索调试 - 直接测试搜索功能"""
import sys
import time
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)

from memory.weighted_memory_manager import get_weighted_memory_manager

user_id = "private_10001__persona__ling_qq_love"
manager = get_weighted_memory_manager(user_id)
time.sleep(5)

print(f"weighted_memories 数量: {len(manager.weighted_memories)}")
print(f"关键词索引关键词数: {len(manager._keyword_index)}")

# 检查导入的记忆 content 是否为空
empty_count = 0
pairs_count = 0
wechat_count = 0
for m in manager.weighted_memories.values():
    src = m.get("metadata", {}).get("import_source", "")
    if src == "pairs_jsonl":
        pairs_count += 1
        if not m.get("content"):
            empty_count += 1
    elif src == "wechat_json":
        wechat_count += 1
        if not m.get("content"):
            empty_count += 1

print(f"\npairs_jsonl 记忆数: {pairs_count}, content为空: {empty_count}")
print(f"wechat_json 记忆数: {wechat_count}, content为空: {empty_count}")

# 抽样看几条导入记忆的 content
print("\n--- 抽样 pairs_jsonl 记忆 ---")
count = 0
for m in manager.weighted_memories.values():
    if m.get("metadata", {}).get("import_source") == "pairs_jsonl":
        content = m.get("content", "")
        print(f"  content长度={len(content)}: {content[:80]}...")
        count += 1
        if count >= 3:
            break

# 直接用关键词搜索
print("\n--- search_by_keyword 测试 ---")
try:
    results = manager._search_by_keyword("猫", limit=5)
    print(f"搜索\"猫\": {len(results)} 条结果")
    for r in results[:3]:
        content = r.get("content", "")[:80]
        print(f"  {content}...")
except Exception as e:
    print(f"搜索失败: {e}")

# 用 search_memories 测试
print("\n--- search_memories 测试 ---")
try:
    results = manager.search_memories(query="猫", limit=5)
    print(f"搜索\"猫\": {len(results)} 条结果")
    for r in results[:3]:
        content = r.get("content", "")[:80]
        print(f"  {content}...")
except Exception as e:
    print(f"搜索失败: {e}")
