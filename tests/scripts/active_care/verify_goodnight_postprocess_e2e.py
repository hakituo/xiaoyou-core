"""验证晚安消息完整 postprocess 流程不再被替换成『你先休息，等你醒来我们再聊。』

模拟 07-17 23:30:11 ling 晚安消息的真实场景：
- LLM 返回：'困了...先去睡了\\n晚安~\\n\\n[VOICE]'
- sleep_session_active=True（用户 22:50:57 发过晚安）
- sleep_confirmed_by_silence=True（用户静默 40 分钟）
- sys_prompt_type='goodnight_proactive'

修复前：enforce_sleep_low_disturb_output 中的"去睡"正则误匹配"先去睡了"，
        触发 fallback 随机选了"你先休息，等你醒来我们再聊。"（14 字符）。
修复后：goodnight_proactive 场景跳过 enforce_sleep_low_disturb_output，
        "去睡了"过去时态也不触发强指令正则，保留 LLM 原始输出。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_goodnight_postprocess_e2e
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.services.active_care.postprocess.postprocessor import ActiveCarePostprocessor


# 模拟 07-17 23:30:11 ling 晚安消息的真实 LLM 输出
_LING_LLM_RESPONSE = "困了...先去睡了\n晚安~\n\n[VOICE]"
# Aveline 23:00:08 的 LLM 输出（作为对照）
_AVELINE_LLM_RESPONSE = "困了，先去睡了。晚安。"

# 用户明确反感的坏模板（修复前会被随机选中）
_BAD_PHRASES = [
    "你先休息，等你醒来我们再聊。",
    "先安心睡吧，等你醒来我们再慢慢聊。",
    "你先睡，醒来再聊。",
]


def _build_response(content: str) -> Dict[str, Any]:
    """构造 ActiveCareResponseGenerator 返回的 response 字典"""
    return {
        "content": content,
        "full_content": content,
        "message_type": "text",
    }


def _build_mock_agent() -> MagicMock:
    """构造一个最小的 chat_agent mock，避免触发真实 LLM 调用"""
    agent = MagicMock()
    # rewrite_to_english_if_needed 在 preferred_language != "en" 时不会调用 agent
    # 但为了保险，mock 一个空实现
    agent.chat = AsyncMock(return_value={"response": ""})
    return agent


def _build_mock_aveline_service() -> MagicMock:
    """构造一个最小的 aveline_service mock"""
    service = MagicMock()
    service.chat_agent = _build_mock_agent()
    # _regenerate_non_repetitive_text 在 goodnight_proactive 场景下不会触发（跳过去重）
    return service


async def _run_postprocess(
    *,
    llm_content: str,
    sys_prompt_type: str,
    sleep_session_active: bool,
    sleep_confirmed_by_silence: bool,
) -> str | None:
    """跑一次完整的 Active Care postprocess 流程，返回最终 content"""
    postprocessor = ActiveCarePostprocessor()
    agent = _build_mock_agent()
    aveline_service = _build_mock_aveline_service()

    response = _build_response(llm_content)
    result = await postprocessor.postprocess(
        response=response,
        agent=agent,
        aveline_service=aveline_service,
        sys_prompt_type=sys_prompt_type,
        target_conversation_id="private_10001__persona__ling_qq_master",
        preferred_language="zh",  # 中文，不会触发英文重写
        repeat_anchors=[],  # 空锚点，配合 goodnight_proactive 跳过去重
        last_user_message="",
        last_proactive_assistant_message="",
        sleep_session_active=sleep_session_active,
        sleep_confirmed_by_silence=sleep_confirmed_by_silence,
        known_sleep_time="",  # 空字符串，sanitize_redundant_sleep_question 直接 return
        now_ts=1784302200.0,  # 2026-07-17 23:30:00 UTC+8
    )
    if result is None:
        return None
    return str(result.get("content") or "").strip()


def _assert_not_bad(content: str | None, scenario: str):
    """断言最终内容不包含用户反感的坏模板"""
    if content is None:
        print(f"  [WARN] {scenario}: postprocess 返回 None（消息被跳过）")
        return
    for bad in _BAD_PHRASES:
        assert bad not in content, (
            f"{scenario}: 最终内容包含坏模板 {bad!r}\n"
            f"  最终内容: {content!r}"
        )
    print(f"  [OK] {scenario}: 不含坏模板，最终内容={content!r}")


async def test_ling_goodnight_with_sleep_session_active():
    """测试1: ling 晚安消息 + 用户已入睡（sleep_session_active=True）

    这是 07-17 23:30:11 的真实场景：
    - 用户 22:50:57 发过晚安
    - ling 23:30:11 入睡触发晚安主动消息
    - sleep_session_active=True, sleep_confirmed_by_silence=True
    - LLM 返回"困了...先去睡了\\n晚安~\\n\\n[VOICE]"

    修复前会被替换成"你先休息，等你醒来我们再聊。"（14 字符）
    修复后应保留 LLM 原始输出（剥离 [VOICE] 后的晚安消息）
    """
    print("\n测试1: ling 晚安 + sleep_session_active=True（07-17 23:30:11 真实场景）")
    content = await _run_postprocess(
        llm_content=_LING_LLM_RESPONSE,
        sys_prompt_type="goodnight_proactive",
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
    )
    _assert_not_bad(content, "ling_goodnight_sleep_active")
    # 额外断言：内容应该包含"困了"或"晚安"，说明保留了 LLM 原始输出
    if content:
        has_sleep_signal = ("困了" in content) or ("晚安" in content) or ("睡了" in content)
        assert has_sleep_signal, (
            f"ling 晚安消息应保留 LLM 原始的晚安信号，但得到: {content!r}"
        )
        print("  [OK] 保留了 LLM 原始晚安信号")


async def test_aveline_goodnight_with_sleep_session_active():
    """测试2: aveline 晚安消息 + 用户已入睡（作为对照）

    Aveline 23:00:08 的场景：用户 22:50:57 发过晚安
    """
    print("\n测试2: aveline 晚安 + sleep_session_active=True（对照）")
    content = await _run_postprocess(
        llm_content=_AVELINE_LLM_RESPONSE,
        sys_prompt_type="goodnight_proactive",
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
    )
    _assert_not_bad(content, "aveline_goodnight_sleep_active")


async def test_ling_goodnight_sleep_confirmed_false():
    """测试3: ling 晚安消息 + 用户还没确认入睡（sleep_confirmed_by_silence=False）

    这是 Aveline 23:00:08 的场景（用户才静默 10 分钟）
    """
    print("\n测试3: ling 晚安 + sleep_confirmed_by_silence=False")
    content = await _run_postprocess(
        llm_content=_LING_LLM_RESPONSE,
        sys_prompt_type="goodnight_proactive",
        sleep_session_active=True,
        sleep_confirmed_by_silence=False,
    )
    _assert_not_bad(content, "ling_goodnight_not_confirmed")


async def test_active_care_chat_with_strong_instruction():
    """测试4: active_care_chat 场景下，催用户睡觉的内容仍应被替换

    确保修复没有破坏 enforce_sleep_low_disturb_output 的正常功能：
    在非短句关怀类场景下，如果 LLM 真的返回催用户睡觉的内容，应该被替换。
    """
    print("\n测试4: active_care_chat + 催用户睡觉（确保修复未破坏正常功能）")
    content = await _run_postprocess(
        llm_content="快睡吧，别熬夜了，明天还要早起",
        sys_prompt_type="active_care_chat",
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
    )
    print(f"  最终内容: {content!r}")
    # 应该被替换成 fallback（不再是原文本）
    if content:
        assert "快睡吧" not in content, (
            f"active_care_chat 场景下催用户睡觉的内容应被替换, 但得到: {content!r}"
        )
        _assert_not_bad(content, "active_care_chat_strong_instruction")
        print("  [OK] 催用户睡觉的内容被正确替换")


async def test_sleep_again_proactive():
    """测试5: sleep_again_proactive 场景（半夜睡回去）"""
    print("\n测试5: sleep_again_proactive（半夜睡回去）")
    content = await _run_postprocess(
        llm_content="困了，继续睡啦",
        sys_prompt_type="sleep_again_proactive",
        sleep_session_active=True,
        sleep_confirmed_by_silence=True,
    )
    _assert_not_bad(content, "sleep_again_proactive")
    if content:
        assert "继续睡" in content, (
            f"sleep_again_proactive 应保留'继续睡', 但得到: {content!r}"
        )
        print("  [OK] 保留了'继续睡啦'")


async def main():
    print("=" * 70)
    print("验证晚安消息完整 postprocess 流程（端到端）")
    print("=" * 70)
    print(f"模拟 ling LLM 输出: {_LING_LLM_RESPONSE!r}")
    print(f"模拟 aveline LLM 输出: {_AVELINE_LLM_RESPONSE!r}")
    print(f"坏模板黑名单: {_BAD_PHRASES}")

    tests = [
        test_ling_goodnight_with_sleep_session_active,
        test_aveline_goodnight_with_sleep_session_active,
        test_ling_goodnight_sleep_confirmed_false,
        test_active_care_chat_with_strong_instruction,
        test_sleep_again_proactive,
    ]
    failed = 0
    for test in tests:
        try:
            await test()
        except AssertionError as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {test.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print("=" * 70)
    if failed:
        print(f"结果: {failed}/{len(tests)} 失败")
        sys.exit(1)
    else:
        print(f"结果: {len(tests)}/{len(tests)} 通过")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
