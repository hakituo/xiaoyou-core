"""验证"被吵醒"机制 + peer_chat 紧急打断路径

覆盖场景：
1. 被动回复：连续消息累积 + 强制唤醒 + persona_hint 注入"前几条没回的消息"
2. 被动回复：累积消息超时清理
3. peer_chat：should_use_urgent_interrupt 概率分支
4. peer_chat：build_situation_context(interrupt_mode=True) 输出"急事打断"情境
5. chat_handlers：累积消息管理 helper（append/get/clear/cleanup）

运行方式（venv_core）：
    venv_core\\Scripts\\python.exe -m pytest tests/character_daily/test_force_wake_and_interrupt.py -v
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.character_daily.config import (
    CharacterDailyConfig,
    PeerChatConfig,
    ReplyPolicyConfig,
)
from core.services.character_daily.activity_model import ActivityType
from core.services.character_daily.reply_policy import (
    build_force_wake_hint,
    evaluate_reply_state,
)
from core.services.life_simulation.sleep_models import SleepPhase, SleepRuntimeState


# =====================================================================
# 1. 被动回复：连续消息强制唤醒
# =====================================================================


def _make_dnd_config(threshold: int = 3) -> ReplyPolicyConfig:
    """构建测试用配置：threshold=N，专注验证强制唤醒"""
    return ReplyPolicyConfig(
        enabled=True,
        dnd_delay_min=0.1,
        dnd_delay_max=0.2,
        busy_delay_min=0.1,
        busy_delay_max=0.2,
        force_reply_threshold=threshold,
        force_reply_cooldown_seconds=600.0,
    )


@pytest.mark.asyncio
async def test_force_wake_never_on_first_message():
    """第 1 条消息（之前拒回 0 条）0% 唤醒，走"延后处理"流程

    新逻辑：第 1 条不强制唤醒（0% 概率），走 DND 静默累积：
    - should_reply=False
    - skip_message=""（统一静默，不再发占位 zZz...）
    - 消息留到起床后处理
    """
    config = _make_dnd_config(threshold=6)

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.SLEEPING
    # reply_policy 检测到 DND 时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = ActivityType.SLEEPING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": time.time() - 3600,
        "last_goodmorning_ts": 0.0,
    })

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        # 第 1 条不强制唤醒
        assert "force_wake" not in decision.reason
        # 走 DND 静默累积：不回复，不发占位消息
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默累积，不再发占位
        assert "dnd_sleeping_silent" in decision.reason
        assert "will_process_on_wake" in decision.reason


@pytest.mark.asyncio
async def test_force_wake_at_hard_threshold():
    """达到硬上限（默认 6 条）时 100% 强制唤醒"""
    config = _make_dnd_config(threshold=6)

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.SLEEPING
    # reply_policy 检测到 DND 时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = ActivityType.SLEEPING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": time.time() - 3600,
        "last_goodmorning_ts": 0.0,
    })

    accumulated = [f"消息{i}" for i in range(5)]  # 之前拒回 5 条
    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.99,
    ):
        # 第 6 条：count=5+1=6 >= 6 → wake_prob=1.0，即使 random=0.99 也必然唤醒
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=5,
            accumulated_messages=accumulated,
        )
        assert decision.should_reply is True
        assert "force_wake" in decision.reason
        assert "wake_prob=1.00" in decision.reason
        # 累积消息注入 persona_hint
        assert "连续发了 6 条消息" in decision.persona_hint
        assert "前 5 条消息你都没回" in decision.persona_hint
        for i in range(5):
            assert f"消息{i}" in decision.persona_hint
        assert len(decision.accumulated_messages) == 5


@pytest.mark.asyncio
async def test_force_wake_probability_increases_with_count():
    """递增概率：第 3 条（count=2）25% 醒，mock random=0.2 < 0.25 应唤醒"""
    config = _make_dnd_config(threshold=6)

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.SLEEPING
    # reply_policy 检测到 DND 时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = ActivityType.SLEEPING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": time.time() - 3600,
        "last_goodmorning_ts": 0.0,
    })

    accumulated = ["第一条", "第二条"]
    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # random.random()=0.2 < wake_prob=0.25，触发强制唤醒
        "core.services.character_daily.reply_policy.random.random", return_value=0.20,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=2,
            accumulated_messages=accumulated,
        )
        assert decision.should_reply is True
        assert "force_wake" in decision.reason
        assert "wake_prob=0.25" in decision.reason
        assert "连续发了 3 条消息" in decision.persona_hint


@pytest.mark.asyncio
async def test_force_wake_not_triggered_when_random_above_prob():
    """递增概率：第 3 条（count=2）25% 醒，mock random=0.5 > 0.25 不唤醒

    新逻辑：不强制唤醒时走"静默累积"流程：
    - should_reply=False
    - skip_message=""（统一静默，不再发占位）
    - reason 含 "dnd_sleeping_silent"
    """
    config = _make_dnd_config(threshold=6)

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.SLEEPING
    # reply_policy 检测到 DND 时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = ActivityType.SLEEPING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": time.time() - 3600,
        "last_goodmorning_ts": 0.0,
    })

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # random.random()=0.5 > wake_prob=0.25，不触发强制唤醒
        # 走静默累积
        "core.services.character_daily.reply_policy.random.random", return_value=0.50,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=2,
            accumulated_messages=["第一条", "第二条"],
        )
        # 不强制唤醒
        assert "force_wake" not in decision.reason
        # 走静默累积
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默
        assert "dnd_sleeping_silent" in decision.reason
        assert "will_process_on_wake" in decision.reason


@pytest.mark.asyncio
async def test_fresh_sleep_bonus_makes_first_message_easier_to_wake():
    """刚睡下时，第 1 条消息也可能把角色叫醒。"""
    config = _make_dnd_config(threshold=6)

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.SLEEPING
    # reply_policy 检测到 DND 时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = ActivityType.SLEEPING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": time.time() - 3600,
        "last_goodmorning_ts": 0.0,
    })

    recent_sleep_state = SleepRuntimeState(
        role_id="aveline",
        phase=SleepPhase.SLEEPING,
        is_sleeping=True,
        actual_sleep_start_ts=time.time() - 120,
    )
    mock_sleep_manager = MagicMock()
    mock_sleep_manager.get_state.return_value = recent_sleep_state
    mock_sleep_manager._get_profile.return_value = SimpleNamespace(
        wake_by_message_sensitivity=0.8
    )

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.life_simulation.sleep_manager.get_sleep_manager",
        return_value=mock_sleep_manager,
    ), patch(
        "core.services.character_daily.reply_policy.random.random",
        return_value=0.20,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is True
        assert "dnd_force_wake" in decision.reason
        assert "fresh_sleep_bonus=" in decision.reason
        assert "fresh_sleep_seconds=120" in decision.reason


# =====================================================================
# 2. 累积消息超时清理（chat_handlers helper）
# =====================================================================


def test_dnd_pending_cleanup_expired():
    """超过 cooldown 的累积记录应被清理"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _append_pending_message,
        _cleanup_expired_dnd_pending,
        _clear_pending_messages,
        _get_pending_messages,
        _DND_PENDING,
    )

    cid = "test-cleanup-cid"
    _clear_pending_messages(cid)  # 确保干净

    # 累积 2 条
    _append_pending_message(cid, "msg1")
    _append_pending_message(cid, "msg2")
    assert len(_get_pending_messages(cid)) == 2

    # 模拟超时：手动改 last_ts 为 10 分钟前
    _DND_PENDING[cid]["last_ts"] = time.time() - 700  # > 600s cooldown
    _cleanup_expired_dnd_pending(600.0)
    assert _get_pending_messages(cid) == []  # 已被清理

    # 未超时的不被清理
    _append_pending_message(cid, "fresh")
    _DND_PENDING[cid]["last_ts"] = time.time()
    _cleanup_expired_dnd_pending(600.0)
    assert len(_get_pending_messages(cid)) == 1

    _clear_pending_messages(cid)


