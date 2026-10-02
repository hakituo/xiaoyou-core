#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检验「工具 schema 逐轮变化」是否就是 prompt cache 的断点。

只读分析，不改业务代码。做法：
1. 从主日志抓每条 `[Native Tools] ... N tools ... schema_chars=C` 的时间与规模；
2. 从 prompt_cache_stats.log 抓每条 deepseek 请求的 prompt/hit/miss；
3. 按时间对齐（取请求前最近一条工具日志），比较「工具集与上一请求相同」
   和「工具集变了」两组请求的命中率。

若两组差异显著，说明工具 schema 被序列化进了可缓存前缀的中段 ——
它一变，后面（历史）就全部失配。
"""

from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_LOG = PROJECT_ROOT / "logs" / "prompt_cache_stats.log"
MAIN_LOG_DIR = PROJECT_ROOT / "logs" / "2026" / "9"

TOOL_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\].*?"
    r"\[Native Tools\].*?(?:Registered|注册)\s*(?P<n>\d+)\s*(?:tools|个工具).*?"
    r"schema_chars=(?P<chars>\d+)"
)

DAY_START = "2026-09-18"


def load_tool_events():
    events = []
    if not MAIN_LOG_DIR.exists():
        return events
    for path in sorted(MAIN_LOG_DIR.rglob("xiaoyou_main.log")):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = TOOL_RE.match(line.strip())
            if not m:
                continue
            try:
                when = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            events.append((when, int(m.group("n")), int(m.group("chars"))))
    events.sort(key=lambda item: item[0])
    return events


def load_cache_rows():
    rows = []
    if not CACHE_LOG.exists():
        return rows
    for line in CACHE_LOG.read_text(encoding="utf-8").splitlines():
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
        # 主日志时间戳是本地朴素时间，缓存日志带时区；统一成朴素时间再对齐
        if when.tzinfo is not None:
            when = when.replace(tzinfo=None)
        rows.append(
            {
                "when": when,
                "hit": int(row.get("hit_tokens") or 0),
                "miss": int(row.get("miss_tokens") or 0),
                "prompt": int(row.get("prompt_tokens") or 0),
            }
        )
    rows.sort(key=lambda item: item["when"])
    return rows


def nearest_tool(events, when: datetime, window: timedelta):
    """取请求前最近一条工具日志；超出窗口则视为未知。"""
    best = None
    for ev_when, count, chars in events:
        delta = when - ev_when
        if delta < timedelta(0):
            break
        if delta > window:
            continue
        best = (count, chars)
    return best


def main():
    events = load_tool_events()
    rows = load_cache_rows()
    print(f"▶ 工具日志 {len(events)} 条，缓存记录 {len(rows)} 条")

    if not events:
        print("主日志里没有 [Native Tools] 记录，无法对齐")
        return
    if not rows:
        print("缓存日志里没有 deepseek 记录")
        return

    # 工具规模分布
    counts = {}
    for _, n, chars in events:
        counts.setdefault(n, []).append(chars)
    print("\n[1] 工具集规模分布（按请求计数）")
    for n in sorted(counts):
        sizes = counts[n]
        print(f"  {n:>2} 个工具: {len(sizes):>4} 次，"
              f"schema_chars 中位 {int(statistics.median(sizes))}")

    # 对齐
    window = timedelta(seconds=90)
    aligned = []
    for row in rows:
        found = nearest_tool(events, row["when"], window)
        if found is None:
            continue
        row["tools"], row["schema_chars"] = found
        aligned.append(row)
    print(f"\n[2] 成功对齐 {len(aligned)}/{len(rows)} 条（窗口 90s）")

    if not aligned:
        return

    # 分组：工具集相对上一条是否变化
    same, changed = [], []
    prev = None
    for row in aligned:
        if prev is not None:
            key_now = (row["tools"], row["schema_chars"])
            key_prev = (prev["tools"], prev["schema_chars"])
            (same if key_now == key_prev else changed).append(row)
        prev = row

    def summarize(name, group):
        if not group:
            print(f"  {name}: 无样本")
            return
        weighted = sum(r["hit"] for r in group) / sum(r["prompt"] for r in group)
        ratios = [r["hit"] / r["prompt"] for r in group if r["prompt"]]
        at_floor = sum(1 for r in group if r["hit"] <= 3584 + 384)
        print(
            f"  {name}: n={len(group):>3}  加权命中 {weighted*100:5.1f}%  "
            f"中位命中率 {statistics.median(ratios)*100:5.1f}%  "
            f"钉底座 {at_floor}/{len(group)} ({at_floor/len(group)*100:.0f}%)"
        )

    print("\n[3] 按「工具集相对上一请求是否变化」分组")
    summarize("工具集不变", same)
    summarize("工具集变了", changed)

    # 再按工具个数分组
    print("\n[4] 按工具个数分组（看 schema 大小与命中的关系）")
    by_count = {}
    for row in aligned:
        by_count.setdefault(row["tools"], []).append(row)
    for n in sorted(by_count):
        group = by_count[n]
        weighted = sum(r["hit"] for r in group) / sum(r["prompt"] for r in group)
        print(f"  {n:>2} 个工具: n={len(group):>3}  加权命中 {weighted*100:5.1f}%")

    print("\n结果: 分析完成（只读）")


if __name__ == "__main__":
    main()
