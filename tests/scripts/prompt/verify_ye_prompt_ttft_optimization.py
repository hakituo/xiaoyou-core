"""
验证脚本：ye 分层 prompt 的 TTFT 优化是否生效。

覆盖项：
1. knowledge 递归检索并遵守工作集预算，追问复用已准入资料。
2. _knowledge_prompt_payload 只投影 topic+facts，丢弃 usage/inference_scope 元指导。
3. CURRENT STATE 注入会剥离 runtime 状态的 source/updated_at/confidence 元数据，
   只留模型生成需要的值（标量对象退化为纯 value）。
4. 静态人设层体积下降（voice_ye.json / policy），且关键结构块完整保留。

运行：在 venv_core / venv_cpu 下执行本脚本。
"""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main() -> None:
    from core.agents.chat_agent_components.persona_system.prompt.ye_layered_prompt import (
        _knowledge_prompt_payload,
        _project_state_for_prompt,
        build_ye_persona_layers,
    )

    root = Path("core/character/configs/ye")

    # ---- 1. knowledge 遵守通用预算，实验资料有独立权威来源 ----
    empty_runtime = {"character": "ye", "state": {}}
    multi = build_ye_persona_layers(
        persona_filename="core_ye.json",
        message="你本科舍友顾南乔现在还联系吗",
        runtime_state=empty_runtime,
    )
    from core.agents.chat_agent_components.persona_system.prompt.context_engine import context_config
    cfg = context_config()
    check("资料数量受预算限制", multi is not None and 0 < len(multi.knowledge_topics) <= cfg["max_chunks"],
          f"topics={multi.knowledge_topics if multi else None}")

    single = build_ye_persona_layers(
        persona_filename="core_ye.json",
        message="实验结果怎么样",
        runtime_state=empty_runtime,
    )
    check("单文档命中正常", single is not None and "lab_work" in single.knowledge_topics,
          f"topics={single.knowledge_topics if single else None}")

    # ---- 2. knowledge payload 只投影 topic+facts ----
    relationships = json.load(io.open(root / "knowledge/relationships.json", encoding="utf-8"))
    payload = _knowledge_prompt_payload(relationships)
    check("knowledge payload 只含 topic/facts", set(payload.keys()) == {"topic", "facts"},
          f"keys={list(payload.keys())}")
    check("knowledge payload 不含 usage/inference_scope",
          "usage" not in payload and "inference_scope" not in payload)

    # ---- 3. runtime 状态元数据剥离 ----
    sample = {
        "location": {"value": "宿舍", "source": "assistant_rule", "updated_at": "2026-09-03", "confidence": 0.9},
        "activity": {"value": "躺着", "source": "user_explicit", "updated_at": "2026-09-03", "confidence": 1.0},
        "active_rules": [
            {
                "type": "borrow", "target": "钥匙", "expires_at": "2026-09-03T18:00:00",
                "source": "user_explicit", "updated_at": "2026-09-03", "confidence": 1.0,
            }
        ],
        "ongoing_interaction": {
            "mode": "ordinary", "label": None, "started_at": None, "state": None,
            "source": "user_explicit", "updated_at": "2026-09-03",
        },
    }
    projected = _project_state_for_prompt(sample)
    flat = json.dumps(projected, ensure_ascii=False)
    check("标量状态对象退化为纯 value", projected.get("location") == "宿舍" and projected.get("activity") == "躺着",
          flat)
    check("runtime 元数据键全部剥离",
          all(key not in flat for key in ("source", "updated_at", "confidence")))
    check("列表项剥离元数据后保留业务字段",
          projected["active_rules"][0] == {"type": "borrow", "target": "钥匙", "expires_at": "2026-09-03T18:00:00"})

    # ---- 4. 主对话实际投影的静态 voice 体积下降且结构完整 ----
    voice_text = io.open(root / "voice_ye.json", encoding="utf-8").read()
    voice = json.loads(voice_text)
    from core.agents.chat_agent_components.persona_system.prompt.ye_layered_prompt import _prompt_payload
    projected_voice_text = json.dumps(_prompt_payload(voice), ensure_ascii=False)
    check(
        "voice_ye 主对话投影体积 < 3400",
        len(projected_voice_text) < 3400,
        f"raw_chars={len(voice_text)}, projected_chars={len(projected_voice_text)}",
    )
    required_blocks = {
        "baseline", "attention", "response_instinct", "rhythm", "brevity_guard",
        "personality_in_speech", "relationship_expression", "emotion_expression",
        "micro_examples", "active_care",
    }
    check("voice_ye.json 结构键完整", required_blocks.issubset(voice.keys()))

    policy_text = io.open(
        Path("core/agents/chat_agent_components/persona_system/prompt/conversation_policy.json"),
        encoding="utf-8",
    ).read()
    policy = json.loads(policy_text)
    check("policy 体积 < 1500", len(policy_text) < 1500, f"chars={len(policy_text)}")
    required_policy = {
        "conversation_model", "response_flow", "continuity", "grounding", "correction_behavior", "output_shape",
    }
    check("policy 结构键完整", required_policy.issubset(policy.keys()))

    # ---- 5. 新契约是完整资料块的预算，而非已废弃的全场景 top-1 字符阈值 ----
    for label, layers in (("multi", multi), ("single", single)):
        check(f"{label} 工作集 token 预算", layers.context_trace["estimated_tokens"] <= cfg["max_tokens"])
    follow = build_ye_persona_layers(persona_filename="core_ye.json", message="你本科哪里读的", runtime_state=empty_runtime, conversation_id="verification")
    again = build_ye_persona_layers(persona_filename="core_ye.json", message="为什么选这个", runtime_state=empty_runtime, conversation_id="verification")
    check("追问保留同一工作集", bool(follow.working_set_prompt) and follow.working_set_prompt == again.working_set_prompt)
    check("不同资料不改变固定层", follow.static_prompt == multi.static_prompt == single.static_prompt)

    print()
    if FAILURES:
        print(f"验证未通过，共 {len(FAILURES)} 项失败：")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("全部验证通过 ✓")


if __name__ == "__main__":
    main()
