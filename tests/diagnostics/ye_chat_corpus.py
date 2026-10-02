"""Ye真实聊天记录的语料分析（只读）。

数据源：companion_data/ye_data/chat_history/YYYY/MM/DD/主线对话/*.jsonl
用途：用真实对话（不是日记、不是人设文件）统计她的实际说话方式，
为"人设 vs 实际"的对照提供基准。

运行：
    venv_cpu\\Scripts\\python.exe tests/diagnostics/ye_chat_corpus.py [天数]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_ROOT = PROJECT_ROOT / "companion_data" / "ye_data" / "chat_history"

# 心想前缀：（心想：xxx）\n\n 正文
THOUGHT_RE = re.compile(r"^（心想[:：]\s*(.*?)）\s*", re.DOTALL)
# 媒体/标签清理，统计"纯文字"长度
TAG_RE = re.compile(r"\[(?:MEME|IMG|BM|VIDEO|VOICE|GIF|WEBM|DICE|DELAY)[^\]]*\]")


def _iter_events():
    files = sorted(HISTORY_ROOT.rglob("*.jsonl"))
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if isinstance(event, dict):
                yield path, event


def _split_thought(content: str) -> tuple[str, str]:
    """返回 (心想内容, 去掉心想后的正文)。"""
    match = THOUGHT_RE.match(content or "")
    if not match:
        return "", (content or "").strip()
    return match.group(1).strip(), (content or "")[match.end():].strip()


def _clean(text: str) -> str:
    return TAG_RE.sub("", text or "").strip()


def main() -> int:
    limit_days = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    assistant_texts: list[tuple[str, str]] = []  # (created_at, 正文)
    thoughts: list[str] = []
    user_texts: list[tuple[str, str]] = []
    files_seen: set[Path] = set()

    for path, event in _iter_events():
        files_seen.add(path)
        role = str(event.get("role") or "")
        content = str(event.get("content") or "")
        created = str(event.get("created_at") or "")
        if role == "assistant":
            thought, body = _split_thought(content)
            if thought:
                thoughts.append(thought)
            body = _clean(body)
            if body:
                assistant_texts.append((created, body))
        elif role == "user":
            body = _clean(content)
            if body:
                user_texts.append((created, body))

    if limit_days:
        dates = sorted({c[:10] for c, _ in assistant_texts})[-limit_days:]
        keep = set(dates)
        assistant_texts = [(c, t) for c, t in assistant_texts if c[:10] in keep]
        user_texts = [(c, t) for c, t in user_texts if c[:10] in keep]

    lengths = [len(t) for _, t in assistant_texts]
    user_lengths = [len(t) for _, t in user_texts]

    print("=" * 78)
    print("Ye真实聊天记录语料分析（只读）")
    print("=" * 78)
    print(f"数据文件: {len(files_seen)} 个 jsonl")
    print(f"Ye消息: {len(assistant_texts)} 条    Master消息: {len(user_texts)} 条")
    if lengths:
        print(f"Ye长度: 平均 {statistics.mean(lengths):.1f} 字，中位 {statistics.median(lengths):.0f}，"
              f"最长 {max(lengths)} 字")
        buckets = [(0, 5), (6, 10), (11, 20), (21, 40), (41, 80), (81, 10**6)]
        print("长度分布: " + "  ".join(
            f"{lo}-{hi if hi < 10**6 else '+'}字 {sum(1 for n in lengths if lo <= n <= hi)}条"
            for lo, hi in buckets
        ))
    if user_lengths:
        print(f"Master长度: 平均 {statistics.mean(user_lengths):.1f} 字，中位 {statistics.median(user_lengths):.0f}")

    if thoughts:
        print()
        print(f"【心想】共 {len(thoughts)} 条，平均 {statistics.mean([len(t) for t in thoughts]):.1f} 字")
        print("  样例（最近 5 条）:")
        for t in thoughts[-5:]:
            print(f"    {t[:110]}")

    all_text = "\n".join(t for _, t in assistant_texts)
    print()
    print("【用词频率】")
    for word in ("主人", "就是", "就", "真的", "嘻嘻", "哈哈", "嗯", "不是", "没有", "好像", "可能", "有点"):
        count = all_text.count(word)
        per_1000 = count / max(len(all_text), 1) * 1000
        print(f"  {word:<6} {count:>5} 次   每千字 {per_1000:>6.1f}")

    print()
    print("【句首呼语统计】")
    head_calls = [t for _, t in assistant_texts if t.startswith("主人")]
    print(f"  以「主人」开头: {len(head_calls)} 条 / 共 {len(assistant_texts)} 条"
          f"（{len(head_calls) / max(len(assistant_texts), 1) * 100:.1f}%）")

    print()
    print("【最长回复 Top 8】")
    for created, text in sorted(assistant_texts, key=lambda x: len(x[1]), reverse=True)[:8]:
        print(f"  [{created}] {len(text)} 字")
        print(f"    {text[:300]}")
    print()
    print("【最短回复 Top 8】")
    for created, text in sorted(assistant_texts, key=lambda x: len(x[1]))[:8]:
        print(f"  [{created}] {len(text)} 字: {text[:60]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
