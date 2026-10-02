#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证云端历史「连续最近窗口 + 时间锚点」的行为。

背景（2026-09-18）：云端历史曾用 `_select_relevant_history_for_cloud` 做关键词抽样，
实测（351 条真实历史回放）85.3% 的轮次里关键词完全不生效，退化成「最近的 12 条
用户消息」，且对应的助手回复被系统性丢弃。该抽样已删除，统一改为连续最近窗口。

随后发现第二个问题：窗口起点用 `len(history)` 当锚点算不出稳定前缀 ——
上游 `list_conversation_events` 带 limit，返回的是「最近 N 条」的**滑动列表**
（实测被截在约 100 条），列表一滑动，同一个下标就指向不同消息，前缀永远对不上。
因此起点改用**时间锚点**：把候选起点的时刻向下取整到 `cloud_history_quantum_seconds`
边界，再回退到第一条不早于该边界的消息。

本脚本不发送真实 LLM 请求，仅做结构与行为验证：
1. 普通聊天取连续尾部，成对包含助手回复（无断档、无孤儿用户消息）
2. 窗口内容与当前用户消息无关（证明关键词抽样已移除）
3. 学习上下文仍保留精确的连续工作窗口（不参与时间锚点）
4. 字符上限从尾部裁剪，且不丢最新一条
5. **滑动列表下窗口能作为稳定前缀复用**（时间锚点的核心目标），并反向锁死
   「纯条数量化在滑动列表下复用率为 0」
6. 窗口有界：不超过 cap + quantize
7. 窗口起点对齐到 user 消息（不以助手回复开头；整段无 user 时不清空）
8. 时间戳缺失或为脏数据时退回条数量化，不报错也不丢历史
9. `_select_relevant_history_for_cloud` 与 `extract_match_tokens` 已删除
10. `ChatContextBudgetSettings` 不再暴露 cloud_relevance_* 字段
11. 真实配置满足 messages >= study_active_recent_window

运行：
    venv_core\\Scripts\\python.exe tests/scripts/prompt_cache/verify_cloud_history_contiguous_window.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

CAP = 60
QUANTIZE = 20
QUANTUM_SECONDS = 300
BASE_TS = 1_700_000_000


def _settings(**overrides) -> SimpleNamespace:
    """构造只含云端预算字段的 settings 桩。"""
    values = {
        "cloud_max_history_messages": CAP,
        "cloud_max_history_chars": 12000,
        "cloud_history_quantize_messages": QUANTIZE,
        "cloud_history_quantum_seconds": QUANTUM_SECONDS,
        "study_active_recent_window": 20,
        "study_active_cloud_max_history_chars": 18000,
    }
    values.update(overrides)
    return SimpleNamespace(
        chat=SimpleNamespace(context_budget=SimpleNamespace(**values))
    )


def _chat_history(
    count: int,
    *,
    category: str | None = None,
    step_seconds: int = 60,
    with_ts: bool = True,
    start_ts: int = BASE_TS,
) -> list[dict]:
    """构造 user/assistant 交替的闲聊历史；默认每条间隔 60 秒。"""
    history = []
    for index in range(count):
        item: dict = {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"闲聊-{index}",
        }
        if with_ts:
            item["timestamp"] = start_ts + index * step_seconds
        if category:
            item["category"] = category
        history.append(item)
    return history


def _apply(history, message, **overrides):
    from core.agents.chat_agent_components.context_budget.budget_apply import (
        apply_cloud_history_budget,
    )

    with patch("config.integrated_config.get_settings", return_value=_settings(**overrides)):
        return apply_cloud_history_budget(history, message)


def _contents(messages) -> list[str]:
    return [m["content"] for m in messages]


# ============================================================
# 1. 连续尾部 + 成对带回复
# ============================================================

def test_normal_chat_uses_contiguous_tail() -> None:
    """普通聊天必须取原历史的连续尾部，不能跳档、不能丢回复。"""
    history = _chat_history(80)
    result = _apply(history, "今天有点累")

    assert _contents(result) == _contents(history)[-len(result):], (
        "普通聊天未取连续尾部"
    )
    roles = [m["role"] for m in result]
    assert roles.count("assistant") >= 25, (
        f"assistant 只有 {roles.count('assistant')} 条——回复被丢掉了"
    )
    assert abs(roles.count("user") - roles.count("assistant")) <= 1, (
        "user/assistant 数量失衡，可能只剩孤立的用户消息"
    )


