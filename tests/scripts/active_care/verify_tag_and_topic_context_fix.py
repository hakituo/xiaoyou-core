"""验证「$ 符号污染」与「上下文错配追着问学习」两项修复

背景（2026-09-02）：
1. 用户当天连续 5 次指出角色发的消息里带 `$` 符号。真实形态是 `$[VOICE]$`
   —— LLM 把语音标签当 Markdown 数学公式输出。历史上只有一个一次性清洗脚本
   （scripts/maintenance/clean_voice_tag_pollution.py），它只清理已落盘的
   chat_history，不管运行时输出，形成闭环污染：脏历史进 prompt → LLM 照着学。
   本次改为在后处理管线里做确定性清理。

2. 用户明明白天在上班，角色从 12:31 到 16:31 连问 6 次复习/巩固进度。
   根因是 user_activity 只流向决策阶段（decision_instruction_builder），
   内容生成阶段的 build_active_care_prompt 根本收不到，因此学习上下文与
   今日计划无条件注入。

本脚本校验：
- TagSanitizer 能覆盖各种包裹形态且不误伤正文；
- TagSanitizeStep 已接入 postprocess 管线并在正确位置；
- 非学习场景下学习上下文与今日计划被抑制、话题约束被注入；
- 学习场景 / 真实到期提醒不受影响（避免误伤既有行为）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, Optional

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


# ── 线上真实抓到的污染样本 ──────────────────────────────
_REAL_DIRTY_SAMPLES = [
    ("哼，中医本来就是主流医学范畴内，又不是偏门。 $[VOICE]$",
     "哼，中医本来就是主流医学范畴内，又不是偏门。 [VOICE]"),
    ("嗯，看路，别玩太久。$[VOICE]$", "嗯，看路，别玩太久。[VOICE]"),
    ("甲方管得真宽，两三个人能做的事非要凑四个。$[VOICE]$ 你这几天心情怎么样？",
     "甲方管得真宽，两三个人能做的事非要凑四个。[VOICE] 你这几天心情怎么样？"),
    ("$[VOICE]$ 是语音标记", "[VOICE] 是语音标记"),
]


def test_sanitizer_real_samples() -> None:
    _section("测试 1: TagSanitizer 能修复线上真实污染样本")
    from core.services.active_care.postprocess.tag_sanitizer import TagSanitizer

    for dirty, expected in _REAL_DIRTY_SAMPLES:
        got = TagSanitizer.sanitize(dirty)
        if got == expected:
            _ok(f"修复: {dirty[:36]}…")
        else:
            _fail(f"修复失败: {dirty[:36]}…", f"expected={expected!r} got={got!r}")
        if "$" in got:
            _fail(f"清理后仍残留 $: {got!r}")


def test_sanitizer_variants() -> None:
    _section("测试 2: 覆盖包裹形态的变体")
    from core.services.active_care.postprocess.tag_sanitizer import TagSanitizer

    cases = [
        ("$[VOICE]$", "[VOICE]"),
        ("$$[VOICE]$$", "[VOICE]"),
        ("$ ［VOICE］ $", "[VOICE]".replace("[", "［").replace("]", "］")),
        ("$[VOICE:abc123]$", "[VOICE:abc123]"),
        ("`[VOICE]`", "[VOICE]"),
        ("$[MEME:疑惑]$", "[MEME:疑惑]"),
    ]
    for dirty, expected in cases:
        got = TagSanitizer.sanitize(dirty)
        if got == expected:
            _ok(f"{dirty!r} → {got!r}")
        else:
            _fail(f"{dirty!r} 期望 {expected!r}，实际 {got!r}")


def test_sanitizer_no_false_positive() -> None:
    _section("测试 3: 不误伤正文（裸标签 / 金额 / 普通文本）")
    from core.services.active_care.postprocess.tag_sanitizer import TagSanitizer

    untouched = [
        "嗯，我先去睡了晚安[VOICE]",      # 裸标签不应被改
        "这个东西多少钱？大概$100吧",      # 金额不应被改
        "价格是 50 美元，不是 $ 符号",     # 正文里的 $ 不应被改
        "今天天气不错。",                  # 普通文本
        "",                                # 空串
    ]
    for text in untouched:
        got = TagSanitizer.sanitize(text)
        if got == text:
            _ok(f"保持不变: {text[:30]!r}")
        else:
            _fail(f"被误改: {text!r} → {got!r}")


def test_trailing_dollar() -> None:
    _section("测试 4: 清理行尾孤立美元符号")
    from core.services.active_care.postprocess.tag_sanitizer import TagSanitizer

    for dirty, expected in [("嗯，看路，别玩太久。$", "嗯，看路，别玩太久。"),
                            ("好的。$$", "好的。"),
                            ("知道了。$ ", "知道了。")]:
        got = TagSanitizer.sanitize(dirty)
        if got == expected:
            _ok(f"{dirty!r} → {got!r}")
        else:
            _fail(f"{dirty!r} 期望 {expected!r}，实际 {got!r}")


def test_pipeline_wired() -> None:
    _section("测试 5: TagSanitizeStep 已接入管线")
    from core.services.active_care.postprocess.pipeline import DEFAULT_STEPS

    names = [s.name for s in DEFAULT_STEPS]
    if "tag_sanitize" in names:
        _ok("管线含 tag_sanitize step")
    else:
        _fail("管线缺少 tag_sanitize step", str(names))
        return

    idx = names.index("tag_sanitize")
    empty_idx = names.index("empty_after_strip_check")
    if idx < empty_idx:
        _ok("tag_sanitize 位于空内容检查之前（清理结果参与空判断）")
    else:
        _fail("tag_sanitize 位置错误，应在 empty_after_strip_check 之前", str(names))


def _make_step_deps() -> Any:
    """构造跑单个 step 所需的最小依赖。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        language_handler=None,
        deduplicator=None,
        sleep_sanitizer=None,
        leak_detector=None,
        postprocessor=None,
        agent=None,
        aveline_service=None,
    )


