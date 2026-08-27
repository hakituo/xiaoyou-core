"""验证"消息延后处理"机制（reply_policy + reply_hints + chat_handlers helper）

覆盖场景：
1. 延后处理（DND）：第 1 条起即静默累积，消息留到起床后处理
2. 延后处理（BUSY）：第 1 条起即静默累积（不再延迟回复），消息留到做完后处理
3. 强制打断（BUSY）：连发多条后递增概率强制打断，把前几条一起发给 LLM
4. 回复窗口期：BUSY 回复后窗口期内继续聊正常回复，DND 强制唤醒后不享受窗口期
5. build_morning_after_hint / build_busy_done_hint 单元测试
6. chat_handlers._build_after_activity_done_hint：按活动类型选择 hint 模板

运行方式（venv_core）：
    venv_core\\Scripts\\python.exe -m pytest tests/character_daily/test_message_deferral.py -v
"""

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyPlan,
)
from core.services.character_daily.config import ReplyPolicyConfig
from core.services.character_daily.reply_policy import evaluate_reply_state


# =====================================================================
# 工具函数：构建测试用 ReplyPolicyConfig
# =====================================================================


def _make_config(
    threshold: int = 6,
    reply_window_seconds: float = 120.0,
    proactive_reply_window_seconds: float = 300.0,
    plan_transition_notice_seconds: float = 300.0,
    soft_delay_quick_min_seconds: float = 8.0,
    soft_delay_quick_max_seconds: float = 18.0,
    soft_delay_normal_min_seconds: float = 18.0,
    soft_delay_normal_max_seconds: float = 35.0,
    soft_delay_slow_min_seconds: float = 28.0,
    soft_delay_slow_max_seconds: float = 55.0,
    soft_delay_recovery_min_seconds: float = 20.0,
    soft_delay_recovery_max_seconds: float = 40.0,
) -> ReplyPolicyConfig:
    """构建测试用配置

    Args:
        threshold: 强制唤醒/打断的硬上限
        reply_window_seconds: 回复窗口期长度（秒）
    """
    return ReplyPolicyConfig(
        enabled=True,
        dnd_delay_min=0.1,
        dnd_delay_max=0.2,
        busy_delay_min=0.1,
        busy_delay_max=0.2,
        force_reply_threshold=threshold,
        force_reply_cooldown_seconds=600.0,
        soft_delay_quick_min_seconds=soft_delay_quick_min_seconds,
        soft_delay_quick_max_seconds=soft_delay_quick_max_seconds,
        soft_delay_normal_min_seconds=soft_delay_normal_min_seconds,
        soft_delay_normal_max_seconds=soft_delay_normal_max_seconds,
        soft_delay_slow_min_seconds=soft_delay_slow_min_seconds,
        soft_delay_slow_max_seconds=soft_delay_slow_max_seconds,
        soft_delay_recovery_min_seconds=soft_delay_recovery_min_seconds,
        soft_delay_recovery_max_seconds=soft_delay_recovery_max_seconds,
        reply_window_seconds=reply_window_seconds,
        proactive_reply_window_seconds=proactive_reply_window_seconds,
        plan_transition_notice_seconds=plan_transition_notice_seconds,
    )


def _make_mocks(activity: ActivityType):
    """构建 character_daily engine + active_care 的 mock

    active_care 默认不处于睡眠会话（用 character_daily 的活动判定 DND/BUSY）。
    """
    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = activity
    # reply_policy 在检测到 DND 活动时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = activity

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": 0.0,
        "last_goodmorning_ts": 0.0,
        "last_sent_ts": 0.0,
    })
    return mock_engine, mock_ac


