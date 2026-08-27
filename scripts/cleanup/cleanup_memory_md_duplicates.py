"""
一次性存量清理脚本：合并 MEMORY.md 重复条目 + 迁移用户级偏好到 user_data

背景：
- 旧版 CoreMemory.add_item 用全等字符串去重，LLM 每次措辞略变就失效
- 旧版 record_memory_tool 的 scope 解析依赖全局 persona_manager，并发时会串角色
- 导致 aveline_data/MEMORY.md 里堆积了 5 条"回复要简短"和 3 条饮食偏好
- 同时"用户居住在重庆九龙坡"这种用户级偏好被错写到角色文件

本脚本做的事：
1. 用 embedding 语义相似度合并 aveline_data/MEMORY.md 内的重复偏好
2. 把识别出的"用户级偏好"（住址、通用回复风格、通用饮食禁忌）迁移到 user_data/MEMORY.md
3. 同样处理 ling_data/MEMORY.md（如果也有重复/错位）

用法：
    # 干跑（只显示会怎么改，不写文件）
    python scripts/cleanup/cleanup_memory_md_duplicates.py --dry-run

    # 真的执行
    python scripts/cleanup/cleanup_memory_md_duplicates.py

    # 自定义路径
    python scripts/cleanup/cleanup_memory_md_duplicates.py --base-dir D:/AI/xiaoyou-core/companion_data
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import List, Tuple

# 让脚本能在不安装包的情况下导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 迁移规则：哪些偏好转到 user_data ──────────────────
# 关键词命中即判定为用户级（住址/通用回复风格/通用饮食禁忌 等）
USER_LEVEL_PREFERENCE_PATTERNS = [
    r"居住在|住在|地址",
    r"回复.{0,10}简短|回复.{0,10}字数|回复.{0,10}长度|回复.{0,10}碎片化",
    r"长篇大论|刷屏|不要发大段",
    r"\[DELAY\]|延迟标记",
    r"饮食偏好|饮食禁忌|不吃海鲜|忌口|能吃辣",
    r"用户居住",
]

# 角色特定关键词：含这些词的不迁移（保留在角色文件）
ROLE_LEVEL_PREFERENCE_PATTERNS = [
    r"active care|主动关怀",
    r"黄腔|撩拨|sensitive",
    r"笨蛋|称呼",
    r"媚黑|raceplay",
    r"偷笑表情|face id",
]


def _matches_any(text: str, patterns: List[str]) -> bool:
    text_lower = text.lower()
    for p in patterns:
        if re.search(p, text_lower, re.IGNORECASE):
            return True
    return False


def is_user_level_preference(item: str) -> bool:
    """判断一条偏好是否属于用户级（所有角色共享）"""
    # 角色特定优先：含角色特定词的不迁
    if _matches_any(item, ROLE_LEVEL_PREFERENCE_PATTERNS):
        return False
    return _matches_any(item, USER_LEVEL_PREFERENCE_PATTERNS)


# ── MEMORY.md 解析与写出 ─────────────────────────────


SECTION_HEADERS = {
    "preferences": "## 🔒 用户偏好（永久保留）",
    "role": "## 💼 角色定位（永久保留）",
    "experience": "## 📝 业务经验（长期保留，≤15条）",
    "active_tasks": "## 📋 活跃任务（完成后删）",
    "corrections": "## 🔄 纠正记录（≤10条）",
    "summaries": "## 💬 对话摘要（7天后精简）",
}

SECTION_ORDER = [
    "preferences", "role", "experience",
    "active_tasks", "corrections", "summaries",
]


def parse_memory_md(content: str) -> dict:
    """解析 MEMORY.md，返回 {section_name: [items]}"""
    sections = {k: [] for k in SECTION_ORDER}
    current = None
    for line in content.split("\n"):
        for name, header in SECTION_HEADERS.items():
            if line.strip().startswith(header):
                current = name
                break
        else:
            if current is not None:
                s = line.strip()
                if s and not s.startswith("#"):
                    sections[current].append(s)
    return sections


def build_memory_md(sections: dict) -> str:
    """把 sections dict 重新序列化为 MEMORY.md 内容"""
    lines = ["# MEMORY.md - 核心记忆（自动加载）\n"]
    for name in SECTION_ORDER:
        header = SECTION_HEADERS[name]
        lines.append(f"\n{header}\n")
        for item in sections.get(name, []):
            lines.append(f"{item}\n")
    return "\n".join(lines)


# ── 语义合并 ────────────────────────────────────────


# 关键词桶定义：命中同一桶的条目语义必然相关，用更宽松的阈值合并
# 解决 MiniLM-L6-v2 对中文长句语义区分能力不足的问题
# （3 条"回复简短"措辞不同时 embedding 相似度只有 0.68-0.74，低于 0.85 阈值）
KEYWORD_BUCKETS = {
    "reply_style": [
        "回复", "消息", "字数", "简短", "碎片", "长篇", "简洁", "精炼",
        "少于用户", "和用户差不多", "不要发大段",
    ],
    "diet": [
        "饮食", "不吃", "忌口", "海鲜", "腊肠", "能吃辣", "烧腊", "鲜味",
        "味精", "鱼", "讨厌",
    ],
    "location": ["居住", "住在", "地址", "九龙坡", "重庆"],
    "emoji_style": ["表情", "emoji", "偷笑", "🖤"],
}


def _get_bucket(text: str) -> str:
    """返回条目所属的关键词桶，不属于任何桶返回 'other'"""
    text_lower = text.lower()
    for bucket, keywords in KEYWORD_BUCKETS.items():
        for kw in keywords:
            if kw in text_lower:
                return bucket
    return "other"


def keyword_bucket_merge(items: List[str]) -> Tuple[List[str], int]:
    """关键词分桶 + 桶内取最长合并。

    同桶条目语义必然相关（都讲回复风格/饮食/住址等），
    取最长那条作为合并结果（用户逐步细化时最长表述通常最完整）。

    返回 (合并后列表, 移除数量)。
    """
    if len(items) <= 1:
        return items, 0

    # 分桶
    buckets: dict = {}
    for i, item in enumerate(items):
        bucket = _get_bucket(item)
        buckets.setdefault(bucket, []).append((i, item))

    merged = []
    removed = 0
    for bucket, indexed_items in buckets.items():
        if len(indexed_items) <= 1:
            merged.append(indexed_items[0][1])
            continue

        # 桶内多条：取最长（保留最完整表述）
        sorted_items = sorted(indexed_items, key=lambda x: len(x[1]), reverse=True)
        keep = sorted_items[0][1]
        merged.append(keep)
        removed += len(sorted_items) - 1
        print(f"  关键词桶 [{bucket}] 合并 {len(sorted_items)} 条 → 保留: {keep[:60]}")
        for _, item in sorted_items[1:]:
            print(f"    丢弃: {item[:60]}")

    # 保持原顺序（按原 items 的索引排序）
    # merged 是按桶顺序的，需要按原索引恢复
    # 实际上桶内取最长已经丢了索引信息，直接返回合并后的列表即可
    return merged, removed


async def merge_duplicates(items: List[str], threshold: float = 0.85) -> Tuple[List[str], int]:
    """合并语义相似的条目，返回 (合并后列表, 移除数量)。

    两步合并策略：
    1. 关键词分桶 + 桶内取最长（处理 MiniLM 对中文长句漏判的问题）
    2. embedding 语义相似度合并（处理跨桶或 other 桶内的语义重复）
    """
    if len(items) <= 1:
        return items, 0

    # 步骤 1：关键词分桶合并
    items, kw_removed = keyword_bucket_merge(items)
    if kw_removed > 0:
        print(f"  关键词分桶合并移除: {kw_removed} 条")

    if len(items) <= 1:
        return items, kw_removed

    # 步骤 2：embedding 语义合并
    try:
        from memory.embedding_generator import get_embedding_generator, EmbeddingGenerator
        gen = get_embedding_generator()
    except Exception as e:
        print(f"  [warn] 无法加载 embedding 生成器，跳过语义合并: {e}")
        return items, kw_removed

    # 计算 embedding（同步函数，丢线程池）
    embeddings = await asyncio.to_thread(gen.generate_embeddings_batch, items)
    if not embeddings or len(embeddings) != len(items):
        print("  [warn] embedding 批量生成失败，跳过语义合并")
        return items, kw_removed

    # 用 Union-Find 把相似条目分组
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    hash_fallback = bool(getattr(gen, "_use_hash_fallback", False))
    actual_threshold = 0.95 if hash_fallback else threshold
    if hash_fallback:
        print(f"  [warn] embedding 处于 hash fallback 模式，使用更严格阈值 {actual_threshold}")

    sim_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            sim = EmbeddingGenerator.cosine_similarity(embeddings[i], embeddings[j])
            if sim >= actual_threshold:
                union(i, j)
                sim_pairs += 1

    if sim_pairs == 0:
        return items, kw_removed

    # 每组保留最长的那条（用户逐步细化时，最长表述通常最完整）
    groups: dict = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    merged = []
    emb_removed = 0
    for root, indices in groups.items():
        if len(indices) == 1:
            merged.append(items[indices[0]])
        else:
            # 按长度降序，保留最长，归档其他
            sorted_idx = sorted(indices, key=lambda i: len(items[i]), reverse=True)
            keep = items[sorted_idx[0]]
            merged.append(keep)
            emb_removed += len(indices) - 1
            print(f"  embedding 合并 {len(indices)} 条 → 保留: {keep[:60]}")
            for i in sorted_idx[1:]:
                print(f"    丢弃: {items[i][:60]}")

    return merged, kw_removed + emb_removed


# ── 主流程 ──────────────────────────────────────────


async def process_file(memory_file: Path, dry_run: bool = False) -> dict:
    """处理单个 MEMORY.md：合并重复 + 迁移用户级偏好"""
    if not memory_file.exists():
        return {"skipped": True, "reason": "文件不存在"}

    print(f"\n{'=' * 60}")
    print(f"处理: {memory_file}")
    print(f"{'=' * 60}")

    content = memory_file.read_text(encoding="utf-8")
    sections = parse_memory_md(content)

    prefs = sections["preferences"]
    original_count = len(prefs)
    print(f"原偏好数: {original_count}")

    # 步骤 1：语义合并
    merged_prefs, merged_removed = await merge_duplicates(prefs)
    print(f"语义合并移除: {merged_removed} 条")

    # 步骤 2：识别用户级偏好
    user_level = [p for p in merged_prefs if is_user_level_preference(p)]
    role_level = [p for p in merged_prefs if not is_user_level_preference(p)]
    print(f"用户级偏好（待迁移到 user_data）: {len(user_level)} 条")
    for p in user_level:
        print(f"  → {p[:60]}")
    print(f"角色级偏好（保留）: {len(role_level)} 条")

    sections["preferences"] = role_level

    result = {
        "file": str(memory_file),
        "original_count": original_count,
        "merged_removed": merged_removed,
        "user_level_moved": len(user_level),
        "role_level_kept": len(role_level),
        "user_level_items": user_level,
    }

    if dry_run:
        print("[dry-run] 不写文件")
        return result

    # 写回原文件
    new_content = build_memory_md(sections)
    memory_file.write_text(new_content, encoding="utf-8")
    print(f"已更新: {memory_file}")

    return result


async def move_user_level_to_user_data(user_level_items: List[str], user_data_file: Path, dry_run: bool = False) -> int:
    """把迁移出的用户级偏好合并到 user_data/MEMORY.md"""
    if not user_level_items:
        return 0

    print(f"\n{'=' * 60}")
    print(f"迁移用户级偏好到: {user_data_file}")
    print(f"{'=' * 60}")

    if not user_data_file.exists():
        # 创建初始文件
        user_data_file.parent.mkdir(parents=True, exist_ok=True)
        user_data_file.write_text(build_memory_md({k: [] for k in SECTION_ORDER}), encoding="utf-8")

    content = user_data_file.read_text(encoding="utf-8")
    sections = parse_memory_md(content)

    existing = set(sections["preferences"])
    added = 0
    for item in user_level_items:
        if item not in existing:
            sections["preferences"].append(item)
            existing.add(item)
            added += 1
            print(f"  + {item[:60]}")
        else:
            print(f"  = 已存在，跳过: {item[:60]}")

    # 在 user_data 内也跑一次语义合并
    sections["preferences"], user_data_merged = await merge_duplicates(sections["preferences"])
    print(f"user_data 内语义合并移除: {user_data_merged} 条")

    if dry_run:
        print("[dry-run] 不写文件")
        return added

    new_content = build_memory_md(sections)
    user_data_file.write_text(new_content, encoding="utf-8")
    print(f"已更新: {user_data_file}")
    return added


async def main() -> int:
    parser = argparse.ArgumentParser(description="清理 MEMORY.md 重复条目 + 迁移用户级偏好")
    parser.add_argument("--base-dir", default="D:/AI/xiaoyou-core/companion_data",
                        help="companion_data 目录路径")
    parser.add_argument("--dry-run", action="store_true", help="只显示会怎么改，不写文件")
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="语义相似度阈值（默认 0.85）")
    args = parser.parse_args()

    base = Path(args.base_dir)
    aveline_file = base / "aveline_data" / "MEMORY.md"
    ling_file = base / "ling_data" / "MEMORY.md"
    user_data_file = base / "user_data" / "MEMORY.md"

    print(f"模式: {'dry-run' if args.dry_run else '实际执行'}")
    print(f"阈值: {args.threshold}")

    all_user_level: List[str] = []

    for f in [aveline_file, ling_file]:
        result = await process_file(f, dry_run=args.dry_run)
        if not result.get("skipped"):
            all_user_level.extend(result.get("user_level_items", []))

    if all_user_level:
        moved = await move_user_level_to_user_data(all_user_level, user_data_file, dry_run=args.dry_run)
        print(f"\n总迁移到 user_data: {moved} 条")
    else:
        print("\n无用户级偏好需要迁移")

    # 始终对 user_data 跑一次合并（即使没有迁移，user_data 本身可能有重复）
    print(f"\n{'=' * 60}")
    print(f"清理 user_data 本身重复: {user_data_file}")
    print(f"{'=' * 60}")
    if user_data_file.exists():
        content = user_data_file.read_text(encoding="utf-8")
        sections = parse_memory_md(content)
        prefs = sections["preferences"]
        original_count = len(prefs)
        print(f"user_data 原偏好数: {original_count}")
        merged_prefs, merged_removed = await merge_duplicates(prefs)
        print(f"user_data 合并移除: {merged_removed} 条")
        if merged_removed > 0 and not args.dry_run:
            sections["preferences"] = merged_prefs
            user_data_file.write_text(build_memory_md(sections), encoding="utf-8")
            print(f"已更新: {user_data_file}")
        elif merged_removed > 0 and args.dry_run:
            print("[dry-run] 不写文件")
    else:
        print("user_data/MEMORY.md 不存在，跳过")

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
