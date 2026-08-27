import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.agents.chat_agent_components.persona_system.prompt.components import (
    _format_elapsed_human,
    build_conversation_gap_context,
)
from core.services.active_care.shared.constants import format_message_age_human


def test_format_elapsed_human_day_precision():
    print("=== 测试 _format_elapsed_human 天级精度 ===")

    assert _format_elapsed_human(86400) == "1天", f"86400秒应为'1天'，实际: {_format_elapsed_human(86400)}"
    assert _format_elapsed_human(90000) == "1天1小时", f"90000秒(25h)应为'1天1小时'，实际: {_format_elapsed_human(90000)}"
    assert _format_elapsed_human(93600) == "1天2小时", f"93600秒(26h)应为'1天2小时'，实际: {_format_elapsed_human(93600)}"
    assert _format_elapsed_human(129600) == "1天12小时", f"129600秒(36h)应为'1天12小时'，实际: {_format_elapsed_human(129600)}"
    assert _format_elapsed_human(169200) == "1天23小时", f"169200秒(47h)应为'1天23小时'，实际: {_format_elapsed_human(169200)}"
    assert _format_elapsed_human(172800) == "2天", f"172800秒(48h)应为'2天'，实际: {_format_elapsed_human(172800)}"
    assert _format_elapsed_human(180000) == "2天2小时", f"180000秒(50h)应为'2天2小时'，实际: {_format_elapsed_human(180000)}"

    assert _format_elapsed_human(3600) == "1小时", f"3600秒应为'1小时'，实际: {_format_elapsed_human(3600)}"
    assert _format_elapsed_human(5400) == "1小时30分钟", f"5400秒应为'1小时30分钟'，实际: {_format_elapsed_human(5400)}"

    print("  ✅ _format_elapsed_human 天级精度测试全部通过")


def test_format_message_age_human_day_precision():
    print("\n=== 测试 format_message_age_human 天级精度 ===")
    now = time.time()

    assert format_message_age_human(now - 86400, now) == "（约1天前）", \
        f"1天前应为'（约1天前）'，实际: {format_message_age_human(now - 86400, now)}"
    assert format_message_age_human(now - 90000, now) == "（约1天1小时前）", \
        f"25小时前应为'（约1天1小时前）'，实际: {format_message_age_human(now - 90000, now)}"
    assert format_message_age_human(now - 129600, now) == "（约1天12小时前）", \
        f"36小时前应为'（约1天12小时前）'，实际: {format_message_age_human(now - 129600, now)}"
    assert format_message_age_human(now - 180000, now) == "（约2天2小时前）", \
        f"50小时前应为'（约2天2小时前）'，实际: {format_message_age_human(now - 180000, now)}"

    print("  ✅ format_message_age_human 天级精度测试全部通过")


def test_gap_context_detects_user_return():
    print("\n=== 测试 build_conversation_gap_context 感知用户回来 ===")

    now = time.time()
    history = [
        {"role": "user", "content": "晚安", "timestamp": now - 36 * 3600},  # 36小时前
        {"role": "assistant", "content": "嗯晚安", "timestamp": now - 36 * 3600 + 30},
    ]

    result = build_conversation_gap_context(history, now)
    print(f"  输出:\n{result}")

    assert "⚠️" in result, "应包含间隔警告⚠️"
    assert "1天12小时" in result, \
        f"应包含精确的天+小时信息，实际: {result}"
    assert "用户距上次发言" in result, \
        f"应包含用户回来的提示，实际: {result}"

    print("  ✅ 用户回来感知测试通过")


def test_gap_context_no_false_positive():
    print("\n=== 测试 build_conversation_gap_context 短对话无间隔 ===")
    now = time.time()
    history = [
        {"role": "user", "content": "你好", "timestamp": now - 60},
        {"role": "assistant", "content": "嗯", "timestamp": now - 30},
    ]
    result = build_conversation_gap_context(history, now)
    assert result == "", f"短对话不应有间隔警告，实际: {result}"
    print("  ✅ 短对话无间隔测试通过")


def test_gap_context_single_message():
    print("\n=== 测试 build_conversation_gap_context 单条消息（长时间前）===")
    now = time.time()
    history = [
        {"role": "user", "content": "你好", "timestamp": now - 86400 - 3600},  # 1天1小时前
    ]
    result = build_conversation_gap_context(history, now)
    print(f"  输出:\n{result}")
    assert "1天1小时" in result, f"单条消息也应检测到距当前的间隔，实际: {result}"
    assert "用户距上次发言" in result, f"应包含用户回来的提示，实际: {result}"
    print("  ✅ 单条消息间隔检测测试通过")


def test_real_scenario_0508_to_0510():
    print("\n=== 复现用户场景：05-08 到 05-10 ===")

    now = time.time()

    gap_36h = 36 * 3600
    gap_str_36h = _format_elapsed_human(int(gap_36h))
    print(f"  36小时间隔 = {gap_str_36h}")
    assert "1天12小时" in gap_str_36h, f"36小时间隔应为'1天12小时'，实际: {gap_str_36h}"

    gap_50h = 50 * 3600
    gap_str_50h = _format_elapsed_human(int(gap_50h))
    print(f"  50小时间隔 = {gap_str_50h}")
    assert "2天2小时" in gap_str_50h, f"50小时间隔应为'2天2小时'，实际: {gap_str_50h}"

    gap_47h = 47 * 3600
    gap_str_47h = _format_elapsed_human(int(gap_47h))
    print(f"  47小时间隔 = {gap_str_47h}")
    assert "1天23小时" in gap_str_47h, f"47小时间隔应为'1天23小时'，实际: {gap_str_47h}"

    print("  ✅ 真实场景复现测试通过")
    print("  📝 修复前：36小时→'1天'，47小时→'1天'，50小时→'2天'（LLM会说'两天不见'）")
    print("  📝 修复后：36小时→'1天12小时'，47小时→'1天23小时'，50小时→'2天2小时'（LLM能精确理解）")


if __name__ == "__main__":
    print("=" * 60)
    print("时间格式化精度修复验证测试")
    print("=" * 60)

    test_format_elapsed_human_day_precision()
    test_format_message_age_human_day_precision()
    test_gap_context_detects_user_return()
    test_gap_context_no_false_positive()
    test_gap_context_single_message()
    test_real_scenario_0508_to_0510()

    print("\n" + "=" * 60)
    print("🎉 所有测试通过！时间格式化精度修复验证成功")
    print("=" * 60)