def _attach_plan(
    mock_engine: MagicMock,
    role_id: str,
    *,
    current_activity: ActivityType,
    next_activity: ActivityType,
    next_in_seconds: float,
) -> None:
    """给 mock engine 挂一个最小可用的 daily plan。"""
    now = datetime.now()
    current_slot = ActivitySlot(
        activity=current_activity,
        planned_start=now - timedelta(minutes=10),
        planned_end=now + timedelta(seconds=max(60.0, next_in_seconds)),
        flexible=True,
        chat_eligible=True,
    )
    next_slot = ActivitySlot(
        activity=next_activity,
        planned_start=now + timedelta(seconds=next_in_seconds),
        planned_end=now + timedelta(seconds=next_in_seconds + 1800),
        flexible=True,
        chat_eligible=False,
    )
    plan = DailyPlan(
        role_id=role_id,
        date=now.strftime("%Y-%m-%d"),
        slots=[current_slot, next_slot],
        current_activity=current_activity,
    )
    mock_state = MagicMock()
    mock_state.get_plan.return_value = plan
    mock_engine.state = mock_state


# =====================================================================
# 1. DND（睡觉/午休）延后处理
# =====================================================================


@pytest.mark.asyncio
async def test_dnd_first_message_silently_accumulates():
    """DND 第 1 条：静默累积（不再发占位 zZz...），消息留到起床后处理"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.SLEEPING)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # 第 1 条 wake_prob=0.0，random=0.0 也不触发强制唤醒
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默累积，不再发占位
        assert "dnd_sleeping_silent" in decision.reason
        assert "will_process_on_wake" in decision.reason


@pytest.mark.asyncio
async def test_dnd_second_message_silently_accumulates():
    """DND 第 2 条：静默累积（skip_message="" 不刷屏）"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.SLEEPING)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # prev_count=1, wake_prob=0.08，random=0.5 > 0.08 不唤醒
        "core.services.character_daily.reply_policy.random.random", return_value=0.5,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=1,
            accumulated_messages=["第一条"],
        )
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默
        assert "dnd_sleeping_silent" in decision.reason
        assert "will_process_on_wake" in decision.reason


@pytest.mark.asyncio
async def test_dnd_active_care_sleeping_alone_triggers_defer():
    """active_care 判定睡眠会话活跃时也走 DND（即使 character_daily 活动非 sleeping）"""
    config = _make_config(threshold=6)

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.IDLE  # character_daily 不是 sleeping

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": time.time() - 3600,  # 1 小时前说晚安，没说早安
        "last_goodmorning_ts": 0.0,
    })

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        # 即使 character_daily 是 IDLE，active_care 判定睡眠也走 DND
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默累积，不再发占位
        assert "ac_sleeping=True" in decision.reason


# =====================================================================
# 2. BUSY（学习/做饭）延后处理
# =====================================================================


@pytest.mark.asyncio
async def test_busy_first_message_silently_accumulates():
    """BUSY 第 1 条：静默累积（不再延迟回复），消息留到做完后处理"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # prev_count=0, wake_prob=0.0，random=0.0 也不强制打断
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默累积，不再发占位
        assert "busy_defer_silent" in decision.reason
        assert "will_process_on_done" in decision.reason


@pytest.mark.asyncio
async def test_busy_subsequent_message_silently_accumulates():
    """BUSY 第 2 条（之前已延后处理）：静默累积"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # prev_count=1, wake_prob=0.08，random=0.5 > 0.08 不打断
        "core.services.character_daily.reply_policy.random.random", return_value=0.5,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=1,
            accumulated_messages=["第一条"],
        )
        assert decision.should_reply is False
        assert decision.skip_message == ""  # 静默累积
        assert "busy_defer_silent" in decision.reason
        assert "will_process_on_done" in decision.reason


# =====================================================================
# 3. BUSY 强制打断（递增概率）
# =====================================================================


