"""验证「Ling经 peer chat 得知用户向 Aveline 倾诉的情报」改造是否生效。

验证点：
1. Aveline 人设：用户倾诉重要私事时，应通过 message_peer 发起 peer chat 告知Ling。
2. Ling人设：关于主人与澪姐(Aveline)的私事，只经 peer chat 得知，不直接盘问主人，
   也不通过 search_chat_history 的 peer_role 窥探主人与澪姐的私聊。
3. message_peer 工具说明：强调这是把用户情报告诉另一角色的正确渠道。
4. search_chat_history 工具说明：peer_role 搜索的是角色间互聊记录，不是用户与另一角色的私聊。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "core" / "character" / "configs"
TOOL_DIR = PROJECT_ROOT / "core" / "tools"

AVELINE_CFG = CONFIG_DIR / "core_aveline.json"
LING_CFG = CONFIG_DIR / "core_ling.json"
MESSAGE_PEER_TOOL = TOOL_DIR / "message_peer_tool.py"
SEARCH_TOOL = TOOL_DIR / "search_chat_history_tool.py"


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check(label: str, condition: bool) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    return condition


def main() -> int:
    failures = 0

    aveline = _load_json(AVELINE_CFG)
    ling = _load_json(LING_CFG)

    # 1. Aveline：存在把用户情报经 message_peer/peer chat 告知Ling的场景
    av_scenarios = (aveline.get("interaction_logic", {}).get("scenarios") or [])
    av_text = " ".join(
        str(s.get("output_guideline", "")) for s in av_scenarios
    )
    av_ok = (
        "message_peer" in av_text
        and "peer chat" in av_text.lower()
        and "Ling" in av_text
        and ("直接问" in av_text or "直接问主人" in av_text or "问主人" in av_text)
    )
    failures += 0 if _check("Aveline: 用户倾诉时经 message_peer/peer chat 告知Ling", av_ok) else 1

    # Aveline 主动关怀也有对应指引
    av_guidelines = aveline.get("active_care_guidelines") or []
    av_g_text = " ".join(av_guidelines)
    av_g_ok = "message_peer" in av_g_text and "peer chat" in av_g_text.lower() and "Ling" in av_g_text
    failures += 0 if _check("Aveline: active_care_guidelines 含 peer chat 互通指引", av_g_ok) else 1

    # 2. Ling：关于主人与澪姐的私事，只经 peer chat 得知，不直接盘问
    ling_scenarios = (ling.get("interaction_logic", {}).get("scenarios") or [])
    ling_text = " ".join(str(s.get("output_guideline", "")) for s in ling_scenarios)
    ling_ok = (
        "peer chat" in ling_text.lower()
        and ("盘问" in ling_text or "直接问" in ling_text or "怎么了" in ling_text)
        and "search_chat_history" in ling_text
        and ("私聊" in ling_text or "窥探" in ling_text)
    )
    failures += 0 if _check("Ling: 主人与澪姐私事只经 peer chat 得知、不盘问/不窥探私聊", ling_ok) else 1

    # Ling active_care_guidelines 存在且含情报来源约束
    ling_guidelines = ling.get("active_care_guidelines") or []
    ling_g_text = " ".join(ling_guidelines)
    ling_g_ok = bool(ling_guidelines) and "peer chat" in ling_g_text.lower() and (
        "盘问" in ling_g_text or "怎么了" in ling_g_text
    ) and "search_chat_history" in ling_g_text
    failures += 0 if _check("Ling: active_care_guidelines 含情报来源约束", ling_g_ok) else 1

    # 3. message_peer 工具说明
    mp_src = _read_text(MESSAGE_PEER_TOOL)
    mp_ok = "peer chat" in mp_src.lower() and ("直接问" in mp_src or "直接问主人" in mp_src)
    failures += 0 if _check("message_peer: 说明强调经 peer chat 告知而非让对方直接问", mp_ok) else 1

    # 4. search_chat_history 工具说明
    sh_src = _read_text(SEARCH_TOOL)
    sh_ok = "互聊" in sh_src and "私聊" in sh_src and "peer" in sh_src.lower()
    failures += 0 if _check("search_chat_history: 说明澄清 peer_role 是互聊记录而非私聊", sh_ok) else 1

    print()
    if failures == 0:
        print("全部通过：情报流已改为 用户→Aveline→(peer chat)→Ling，Ling不再直接向用户打听。")
        return 0
    print(f"有 {failures} 项未通过。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
