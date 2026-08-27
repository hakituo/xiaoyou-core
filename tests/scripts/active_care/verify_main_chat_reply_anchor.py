"""验证：主程序已回复用户消息后，active care 顺着主程序回复继续说，而不是重新回应用户。

背景：2026-08-04 发现 active care 在主程序（chat agent）已经回复过用户最后一条消息后，
仍然把用户那条消息当作"待跟进"目标，导致 active care 重新回应用户（"不许什么你自己想去"），
而不是接着主程序的回复（"不许再试了听不懂吗..."）继续往下说。

时间线复现：
  02:42:40  active care 主动消息 "赶紧去睡觉，不许"      (is_proactive=True)
  02:43:16  用户回复 "不许什么"                          (user)
  02:43:27  主程序回复 "不许再试了听不懂吗..."            (is_proactive=False)
  02:50:22  active care 再次触发 → 错误地回 "不许什么你自己想去"

根因：build_model_user_input_for_active_care 的 is_last_from_main_chat 分支
无条件把 continuation_anchor 置空，导致流程落到 build_follow_up_input(last_user_message)，
让 LLM 去跟进一条"已被主程序回复过"的用户消息。

修复：新增 last_assistant_after_user 参数。当主程序回复晚于用户最后一条消息时
（用户消息已被回应），把主程序回复作为延续锚点（build_continuation_input），
而不是重新回应用户。

运行：D:\\AI\\xiaoyou-core\\venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_main_chat_reply_anchor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _make_builder():
    from core.services.active_care.core.input_builder import ModelInputBuilder

    return ModelInputBuilder()


def test_main_chat_replied_after_user_uses_continuation() -> None:
    """场景一（用户报告的 bug 场景）：主程序回复晚于用户消息。

    预期：active care 顺着主程序回复继续说（build_continuation_input），
         不再去回应用户那条"已被回复过"的消息。
    """
    _section("场景一：主程序已回复用户 → 应顺着主程序回复继续")
    builder = _make_builder()

    last_proactive = "赶紧去睡觉，不许"
    last_user = "不许什么"
    last_assistant = "不许再试了听不懂吗 你是真困还是不困啊都快三点"
    # 主程序回复晚于用户消息
    last_assistant_after_user = True
    # 距用户消息 ~7 分钟，非长沉默
    elapsed = 420.0

    result = builder.build_model_user_input_for_active_care(
        user_input_mock="[PLANNED_TRIGGER]",
        last_user_message=last_user,
        last_assistant_message=last_assistant,
        last_proactive_assistant_message=last_proactive,
        elapsed_seconds=elapsed,
        preferred_language="zh",
        last_assistant_after_user=last_assistant_after_user,
    )

    print(f"  生成的 model_user_input:\n{result}\n")

    # 关键断言：应使用延续模式（包含 LAST_ASSISTANT_MESSAGE 和主程序回复内容）
    assert "[LAST_ASSISTANT_MESSAGE]" in result, (
        "应包含 [LAST_ASSISTANT_MESSAGE] 标记，使用延续模式"
    )
    assert "不许再试了" in result, (
        "延续锚点应是主程序的回复内容，而不是用户消息"
    )
    # 关键断言：不应使用跟进模式（不应包含 [LAST_USER_MESSAGE]）
    assert "[LAST_USER_MESSAGE]" not in result, (
        "不应使用 build_follow_up_input（不应包含 [LAST_USER_MESSAGE]），"
        "因为主程序已经回复过用户那条消息"
    )
    # 不应把用户那条消息当作待跟进目标
    assert "不许什么" not in result or "[LAST_ASSISTANT_MESSAGE]" in result, (
        "不应把用户消息 '不许什么' 作为跟进目标"
    )

    print("  PASS: active care 顺着主程序回复继续，不再重新回应用户")


def test_main_chat_replied_before_user_still_follows_up() -> None:
    """场景二：主程序回复早于用户最后一条消息（用户消息尚未被回复）。

    预期：active care 跟进用户那条尚未被回复的消息（build_follow_up_input）。
    """
    _section("场景二：用户消息尚未被主程序回复 → 应跟进用户消息")
    builder = _make_builder()

    last_proactive = "赶紧去睡觉，不许"
    last_user = "那我睡了"  # 用户在主程序回复后又发了新消息，主程序还没回
    last_assistant = "不许再试了听不懂吗..."  # 主程序的旧回复
    # 主程序回复早于用户最后一条消息（用户消息尚未被回复）
    last_assistant_after_user = False
    elapsed = 300.0

    result = builder.build_model_user_input_for_active_care(
        user_input_mock="[PLANNED_TRIGGER]",
        last_user_message=last_user,
        last_assistant_message=last_assistant,
        last_proactive_assistant_message=last_proactive,
        elapsed_seconds=elapsed,
        preferred_language="zh",
        last_assistant_after_user=last_assistant_after_user,
    )

    print(f"  生成的 model_user_input:\n{result}\n")

    # 应使用跟进模式
    assert "[LAST_USER_MESSAGE]" in result, (
        "用户消息尚未被回复时，应使用 build_follow_up_input 跟进用户消息"
    )
    assert "那我睡了" in result, "应包含用户最新消息内容"

    print("  PASS: 用户消息未被回复时，active care 正确跟进用户消息")


def test_long_silence_after_main_chat_reply_opens_new_topic() -> None:
    """场景三：主程序回复后长时间沉默（>= 1800s）。

    预期：开启新话题（build_proactive_trigger_input），不延续主程序旧回复。
    """
    _section("场景三：主程序回复后长沉默 → 应开启新话题")
    builder = _make_builder()

    last_proactive = "赶紧去睡觉，不许"
    last_user = "不许什么"
    last_assistant = "不许再试了听不懂吗..."
    last_assistant_after_user = True
    # 长沉默
    elapsed = 2400.0

    result = builder.build_model_user_input_for_active_care(
        user_input_mock="[PLANNED_TRIGGER]",
        last_user_message=last_user,
        last_assistant_message=last_assistant,
        last_proactive_assistant_message=last_proactive,
        elapsed_seconds=elapsed,
        preferred_language="zh",
        last_assistant_after_user=last_assistant_after_user,
    )

    print(f"  生成的 model_user_input:\n{result}\n")

    # 应使用主动触发模式（新话题）
    assert "[ACTIVE_CARE_PROACTIVE_TRIGGER]" in result, (
        "长沉默应使用 build_proactive_trigger_input 开启新话题"
    )
    assert "[LAST_ASSISTANT_MESSAGE]" not in result, (
        "长沉默不应延续主程序旧回复"
    )

    print("  PASS: 长沉默时正确开启新话题")


def test_default_param_backward_compatible() -> None:
    """场景四：不传 last_assistant_after_user 时应向后兼容（默认 False）。

    预期：行为与修复前一致（主程序回复时不作为锚点，落到 follow_up）。
    """
    _section("场景四：默认参数向后兼容（不传 last_assistant_after_user）")
    builder = _make_builder()

    last_proactive = "赶紧去睡觉，不许"
    last_user = "不许什么"
    last_assistant = "不许再试了听不懂吗..."
    elapsed = 420.0

    # 不传 last_assistant_after_user，应默认 False
    result = builder.build_model_user_input_for_active_care(
        user_input_mock="[PLANNED_TRIGGER]",
        last_user_message=last_user,
        last_assistant_message=last_assistant,
        last_proactive_assistant_message=last_proactive,
        elapsed_seconds=elapsed,
        preferred_language="zh",
    )

    print(f"  生成的 model_user_input:\n{result}\n")

    # 默认 False → 走 follow_up（向后兼容）
    assert "[LAST_USER_MESSAGE]" in result, (
        "默认 last_assistant_after_user=False 时应向后兼容，使用 follow_up"
    )

    print("  PASS: 默认参数向后兼容")


def test_facade_method_accepts_new_param() -> None:
    """场景五：executor facade 方法应接受新参数。"""
    _section("场景五：executor facade 方法签名兼容")
    import inspect

    from core.services.active_care.core.executor import ActiveCareExecutor

    sig = inspect.signature(ActiveCareExecutor._build_model_user_input_for_active_care)
    params = sig.parameters
    assert "last_assistant_after_user" in params, (
        "ActiveCareExecutor._build_model_user_input_for_active_care 应接受 last_assistant_after_user 参数"
    )
    print(f"  PASS: facade 方法签名包含 last_assistant_after_user（默认={params['last_assistant_after_user'].default}）")


def test_context_builder_passes_flag() -> None:
    """场景六：context_builder 应在 context dict 中放入 last_assistant_after_user。"""
    _section("场景六：context_builder 计算并传递 last_assistant_after_user")
    import inspect

    from core.services.active_care.core.context_builder import TriggerContextBuilder

    # 检查 build_prompt 方法调用了 last_assistant_after_user
    src = inspect.getsource(TriggerContextBuilder.build_prompt)
    assert "last_assistant_after_user" in src, (
        "TriggerContextBuilder.build_prompt 应传递 last_assistant_after_user"
    )

    # 检查 build_trigger_context 计算了该字段
    src_ctx = inspect.getsource(TriggerContextBuilder.build_trigger_context)
    assert "last_assistant_after_user" in src_ctx, (
        "TriggerContextBuilder.build_trigger_context 应计算 last_assistant_after_user"
    )
    print("  PASS: context_builder 正确计算并传递 last_assistant_after_user")


def main() -> None:
    print("=" * 60)
    print("验证：主程序已回复用户后，active care 顺着主程序回复继续说")
    print("=" * 60)

    tests = [
        test_main_chat_replied_after_user_uses_continuation,
        test_main_chat_replied_before_user_still_follows_up,
        test_long_silence_after_main_chat_reply_opens_new_topic,
        test_default_param_backward_compatible,
        test_facade_method_accepts_new_param,
        test_context_builder_passes_flag,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"\n  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"\n  ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    if failed == 0:
        print(f"全部通过（{len(tests)}/{len(tests)}）")
        return 0
    print(f"失败 {failed}/{len(tests)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