@pytest.mark.asyncio
async def test_busy_force_interrupt_at_high_count():
    """BUSY 第 4 条（prev_count=3）55% 打断，mock random=0.4 < 0.55 触发"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    accumulated = ["第一条", "第二条", "第三条"]
    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # prev_count=3, wake_prob=0.55，random=0.4 < 0.55 触发打断
        "core.services.character_daily.reply_policy.random.random", return_value=0.4,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=3,
            accumulated_messages=accumulated,
        )
        assert decision.should_reply is True
        assert "busy_force_interrupt" in decision.reason
        assert "wake_prob=0.55" in decision.reason
        # persona_hint 包含"被强制打断"文案 + 前几条消息
        assert "学习" in decision.persona_hint  # 活动动词
        assert "连续发了 4 条消息" in decision.persona_hint
        assert "前 3 条消息你都没回" in decision.persona_hint
        for msg in accumulated:
            assert msg in decision.persona_hint
        # accumulated_messages 字段回传（chat_handlers 用它清空 pending）
        assert len(decision.accumulated_messages) == 3


@pytest.mark.asyncio
async def test_busy_force_interrupt_at_hard_threshold():
    """BUSY 第 6 条（达到硬上限）100% 打断，即使 random=0.99"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.COOKING)

    accumulated = [f"消息{i}" for i in range(5)]
    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # prev_count=5, wake_prob=1.0，random=0.99 仍打断
        "core.services.character_daily.reply_policy.random.random", return_value=0.99,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=5,
            accumulated_messages=accumulated,
        )
        assert decision.should_reply is True
        assert "wake_prob=1.00" in decision.reason
        assert "做饭" in decision.persona_hint


# =====================================================================
# 4. build_morning_after_hint / build_busy_done_hint / build_busy_interrupt_hint
# =====================================================================


def test_build_morning_after_hint_with_messages():
    """起床后处理提示：格式化正确，含消息列表和"刚醒"指引"""
    from core.services.character_daily.reply_hints import build_morning_after_hint

    messages = ["你睡了吗？", "在吗？", "想你了"]
    hint = build_morning_after_hint(messages)

    assert "你刚才在睡觉" in hint
    assert "现在已经起床了" in hint
    assert "3 条消息" in hint
    for i, msg in enumerate(messages, 1):
        assert f"{i}. {msg}" in hint
    assert "刚醒" in hint  # 含指引


def test_build_morning_after_hint_empty_returns_empty_string():
    """空消息列表返回空字符串"""
    from core.services.character_daily.reply_hints import build_morning_after_hint

    assert build_morning_after_hint([]) == ""


def test_build_morning_after_hint_truncates_long_messages():
    """超长消息截断到 200 字符 + "..." """
    from core.services.character_daily.reply_hints import build_morning_after_hint

    long_msg = "字" * 300
    hint = build_morning_after_hint([long_msg])
    assert "字" * 200 + "..." in hint
    assert "字" * 300 not in hint  # 没有完整的长串


def test_build_busy_done_hint_with_messages():
    """忙完后处理提示：含活动动词、消息列表、"刚做完"指引"""
    from core.services.character_daily.reply_hints import build_busy_done_hint

    messages = ["你在干嘛？", "回我一下"]
    hint = build_busy_done_hint(messages, activity_verb="学习")

    assert "你刚才在学习" in hint  # 活动动词
    assert "现在做完了" in hint
    assert "2 条消息" in hint
    for i, msg in enumerate(messages, 1):
        assert f"{i}. {msg}" in hint
    assert "刚做完xx" in hint  # 含指引


def test_build_busy_done_hint_empty_returns_empty_string():
    """空消息列表返回空字符串"""
    from core.services.character_daily.reply_hints import build_busy_done_hint

    assert build_busy_done_hint([], activity_verb="学习") == ""


def test_build_busy_interrupt_hint_with_messages():
    """忙碌强制打断提示：含活动动词、连发条数、前几条消息列表"""
    from core.services.character_daily.reply_hints import build_busy_interrupt_hint

    messages = ["第一条", "第二条"]
    hint = build_busy_interrupt_hint(messages, activity_verb="做饭")

    assert "你正在做饭" in hint
    assert "连续发了 3 条消息" in hint  # total_count = 2 + 1
    assert "前 2 条消息你都没回" in hint
    for i, msg in enumerate(messages, 1):
        assert f"{i}. {msg}" in hint