def test_no_orphan_user_messages() -> None:
    """连续窗口里每条 user 后面都应紧跟它的 assistant 回复（除最后一条）。"""
    history = _chat_history(60)
    result = _apply(history, "随便聊聊")

    for index in range(len(result) - 1):
        if result[index]["role"] == "user":
            assert result[index + 1]["role"] == "assistant", (
                f"第 {index} 条 user 消息后面不是 assistant 回复，出现孤立提问"
            )


# ============================================================
# 2. 窗口与当前用户消息无关
# ============================================================

def test_window_is_independent_of_user_message() -> None:
    """同一份历史下，不同用户消息必须得到完全相同的窗口。"""
    history = _chat_history(80)
    baseline = _contents(_apply(history, "今天天气不错"))

    for query in ("沉没成本", "哎Aveline", "换个模型又不是换你，给你换个更好的模型而已"):
        assert _contents(_apply(history, query)) == baseline, (
            f"query={query!r} 改变了历史窗口，关键词抽样可能仍在生效"
        )


# ============================================================
# 3. 学习上下文（不参与时间锚点）
# ============================================================

def test_study_context_keeps_wider_window() -> None:
    """学习上下文必须保留连续工作窗口（至少覆盖最近 20 条）。

    时间锚点回退让窗口比 20 条多出几条（最多 +quantize），起点对齐到
    user 消息最多再让 1 条；窗口必须是原历史的连续尾部。
    """
    history = _chat_history(40, category="learning")
    result = _apply(history, "B")

    assert _contents(result) == _contents(history)[-len(result):], (
        "学习窗口不是原历史的连续尾部"
    )
    assert 19 <= len(result) <= 30, (
        f"学习窗口 {len(result)} 条，超出 [19, 30]（20 + quantize(10)，"
        "起点对齐最多让 1 条）"
    )
    assert result[-1]["content"] == history[-1]["content"], "裁掉了最新一条"


def test_study_window_is_anchored_stable_prefix() -> None:
    """学习窗口也走时间锚点：滑动列表下前缀可复用。

    旧实现「精确最近 20 条」逐轮滑动，实测早自习一串 8 个 study 请求
    全部各自打穿历史前缀。这里用与普通聊天相同的滑动列表模拟
    （上游 `list_conversation_events` 带 limit），学习上下文的前缀
    复用率必须同样达标——这是 DeepSeek 前缀缓存能否命中的判据。
    """
    full = _chat_history(200, category="learning")
    fetch = 100
    prev = None
    hits = 0
    turns = 0
    sizes = []

    for k in range(40, 80):
        result = _apply(full[k:k + fetch], "B")
        current = _contents(result)
        sizes.append(len(current))
        if prev is not None:
            turns += 1
            if len(current) >= len(prev) and current[:len(prev)] == prev:
                hits += 1
        prev = current

    assert turns > 0
    rate = hits / turns
    assert rate >= 0.7, (
        f"{turns} 轮学习请求里只有 {hits} 轮前缀可复用（{rate:.0%}），"
        "学习窗口没吃到时间锚点"
    )
    assert min(sizes) >= 19, f"学习窗口最小 {min(sizes)} 条，工作记忆被切短"
    assert max(sizes) <= 30, f"学习窗口最大 {max(sizes)} 条，超过 20+quantize(10)"


def test_study_window_respects_smaller_message_cap() -> None:
    """messages 上限小于学习窗口时，取更小的那个（不越界）。"""
    history = _chat_history(40, category="learning")
    result = _apply(history, "B", cloud_max_history_messages=12)

    assert _contents(result) == _contents(history)[-12:]


# ============================================================
# 4. 字符上限
# ============================================================

def test_char_budget_clips_from_tail_and_keeps_latest() -> None:
    """字符超限时从尾部往前裁，最新一条必须保留，且裁剪后仍是连续尾部。"""
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"长消息-{index}-" + "内容" * 200,
            "timestamp": BASE_TS + index * 60,
        }
        for index in range(40)
    ]
    result = _apply(history, "今天有点累")

    total_chars = sum(len(m["content"]) for m in result)
    assert 0 < total_chars <= 12000, f"字符数 {total_chars} 超出 12000 上限"
    assert result[-1]["content"] == history[-1]["content"], "裁剪丢掉了最新一条"
    assert _contents(result) == _contents(history)[-len(result):], (
        "裁剪后不是原历史的连续尾部"
    )


def test_empty_history_returns_as_is() -> None:
    """空历史直接返回，不做任何处理。"""
    assert _apply([], "你好") == []


# ============================================================
# 5. 滑动列表下的前缀复用（时间锚点的核心目标）
# ============================================================

