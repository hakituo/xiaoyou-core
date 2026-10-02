"""按来源分组比较Ye语料：导入的合成转录 vs 运行时真实产物（只读）。

背景：chat_history 里混着两类内容——
  - source=dated_chat_transcript_import / source_kind=synthetic_user_authorized
    → 人工授权写入的合成转录（imported=True，带 source_sha256 / shifted_date）
  - source=chat_agent / active_care
    → 系统真实运行时产生的事件（带 model_hint）
混用会把编造语料当作"她真实怎么说话"的基准。

运行：
    venv_cpu\\Scripts\\python.exe tests/diagnostics/ye_source_compare.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_ROOT = PROJECT_ROOT / "companion_data" / "ye_data" / "chat_history"

TAG_RE = re.compile(r"\[(?:MEME|IMG|BM|VIDEO|VOICE|GIF|WEBM|DICE|DELAY)[^\]]*\]")
THOUGHT_RE = re.compile(r"^（心想[:：]\s*(.*?)）\s*", re.DOTALL)
REASONING_MARKERS = ("用户当前", "我应该", "根据角色", "考虑到用户", "去重规则", "最近的聊天记录显示")

SYNTHETIC = "dated_chat_transcript_import"


def _clean(text: str) -> str:
    match = THOUGHT_RE.match(text or "")
    body = (text or "")[match.end():] if match else (text or "")
    return TAG_RE.sub("", body).strip()


def _merge_consecutive(turns: list[tuple[str, int]], gap_seconds: int = 180) -> list[dict]:
    """把同一方在短时间内的连续消息合并为一次发言（含分条数）。"""
    blocks: list[dict] = []
    for role, ts, text in turns:
        if blocks and blocks[-1]["role"] == role and ts - blocks[-1]["last_ts"] <= gap_seconds:
            blocks[-1]["parts"].append(text)
            blocks[-1]["last_ts"] = ts
        else:
            blocks.append({"role": role, "parts": [text], "last_ts": ts})
    return blocks


def main() -> int:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(HISTORY_ROOT.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
            source = str(metadata.get("source") or "unknown")
            role = str(event.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            text = _clean(str(event.get("content") or ""))
            if not text:
                continue
            if len(text) > 120 and any(m in text for m in REASONING_MARKERS):
                continue  # 推理泄漏，不代表她的表达
            buckets[source].append({
                "role": role,
                "ts": float(event.get("timestamp") or 0.0),
                "text": text,
            })

    for source in sorted(buckets, key=lambda s: -len(buckets[s])):
        rows = buckets[source]
        rows.sort(key=lambda r: r["ts"])
        blocks = _merge_consecutive([(r["role"], r["ts"], r["text"]) for r in rows])
        speaker_blocks = [b for b in blocks if b["role"] == "assistant"]
        parts_per_block = [len(b["parts"]) for b in speaker_blocks]
        part_lengths = [len(p) for b in speaker_blocks for p in b["parts"]]
        block_lengths = [sum(len(p) for p in b["parts"]) for b in speaker_blocks]
        all_text = "\n".join(r["text"] for r in rows if r["role"] == "assistant")
        total = max(len(all_text), 1)

        print("=" * 78)
        label = "合成转录（人工写入）" if source == SYNTHETIC else "运行时产物"
        print(f"source = {source}    [{label}]")
        print("=" * 78)
        print(f"  总事件 {len(rows)}    其中Ye {len(speaker_blocks)} 次发言 / {len(part_lengths)} 条消息")
        if block_lengths:
            print(f"  单条消息长度: 平均 {statistics.mean(part_lengths):.1f} 字，中位 {statistics.median(part_lengths):.0f}，最长 {max(part_lengths)}")
            print(f"  单次发言总长: 平均 {statistics.mean(block_lengths):.1f} 字，中位 {statistics.median(block_lengths):.0f}")
        if parts_per_block:
            dist = Counter(min(n, 5) for n in parts_per_block)
            print("  一轮分几条: " + "  ".join(
                f"{k}{'+' if k == 5 else ''}条 {dist.get(k, 0)}次" for k in sorted(dist)
            ))
            print(f"  平均一轮 {statistics.mean(parts_per_block):.2f} 条")
        head_calls = [b for b in speaker_blocks if b["parts"] and b["parts"][0].startswith("主人")]
        print(f"  句首「主人」: {len(head_calls)} 次发言（{len(head_calls) / max(len(speaker_blocks), 1) * 100:.1f}%）")
        print("  词频（每千字）:")
        for word in ("主人", "就", "真的", "嗯", "……", "不是", "没有", "有点", "嘻嘻"):
            count = all_text.count(word)
            print(f"    {word:<6} {count:>5} 次   {count / total * 1000:>6.1f}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
