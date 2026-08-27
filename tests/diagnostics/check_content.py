"""直接检查磁盘文件中的 content 是否被 compact 清空"""
import json
import os

base = r"d:\AI\xiaoyou-core\companion_data\ling_data\memories\weighted\daily"
fp = os.path.join(base, "private_10001__scope__ling_weighted.json")

with open(fp, "r", encoding="utf-8") as f:
    data = json.load(f)

mems = data.get("weighted_memories", [])
print(f"总记忆数: {len(mems)}")

# 统计 content 为空的
empty_count = 0
pairs_count = 0
wechat_count = 0
pairs_empty = 0
wechat_empty = 0
original_empty = 0

for m in mems:
    src = m.get("metadata", {}).get("import_source", "original")
    content = m.get("content", "")
    is_empty = not content or not content.strip()

    if src == "pairs_jsonl":
        pairs_count += 1
        if is_empty:
            pairs_empty += 1
    elif src == "wechat_json":
        wechat_count += 1
        if is_empty:
            wechat_empty += 1
    else:
        if is_empty:
            original_empty += 1

    if is_empty:
        empty_count += 1

print(f"\ncontent 为空的总数: {empty_count}/{len(mems)}")
print(f"  pairs_jsonl: {pairs_empty}/{pairs_count} 为空")
print(f"  wechat_json: {wechat_empty}/{wechat_count} 为空")
print(f"  original: {original_empty} 为空")

# 抽样看几条
print("\n--- 抽样 pairs_jsonl ---")
count = 0
for m in mems:
    if m.get("metadata", {}).get("import_source") == "pairs_jsonl":
        content = m.get("content", "")
        print(f"  content长度={len(content)}: {content[:80]}...")
        count += 1
        if count >= 3:
            break

print("\n--- 抽样 wechat_json ---")
count = 0
for m in mems:
    if m.get("metadata", {}).get("import_source") == "wechat_json":
        content = m.get("content", "")
        print(f"  content长度={len(content)}: {content[:80]}...")
        count += 1
        if count >= 3:
            break
