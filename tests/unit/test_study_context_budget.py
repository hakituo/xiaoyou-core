from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config.settings_chat import ChatContextBudgetSettings
from core.agents.chat_agent_components.context_budget.budget_apply import (
    apply_cloud_history_budget,
)
from core.agents.chat_agent_components.context_budget.history_compression import (
    apply_long_message_compression,
    compress_study_session_messages,
)
from core.agents.chat_agent_components.context_budget.history_fetch import (
    fetch_history_for_scope,
)


def _settings(**overrides):
    values = {
        "cloud_max_history_messages": 60,
        "cloud_max_history_chars": 12000,
        "cloud_history_quantize_messages": 20,
        "cloud_history_quantum_seconds": 300,
        "long_message_compress_threshold": 400,
        "long_message_compress_recent_window": 6,
        "long_message_compress_max_chars": 160,
        "study_active_recent_window": 20,
        "study_active_cloud_max_history_chars": 18000,
        "study_session_compress_enabled": True,
        "study_session_compress_recent_window": 4,
        "study_session_compress_max_chars": 1200,
    }
    values.update(overrides)
    return SimpleNamespace(
        chat=SimpleNamespace(context_budget=SimpleNamespace(**values))
    )


def test_study_context_budget_defaults_protect_working_memory():
    settings = ChatContextBudgetSettings()

    assert settings.study_active_recent_window == 20
    assert settings.study_active_cloud_max_history_chars == 18000
    assert settings.study_session_compress_max_chars == 1200


def test_active_study_long_responses_keep_recent_twenty_raw():
    history = []
    for index in range(24):
        role = "user" if index % 2 == 0 else "assistant"
        content = f"第{index}条-" + ("讲解" * 220 if role == "assistant" else "问题")
        history.append({"role": role, "content": content, "category": "learning"})

    with patch("config.integrated_config.get_settings", return_value=_settings()):
        result = apply_long_message_compression(
            history,
            study_context_active=True,
        )

    # 24 条里最早 4 条在保护窗口之外，其中的 assistant 长回复允许被压缩。
    assert result[1]["content"].startswith("[上下文压缩]")
    # 最近 20 条是课堂工作记忆，必须保持原文，不把推导/题目链提前压掉。
    for original, current in zip(history[-20:], result[-20:]):
        assert current["content"] == original["content"]


def test_explicit_exit_compresses_only_session_bounds_and_keeps_learning_trace():
    history = [
        {"role": "user", "content": "先聊点别的", "timestamp": 90},
        {
            "role": "user",
            "content": "为什么 F=-kx 里面有负号？",
            "timestamp": 100,
            "category": "learning",
        },
        {
            "role": "assistant",
            "content": "F=-kx 中的负号表示回复力方向总与位移方向相反。" * 6,
            "timestamp": 101,
            "category": "learning",
        },
        {
            "role": "user",
            "content": "那我理解成弹簧总想回到平衡位置，对吗？",
            "timestamp": 102,
            "category": "learning",
        },
        {
            "role": "assistant",
            "content": "对，这个理解是正确的；负号编码的正是这个方向关系。" * 4,
            "timestamp": 103,
            "category": "learning",
        },
        {"role": "user", "content": "换个话题", "timestamp": 110},
    ]

    result = compress_study_session_messages(
        history,
        recent_window=4,
        max_summary_chars=1200,
        force=True,
        session_start_ts=100,
        session_end_ts=103,
    )

    assert result[0]["content"] == "先聊点别的"
    assert result[-1]["content"] == "换个话题"
    summaries = [m for m in result if "[学习会话摘要]" in str(m.get("content"))]
    assert len(summaries) == 1
    summary = summaries[0]["content"]
    assert "F=-kx" in summary
    assert "用户最近问题/作答" in summary
    assert "平衡位置" in summary
    assert not any(m.get("timestamp") == 102 for m in result)


def test_cloud_study_budget_keeps_contiguous_recent_window_for_short_answer():
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"课堂消息-{index}",
            "category": "learning",
        }
        for index in range(30)
    ]

    with patch("config.integrated_config.get_settings", return_value=_settings()):
        result = apply_cloud_history_budget(history, "B")

    assert [m["content"] for m in result] == [
        m["content"] for m in history[-20:]
    ]


