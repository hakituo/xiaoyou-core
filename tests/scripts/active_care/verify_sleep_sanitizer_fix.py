"""验证 sleep_sanitizer.py 修复后的行为。

修复内容：
1. enforce_sleep_low_disturb_output 添加 sys_prompt_type 参数
   - goodnight_proactive/good_morning_proactive/sleep_again_proactive 场景跳过
   - 避免 LLM 返回"困了...先去睡了"被误判为催用户睡觉
2. contains_strong_instruction 正则用负向先行断言排除"去睡了"（过去时态）
3. fallback 移除"你先休息，等你醒来我们再聊。"

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_sleep_sanitizer_fix
"""

import random
import sys

from core.services.active_care.postprocess.sleep_sanitizer import SleepSanitizer


def test_goodnight_proactive_skip():
    """测试1: goodnight_proactive 场景下应跳过 enforce_sleep_low_disturb_output"""
    text = "困了...先去睡了 晚安~ [VOICE]"
    result = SleepSanitizer.enforce_sleep_low_disturb_output(
        text,
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
        sys_prompt_type="goodnight_proactive",
    )
    assert result == text, f"goodnight_proactive 应跳过, 但得到: {result!r}"
    print(f"[OK] 测试1 (goodnight_proactive 跳过): {result!r}")


def test_active_care_chat_skip_past_tense():
    """测试2: active_care_chat 场景下，'去睡了' 是过去时态，应跳过"""
    text = "困了...先去睡了 晚安~ [VOICE]"
    result = SleepSanitizer.enforce_sleep_low_disturb_output(
        text,
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
        sys_prompt_type="active_care_chat",
    )
    assert result == text, f"'去睡了' 是过去时态应跳过, 但得到: {result!r}"
    print(f"[OK] 测试2 (去睡了 过去时态跳过): {result!r}")


def test_active_care_chat_trigger_fast_sleep():
    """测试3: active_care_chat 场景下，'快睡吧' 应触发 fallback"""
    text = "快睡吧，别熬夜了"
    result = SleepSanitizer.enforce_sleep_low_disturb_output(
        text,
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
        sys_prompt_type="active_care_chat",
    )
    assert result != text, f"'快睡吧' 应触发 fallback, 但返回原文本: {result!r}"
    assert "你先休息" not in result, f"fallback 不应包含'你先休息': {result!r}"
    assert "等你醒来" not in result, f"fallback 不应包含'等你醒来': {result!r}"
    print(f"[OK] 测试3 (快睡吧 触发fallback): {result!r}")


def test_active_care_chat_trigger_go_sleep_imperative():
    """测试4: active_care_chat 场景下，'去睡吧' 应触发 fallback（祈使语气）"""
    text = "去睡吧，别熬了"
    result = SleepSanitizer.enforce_sleep_low_disturb_output(
        text,
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
        sys_prompt_type="active_care_chat",
    )
    assert result != text, f"'去睡吧' 应触发 fallback, 但返回原文本: {result!r}"
    print(f"[OK] 测试4 (去睡吧 触发fallback): {result!r}")


def test_fallback_no_bad_phrase():
    """测试5: 验证 fallback 不再包含'你先休息，等你醒来我们再聊。'"""
    bad_phrase = "你先休息，等你醒来我们再聊。"
    trigger_texts = [
        "快睡吧", "去睡吧", "睡吧", "别熬夜", "立刻去睡",
        "闭眼", "睡了没？", "睡着没？", "还没睡？", "醒着吗？",
    ]
    # 固定随机种子确保可复现，但仍然多轮采样覆盖
    random.seed(42)
    found_bad = False
    for t in trigger_texts:
        for _ in range(30):
            r = SleepSanitizer.enforce_sleep_low_disturb_output(
                t,
                sleep_session_active=True,
                sleep_confirmed_by_silence=True,
                sys_prompt_type="active_care_chat",
            )
            if r == bad_phrase:
                found_bad = True
                print(f"  [FAIL] 发现坏 fallback! 触发文本={t!r} 结果={r!r}")
                break
        if found_bad:
            break
    assert not found_bad, "fallback 中仍包含'你先休息，等你醒来我们再聊。'"
    print("[OK] 测试5 (fallback 不含坏模板)")


