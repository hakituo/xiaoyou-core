"""诊断 AI 精力显示问题：检查运行时 energy 值和对话历史污染。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def check_runtime_energy() -> None:
    """检查运行时 life_sim_state 里的 energy 值。"""
    print("\n[1] 检查运行时 energy 值")
    try:
        from core.services.life_simulation.service import get_life_simulation_service

        sim = get_life_simulation_service()
        state = sim.get_state()
        life = state.get("life", {})
        energy = life.get("energy")
        print(f"  life_sim_state.life.energy = {energy}")
        print(f"  today_sleep_impact_level = {life.get('today_sleep_impact_level')}")
        print(f"  sleep_inertia_score = {life.get('sleep_inertia_score')}")
        print(f"  nightmare_level = {life.get('nightmare_level')}")
        print(f"  activity = {state.get('activity')}")

        # 构建 prompt 文本看 energy 显示
        from core.agents.chat_agent_components.persona_system.prompt import build_food_context_text

        food_text = build_food_context_text(life)
        print(f"\n  build_food_context_text 输出:")
        for line in food_text.strip().split("\n"):
            print(f"    {line}")
    except Exception as exc:
        print(f"  ❌ 检查失败: {type(exc).__name__}: {exc}")


def check_chat_history_energy() -> None:
    """检查最近对话历史里是否有'精力'相关说法。"""
    print("\n[2] 检查对话历史里的'精力'说法")
    try:
        from core.services.chat_history_store import get_chat_history_store

        store = get_chat_history_store()
        # 查最近 50 条对话
        events = store.list_conversation_events("10001", limit=50, roles=["user", "assistant"])
        energy_mentions = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            content = str(ev.get("content") or "")
            if any(kw in content for kw in ["精力", "energy", "累", "困", "没力气"]):
                ts = float(ev.get("timestamp", 0) or 0)
                role = ev.get("role", "?")
                # 截取前 80 字
                preview = content[:80].replace("\n", " ")
                energy_mentions.append((ts, role, preview))

        if not energy_mentions:
            print("  (最近 50 条对话里没有提到精力相关内容)")
        else:
            print(f"  找到 {len(energy_mentions)} 条提到精力的对话:")
            for ts, role, preview in energy_mentions[-10:]:  # 只看最后 10 条
                from datetime import datetime

                time_str = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts > 0 else "??"
                print(f"    [{time_str}] {role}: {preview}...")
    except Exception as exc:
        print(f"  ❌ 检查失败: {type(exc).__name__}: {exc}")


def check_short_term_memory() -> None:
    """检查 short_term_memory 里是否有'精力0'的残留。"""
    print("\n[3] 检查 short_term_memory 里的'精力'残留")
    try:
        from memory.weighted_memory_manager import WeightedMemoryManager

        mm = WeightedMemoryManager("10001")
        with mm.lock:
            memories = list(mm.short_term_memory)

        energy_memories = []
        for mem in memories:
            content = str(mem.get("content") or "")
            if any(kw in content for kw in ["精力", "energy", "累", "困", "没力气"]):
                ts = float(mem.get("timestamp", 0) or 0)
                preview = content[:80].replace("\n", " ")
                energy_memories.append((ts, preview))

        if not energy_memories:
            print(f"  (short_term_memory 里 {len(memories)} 条记忆，没有提到精力)")
        else:
            print(f"  找到 {len(energy_memories)} 条提到精力的记忆:")
            for ts, preview in energy_memories[-5:]:
                from datetime import datetime

                time_str = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts > 0 else "??"
                print(f"    [{time_str}] {preview}...")
    except Exception as exc:
        print(f"  ❌ 检查失败: {type(exc).__name__}: {exc}")


def main() -> int:
    print("=" * 70)
    print("诊断 AI 精力显示问题")
    print("=" * 70)

    check_runtime_energy()
    check_chat_history_energy()
    check_short_term_memory()

    print("\n" + "=" * 70)
    print("诊断完成。如果运行时 energy 正常但 AI 仍说精力低，")
    print("说明是对话历史污染，需要清理历史或强化 prompt 注入。")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