def test_dnd_pending_append_and_clear():
    """累积消息 append/get/clear 基本流程"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _append_pending_message,
        _clear_pending_messages,
        _get_pending_messages,
    )

    cid = "test-append-cid"
    _clear_pending_messages(cid)

    _append_pending_message(cid, "hello")
    _append_pending_message(cid, "world")
    msgs = _get_pending_messages(cid)
    assert msgs == ["hello", "world"]

    _clear_pending_messages(cid)
    assert _get_pending_messages(cid) == []


def test_dnd_pending_cap_at_20():
    """累积消息超过 20 条应只保留最后 20 条（防止 prompt 膨胀）"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _append_pending_message,
        _clear_pending_messages,
        _get_pending_messages,
    )

    cid = "test-cap-cid"
    _clear_pending_messages(cid)

    for i in range(25):
        _append_pending_message(cid, f"msg{i}")

    msgs = _get_pending_messages(cid)
    assert len(msgs) == 20
    # 保留最后 20 条（msg5 ~ msg24）
    assert msgs[0] == "msg5"
    assert msgs[-1] == "msg24"

    _clear_pending_messages(cid)


# =====================================================================
# 3. peer_chat: should_use_urgent_interrupt 概率分支
# =====================================================================


def test_should_use_urgent_interrupt_returns_false_when_not_async():
    """非异步聊天（双方空闲）时不应走紧急打断"""
    from core.services.character_daily.peer_chat_gate import (
        should_use_urgent_interrupt,
    )
    config = CharacterDailyConfig(
        peer_chat=PeerChatConfig(urgent_interrupt_probability=1.0),
    )
    # is_async=False，即使概率=1.0 也返回 False
    assert should_use_urgent_interrupt(is_async=False, config=config) is False


