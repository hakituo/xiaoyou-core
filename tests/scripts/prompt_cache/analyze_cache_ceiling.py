#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量化「为什么到不了 AI IDE 那种 99% 命中」：拆解未命中尾部的构成。

只读分析 logs/prompt_cache_stats.log，不改任何业务代码。

看三件事：
1. 未命中尾部（miss_tokens）的体量分布 —— IDE 的尾部只有"本轮新增"，
   我们的尾部里还包含「检索块/动态块/窗口起点跳动」造成的整段失配。
2. 命中爬升的连续段（run）长度 —— 段越长说明前缀越稳，段短说明频繁重置。
3. 相邻两次请求之间 hit 的增长量，用来估算"每轮真正新增"有多少 token。
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_PATH = PROJECT_ROOT / "logs" / "prompt_cache_stats.log"

DAY_START = "2026-09-18"


def load_deepseek():
    rows = []
    if not LOG_PATH.exists():
        raise SystemExit(f"缺少日志: {LOG_PATH}")
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "deepseek" not in str(row.get("model") or ""):
            continue
        if not row.get("hit_tokens"):
            continue
        ts = str(row.get("timestamp") or "")
        if ts[:10] < DAY_START:
            continue
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            continue
        rows.append(
            {
                "when": when,
                "hit": int(row.get("hit_tokens") or 0),
                "miss": int(row.get("miss_tokens") or 0),
                "prompt": int(row.get("prompt_tokens") or 0),
                "source": str(row.get("source") or ""),
                "key": str(row.get("key_id") or ""),
            }
        )
    rows.sort(key=lambda item: item["when"])
    return rows


def pct(values, q):
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * q))
    return ordered[index]


def main():
    rows = load_deepseek()
    if not rows:
        raise SystemExit("没有 deepseek 样本")

    print(f"▶ 样本 {len(rows)} 条（{DAY_START} 起）")

    # 1. 未命中尾部体量
    misses = [r["miss"] for r in rows]
    prompts = [r["prompt"] for r in rows]
    hits = [r["hit"] for r in rows]
    print("\n[1] 体量分布")
    print(f"  prompt_tokens  中位 {statistics.median(prompts):.0f}"
          f"  p10 {pct(prompts,0.1)}  p90 {pct(prompts,0.9)}")
    print(f"  hit_tokens     中位 {statistics.median(hits):.0f}"
          f"  p10 {pct(hits,0.1)}  p90 {pct(hits,0.9)}")
    print(f"  miss_tokens    中位 {statistics.median(misses):.0f}"
          f"  p10 {pct(misses,0.1)}  p90 {pct(misses,0.9)}")

    # 底座：每个 key 的最小 hit 视为静态前缀下界
    floors = {}
    for r in rows:
        key = r["key"] or r["source"] or "?"
        floors[key] = min(floors.get(key, 10**9), r["hit"])
    print(f"  各 key 静态底座: {floors}")

    # 2. 连续爬升段：hit 相对上一条不回落即算同一段
    print("\n[2] 命中爬升段（hit 相对上一条不下降 = 同一段）")
    runs = []
    cur = 1
    for prev, now in zip(rows, rows[1:]):
        if now["hit"] >= prev["hit"]:
            cur += 1
        else:
            runs.append(cur)
            cur = 1
    runs.append(cur)
    print(f"  段数 {len(runs)}，平均段长 {statistics.mean(runs):.2f}，"
          f"最长 {max(runs)}，中位 {statistics.median(runs):.0f}")
    print(f"  段长分布(前8): {Counter(runs).most_common(8)}")

    # 3. 相邻请求 hit 增量（未跨 session：间隔 < 10 分钟）
    print("\n[3] 相邻请求（间隔<10min）的 hit 增量 / prompt 增量")
    deltas = []
    miss_deltas = []
    for prev, now in zip(rows, rows[1:]):
        gap = (now["when"] - prev["when"]).total_seconds()
        if gap > 600:
            continue
        deltas.append(now["hit"] - prev["hit"])
        miss_deltas.append(now["miss"] - prev["miss"])
    if deltas:
        print(f"  样本 {len(deltas)} 对")
        print(f"  Δhit   中位 {statistics.median(deltas):.0f}"
              f"  均值 {statistics.mean(deltas):.0f}")
        print(f"  Δmiss  中位 {statistics.median(miss_deltas):.0f}"
              f"  均值 {statistics.mean(miss_deltas):.0f}")
        grow = sum(1 for d in deltas if d > 0)
        drop = sum(1 for d in deltas if d < 0)
        print(f"  Δhit>0 {grow} 对（{grow/len(deltas)*100:.1f}%）"
              f"  Δhit<0 {drop} 对（{drop/len(deltas)*100:.1f}%）")

    # 4. 结构上限估算：假设前缀完全不动，只剩"本轮新增"未命中
    #    本轮新增 ≈ 上一轮的 miss 里属于新消息的那部分，用最小 miss 近似
    floor_miss = min(misses)
    med_prompt = statistics.median(prompts)
    print("\n[4] 结构上限粗估")
    print(f"  若只留本轮新增（≈最小 miss {floor_miss} tok），"
          f"中位 prompt {med_prompt:.0f} 的命中率上限"
          f" ≈ {(med_prompt - floor_miss) / med_prompt * 100:.1f}%")
    print(f"  实测加权命中率 ≈ "
          f"{sum(hits)/sum(prompts)*100:.1f}%")

    # 5. 命中率分桶，看"到底卡在哪"
    print("\n[5] 命中率分桶")
    buckets = Counter()
    for r in rows:
        ratio = r["hit"] / r["prompt"] if r["prompt"] else 0
        buckets[int(ratio * 10) * 10] += 1
    for bucket in sorted(buckets):
        count = buckets[bucket]
        print(f"  {bucket:>3}-{bucket+10:<3}% : {count:>4} "
              f"({count/len(rows)*100:.1f}%) {'#' * max(1, int(count/len(rows)*60))}")

    print("\n结果: 分析完成（只读）")


if __name__ == "__main__":
    main()
