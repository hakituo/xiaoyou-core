"""导出Ye真实聊天记录中的连续对话片段（只读，供人读）。

用途：按时间顺序打印「Master / Ye」的一来一回，用于人工比对
"人设驱动出来的回复" 与 "她真实怎么回"。

运行：
    venv_cpu\\Scripts\\python.exe tests/diagnostics/ye_chat_snippets.py [起始日] [结束日]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_ROOT = PROJECT_ROOT / "companion_data" / "ye_data" / "chat_history"

THOUGHT_RE = re.compile(r"^（心想[:：]\s*(.*?)）\s*", re.DOTALL)
TAG_RE = re.compile(r"\[(?:MEME|IMG|BM|VIDEO|VOICE|GIF|WEBM|DICE|DELAY)[^\]]*\]")
# 过滤掉泄漏的推理文本（事件里出现过把推理过程当回复存下来的脏数据）
REASONING_MARKERS = ("用户当前", "我应该", "根据角色", "考虑到用户", "去重规则", "最近的聊天记录显示")


def _clean(text: str) -> tuple[str, str]:
    match = THOUGHT_RE.match(text or "")
    thought = match.group(1).strip() if match else ""
    body = (text or "")[match.end():] if match else (text or "")
    return thought, TAG_RE.sub("", body).strip()


def _events_for(day: str):
    folder = HISTORY_ROOT / day[:4] / day[5:7] / day[8:10] / "主线对话"
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if isinstance(event, dict):
                rows.append(event)
    rows.sort(key=lambda e: e.get("timestamp") or 0)
    return rows


def main() -> int:
    days = sys.argv[1:] or ["2026-09-20", "2026-09-21", "2026-09-22"]
    for day in days:
        events = _events_for(day)
        if not events:
            continue
        print("=" * 78)
        print(f"【{day}】")
        print("=" * 78)
        for event in events:
            role = str(event.get("role") or "")
            content = str(event.get("content") or "")
            stamp = str(event.get("created_at") or "")[11:16]
            proactive = (event.get("metadata") or {}).get("is_proactive")
            thought, body = _clean(content)
            if not body:
                continue
            # 跳过把推理过程写进回复的脏数据
            if len(body) > 120 and any(marker in body for marker in REASONING_MARKERS):
                print(f"{stamp}  [{role}] <已跳过：疑似推理泄漏 {len(body)} 字>")
                continue
            who = "Ye" if role == "assistant" else "Master"
            flag = "（主动）" if proactive else ""
            if thought:
                print(f"{stamp}  {who}{flag}：{body}   ←心想: {thought[:60]}")
            else:
                print(f"{stamp}  {who}{flag}：{body}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