def test_should_use_urgent_interrupt_probability_distribution():
    """is_async=True 时，概率应接近配置值（统计检验，允许误差）"""
    from core.services.character_daily.peer_chat_gate import (
        should_use_urgent_interrupt,
    )
    config = CharacterDailyConfig(
        peer_chat=PeerChatConfig(urgent_interrupt_probability=0.15),
    )
    n = 2000
    hits = sum(1 for _ in range(n) if should_use_urgent_interrupt(True, config))
    ratio = hits / n
    # 允许 ±5% 误差
    assert 0.10 <= ratio <= 0.20, f"紧急打断概率 {ratio:.3f} 偏离预期 0.15"


# =====================================================================
# 4. peer_chat: build_situation_context(interrupt_mode=True) 输出
# =====================================================================


def test_build_situation_context_interrupt_mode():
    """紧急打断模式下，情境字符串应包含"急事"和"打断"提示"""
    from core.services.character_daily.activity_model import (
        ActivityType,
        DailyPlan,
    )
    from core.services.character_daily.peer_chat_gate import (
        build_situation_context,
    )

    # 发起者空闲，对方在 cooking（忙碌）
    plan_i = DailyPlan(role_id="aveline", date="2026-06-27", current_activity=ActivityType.IDLE)
    plan_p = DailyPlan(role_id="ling", date="2026-06-27", current_activity=ActivityType.COOKING)

    # 异步聊天（非打断）
    async_text = build_situation_context("aveline", plan_i, plan_p, interrupt_mode=False)
    assert "可能在忙" in async_text
    assert "不一定马上回" in async_text

    # 紧急打断
    interrupt_text = build_situation_context("aveline", plan_i, plan_p, interrupt_mode=True)
    assert "急事" in interrupt_text
    assert "打断" in interrupt_text
    # 打断模式应该提示 LLM 忙碌方会正经回应
    assert "放下手头的事" in interrupt_text or "怎么了" in interrupt_text