def test_cloud_study_window_is_stable_prefix_under_sliding_fetch():
    """学习上下文的窗口同样要能作为稳定前缀复用。

    学习窗口曾按「精确最近 20 条」逐轮滑动，每个学习请求都把历史前缀
    整个打穿（实测早自习一串 8 个 study 请求全部各自 miss，prompt cache
    只剩静态 system 命中）。这里模拟上游 100 条滑动列表 + 连续学习请求，
    统计前缀复用率——与普通聊天的同款判据。
    """
    base_ts = 1_700_000_000
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"学习链-{index}",
            "timestamp": base_ts + index * 60,
            "category": "learning",
        }
        for index in range(200)
    ]

    fetch = 100
    prev = None
    hits = turns = 0
    sizes = []
    for k in range(40, 80):
        with patch("config.integrated_config.get_settings", return_value=_settings()):
            result = apply_cloud_history_budget(history[k:k + fetch], "B")
        current = [m["content"] for m in result]
        sizes.append(len(current))
        if prev is not None:
            turns += 1
            if len(current) >= len(prev) and current[:len(prev)] == prev:
                hits += 1
        prev = current

    assert turns > 0
    assert hits / turns >= 0.7, (
        f"{turns} 轮学习请求里只有 {hits} 轮前缀可复用（{hits / turns:.0%}），"
        "学习窗口没吃到时间锚点，历史块仍命中不了缓存"
    )
    # 工作窗口下限 20；锚点回退最多 +10，起点对齐到 user 最多再让 1 条。
    assert min(sizes) >= 19, f"学习窗口最小 {min(sizes)} 条，工作记忆被切短"
    assert max(sizes) <= 30, f"学习窗口最大 {max(sizes)} 条，超过 20+quantize(10)"


def test_cloud_normal_chat_uses_contiguous_window_with_replies():
    """普通聊天必须取连续最近窗口。

    历史曾按关键词抽样：用户消息单独被抽出来、对应的助手回复被丢掉，
    模型看到的是「用户连问多句、中间没有任何回应」。这里锁死连续语义。
    """
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"闲聊-{index}",
        }
        for index in range(80)
    ]

    with patch("config.integrated_config.get_settings", return_value=_settings()):
        result = apply_cloud_history_budget(history, "今天有点累")

    assert [m["content"] for m in result] == [m["content"] for m in history[-60:]]
    # 连续窗口必须成对带回复，不能只剩用户消息。
    roles = [m["role"] for m in result]
    assert roles.count("user") == 30
    assert roles.count("assistant") == 30


def test_cloud_normal_chat_clips_by_char_budget_from_the_tail():
    """字符上限从尾部往前裁，且不会因为裁剪丢掉最新一条。"""
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"长消息-{index}-" + "内容" * 200,
        }
        for index in range(40)
    ]

    with patch("config.integrated_config.get_settings", return_value=_settings()):
        result = apply_cloud_history_budget(history, "今天有点累")

    total_chars = sum(len(m["content"]) for m in result)
    assert 0 < total_chars <= 12000
    assert result[-1]["content"] == history[-1]["content"]
    # 裁剪后仍是原历史的连续尾部。
    assert [m["content"] for m in result] == [
        m["content"] for m in history[-len(result):]
    ]


def test_cloud_window_is_stable_prefix_under_sliding_fetch():
    """上游历史是滑动列表时，窗口必须能作为稳定前缀复用。

    `list_conversation_events` 带 limit，返回「最近 N 条」；用 len(history) 当锚点
    会让起点随列表一起滑，prompt cache 前缀永远对不上。这里模拟 100 条滑动列表，
    统计连续两轮之间「本轮窗口以上轮窗口为前缀」的比例。
    """
    base_ts = 1_700_000_000
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"闲聊-{index}",
            "timestamp": base_ts + index * 60,
        }
        for index in range(200)
    ]

    fetch = 100
    prev = None
    hits = turns = 0
    for k in range(40, 80):
        with patch("config.integrated_config.get_settings", return_value=_settings()):
            result = apply_cloud_history_budget(history[k:k + fetch], "今天有点累")
        current = [m["content"] for m in result]
        if prev is not None:
            turns += 1
            if len(current) >= len(prev) and current[:len(prev)] == prev:
                hits += 1
        prev = current

    assert turns > 0
    assert hits / turns >= 0.7, (
        f"{turns} 轮里只有 {hits} 轮前缀可复用（{hits / turns:.0%}），"
        "时间锚点没起作用，历史块仍命中不了缓存"
    )


