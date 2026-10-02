"""验证主动关怀"反查岗"约束已生效

背景（2026-08-30）：线上 active care 记录显示消息稳定收敛成
『我在做X → 突然想到你 → 你在干什么呢』三段式，用户反馈"像催债、像查岗"。
根因是 ROLE_ACTIVITY_ANCHOR_TEMPLATE 把三段式逐条写成范例，
并与 curious_question 的"你在干嘛"示范句组合成固定模板。

本脚本校验：
1. 角色活动锚点模板不再提供三段式句式范例；
2. 新增 NO_INTERROGATION_CONSTRAINT 且包含核心禁令；
3. 自由发挥类 sys_prompt_type 会注入该约束，固定任务类不注入；
4. 去重锚点窗口从 3 条放宽到 5 条；
5. curious_question / emotional_support 动作提示不再直接示范查岗问句；
6. 风格约束里新增三段式红线。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


# ── 三段式的历史特征串 ────────────────────────────────────────────
_FORBIDDEN_ANCHOR_PHRASES = (
    "顺口提一句自己正在做什么",
    "从当前活动联想到他",
    "突然想到你昨天说的那个梗",
)

_FORBIDDEN_INTERROGATION_SAMPLES = (
    "你晚上一般都干嘛",
    "你平时听什么歌",
    "你今天过得怎么样",
    "最近怎么样",
)


def test_role_activity_anchor_no_formula() -> None:
    _section("测试 1: ROLE_ACTIVITY_ANCHOR_TEMPLATE 不再提供三段式范例")
    from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
        ROLE_ACTIVITY_ANCHOR_TEMPLATE,
    )

    for phrase in _FORBIDDEN_ANCHOR_PHRASES:
        if phrase in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
            _fail(f"锚点模板仍含三段式范例: {phrase}")
        else:
            _ok(f"锚点模板已移除三段式范例: {phrase}")

    if "{role_activity_text}" in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
        _ok("锚点模板保留 {role_activity_text} 占位符")
    else:
        _fail("锚点模板丢失 {role_activity_text} 占位符")

    if "素材" in ROLE_ACTIVITY_ANCHOR_TEMPLATE and "不代表必须在本条消息中提及" in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
        _ok("锚点模板已明确声明'只给素材、不给句式'")
    else:
        _fail("锚点模板未声明素材定位", ROLE_ACTIVITY_ANCHOR_TEMPLATE[:200])

    if "禁止固定结构" in ROLE_ACTIVITY_ANCHOR_TEMPLATE or "我在做 X" in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
        _ok("锚点模板显式禁止三段式")
    else:
        _fail("锚点模板未显式禁止三段式")


def test_no_interrogation_constraint_content() -> None:
    _section("测试 2: NO_INTERROGATION_CONSTRAINT 内容完整")
    from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
        NO_INTERROGATION_CONSTRAINT,
    )

    required = (
        "反查岗约束",
        "三段式",
        "尚未确认的具体信息",
        "可以完全不提问",
        "不再重复追问",
    )
    for phrase in required:
        if phrase in NO_INTERROGATION_CONSTRAINT:
            _ok(f"约束包含: {phrase}")
        else:
            _fail(f"约束缺少: {phrase}")

    for sample in ("在干嘛", "吃了没", "你呢"):
        if sample in NO_INTERROGATION_CONSTRAINT:
            _ok(f"约束点名禁用: {sample}")
        else:
            _fail(f"约束未点名禁用: {sample}")

    # 反幻觉原则（P0 事实约束承载核心禁编造）
    from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
        CORE_CONSTRAINTS,
    )
    for phrase in (
        "严禁编造未发生的事实",
        "如果无法在不编造事实的前提下",
    ):
        if phrase in CORE_CONSTRAINTS:
            _ok(f"P0 约束含反幻觉原则: {phrase}")
        else:
            _fail(f"P0 约束缺少反幻觉原则: {phrase}")
    if "由当前可靠上下文自然产生" in NO_INTERROGATION_CONSTRAINT:
        _ok("约束含反幻觉原则: 由当前可靠上下文自然产生")
    else:
        _fail("约束缺少反幻觉原则: 必须由当前上下文自然产生")


def test_prompt_injection() -> None:
    _section("测试 3: build_active_care_prompt 注入反查岗约束")
    from core.services.active_care.prompt.prompt_builder import (
        build_active_care_prompt,
    )

    def _section_text(sys_prompt_type: str) -> str:
        result = build_active_care_prompt(
            sys_prompt_type=sys_prompt_type,
            user_input_mock="[ACTIVE_CARE_TRIGGER]",
            reminder_msg=None,
            thought=None,
            tod="下午",
            now=1788000000.0,
            user_display_name="主人",
            persona_prompt="你是 Aveline。",
            recent_history_text="",
            role_activity_text="Aveline现在在做饭",
        )
        for sec in result.sections:
            if sec.name == "no_interrogation":
                return sec.content or ""
        return ""

    for prompt_type in (
        "proactive_chat",
        "curious_question",
        "share_thought",
        "emotional_support",
        "planned_topic",
        "share_peer_chat",
        "reminder",
    ):
        text = _section_text(prompt_type)
        if text and "反查岗约束" in text:
            _ok(f"{prompt_type} 已注入反查岗约束")
        else:
            _fail(f"{prompt_type} 未注入反查岗约束", repr(text[:80]))

    for prompt_type in (
        "goodnight_proactive",
        "sleep_again_proactive",
        "activity_return_proactive",
        "good_morning_proactive",
        "focus_nudge",
        "notification_assistant",
    ):
        text = _section_text(prompt_type)
        if text:
            _fail(f"{prompt_type} 属于固定任务类，不应注入反查岗约束", repr(text[:80]))
        else:
            _ok(f"{prompt_type} 正确跳过反查岗约束")


def test_dedup_anchor_window() -> None:
    _section("测试 4: 去重锚点窗口放宽到 5 条")
    from core.services.active_care.prompt.prompt_builder import build_active_care_prompt

    anchors = [f"锚点消息 {idx}" for idx in range(1, 8)]
    result = build_active_care_prompt(
        sys_prompt_type="proactive_chat",
        user_input_mock="[ACTIVE_CARE_TRIGGER]",
        reminder_msg=None,
        thought=None,
        tod="下午",
        now=1788000000.0,
        user_display_name="主人",
        persona_prompt="你是 Aveline。",
        recent_history_text="",
        repeat_anchors=anchors,
    )
    dedup = ""
    for sec in result.sections:
        if sec.name == "dedup_constraint":
            dedup = sec.content or ""
            break

    hits = sum(1 for a in anchors if a in dedup)
    if hits == 5:
        _ok(f"去重锚点取前 5 条（实际 {hits} 条）")
    else:
        _fail(f"去重锚点数量应为 5，实际 {hits}", dedup[:300])

    if "最近已经问过的问题，不要再次询问" in dedup:
        _ok("去重约束已加入'禁止再问同一个问题'")
    else:
        _fail("去重约束未加入'禁止再问同一个问题'", dedup[:300])


def test_action_prompts_cleaned() -> None:
    _section("测试 5: 动作提示不再示范查岗问句")
    from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
        ACTION_PROMPT_VARIANTS,
    )

    def _mimicked(sample: str, variant: str) -> bool:
        """sample 是否作为'可模仿的查岗问句'出现（而非反例说明）。"""
        idx = variant.find(sample)
        if idx < 0:
            return False
        window = variant[max(0, idx - 8):idx]
        # 仅当紧邻前面是"不要问/禁止/别/不"等否定义时才允许出现（反例）
        return not any(k in window for k in ("不要问", "禁止", "不要", "别", "不"))

    for action in ("curious_question", "emotional_support"):
        variants = ACTION_PROMPT_VARIANTS.get(action) or []
        if not variants:
            _fail(f"{action} 动作提示缺失")
            continue
        dirty = [
            sample
            for variant in variants
            for sample in _FORBIDDEN_INTERROGATION_SAMPLES
            if _mimicked(sample, variant)
        ]
        if dirty:
            _fail(f"{action} 仍以'可模仿问句'示范: {dirty}")
        else:
            _ok(f"{action} 未示范可仿查岗问句")

    curious = ACTION_PROMPT_VARIANTS.get("curious_question") or []
    if any("先给一句自己的具体判断" in v or "先给一句自己的判断" in v for v in curious):
        _ok("curious_question 已改为'先给内容再发问'")
    else:
        _fail("curious_question 未改为'先给内容再发问'")


def test_style_enforcement_redline() -> None:
    _section("测试 6: STYLE_ENFORCEMENT_TEMPLATE 新增三段式红线")
    from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
        STYLE_ENFORCEMENT_TEMPLATE,
    )

    if "三段式" in STYLE_ENFORCEMENT_TEMPLATE:
        _ok("风格约束已加入三段式红线")
    else:
        _fail("风格约束缺少三段式红线")

    if "作为默认开场或机械收尾" in STYLE_ENFORCEMENT_TEMPLATE:
        _ok("查户口追问禁令已覆盖开场与收尾")
    else:
        _fail("查户口追问禁令仅覆盖开场，LLM 仍可挪到句尾")

    if "CHARACTER VOICE 决定" in STYLE_ENFORCEMENT_TEMPLATE:
        _ok("风格约束已改为服从角色 Character Voice（不再硬编码角色性格）")
    else:
        _fail("风格约束仍可能覆盖角色性格")

    if "傲娇" not in STYLE_ENFORCEMENT_TEMPLATE and "冷静克制" not in STYLE_ENFORCEMENT_TEMPLATE:
        _ok("风格约束已移除'傲娇毒舌/冷静克制'硬编码")
    else:
        _fail("风格约束仍残留'傲娇毒舌/冷静克制'硬编码")


def main() -> int:
    print("=" * 60)
    print("Active Care 反查岗约束验证")
    print("=" * 60)

    test_role_activity_anchor_no_formula()
    test_no_interrogation_constraint_content()
    test_prompt_injection()
    test_dedup_anchor_window()
    test_action_prompts_cleaned()
    test_style_enforcement_redline()

    print("\n" + "=" * 60)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 60)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