def test_window_is_stable_prefix_under_sliding_fetch() -> None:
    """上游是滑动列表时，窗口必须能作为稳定前缀复用。

    `list_conversation_events` 带 limit，返回「最近 N 条」；如果拿 len(history)
    当锚点，列表一滑动起点就跟着滑，prompt cache 前缀永远对不上。
    这里用 100 条滑动列表模拟上游，统计连续两轮之间「本轮窗口以 上轮窗口 为前缀」
    的比例 —— 这正是 DeepSeek 前缀缓存能否命中的判据。
    """
    full = _chat_history(200)
    fetch = 100
    prev = None
    hits = 0
    turns = 0
    sizes = []

    for k in range(40, 80):
        result = _apply(full[k:k + fetch], "今天有点累")
        current = _contents(result)
        sizes.append(len(current))
        if prev is not None:
            turns += 1
            if len(current) >= len(prev) and current[:len(prev)] == prev:
                hits += 1
        prev = current

    assert turns > 0
    rate = hits / turns
    assert rate >= 0.7, (
        f"{turns} 轮里只有 {hits} 轮前缀可复用（{rate:.0%}），"
        "时间锚点没起作用，历史块仍命中不了缓存"
    )
    assert max(sizes) <= CAP + QUANTIZE, f"窗口最大 {max(sizes)} 条，超过上限"


def test_count_anchor_alone_is_not_enough() -> None:
    """反向确认：只按条数量化（不加时间锚点）在滑动列表下前缀复用率为 0。

    这条测试锁死「为什么必须用时间锚点」，防止后人把锚点改回 len(history)。
    """
    from core.agents.chat_agent_components.context_budget.budget_apply import (
        _resolve_window_start,
    )

    full = _chat_history(200)
    fetch = 100
    prev = None
    hits = 0
    turns = 0
    for k in range(40, 80):
        window = full[k:k + fetch]
        # quantum_seconds=0 即关闭时间锚点，退回纯条数量化
        start = _resolve_window_start(window, CAP, QUANTIZE, 0)
        current = _contents(window[start:])
        if prev is not None:
            turns += 1
            if len(current) >= len(prev) and current[:len(prev)] == prev:
                hits += 1
        prev = current

    assert turns > 0
    assert hits == 0, f"纯条数量化竟然复用了 {hits}/{turns} 轮，测试前提已变"


# ============================================================
# 6. 窗口有界
# ============================================================

def test_window_never_exceeds_cap_plus_quantize() -> None:
    """时间锚点回退距离以 quantize 条为上限，窗口不能无限膨胀。"""
    history = _chat_history(300, step_seconds=5)  # 密集聊天：5 秒一条
    for total in range(80, 200, 2):
        result = _apply(history[:total], "今天有点累")
        assert len(result) <= CAP + QUANTIZE, (
            f"total={total} 时窗口 {len(result)} 条，超过 {CAP + QUANTIZE} 上限"
        )


def test_small_message_cap_does_not_collapse_window() -> None:
    """小条数上限时窗口不能被压到接近空。"""
    history = _chat_history(120)
    for total in range(40, 120, 2):
        result = _apply(history[:total], "今天有点累", cloud_max_history_messages=12)
        assert len(result) > 6, f"total={total} 时窗口只剩 {len(result)} 条"
        assert len(result) <= 12 + QUANTIZE, f"total={total} 时窗口 {len(result)} 条过大"


# ============================================================
# 7. 起点对齐到 user 消息
# ============================================================

def test_window_start_aligned_to_user_message() -> None:
    """窗口起点必须对齐到 user 消息，不能以助手回复开头。

    构造「以助手回复开头」的历史（真实历史里角色并不严格交替），
    让锚点后的起点落在助手回复上，验证会被修正。
    """
    history = [
        {"role": "assistant", "content": "（孤立的上一轮回复）", "timestamp": BASE_TS}
    ]
    history.extend(_chat_history(139, start_ts=BASE_TS + 60))

    for total in range(60, 140, 2):
        result = _apply(history[:total], "今天有点累")
        assert result, f"total={total} 时窗口为空"
        assert result[0]["role"] == "user", (
            f"total={total} 时窗口首条是 {result[0]['role']}，"
            "模型会看到自己的回复却没有前面的提问"
        )


def test_all_history_has_no_user_message_returns_original() -> None:
    """整段没有 user 消息时不能被对齐逻辑清空。"""
    history = [
        {"role": "assistant", "content": f"回复-{i}", "timestamp": BASE_TS + i * 60}
        for i in range(40)
    ]
    result = _apply(history, "今天有点累")

    assert len(result) == 40, f"没有 user 消息时窗口被清成 {len(result)} 条"


# ============================================================
# 8. 时间戳缺失时的兜底
# ============================================================

