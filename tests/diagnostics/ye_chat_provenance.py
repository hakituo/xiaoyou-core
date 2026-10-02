"""核查Ye聊天记录里各条事件的来源标记（只读）。

用途：区分「真实运行产生的记录」与「人工写入 / 导入 / 播种」的内容——
两者的 metadata 与用户侧特征不同，混用会把编造语料当成真实语料分析。

运行：
    venv_cpu\\Scripts\\python.exe tests/diagnostics/ye_chat_provenance.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_ROOT = PROJECT_ROOT / "companion_data" / "ye_data" / "chat_history"


def main() -> int:
    per_day = defaultdict(Counter)
    meta_keys = Counter()
    event_types = Counter()
    sources = Counter()
    user_ids = Counter()
    samples: dict[str, list[dict]] = defaultdict(list)

    files = sorted(HISTORY_ROOT.rglob("*.jsonl"))
    for path in files:
        day = "/".join(path.parts[-5:-3])
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
            for key in metadata:
                meta_keys[key] += 1
            event_types[str(event.get("event_type") or "-")] += 1
            source = str(metadata.get("source") or metadata.get("origin") or "-")
            sources[source] += 1
            uid = str(event.get("user_id") or metadata.get("user_id") or "-")
            user_ids[uid] += 1
            per_day[day][source] += 1
            if len(samples[source]) < 2:
                samples[source].append({
                    "file": path.name,
                    "role": event.get("role"),
                    "content": str(event.get("content") or "")[:150],
                    "metadata": metadata,
                    "user_id": uid,
                })

    print("=" * 78)
    print("Ye聊天记录来源核查（只读）")
    print("=" * 78)
    print(f"jsonl 文件 {len(files)} 个")
    print()
    print("【metadata 字段出现次数】")
    for key, count in meta_keys.most_common():
        print(f"  {key:<20} {count}")
    print()
    print("【event_type 分布】")
    for key, count in event_types.most_common():
        print(f"  {key:<24} {count}")
    print()
    print("【source / origin 分布】")
    for key, count in sources.most_common():
        print(f"  {key:<24} {count}")
    print()
    print("【user_id 分布】")
    for key, count in user_ids.most_common(10):
        print(f"  {key:<28} {count}")
    print()
    print("【逐日 source 构成（前 30 天）】")
    for day in sorted(per_day)[:30]:
        items = " ".join(f"{k}={v}" for k, v in per_day[day].most_common())
        print(f"  {day:<14} {items}")
    print()
    print("【各 source 样例】")
    for source, rows in samples.items():
        print(f"  --- source={source} ---")
        for row in rows:
            print(f"    file={row['file']} role={row['role']} user_id={row['user_id']}")
            print(f"    meta={row['metadata']}")
            print(f"    content={row['content']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