def test_sanitize_sleep_scene_invitation_skip_goodnight():
    """测试6: goodnight_proactive 场景下应跳过 sanitize_sleep_scene_invitation"""
    # 这个文本同时包含睡眠场景词和邀请词，在普通场景下会触发 fallback
    # 但在 goodnight_proactive 场景下应跳过
    text = "晚安，等你醒来再聊"
    result = SleepSanitizer.sanitize_sleep_scene_invitation(
        text, sys_prompt_type="goodnight_proactive"
    )
    assert result == text, f"goodnight_proactive 应跳过, 但得到: {result!r}"
    print(f"[OK] 测试6 (goodnight_proactive 跳过矛盾邀请检测): {result!r}")


def test_sanitize_sleep_scene_invitation_no_bad_phrase():
    """测试7: sanitize_sleep_scene_invitation 的 fallback 不含'等你醒来'"""
    random.seed(42)
    bad_phrases = ["等你醒来", "你先睡，醒来再聊"]
    # 这个文本同时包含"晚安"和"来聊"，会触发 sanitize_sleep_scene_invitation
    text = "晚安，来聊"
    found_bad = False
    for _ in range(50):
        r = SleepSanitizer.sanitize_sleep_scene_invitation(
            text, sys_prompt_type="active_care_chat"
        )
        for bad in bad_phrases:
            if bad in r:
                found_bad = True
                print(f"  [FAIL] 发现坏 fallback! 结果={r!r} 包含={bad!r}")
                break
        if found_bad:
            break
    assert not found_bad, "sanitize_sleep_scene_invitation fallback 仍含坏模板"
    print("[OK] 测试7 (矛盾邀请 fallback 不含'等你醒来')")


def test_sleep_again_proactive_skip():
    """测试8: sleep_again_proactive 场景下应跳过 enforce_sleep_low_disturb_output"""
    text = "困了，继续睡啦"
    result = SleepSanitizer.enforce_sleep_low_disturb_output(
        text,
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
        sys_prompt_type="sleep_again_proactive",
    )
    assert result == text, f"sleep_again_proactive 应跳过, 但得到: {result!r}"
    print(f"[OK] 测试8 (sleep_again_proactive 跳过): {result!r}")


def test_good_morning_proactive_skip():
    """测试9: good_morning_proactive 场景下应跳过 enforce_sleep_low_disturb_output"""
    text = "早，醒了就别赖床"
    result = SleepSanitizer.enforce_sleep_low_disturb_output(
        text,
        sleep_session_active=False,  # 起床场景 sleep_session_active=False
        sleep_confirmed_by_silence=False,
        sys_prompt_type="good_morning_proactive",
    )
    assert result == text, f"good_morning_proactive 应跳过, 但得到: {result!r}"
    print(f"[OK] 测试9 (good_morning_proactive 跳过): {result!r}")


def main():
    print("=" * 70)
    print("验证 sleep_sanitizer.py 修复后的行为")
    print("=" * 70)
    tests = [
        test_goodnight_proactive_skip,
        test_active_care_chat_skip_past_tense,
        test_active_care_chat_trigger_fast_sleep,
        test_active_care_chat_trigger_go_sleep_imperative,
        test_fallback_no_bad_phrase,
        test_sanitize_sleep_scene_invitation_skip_goodnight,
        test_sanitize_sleep_scene_invitation_no_bad_phrase,
        test_sleep_again_proactive_skip,
        test_good_morning_proactive_skip,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test.__name__}: {e}")
            failed += 1
    print("=" * 70)
    if failed:
        print(f"结果: {failed}/{len(tests)} 失败")
        sys.exit(1)
    else:
        print(f"结果: {len(tests)}/{len(tests)} 通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