def test_missing_timestamp_falls_back_to_count_quantization() -> None:
    """历史没有 timestamp 时必须退回条数量化，不报错也不丢历史。"""
    history = _chat_history(120, with_ts=False)
    result = _apply(history, "今天有点累")

    assert result, "缺时间戳时窗口被清空"
    assert len(result) <= CAP, f"缺时间戳时窗口 {len(result)} 条，超过 {CAP} 上限"
    assert _contents(result) == _contents(history)[-len(result):]


def test_invalid_timestamp_does_not_crash() -> None:
    """时间戳为脏数据（字符串/None/负数）时不能抛异常。"""
    history = _chat_history(100)
    for bad in (None, "abc", -1, 0):
        history[40]["timestamp"] = bad
        result = _apply(history, "今天有点累")
        assert result, f"timestamp={bad!r} 时窗口被清空"


# ============================================================
# 9. 旧实现已删除
# ============================================================

def test_relevance_picker_removed() -> None:
    """关键词抽样函数与分词工具必须已从代码里删除。"""
    from core.agents.chat_agent_components.context_budget import _utils, budget_apply

    assert not hasattr(budget_apply, "_select_relevant_history_for_cloud"), (
        "budget_apply 里仍存在 _select_relevant_history_for_cloud"
    )
    assert not hasattr(_utils, "extract_match_tokens"), (
        "_utils 里仍存在 extract_match_tokens"
    )
    source = Path(budget_apply.__file__).read_text(encoding="utf-8")
    assert "cloud_relevance" not in source, "budget_apply 里仍残留 cloud_relevance 引用"


# ============================================================
# 10. 配置面
# ============================================================

def test_settings_have_no_relevance_fields() -> None:
    """ChatContextBudgetSettings 不再暴露 cloud_relevance_* 字段。"""
    from config.settings_chat import ChatContextBudgetSettings

    settings = ChatContextBudgetSettings()
    for field in (
        "cloud_relevance_keep_recent",
        "cloud_relevance_top_k",
        "cloud_relevance_candidate_window",
    ):
        assert not hasattr(settings, field), f"配置项 {field} 仍存在"
    assert settings.cloud_max_history_messages == 60
    assert settings.cloud_max_history_chars == 12000
    assert settings.cloud_history_quantize_messages == 20
    assert settings.cloud_history_quantum_seconds == 300


def test_real_config_keeps_study_window_intact() -> None:
    """真实配置必须满足 messages >= study_active_recent_window。

    否则普通聊天的消息上限会把学习模式的工作窗口一起截短。
    """
    from config.integrated_config import get_settings

    budget = get_settings().chat.context_budget
    assert budget.cloud_max_history_messages >= budget.study_active_recent_window, (
        f"cloud_max_history_messages={budget.cloud_max_history_messages} 小于 "
        f"study_active_recent_window={budget.study_active_recent_window}，"
        "会把学习工作窗口截短"
    )
    assert budget.cloud_max_history_chars > 0, "云端历史字符上限必须为正"
    assert 0 < budget.cloud_history_quantize_messages <= budget.cloud_max_history_messages, (
        f"quantize={budget.cloud_history_quantize_messages} 必须落在 "
        f"(0, {budget.cloud_max_history_messages}] 内，否则窗口会被压空"
    )
    assert budget.cloud_history_quantum_seconds > 0, "时间锚点粒度必须为正"


def main() -> int:
    tests = [
        test_normal_chat_uses_contiguous_tail,
        test_no_orphan_user_messages,
        test_window_is_independent_of_user_message,
        test_study_context_keeps_wider_window,
        test_study_window_is_anchored_stable_prefix,
        test_study_window_respects_smaller_message_cap,
        test_char_budget_clips_from_tail_and_keeps_latest,
        test_empty_history_returns_as_is,
        test_window_is_stable_prefix_under_sliding_fetch,
        test_count_anchor_alone_is_not_enough,
        test_window_never_exceeds_cap_plus_quantize,
        test_small_message_cap_does_not_collapse_window,
        test_window_start_aligned_to_user_message,
        test_all_history_has_no_user_message_returns_original,
        test_missing_timestamp_falls_back_to_count_quantization,
        test_invalid_timestamp_does_not_crash,
        test_relevance_picker_removed,
        test_settings_have_no_relevance_fields,
        test_real_config_keeps_study_window_intact,
    ]

    failed = 0
    for test in tests:
        print(f"\n▶ {test.__name__}")
        try:
            test()
            print("  [PASS]")
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 72)
    if failed:
        print(f"结果: {failed}/{len(tests)} 失败")
    else:
        print(f"结果: {len(tests)}/{len(tests)} 通过")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