def test_cloud_window_start_aligned_to_user_message():
    """窗口起点不能落在助手回复上（模型会看到自己的回复却没有提问）。"""
    base_ts = 1_700_000_000
    history = [
        {"role": "assistant", "content": "（孤立的上一轮回复）", "timestamp": base_ts}
    ]
    history.extend(
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"闲聊-{index}",
            "timestamp": base_ts + (index + 1) * 60,
        }
        for index in range(119)
    )

    with patch("config.integrated_config.get_settings", return_value=_settings()):
        result = apply_cloud_history_budget(history, "今天有点累")

    assert result, "窗口被清空了"
    assert result[0]["role"] == "user", f"窗口首条是 {result[0]['role']}"


def test_fetch_history_active_session_does_not_create_study_summary():
    history = []
    for index in range(24):
        role = "user" if index % 2 == 0 else "assistant"
        history.append(
            {
                "role": role,
                "content": (
                    f"物理问题-{index}"
                    if role == "user"
                    else f"物理讲解-{index}-" + "说明" * 220
                ),
                "timestamp": 100 + index,
                "category": "learning",
            }
        )

    class DummyMemoryManager:
        def get_history(self, *args, **kwargs):
            excluded = set(kwargs.get("exclude_categories") or [])
            return [m for m in history if m.get("category") not in excluded]

    async def _run():
        with patch(
            "core.tools.study_mode_tool.get_study_session",
            return_value={"active": True, "entered_at": 100},
        ), patch(
            "config.integrated_config.get_settings",
            return_value=_settings(),
        ), patch(
            "core.agents.chat_agent_components.context_budget.history_fetch."
            "_backfill_from_chat_history_store",
            AsyncMock(side_effect=lambda items, *args, **kwargs: items),
        ):
            return await fetch_history_for_scope(
                DummyMemoryManager(),
                user_id="student-1",
                scope="cloud",
                is_study_mode=False,
            )

    result = asyncio.run(_run())
    assert not any("[学习会话摘要]" in str(m.get("content")) for m in result)
    assert result[-1]["content"].endswith("说明" * 220)


def test_fetch_history_explicit_exit_immediately_summarizes_finished_session():
    history = [
        {"role": "user", "content": "普通聊天", "timestamp": 90},
        {
            "role": "user",
            "content": "数学里导数是什么意思？",
            "timestamp": 100,
            "category": "learning",
        },
        {
            "role": "assistant",
            "content": "导数描述函数在某一点附近的瞬时变化率。" * 8,
            "timestamp": 101,
            "category": "learning",
        },
        {
            "role": "user",
            "content": "也就是斜率变化吗？",
            "timestamp": 102,
            "category": "learning",
        },
        {
            "role": "assistant",
            "content": "更准确地说，是函数图像切线的斜率。" * 8,
            "timestamp": 103,
            "category": "learning",
        },
        {"role": "user", "content": "先休息", "timestamp": 110},
    ]

    class DummyMemoryManager:
        def get_history(self, *args, **kwargs):
            excluded = set(kwargs.get("exclude_categories") or [])
            return [m for m in history if m.get("category") not in excluded]

    async def _run():
        with patch(
            "core.tools.study_mode_tool.get_study_session",
            return_value={
                "active": False,
                "entered_at": 100,
                "exited_at": 103,
            },
        ), patch(
            "config.integrated_config.get_settings",
            return_value=_settings(),
        ), patch(
            "core.agents.chat_agent_components.context_budget.history_fetch."
            "_backfill_from_chat_history_store",
            AsyncMock(side_effect=lambda items, *args, **kwargs: items),
        ):
            return await fetch_history_for_scope(
                DummyMemoryManager(),
                user_id="student-2",
                scope="cloud",
                is_study_mode=False,
            )

    result = asyncio.run(_run())
    assert result[0]["content"].endswith("普通聊天")
    assert result[-1]["content"].endswith("先休息")
    summaries = [m for m in result if "[学习会话摘要]" in str(m.get("content"))]
    assert len(summaries) == 1
    assert "导数" in summaries[0]["content"]
    assert not any(m.get("timestamp") == 102 for m in result)