def test_build_situation_context_normal_when_peer_free():
    """对方空闲时，interrupt_mode 应被忽略（走正常聊天路径）"""
    from core.services.character_daily.activity_model import (
        ActivityType,
        DailyPlan,
    )
    from core.services.character_daily.peer_chat_gate import (
        build_situation_context,
    )

    plan_i = DailyPlan(role_id="aveline", date="2026-06-27", current_activity=ActivityType.IDLE)
    plan_p = DailyPlan(role_id="ling", date="2026-06-27", current_activity=ActivityType.READING)  # 空闲

    # 对方空闲，即使 interrupt_mode=True 也走正常路径
    text = build_situation_context("aveline", plan_i, plan_p, interrupt_mode=True)
    assert "也在" in text  # "看到XX也在看书"
    assert "急事" not in text


# =====================================================================
# 5. build_force_wake_hint 单元测试
# =====================================================================


def test_build_force_wake_hint_with_messages():
    """累积消息应被格式化编号并注入 hint"""
    messages = ["第一条", "第二条", "第三条"]
    hint = build_force_wake_hint(messages)
    # 3 条累积 + 本次 1 条 = 总共 4 条
    assert "连续发了 4 条消息" in hint
    assert "前 3 条消息你都没回" in hint
    assert "1. 第一条" in hint
    assert "2. 第二条" in hint
    assert "3. 第三条" in hint


def test_build_force_wake_hint_truncates_long_messages():
    """超长消息应被截断（防 prompt 膨胀）"""
    long_msg = "A" * 500
    hint = build_force_wake_hint([long_msg])
    assert "..." in hint
    # 截断后应只保留前 200 字符 + "..."
    assert "A" * 200 in hint
    assert "A" * 201 not in hint.replace("...", "")


def test_build_force_wake_hint_empty_falls_back_to_simple_hint():
    """空列表时应回退到普通 DND hint"""
    hint = build_force_wake_hint([])
    assert "被消息吵醒" in hint


# =====================================================================
# 6. force_wake_probability 概率表单元测试（纯函数，无需 mock）
# =====================================================================


def test_force_wake_probability_table_values():
    """验证概率递增表的取值"""
    from core.services.character_daily.reply_hints import force_wake_probability

    # 默认硬上限 6
    # prev_count=0 → 0.0（第 1 条不醒）
    assert force_wake_probability(0, hard_threshold=6) == 0.0
    # prev_count=1 → 0.08（第 2 条 8% 醒）
    assert force_wake_probability(1, hard_threshold=6) == 0.08
    # prev_count=2 → 0.25（第 3 条 25% 醒）
    assert force_wake_probability(2, hard_threshold=6) == 0.25
    # prev_count=3 → 0.55（第 4 条 55% 醒）
    assert force_wake_probability(3, hard_threshold=6) == 0.55
    # prev_count=4 → 0.85（第 5 条 85% 醒）
    assert force_wake_probability(4, hard_threshold=6) == 0.85
    # prev_count=5 → 1.0（第 6 条 100% 醒，达到硬上限）
    assert force_wake_probability(5, hard_threshold=6) == 1.0
    # prev_count>=5 → 1.0（超过硬上限仍 100%）
    assert force_wake_probability(10, hard_threshold=6) == 1.0


def test_force_wake_probability_respects_custom_threshold():
    """自定义硬上限（如 threshold=3）"""
    from core.services.character_daily.reply_hints import force_wake_probability

    # threshold=3：第 3 条（prev_count=2）就 100% 醒
    assert force_wake_probability(0, hard_threshold=3) == 0.0
    assert force_wake_probability(1, hard_threshold=3) == 0.08
    assert force_wake_probability(2, hard_threshold=3) == 1.0  # 达到硬上限
    assert force_wake_probability(5, hard_threshold=3) == 1.0


def test_force_wake_probability_monotonic_increasing():
    """概率必须单调递增（不会出现后面的比前面小）"""
    from core.services.character_daily.reply_hints import force_wake_probability

    threshold = 10
    probs = [force_wake_probability(i, threshold) for i in range(threshold + 2)]
    for i in range(1, len(probs)):
        assert probs[i] >= probs[i - 1], (
            f"概率非单调递增: prev_count={i-1} prob={probs[i-1]}, "
            f"prev_count={i} prob={probs[i]}"
        )