def test_build_busy_interrupt_hint_empty_falls_back_to_simple_hint():
    """空消息列表：返回简短"被打断"提示（不是"强制打断"模板）"""
    from core.services.character_daily.reply_hints import build_busy_interrupt_hint

    hint = build_busy_interrupt_hint([], activity_verb="做饭")
    assert "被消息打断" in hint  # 简短提示（_BUSY_INTERRUPTED_PERSONA_HINT 文案）


# =====================================================================
# 5. chat_handlers._build_after_activity_done_hint：按活动类型选择模板
# =====================================================================


def test_build_after_activity_done_hint_dnd_activity():
    """DND 类活动（sleeping）：使用 build_morning_after_hint（"起床后处理"）"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _build_after_activity_done_hint,
    )

    pending = ["第一条", "第二条"]
    hint = _build_after_activity_done_hint("sleeping", pending)

    assert "你刚才在睡觉" in hint  # morning_after 模板
    assert "现在已经起床了" in hint
    for i, msg in enumerate(pending, 1):
        assert f"{i}. {msg}" in hint


def test_build_after_activity_done_hint_busy_activity():
    """BUSY 类活动（studying）：使用 build_busy_done_hint（"忙完后处理"，含活动动词）"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _build_after_activity_done_hint,
    )

    pending = ["第一条", "第二条"]
    hint = _build_after_activity_done_hint("studying", pending)

    assert "你刚才在学习" in hint  # busy_done 模板 + 活动动词
    assert "现在做完了" in hint
    for i, msg in enumerate(pending, 1):
        assert f"{i}. {msg}" in hint


def test_build_after_activity_done_hint_empty_returns_empty():
    """空消息列表返回空字符串"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _build_after_activity_done_hint,
    )

    assert _build_after_activity_done_hint("sleeping", []) == ""
    assert _build_after_activity_done_hint("studying", []) == ""


def test_build_after_activity_done_hint_unknown_activity_uses_busy_template():
    """未知活动类型：默认走 busy_done 路径（用通用文案）

    未知活动 → ActivityType.from_str 返回 IDLE → 不在 DND 集合 → 走 busy_done
    ACTIVITY_VERBS_ONGOING[IDLE] = "发呆"，所以文案是"刚才在发呆，现在做完了"
    """
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _build_after_activity_done_hint,
    )

    pending = ["消息"]
    hint = _build_after_activity_done_hint("unknown_activity", pending)

    # IDLE 走 busy_done 路径，动词是 ACTIVITY_VERBS_ONGOING[IDLE]="发呆"
    assert "你刚才在发呆" in hint
    assert "现在做完了" in hint


def test_dnd_pending_stores_activity_on_append():
    """_append_pending_message 第一次追加时记录 activity"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _append_pending_message,
        _clear_pending_messages,
        _get_pending_activity,
    )

    cid = "test-activity-cid"
    _clear_pending_messages(cid)

    _append_pending_message(cid, "消息1", activity="sleeping")
    assert _get_pending_activity(cid) == "sleeping"

    # 第二次追加（活动参数不会覆盖第一次记录）
    _append_pending_message(cid, "消息2", activity="studying")
    assert _get_pending_activity(cid) == "sleeping"  # 仍是第一次的活动

    _clear_pending_messages(cid)


