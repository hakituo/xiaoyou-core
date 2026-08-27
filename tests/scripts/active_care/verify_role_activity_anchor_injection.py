"""验证 Active Care 「想你」消息优化：角色活动锚点注入

验证三项改动：
1. prompt_builder.py: role_activity_anchor section 在不同活动下的注入行为
2. decision_instruction_builder.py: gaming/working 时不再硬建议 should_send=false
3. decision.py: character_daily 注入从「拦截」改为「话题源」（关键字符串校验）

运行：
    d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe ^
        d:\\AI\\xiaoyou-core\\tests\\scripts\\active_care\\verify_role_activity_anchor_injection.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# 把项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# 工具：统一打印
# ──────────────────────────────────────────────────────────────────
_PASS = 0
_FAIL = 0


def _ok(label: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [PASS] {label}")


def _fail(label: str, detail: str = "") -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {label}")
    if detail:
        print(f"         {detail}")


def _section(name: str) -> None:
    print(f"\n=== {name} ===")


# ──────────────────────────────────────────────────────────────────
# 测试 1: prompt_builder.role_activity_anchor 注入
# ──────────────────────────────────────────────────────────────────
def test_prompt_builder_role_activity_anchor() -> None:
    _section("测试 1: prompt_builder 的 role_activity_anchor 注入")
    from core.services.active_care.prompt.prompt_builder import build_active_care_prompt

    def _build(role_activity_text: str) -> List[Any]:
        result = build_active_care_prompt(
            sys_prompt_type="proactive_chat",
            user_input_mock="[ACTIVE_CARE_TRIGGER]",
            reminder_msg=None,
            thought="想他了",
            tod="afternoon",
            now=1735660800.0,
            user_display_name="主人",
            persona_prompt="你是 Aveline。",
            recent_history_text="",
            role_activity_text=role_activity_text,
        )
        return result.sections

    def _find_anchor(sections: List[Any]) -> str:
        for s in sections:
            if getattr(s, "name", "") == "role_activity_anchor":
                return str(getattr(s, "content", "") or "")
        return ""

    # 1.1 做饭 → 应注入锚点
    sections = _build("Aveline现在在做饭")
    anchor = _find_anchor(sections)
    if anchor and "做饭" in anchor and "你（角色）当前正在做的事" in anchor:
        _ok("角色在做饭时注入 role_activity_anchor")
    else:
        _fail("角色在做饭时应注入锚点", f"anchor={anchor!r}")

    # 1.2 学习 → 应注入锚点（关键：不再因为"忙碌"而跳过）
    sections = _build("Aveline现在在学习")
    anchor = _find_anchor(sections)
    if anchor and "学习" in anchor:
        _ok("角色在学习时也注入 role_activity_anchor（不再拦截）")
    else:
        _fail("角色在学习时应注入锚点", f"anchor={anchor!r}")

    # 1.3 sleeping → 不应注入
    sections = _build("Aveline现在在睡觉")
    anchor = _find_anchor(sections)
    if not anchor:
        _ok("角色在睡觉时不注入 role_activity_anchor（由 sleep_policy 兜底）")
    else:
        _fail("角色在睡觉时不应注入锚点", f"anchor={anchor!r}")

    # 1.4 napping → 不应注入
    sections = _build("Aveline现在在午休")
    anchor = _find_anchor(sections)
    if not anchor:
        _ok("角色在午休时不注入 role_activity_anchor")
    else:
        _fail("角色在午休时不应注入锚点", f"anchor={anchor!r}")

    # 1.5 空字符串 → 不应注入
    sections = _build("")
    anchor = _find_anchor(sections)
    if not anchor:
        _ok("空 activity_text 不注入锚点")
    else:
        _fail("空 activity_text 不应注入锚点", f"anchor={anchor!r}")


# ──────────────────────────────────────────────────────────────────
# 测试 2: decision_instruction_builder 用户活动放宽
# ──────────────────────────────────────────────────────────────────
def test_decision_instruction_user_activity() -> None:
    _section("测试 2: decision_instruction_builder 用户活动放宽")
    from core.services.active_care.decision.decision_instruction_builder import (
        _build_specific_instruction,
    )

    def _build_with_user_activity(category: str, app: str = "Code.exe") -> str:
        ctx: Dict[str, Any] = {
            "user_activity": {
                "category": category,
                "display_name": app,
                "is_busy": True,
                "busy_level": 0.6,
            },
        }
        return _build_specific_instruction(
            base_instruction="",
            portrait_priority=[],
            task_probe={},
            focus_stage="",
            quiet_mode_active=False,
            reduced_mode_active=False,
            reduced_mode_reason="",
            active_care_mode="daily",
            elapsed_seconds=600,
            now_hour=15,
            context=ctx,
        )

    # 2.1 gaming → 不再硬建议 should_send=false
    text = _build_with_user_activity("gaming", "League of Legends")
    if "should_send=false" not in text and "极简短" in text:
        _ok("gaming 不再硬建议 should_send=false，改为'极简短'")
    else:
        _fail(
            "gaming 应改为'极简短'而非 should_send=false",
            f"text={text!r}",
        )

    # 2.2 working → 不再硬建议 should_send=false
    text = _build_with_user_activity("working", "Code.exe")
    if "should_send=false" not in text and "极简短" in text:
        _ok("working 不再硬建议 should_send=false")
    else:
        _fail(
            "working 应改为'极简短'而非 should_send=false",
            f"text={text!r}",
        )

    # 2.3 studying → 不再硬建议 should_send=false
    text = _build_with_user_activity("studying", "Anki.exe")
    if "should_send=false" not in text and ("极简短" in text or "学习相关" in text):
        _ok("studying 不再硬建议 should_send=false")
    else:
        _fail(
            "studying 应改为'极简短'而非 should_send=false",
            f"text={text!r}",
        )

    # 2.4 communication → 不再硬建议 should_send=false
    text = _build_with_user_activity("communication", "WeChat.exe")
    if "should_send=false" not in text and "极简短" in text:
        _ok("communication 不再硬建议 should_send=false")
    else:
        _fail(
            "communication 应改为'极简短'而非 should_send=false",
            f"text={text!r}",
        )

    # 2.5 busy_level >= 0.5 → 不再硬建议 should_send=false
    text = _build_with_user_activity("browsing", "Chrome.exe")
    if "should_send=false" not in text and "极简短" in text:
        _ok("busy_level>=0.5 不再硬建议 should_send=false")
    else:
        _fail(
            "busy_level>=0.5 应改为'极简短'而非 should_send=false",
            f"text={text!r}",
        )


# ──────────────────────────────────────────────────────────────────
# 测试 3: decision.py 静态约束 & character_daily 注入逻辑
#   （直接读源码做关键字符串校验，避免依赖 LLM mock）
# ──────────────────────────────────────────────────────────────────
def test_decision_character_daily_injection() -> None:
    _section("测试 3: decision.py character_daily 注入从拦截改为话题源")

    src_path = _PROJECT_ROOT / "core/services/active_care/decision/decision.py"
    src = src_path.read_text(encoding="utf-8")

    # 3.1 静态约束应包含"默认倾向发送"
    if "默认倾向发送" in src and "should_send=true" in src:
        _ok("静态约束已改为'默认倾向发送'")
    else:
        _fail("静态约束应包含'默认倾向发送'和'should_send=true'")

    # 3.2 不应再出现旧的"两人都在忙，除非有紧急事项，否则 should_send=false"
    if "两人都在忙，除非有紧急事项" not in src:
        _ok("已移除旧的'两人都在忙→should_send=false'硬性建议")
    else:
        _fail("仍残留旧的'两人都在忙→should_send=false'拦截逻辑")

    # 3.3 不应再出现旧的"有角色空闲，适合发消息"
    if "有角色空闲，适合发消息" not in src:
        _ok("已移除旧的'有角色空闲，适合发消息'二元判定")
    else:
        _fail("仍残留旧的'有角色空闲，适合发消息'判定")

    # 3.4 应包含正向话题源引导
    if (
        "她正在做事时突然想到他" in src
        and "should_send=true" in src
        and "话题源" in src
    ):
        _ok("已注入正向话题源引导（'她正在做事时突然想到他'）")
    else:
        _fail("未找到正向话题源引导字符串")

    # 3.5 SLEEPING/NAPPING 仍保持安静
    if (
        "SLEEPY_ACTIVITIES" in src
        and "sleeping" in src
        and "napping" in src
        and "两人都在睡觉，should_send=false" in src
    ):
        _ok("SLEEPING/NAPPING 仍保持 should_send=false 安静策略")
    else:
        _fail("SLEEPING/NAPPING 安静策略未保留")


# ──────────────────────────────────────────────────────────────────
# 测试 4: context_builder._resolve_role_activity_text 存在
# ──────────────────────────────────────────────────────────────────
def test_context_builder_role_activity_resolver() -> None:
    _section("测试 4: context_builder._resolve_role_activity_text 方法存在")

    src_path = _PROJECT_ROOT / "core/services/active_care/core/context_builder.py"
    src = src_path.read_text(encoding="utf-8")

    if "def _resolve_role_activity_text" in src:
        _ok("context_builder 新增了 _resolve_role_activity_text 方法")
    else:
        _fail("context_builder 未新增 _resolve_role_activity_text 方法")

    if "role_activity_text=role_activity_text" in src:
        _ok("build_active_care_prompt 调用已传入 role_activity_text")
    else:
        _fail("build_active_care_prompt 调用未传入 role_activity_text")

    if "get_character_daily_engine" in src and "get_activity_context_text" in src:
        _ok("context_builder 已接入 character_daily engine 查询活动文本")
    else:
        _fail("context_builder 未接入 character_daily engine")


# ──────────────────────────────────────────────────────────────────
# 测试 5: active_care_prompts.ROLE_ACTIVITY_ANCHOR_TEMPLATE 存在
# ──────────────────────────────────────────────────────────────────
def test_active_care_prompts_template() -> None:
    _section("测试 5: active_care_prompts.ROLE_ACTIVITY_ANCHOR_TEMPLATE 模板")

    try:
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
            ROLE_ACTIVITY_ANCHOR_TEMPLATE,
        )
    except ImportError as e:
        _fail("无法导入 ROLE_ACTIVITY_ANCHOR_TEMPLATE", str(e))
        return

    if "{role_activity_text}" in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
        _ok("ROLE_ACTIVITY_ANCHOR_TEMPLATE 含 {role_activity_text} 占位符")
    else:
        _fail(
            "ROLE_ACTIVITY_ANCHOR_TEMPLATE 应含 {role_activity_text} 占位符",
            ROLE_ACTIVITY_ANCHOR_TEMPLATE,
        )

    if "你（角色）当前正在做的事" in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
        _ok("ROLE_ACTIVITY_ANCHOR_TEMPLATE 含'你（角色）当前正在做的事'标题")
    else:
        _fail(
            "ROLE_ACTIVITY_ANCHOR_TEMPLATE 应含'你（角色）当前正在做的事'标题",
            ROLE_ACTIVITY_ANCHOR_TEMPLATE,
        )

    if "sleeping" in ROLE_ACTIVITY_ANCHOR_TEMPLATE and "napping" in ROLE_ACTIVITY_ANCHOR_TEMPLATE:
        _ok("ROLE_ACTIVITY_ANCHOR_TEMPLATE 含 sleeping/napping 跳过提示")
    else:
        _fail(
            "ROLE_ACTIVITY_ANCHOR_TEMPLATE 应含 sleeping/napping 跳过提示",
            ROLE_ACTIVITY_ANCHOR_TEMPLATE,
        )


# ──────────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 64)
    print("Active Care 「想你」消息优化验证")
    print("=" * 64)

    test_prompt_builder_role_activity_anchor()
    test_decision_instruction_user_activity()
    test_decision_character_daily_injection()
    test_context_builder_role_activity_resolver()
    test_active_care_prompts_template()

    print("\n" + "=" * 64)
    print(f"结果: PASS={_PASS}, FAIL={_FAIL}")
    print("=" * 64)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
