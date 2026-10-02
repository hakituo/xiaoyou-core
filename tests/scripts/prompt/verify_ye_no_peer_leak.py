"""
验证脚本：ye 人设不再被注入其它角色的硬编码 peer 名（“七濑 Aveline / Aveline”），
且 voice_ye.json 已压缩。

背景：
- 双/多 QQ 模式下 message_peer 被无差别启用，且 get_tool_injection 里 peer 名
  硬编码为“七濑 Aveline”，导致 ye 的 prompt 每轮都被注入该角色名，模型因而“串角色”
  说出人设里根本没有的“Aveline”。
- 修复：peer 名改为按当前角色真实互聊对象动态解析（personas 权威注册表），
  无 peer 角色（ye/rushuang/yeye）不再注入互聊引导；message_peer also 仅在
  当前角色有 peer 时进入激活列表。

运行：在 venv_core / venv_cpu 下执行本脚本。
"""

import io
import json
import sys

sys.path.insert(0, ".")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main() -> None:
    from core.agents.chat_agent_components.persona_system.prompt.context_gathering import (
        _resolve_peer_names,
        get_tool_injection,
    )
    from core.services.dual_role.personas import get_peer_role_ids

    # ---- 1. peer 名动态解析：ye 无 peer，aveline/ling 有正确 peer ----
    ye_peers = _resolve_peer_names("core_ye.json")
    check("ye 不再解析出任何互聊对象", ye_peers == [], f"got={ye_peers}")

    aveline_peers = _resolve_peer_names("core_aveline.json")
    check("aveline 解析到的 peer 名是Ling", aveline_peers == ["Ling"], f"got={aveline_peers}")

    ling_peers = _resolve_peer_names("core_ling.json")
    check("ling 解析到的 peer 是Aveline", "Aveline" in "".join(ling_peers), f"got={ling_peers}")

    # ---- 2. 判定“当前角色有 peer”谓词（context_persona 门控复用同一来源）----
    check("personas 权威表里 ye 无 peer", get_peer_role_ids("ye") == [])
    check("personas 权威表里 aveline 有 peer", get_peer_role_ids("aveline") != [])

    # message_peer 在激活列表里的情况：
    #  - ye：不应注入互聊引导（不含“Aveline”）
    #  - aveline：应注入，且 peer 名是Ling
    tools_with_peer = ["message_peer", "search_chat_history"]
    ye_inj = get_tool_injection(None, None, list(tools_with_peer), persona_filename="core_ye.json") or ""
    check("ye 的互聊引导注入不含『Aveline』", "Aveline" not in ye_inj and "七濑" not in ye_inj, ye_inj[:120])
    check("ye 的互聊引导注入不含『Ling』", "Ling" not in ye_inj, ye_inj[:120])

    aveline_inj = get_tool_injection(None, None, list(tools_with_peer), persona_filename="core_aveline.json") or ""
    check("aveline 的互聊引导注入含『Ling』", "Ling" in aveline_inj, aveline_inj[:160])

    # 无 message_peer 时（含 ye 常规轮次）不应出现任何 peer 引导
    no_peer_inj = get_tool_injection(None, None, [], persona_filename="core_ye.json") or ""
    check("不激活 message_peer 时无互聊引导", "互聊" not in no_peer_inj and "Aveline" not in no_peer_inj)

    # ---- 3. voice_ye.json 主对话投影已压缩且结构完整 ----
    from pathlib import Path

    vpath = Path("core/character/configs/ye/voice_ye.json")
    voice_text = io.open(vpath, encoding="utf-8").read()
    voice = json.loads(voice_text)
    from core.agents.chat_agent_components.persona_system.prompt.ye_layered_prompt import _prompt_payload
    projected_chars = len(json.dumps(_prompt_payload(voice), ensure_ascii=False))
    # Active Care 示例与主对话共用角色文件，但不会进入普通主对话投影。
    check(
        "voice_ye 主对话投影体积已下降",
        projected_chars < 3400,
        f"raw_chars={len(voice_text)}, projected_chars={projected_chars}",
    )
    required_blocks = {
        "baseline", "attention", "response_instinct", "rhythm",
        "brevity_guard", "personality_in_speech", "relationship_expression",
        "emotion_expression", "micro_examples", "active_care",
    }
    check("voice_ye.json 结构键完整", required_blocks.issubset(voice.keys()))
    check("voice_ye.json 微事例已精简", len(voice.get("micro_examples") or []) <= 7,
          f"n={len(voice.get('micro_examples') or [])}")

    # ---- 4. ye 分层静态 system prompt 体积随 voice 压缩下降 ----
    from core.agents.chat_agent_components.persona_system.prompt import ye_layered_prompt
    layers = ye_layered_prompt.build_ye_persona_layers(
        persona_filename="core_ye.json", message="",
    )
    static_len = len(layers.static_prompt) if layers else 0
    check("ye 分层静态 system prompt 小于 7600", layers is not None and static_len < 7600,
          f"static_len={static_len}")

    print()
    if FAILURES:
        print(f"验证未通过，共 {len(FAILURES)} 项失败：")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("全部验证通过 ✓")


if __name__ == "__main__":
    main()