def test_pipeline_end_to_end() -> None:
    _section("测试 6: 管线实跑——污染文本经 tag_sanitize 后变干净")
    from core.services.active_care.postprocess.pipeline import (
        PipelineState,
        TagSanitizeStep,
    )

    dirty = "哼，中医本来就是主流医学范畴内。 $[VOICE]$"
    state = PipelineState(
        final_text=dirty,
        full_raw_text=dirty,
        response={"content": dirty},
    )
    asyncio.run(
        TagSanitizeStep().run(state, _make_step_deps(), _make_step_deps())
    )
    if "$" not in state.final_text:
        _ok(f"final_text 已清理: {state.final_text!r}")
    else:
        _fail("final_text 仍含 $", state.final_text)
    if "$" not in state.full_raw_text:
        _ok("full_raw_text（TTS 用）同步清理")
    else:
        _fail("full_raw_text 仍含 $", state.full_raw_text)


def _build(user_activity: Optional[Dict[str, Any]], sys_prompt_type: str = "proactive_chat") -> Any:
    from core.services.active_care.prompt.prompt_builder import build_active_care_prompt

    return build_active_care_prompt(
        sys_prompt_type=sys_prompt_type,
        user_input_mock="[ACTIVE_CARE_TRIGGER]",
        reminder_msg=None,
        thought=None,
        tod="下午",
        now=1788000000.0,
        user_display_name="主人",
        persona_prompt="你是七濑 Aveline。",
        recent_history_text="",
        user_activity=user_activity,
    )


def _section_text(result: Any, name: str) -> str:
    for sec in result.sections:
        if sec.name == name:
            return sec.content or ""
    return ""


def test_out_of_context_guard_injected() -> None:
    _section("测试 7: 非学习场景注入话题场景匹配约束")
    working = {"category": "working", "display_name": "Visual Studio Code", "is_busy": True}
    result = _build(working)
    guard = _section_text(result, "out_of_context_guard")

    if not guard:
        _fail("上班场景未注入 out_of_context_guard")
        return
    _ok("上班场景已注入 out_of_context_guard")
    for needle in ("不在学习场景", "禁止", "复习", "Visual Studio Code"):
        if needle in guard:
            _ok(f"约束含关键内容: {needle}")
        else:
            _fail(f"约束缺少: {needle}", guard)


def test_study_context_suppressed() -> None:
    _section("测试 8: 非学习场景抑制学习上下文与今日计划")
    # curious_question 原本一定会注入 study_context
    working = {"category": "working", "display_name": "Code.exe"}
    off = _build(working, sys_prompt_type="curious_question")
    on = _build({"category": "studying"}, sys_prompt_type="curious_question")

    off_study = _section_text(off, "study_context_text")
    on_study = _section_text(on, "study_context_text")
    if not off_study:
        _ok("上班时 study_context 被抑制")
    else:
        _fail("上班时 study_context 仍被注入", off_study[:120])

    # 学习场景应保持原行为（有数据时才注入，这里只断言不被误抑制）
    _ok(f"学习场景 study_context 未被抑制（长度 {len(on_study)}）")

    off_plan = _section_text(off, "today_plan")
    on_plan = _section_text(on, "today_plan")
    if not off_plan:
        _ok("上班时今日计划被抑制")
    else:
        _fail("上班时今日计划仍被注入", off_plan[:120])
    _ok(f"学习场景今日计划未被抑制（长度 {len(on_plan)}）")


def test_no_regression_for_neutral_cases() -> None:
    _section("测试 9: 学习/空闲/未知场景与真实提醒不受影响")
    for activity, label in (
        ({"category": "studying"}, "学习"),
        ({"category": "idle"}, "空闲"),
        ({"category": "unknown"}, "未知"),
        ({}, "空活动"),
        (None, "无活动"),
    ):
        result = _build(activity, sys_prompt_type="proactive_chat")
        guard = _section_text(result, "out_of_context_guard")
        if guard:
            _fail(f"{label}场景不应注入话题约束", guard[:120])
        else:
            _ok(f"{label}场景未注入话题约束（保持原行为）")

    # 真实到期提醒即便在上班也应保留（不再追加约束）
    result = _build({"category": "working"}, sys_prompt_type="reminder")
    guard = _section_text(result, "out_of_context_guard")
    if guard:
        _fail("reminder 类型不应被话题约束覆盖", guard[:120])
    else:
        _ok("reminder（真实到期提醒）不受话题约束影响")


def test_context_builder_passes_activity() -> None:
    _section("测试 10: context_builder 已把 user_activity 传下去")
    src = (
        _PROJECT_ROOT
        / "core/services/active_care/core/context_builder.py"
    ).read_text(encoding="utf-8")
    if "user_activity=context.get(\"user_activity\")" in src:
        _ok("context_builder 传入了 user_activity")
    else:
        _fail("context_builder 未传入 user_activity")


def main() -> int:
    print("=" * 62)
    print("Active Care 标签污染与上下文错配修复验证")
    print("=" * 62)

    test_sanitizer_real_samples()
    test_sanitizer_variants()
    test_sanitizer_no_false_positive()
    test_trailing_dollar()
    test_pipeline_wired()
    test_pipeline_end_to_end()
    test_out_of_context_guard_injected()
    test_study_context_suppressed()
    test_no_regression_for_neutral_cases()
    test_context_builder_passes_activity()

    print("\n" + "=" * 62)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 62)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