def test_dnd_pending_no_activity_returns_empty_string():
    """没有累积记录时 _get_pending_activity 返回空串"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _get_pending_activity,
    )

    assert _get_pending_activity("non-existent-cid") == ""


# =====================================================================
# 6. 回复窗口期：BUSY 回复后窗口期内继续聊，DND 强制唤醒后不享受窗口期
# =====================================================================


@pytest.mark.asyncio
async def test_reply_window_within_window_after_busy_reply():
    """BUSY 回复后窗口期内继续聊：正常回复（不走延后处理）

    模拟：上次回复时角色在 studying（BUSY），现在还在 120s 窗口内
    即使现在角色仍在 BUSY，也应该正常回复
    """
    config = _make_config(threshold=6, reply_window_seconds=120.0)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    # 上次回复在 30s 前（窗口内），活动是 studying
    last_reply_ts = time.time() - 30.0
    last_reply_activity = "studying"

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # 第 1 条 wake_prob=0.0，避免被强制打断干扰
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            last_reply_ts=last_reply_ts,
            last_reply_activity=last_reply_activity,
        )
        # 命中窗口期：正常回复
        assert decision.should_reply is True
        assert "reply_window" in decision.reason
        assert "elapsed=" in decision.reason
        # 不应该走 BUSY 延后处理
        assert "busy_defer_silent" not in decision.reason


@pytest.mark.asyncio
async def test_reply_window_expired_after_busy_reply():
    """BUSY 回复后超过窗口期：走 BUSY 延后处理"""
    config = _make_config(threshold=6, reply_window_seconds=120.0)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    # 上次回复在 200s 前（超过 120s 窗口），活动是 studying
    last_reply_ts = time.time() - 200.0
    last_reply_activity = "studying"

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # 第 1 条 wake_prob=0.0
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            last_reply_ts=last_reply_ts,
            last_reply_activity=last_reply_activity,
        )
        # 窗口期已过：走 BUSY 延后处理
        assert decision.should_reply is False
        assert "busy_defer_silent" in decision.reason


@pytest.mark.asyncio
async def test_reply_window_does_not_apply_after_dnd_force_wake():
    """DND 强制唤醒后继续聊不享受窗口期（仍走 DND 流程）

    模拟：上次回复时角色在 sleeping（DND 类，刚被强制唤醒），
    现在用户继续发消息，仍在 120s 窗口内
    应该继续走 DND 流程（不享受窗口期）
    """
    config = _make_config(threshold=6, reply_window_seconds=120.0)
    mock_engine, mock_ac = _make_mocks(ActivityType.SLEEPING)

    # 上次回复在 30s 前（窗口内），但活动是 sleeping（DND 类，不享受窗口期）
    last_reply_ts = time.time() - 30.0
    last_reply_activity = "sleeping"

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        # 第 1 条 wake_prob=0.0，走静默累积
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            last_reply_ts=last_reply_ts,
            last_reply_activity=last_reply_activity,
        )
        # 不享受窗口期：走 DND 静默累积
        assert decision.should_reply is False
        assert "reply_window" not in decision.reason
        assert "dnd_sleeping_silent" in decision.reason


@pytest.mark.asyncio
async def test_reply_window_with_no_last_reply_state():
    """没有上次回复状态（首次消息）：不命中窗口期，走正常流程"""
    config = _make_config(threshold=6, reply_window_seconds=120.0)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    # last_reply_ts=0, last_reply_activity=""
    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline", config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            last_reply_ts=0.0,
            last_reply_activity="",
        )
        # 没有上次回复状态：走 BUSY 延后处理（不命中窗口期）
        assert decision.should_reply is False
        assert "reply_window" not in decision.reason
        assert "busy_defer_silent" in decision.reason


@pytest.mark.asyncio
async def test_proactive_reply_window_allows_sleep_recovery_followup():
    """同 persona 刚主动发过消息时，sleep_recovery 也应直接接话。"""
    config = _make_config(
        threshold=6,
        reply_window_seconds=120.0,
        proactive_reply_window_seconds=300.0,
    )
    mock_engine, mock_ac = _make_mocks(ActivityType.SLEEP_RECOVERY)
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": 0.0,
        "last_goodmorning_ts": 0.0,
        "last_sent_ts": time.time() - 219.0,
    })
    mock_ac.storage.resolve_scope_from_persona_filename.return_value = "aveline"

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.0,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            persona_filename="qq/Aveline_QQ_Master.json",
        )
        assert decision.should_reply is True
        assert "proactive_reply_window" in decision.reason
        assert "scope=aveline" in decision.reason


@pytest.mark.asyncio
async def test_proactive_reply_window_expired_falls_back_to_busy_gate():
    """主动回接窗口过期后，sleep_recovery 改走轻活动静默后回复。"""
    config = _make_config(
        threshold=6,
        reply_window_seconds=120.0,
        proactive_reply_window_seconds=300.0,
    )
    mock_engine, mock_ac = _make_mocks(ActivityType.SLEEP_RECOVERY)
    mock_ac.storage.get_proactive_state = AsyncMock(return_value={
        "last_goodnight_ts": 0.0,
        "last_goodmorning_ts": 0.0,
        "last_sent_ts": time.time() - 420.0,
    })
    mock_ac.storage.resolve_scope_from_persona_filename.return_value = "aveline"

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.5,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            persona_filename="qq/Aveline_QQ_Master.json",
        )
        assert decision.should_reply is True
        assert "proactive_reply_window" not in decision.reason
        assert "soft_delay_reply" in decision.reason
        assert decision.delay_seconds > 0


@pytest.mark.asyncio
async def test_sleep_recovery_reason_mentions_nightmare_source():
    """sleep_recovery 静默后回复时，日志原因应说明噩梦来源。"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.SLEEP_RECOVERY)
    mock_sleep_manager = MagicMock()
    mock_sleep_manager.get_summary.return_value = {
        "nightmare_level": "severe",
        "impact_level": "severe",
        "sleep_debt_hours": 0.0,
    }

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.life_simulation.get_sleep_manager",
        return_value=mock_sleep_manager,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.5,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
            persona_filename="qq/Aveline_QQ_Master.json",
        )
        assert decision.should_reply is True
        assert "soft_delay_reply(activity=sleep_recovery, profile=recovery" in decision.reason
        assert "sleep_recovery_source=nightmare=severe|impact=severe" in decision.reason


