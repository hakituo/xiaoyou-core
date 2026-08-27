"""检查记忆文件状态"""
import json
import os

base = r"d:\AI\xiaoyou-core\companion_data\ling_data\memories"

# 检查 daily weighted
daily_fp = os.path.join(base, "weighted", "daily", "private_10001__scope__ling_weighted.json")
if os.path.exists(daily_fp):
    with open(daily_fp, "r", encoding="utf-8") as f:
        d = json.load(f)
    mems = d.get("weighted_memories", [])
    print(f"daily weighted_memories: {len(mems)}")
    # 统计来源
    sources = {}
    for m in mems:
        src = m.get("metadata", {}).get("import_source", "original")
        sources[src] = sources.get(src, 0) + 1
    print(f"来源分布: {sources}")
else:
    print("daily weighted 文件不存在")

# 检查主 weighted
main_fp = os.path.join(base, "weighted", "private_10001__scope__ling_weighted.json")
if os.path.exists(main_fp):
    with open(main_fp, "r", encoding="utf-8") as f:
        d = json.load(f)
    mems = d.get("weighted_memories", [])
    print(f"\n主 weighted_memories: {len(mems)}")
else:
    print("\n主 weighted 文件不存在")
