#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：Ling最近的主动消息（active care）有没有进主对话上下文。

复现路径与线上一致：
1. 读短期记忆（scope=ling），模拟 WeightedMemoryManager.get_history 的输出结构；
2. 走 sanitize_history_messages（补时间戳前缀 / [主动消息] 标记）；
3. 走 apply_cloud_history_budget（云端相关性抽样）；
4. 走 _build_active_care_handoff_context，看是否判定为「用户正在回应主动消息」。

用法：venv_core/Scripts/python.exe tests/scripts/diagnose/diag_ling_proactive_context.py
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.agents.chat_agent_components.context_budget.budget_apply import (  # noqa: E402
    apply_cloud_history_budget,
)
from core.agents.chat_agent_components.context_budget.history_fetch import (  # noqa: E402
    sanitize_history_messages,
)
from core.agents.chat_agent_components.persona_system.prompt.assembler import (  # noqa: E402
    _build_active_care_handoff_context,
)

SHORT_TERM = ROOT / "companion_data/ling_data/memories/short_term/shared__scope__ling_short.json"


def load_history(scope: str = "cloud"):
    """按 WeightedMemoryManager.get_history 的裁剪逻辑还原喂给 LLM 的历史。"""
    records = json.loads(SHORT_TERM.read_text(encoding="utf-8"))
    history = []
    for m in records:
        scopes = m.get("scopes")
        if scope and scopes and scope not in scopes:
            continue
        role = m.get("role", m.get("source", "user"))
        if role not in ("system", "user", "assistant", "tool"):
            role = "system"
        entry = {
            "role": role,
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp", 0),
        }
        if m.get("category"):
            entry["category"] = m["category"]
        if role == "assistant":
            meta = m.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("is_proactive"):
                entry["is_proactive"] = True
        history.append(entry)
    return history


def main():
    raw = load_history()
    print("=" * 70)
    print("[1] 短期记忆里 role=assistant 的主动消息是否带 is_proactive 标记")
    print("=" * 70)
    for m in raw:
        if m.get("is_proactive"):
            print(f"  OK  ts={m['timestamp']:.0f} content={m['content'][:40]}")

    sanitized = sanitize_history_messages(raw, persona_filename="core_ling")
    print()
    print("=" * 70)
    print("[2] sanitize 之后（LLM 实际看到的历史）")
    print("=" * 70)
    for m in sanitized:
        print(f"  {m.get('role'):9s} | {str(m.get('content'))[:90]}")

    has_proactive, last_content, is_replying = _build_active_care_handoff_context(sanitized)
    print()
    print("=" * 70)
    print("[3] 主动消息衔接判定")
    print("=" * 70)
    print(f"  has_proactive_in_history = {has_proactive}")
    print(f"  is_replying_to_proactive = {is_replying}")
    print(f"  last_proactive_content   = {last_content}")

    for query in ("？", "你发的啥消息"):
        budgeted = apply_cloud_history_budget(sanitized, query, user_id="web_role_ling")
        print()
        print("=" * 70)
        print(f"[4] 云端预算后（query={query!r}）共 {len(budgeted)} 条")
        print("=" * 70)
        for m in budgeted:
            print(f"  {m.get('role'):9s} | {str(m.get('content'))[:90]}")
        _, _, replying = _build_active_care_handoff_context(budgeted)
        print(f"  -> is_replying_to_proactive = {replying}")

    print()
    print("=" * 70)
    print("[5] 逐轮还原：每一轮用户消息发出时，衔接提示走哪个分支")
    print("=" * 70)
    # 第一轮：用户刚发「？」，历史截止到主动消息
    turn1 = sanitized[: sanitized.index(
        next(m for m in sanitized if m.get("role") == "user" and m["content"].endswith("？"))
    )]
    _, last1, reply1 = _build_active_care_handoff_context(turn1)
    print(f"  第 1 轮（用户发「？」）: is_replying_to_proactive={reply1}")
    print(f"     上一条主动消息 = {last1}")
    print("     提示分支 = " + ("正向（用户大概率在回应主动消息）" if reply1 else "反向（别提主动消息）"))

    # 第二轮：用户发「你发的啥消息」，历史里已经有Ling自己的一条回复
    turn2 = sanitized[: sanitized.index(
        next(m for m in sanitized if m.get("role") == "user" and "你发的啥消息" in str(m.get("content")))
    )]
    _, last2, reply2 = _build_active_care_handoff_context(turn2)
    print(f"  第 2 轮（用户发「你发的啥消息」）: is_replying_to_proactive={reply2}")
    print(f"     上一条主动消息 = {last2}")
    print("     提示分支 = " + ("正向（用户大概率在回应主动消息）" if reply2 else "反向（别提主动消息）"))



if __name__ == "__main__":
    main()