@pytest.mark.asyncio
async def test_idle_uses_soft_delay_reply_instead_of_silent_accumulation():
    """发呆等轻活动不应直接吞消息，而应静默几十秒再回。"""
    config = _make_config(
        threshold=6,
        soft_delay_quick_min_seconds=8.0,
        soft_delay_quick_max_seconds=18.0,
    )
    mock_engine, mock_ac = _make_mocks(ActivityType.IDLE)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.uniform",
        return_value=24.0,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is True
        assert decision.delay_seconds == 24.0
        assert "soft_delay_reply(activity=idle, profile=quick" in decision.reason
        assert "隔了大约 24 秒" in decision.persona_hint


@pytest.mark.asyncio
async def test_cooking_uses_slower_soft_delay_profile():
    """做饭应走更慢的轻活动回复档，而不是和发呆同一档。"""
    config = _make_config(
        threshold=6,
        soft_delay_slow_min_seconds=28.0,
        soft_delay_slow_max_seconds=55.0,
    )
    mock_engine, mock_ac = _make_mocks(ActivityType.COOKING)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.uniform",
        return_value=41.0,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is True
        assert decision.delay_seconds == 41.0
        assert "soft_delay_reply(activity=cooking, profile=slow" in decision.reason
        assert "隔了大约 41 秒" in decision.persona_hint


@pytest.mark.asyncio
async def test_studying_still_uses_busy_silent_accumulation():
    """学习时仍维持静默累积，不改成软延迟。"""
    config = _make_config(threshold=6)
    mock_engine, mock_ac = _make_mocks(ActivityType.STUDYING)

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ), patch(
        "core.services.character_daily.reply_policy.random.random", return_value=0.5,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is False
        assert "busy_defer_silent" in decision.reason


@pytest.mark.asyncio
async def test_imminent_plan_transition_injects_persona_hint():
    """下一个计划快开始时，应注入自然收尾/顺延提示。"""
    config = _make_config(
        threshold=6,
        plan_transition_notice_seconds=300.0,
    )
    mock_engine, mock_ac = _make_mocks(ActivityType.IDLE)
    _attach_plan(
        mock_engine,
        "aveline",
        current_activity=ActivityType.IDLE,
        next_activity=ActivityType.SELF_CARE,
        next_in_seconds=180.0,
    )

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is True
        assert "下一个计划快到了" in decision.persona_hint
        assert "顺延一下" in decision.persona_hint
        assert "礼貌收尾" in decision.persona_hint


@pytest.mark.asyncio
async def test_no_plan_transition_hint_when_next_plan_is_far_away():
    """下一个计划还很远时，不应注入收尾提示。"""
    config = _make_config(
        threshold=6,
        plan_transition_notice_seconds=300.0,
    )
    mock_engine, mock_ac = _make_mocks(ActivityType.IDLE)
    _attach_plan(
        mock_engine,
        "aveline",
        current_activity=ActivityType.IDLE,
        next_activity=ActivityType.SELF_CARE,
        next_in_seconds=900.0,
    )

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ):
        decision = await evaluate_reply_state(
            "aveline",
            config,
            consecutive_dnd_count=0,
            accumulated_messages=[],
        )
        assert decision.should_reply is True
        assert "下一个计划快到了" not in decision.persona_hint


# =====================================================================
# 7. chat_handlers._LAST_REPLY_STATE helper 测试
# =====================================================================


def test_last_reply_state_record_and_get():
    """_record_successful_reply + _get_last_reply_state 基本流程"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _clear_last_reply_state,
        _get_last_reply_state,
        _record_successful_reply,
    )

    cid = "test-window-cid"
    _clear_last_reply_state(cid)

    # 初始无记录
    ts, activity = _get_last_reply_state(cid)
    assert ts == 0.0
    assert activity == ""

    # 记录一次回复
    before = time.time()
    _record_successful_reply(cid, "studying")
    after = time.time()

    ts, activity = _get_last_reply_state(cid)
    assert activity == "studying"
    assert before - 1.0 <= ts <= after + 1.0  # 容差 1s

    _clear_last_reply_state(cid)


def test_last_reply_state_clear():
    """_clear_last_reply_state 清空记录"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import (
        _clear_last_reply_state,
        _get_last_reply_state,
        _record_successful_reply,
    )

    cid = "test-clear-cid"
    _record_successful_reply(cid, "cooking")
    assert _get_last_reply_state(cid) != (0.0, "")

    _clear_last_reply_state(cid)
    assert _get_last_reply_state(cid) == (0.0, "")


# =====================================================================
# 8. 用户计划软参考：build_user_plan_context 单元测试
# =====================================================================


def test_build_user_plan_context_with_items():
    """有计划项时：返回格式化文本"""
    from core.agents.chat_agent_components.persona_system.prompt.components.character_schedule_prompts import (
        build_user_plan_context,
    )

    # 构造一个 mock user_plan
    class _FakeItem:
        def __init__(self, time, title, subject=None, dur=0, category="study"):
            self.time = time
            self.title = title
            self.subject = subject
            self.estimated_duration_minutes = dur
            self.category = category

    class _FakePlan:
        def __init__(self):
            self.notes = "今天专注数学"
            self.items = [
                _FakeItem("09:00", "学习数学", subject="代数", dur=60),
                _FakeItem("12:00", "吃午饭", category="life"),
                _FakeItem(None, "看书", dur=30, category="rest"),
            ]

    context = build_user_plan_context(_FakePlan())
    assert "【用户当日计划（软参考）】" in context
    assert "今天专注数学" in context  # notes
    assert "[09:00] 学习数学（代数）（60分钟）" in context
    assert "[12:00] 吃午饭" in context
    assert "[灵活] 看书（30分钟）" in context  # 无 time 显示"灵活"


def test_build_user_plan_context_empty_returns_empty_string():
    """空计划或 None：返回空字符串"""
    from core.agents.chat_agent_components.persona_system.prompt.components.character_schedule_prompts import (
        build_user_plan_context,
    )

    assert build_user_plan_context(None) == ""

    class _EmptyPlan:
        items = []
        notes = None

    assert build_user_plan_context(_EmptyPlan()) == ""
