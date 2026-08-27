import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.active_care.checker.checker_event_handler import CheckerEventHandler
from core.services.active_care.core.proactive_checker import ProactiveChecker
from core.services.active_care.core.proactive_loop import ProactiveLoopRunner
from core.services.active_care.core.trigger_result import (
    TriggerMessageResult,
    TriggerOutcome,
)
from core.services.active_care.core.user_response_handler import UserResponseHandler
from core.services.active_care.decision.decision_context import DecisionFlowContext
from core.services.character_daily.activity_model import ActivityType


class _DummyReminderStorage:
    def __init__(self) -> None:
        self.saved = []

    async def save_proactive_state(self, updates, scope=None, immediate=False):
        self.saved.append(
            {
                "updates": dict(updates),
                "scope": scope,
                "immediate": immediate,
            }
        )
        return dict(updates)


class _DummyLifeSimulation:
    def __init__(self, summary, refreshed_summary=None) -> None:
        self.summary = dict(summary)
        self.refreshed_summary = (
            dict(refreshed_summary) if isinstance(refreshed_summary, dict) else None
        )

    def get_sleep_summary(self, role_id: str):
        return dict(self.summary)

    async def finalize_sleep_recovery_check(self, role_id: str):
        if self.refreshed_summary is not None:
            self.summary = dict(self.refreshed_summary)
        return dict(self.summary)


class _DummyCharacterDailyEngine:
    def __init__(self, activity: ActivityType) -> None:
        self.activity = activity

    def get_current_activity(self, role_id: str):
        return self.activity


@pytest.mark.asyncio
async def test_due_reminder_is_silently_deferred_when_role_sleeping(monkeypatch):
    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation({"phase": "sleeping", "is_sleeping": True}),
    )

    due_reminder = SimpleNamespace(
        id="r_sleep",
        message="「化学选择题训练」时间到了，休息一下吧~",
        metadata={"type": "end", "task_title": "化学选择题训练"},
    )
    storage = _DummyReminderStorage()
    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=due_reminder),
        complete_reminder=AsyncMock(return_value=True),
        trigger_message=AsyncMock(return_value=True),
        storage=storage,
    )
    checker = SimpleNamespace(
        executor=executor,
        storage=SimpleNamespace(
            resolve_scope_from_persona_filename=lambda persona_filename: "aveline"
        ),
        set_next_decision_ts=AsyncMock(),
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(
        now=time.time(),
        state_data={
            "deferred_plan_reminders": [
                {"id": "r1", "task_title": "数学复盘"},
                {"id": "r2", "task_title": "英语听力"},
            ]
        },
        client_type="qq",
    )
    ctx.persona_filename = "qq/Aveline_QQ_Master.json"

    result = await handler.handle_due_reminder(ctx)

    assert result is True
    executor.complete_reminder.assert_awaited_once_with("r_sleep", triggered_at=ctx.now)
    executor.trigger_message.assert_not_called()
    checker.set_next_decision_ts.assert_not_called()
    assert storage.saved
    assert storage.saved[0]["scope"] == "aveline"
    deferred_items = storage.saved[0]["updates"]["deferred_plan_reminders"]
    assert len(deferred_items) == 3


@pytest.mark.asyncio
async def test_due_reminder_short_circuits_when_role_sleeping_without_reminder(monkeypatch):
    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation({"phase": "sleeping", "is_sleeping": True}),
    )

    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=None),
        complete_reminder=AsyncMock(return_value=True),
        trigger_message=AsyncMock(return_value=True),
        storage=_DummyReminderStorage(),
    )
    checker = SimpleNamespace(
        executor=executor,
        storage=SimpleNamespace(
            resolve_scope_from_persona_filename=lambda persona_filename: "aveline"
        ),
        set_next_decision_ts=AsyncMock(),
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(now=time.time(), state_data={}, client_type="qq")
    ctx.persona_filename = "qq/Aveline_QQ_Master.json"

    result = await handler.handle_due_reminder(ctx)

    assert result is True
    executor.check_reminders.assert_awaited_once()
    executor.complete_reminder.assert_not_called()
    executor.trigger_message.assert_not_called()


@pytest.mark.asyncio
async def test_due_reminder_is_deferred_when_role_is_hard_busy(monkeypatch):
    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation({"phase": "fully_awake", "is_sleeping": False}),
    )
    monkeypatch.setattr(
        "core.services.character_daily.engine.get_character_daily_engine",
        lambda: _DummyCharacterDailyEngine(ActivityType.STUDYING),
    )

    due_reminder = SimpleNamespace(
        id="r_busy",
        message="该开始「数学复习」了",
        metadata={"type": "start", "task_title": "数学复习"},
    )
    storage = _DummyReminderStorage()
    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=due_reminder),
        complete_reminder=AsyncMock(return_value=True),
        trigger_message=AsyncMock(return_value=True),
        storage=storage,
    )
    checker = SimpleNamespace(
        executor=executor,
        storage=SimpleNamespace(
            resolve_scope_from_persona_filename=lambda persona_filename: "aveline"
        ),
        set_next_decision_ts=AsyncMock(),
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(now=time.time(), state_data={}, client_type="qq")
    ctx.persona_filename = "qq/Aveline_QQ_Master.json"

    result = await handler.handle_due_reminder(ctx)

    assert result is True
    executor.complete_reminder.assert_awaited_once_with("r_busy", triggered_at=ctx.now)
    executor.trigger_message.assert_not_called()
    checker.set_next_decision_ts.assert_not_called()
    assert storage.saved
    assert storage.saved[0]["scope"] == "aveline"
    assert storage.saved[0]["updates"]["deferred_plan_reminders"][0]["task_title"] == "数学复习"


@pytest.mark.asyncio
async def test_due_reminder_is_deferred_when_role_is_night_awake(monkeypatch):
    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation(
            {
                "phase": "night_awake",
                "is_sleeping": False,
                "sleep_debt_hours": 1.2,
                "sleep_inertia_score": 28,
                "impact_level": "mild",
                "night_wake_count": 1,
                "silence_window_seconds": 240,
            }
        ),
    )

    due_reminder = SimpleNamespace(
        id="r_night_awake",
        message="该开始「化学训练」了",
        metadata={"type": "start", "task_title": "化学训练"},
    )
    storage = _DummyReminderStorage()
    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=due_reminder),
        complete_reminder=AsyncMock(return_value=True),
        trigger_message=AsyncMock(return_value=True),
        storage=storage,
    )
    checker = SimpleNamespace(
        executor=executor,
        storage=SimpleNamespace(
            resolve_scope_from_persona_filename=lambda persona_filename: "aveline"
        ),
        set_next_decision_ts=AsyncMock(),
        last_skip_reason="",
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(now=time.time(), state_data={}, client_type="qq")
    ctx.persona_filename = "qq/Aveline_QQ_Master.json"

    result = await handler.handle_due_reminder(ctx)

    assert result is True
    executor.complete_reminder.assert_awaited_once_with(
        "r_night_awake",
        triggered_at=ctx.now,
    )
    executor.trigger_message.assert_not_called()
    checker.set_next_decision_ts.assert_not_called()
    assert storage.saved
    assert storage.saved[0]["updates"]["deferred_plan_reminders"][0]["task_title"] == "化学训练"


@pytest.mark.asyncio
async def test_due_reminder_uses_explicit_overlap_result_for_retry_schedule(monkeypatch):
    import config.integrated_config as integrated_config_module
    import core.services.active_care.checker.checker_event_handler as handler_module

    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation({"phase": "fully_awake", "is_sleeping": False}),
    )
    monkeypatch.setattr(
        "core.services.character_daily.engine.get_character_daily_engine",
        lambda: None,
    )
    monkeypatch.setattr(
        handler_module,
        "get_reminder_injection_store",
        lambda: SimpleNamespace(
            is_user_recently_active=lambda threshold_seconds=600: False
        ),
    )
    monkeypatch.setattr(
        integrated_config_module,
        "get_settings",
        lambda: SimpleNamespace(
            life_simulation=SimpleNamespace(
                active_care_reminder_inject_to_chat=True,
                active_care_reminder_inject_window_seconds=600,
            )
        ),
    )

    due_reminder = SimpleNamespace(
        id="r_overlap",
        message="该开始「数学复习」了",
        trigger_ts=time.time(),
        metadata={"type": "start", "task_title": "数学复习"},
    )
    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=due_reminder),
        format_due_reminder_message=lambda reminder: "任务「数学复习」到时间该开始了",
        complete_reminder=AsyncMock(),
        trigger_message_with_result=AsyncMock(
            return_value=TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.OVERLAP_BLOCKED,
            )
        ),
    )
    checker = SimpleNamespace(
        executor=executor,
        set_next_decision_ts=AsyncMock(),
        last_intent=None,
        last_skip_reason=None,
        _consecutive_reminder_retries=0,
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(
        now=time.time(),
        default_next_check=300,
        min_gap_seconds=600,
        state_data={
            "last_sent_ts": time.time() - 1800,
            "last_attempt_ts": time.time() - 1800,
        },
        client_type="qq",
    )

    handled = await handler.handle_due_reminder(ctx)

    assert handled is True
    executor.trigger_message_with_result.assert_awaited_once()
    checker.set_next_decision_ts.assert_awaited_once()
    assert checker.last_skip_reason == "reminder_interval_blocked"
    assert checker._consecutive_reminder_retries == 0


@pytest.mark.asyncio
async def test_due_reminder_retries_on_explicit_dispatch_failure(monkeypatch):
    import config.integrated_config as integrated_config_module
    import core.services.active_care.checker.checker_event_handler as handler_module

    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation({"phase": "fully_awake", "is_sleeping": False}),
    )
    monkeypatch.setattr(
        "core.services.character_daily.engine.get_character_daily_engine",
        lambda: None,
    )
    monkeypatch.setattr(
        handler_module,
        "get_reminder_injection_store",
        lambda: SimpleNamespace(
            is_user_recently_active=lambda threshold_seconds=600: False
        ),
    )
    monkeypatch.setattr(
        integrated_config_module,
        "get_settings",
        lambda: SimpleNamespace(
            life_simulation=SimpleNamespace(
                active_care_reminder_inject_to_chat=True,
                active_care_reminder_inject_window_seconds=600,
            )
        ),
    )

    due_reminder = SimpleNamespace(
        id="r_dispatch",
        message="该开始「英语听力」了",
        trigger_ts=time.time(),
        metadata={"type": "start", "task_title": "英语听力"},
    )
    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=due_reminder),
        format_due_reminder_message=lambda reminder: "任务「英语听力」到时间该开始了",
        complete_reminder=AsyncMock(),
        trigger_message_with_result=AsyncMock(
            return_value=TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.DISPATCH_FAILED,
            )
        ),
    )
    checker = SimpleNamespace(
        executor=executor,
        set_next_decision_ts=AsyncMock(),
        last_intent=None,
        last_skip_reason=None,
        _consecutive_reminder_retries=0,
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(
        now=time.time(),
        default_next_check=300,
        min_gap_seconds=0,
        state_data={},
        client_type="qq",
    )

    handled = await handler.handle_due_reminder(ctx)

    assert handled is True
    executor.complete_reminder.assert_not_called()
    checker.set_next_decision_ts.assert_awaited_once()
    assert checker.last_skip_reason == "due_reminder_retry"
    assert checker._consecutive_reminder_retries == 1


@pytest.mark.asyncio
async def test_general_proactive_is_blocked_during_sleep_recovery(monkeypatch):
    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation(
            {
                "phase": "sleep_later",
                "is_sleeping": False,
                "sleep_debt_hours": 0.9,
                "sleep_inertia_score": 20,
                "impact_level": "mild",
                "night_wake_count": 1,
                "silence_window_seconds": 240,
            }
        ),
    )

    checker = SimpleNamespace(
        executor=SimpleNamespace(),
        storage=SimpleNamespace(
            resolve_scope_from_persona_filename=lambda persona_filename: "aveline"
        ),
        set_next_decision_ts=AsyncMock(),
        last_skip_reason="",
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(
        now=time.time(),
        state_data={},
        client_type="qq",
        default_next_check=300,
    )
    ctx.persona_filename = "qq/Aveline_QQ_Master.json"

    blocked = await handler.guard_general_proactive_during_sleep_recovery(ctx)

    assert blocked is True
    checker.set_next_decision_ts.assert_awaited_once()
    assert checker.last_skip_reason == "role_sleep_recovery_blocked:sleep_later"


@pytest.mark.asyncio
async def test_general_proactive_refreshes_stale_night_awake_before_guard(monkeypatch):
    now_ts = time.time()
    monkeypatch.setattr(
        "core.services.life_simulation.get_life_simulation_service",
        lambda: _DummyLifeSimulation(
            {
                "phase": "night_awake",
                "is_sleeping": False,
                "sleep_debt_hours": 0.0,
                "sleep_inertia_score": 20.2,
                "impact_level": "mild",
                "night_wake_count": 1,
                "silence_window_seconds": 240,
                "last_wake_ts": now_ts - 3 * 3600,
                "last_chat_ts": now_ts - 3 * 3600,
            },
            refreshed_summary={
                "phase": "fully_awake",
                "is_sleeping": False,
                "sleep_debt_hours": 0.0,
                "sleep_inertia_score": 8.0,
                "impact_level": "none",
                "night_wake_count": 1,
                "silence_window_seconds": 240,
                "last_wake_ts": now_ts - 3 * 3600,
                "last_chat_ts": now_ts - 3 * 3600,
            },
        ),
    )

    checker = SimpleNamespace(
        executor=SimpleNamespace(),
        storage=SimpleNamespace(
            resolve_scope_from_persona_filename=lambda persona_filename: "aveline"
        ),
        set_next_decision_ts=AsyncMock(),
        last_skip_reason="",
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(
        now=now_ts,
        state_data={},
        client_type="qq",
        default_next_check=300,
    )
    ctx.persona_filename = "qq/Aveline_QQ_Master.json"

    blocked = await handler.guard_general_proactive_during_sleep_recovery(ctx)

    assert blocked is False
    checker.set_next_decision_ts.assert_not_awaited()


@pytest.mark.asyncio
async def test_calculate_sleep_interval_respects_next_decision_and_reminder(monkeypatch):
    service = SimpleNamespace(
        life_sim_service=None,
        emotion_manager=SimpleNamespace(get_effective_state=lambda user_id: None),
        scheduler_logic=SimpleNamespace(
            calculate_dynamic_interval=lambda *args, **kwargs: 600
        ),
        consecutive_non_responses=0,
        checker=SimpleNamespace(next_decision_ts=time.time() + 300),
    )
    runner = ProactiveLoopRunner(service)
    runner.is_quiet_mode = AsyncMock(return_value=False)
    runner._get_seconds_until_next_pending_reminder = AsyncMock(return_value=120.0)

    sleep_seconds = await runner.calculate_sleep_interval()

    assert 119.0 <= sleep_seconds <= 121.0


@pytest.mark.asyncio
async def test_calculate_sleep_interval_no_longer_oversleeps_next_decision(monkeypatch):
    service = SimpleNamespace(
        life_sim_service=None,
        emotion_manager=SimpleNamespace(get_effective_state=lambda user_id: None),
        scheduler_logic=SimpleNamespace(
            calculate_dynamic_interval=lambda *args, **kwargs: 600
        ),
        consecutive_non_responses=0,
        checker=SimpleNamespace(next_decision_ts=time.time() + 300),
    )
    runner = ProactiveLoopRunner(service)
    runner.is_quiet_mode = AsyncMock(return_value=False)
    runner._get_seconds_until_next_pending_reminder = AsyncMock(return_value=None)

    sleep_seconds = await runner.calculate_sleep_interval()

    assert 295.0 <= sleep_seconds <= 300.5


@pytest.mark.asyncio
async def test_calculate_sleep_interval_ignores_overdue_reminder_during_manual_delay(monkeypatch):
    service = SimpleNamespace(
        life_sim_service=None,
        emotion_manager=SimpleNamespace(get_effective_state=lambda user_id: None),
        scheduler_logic=SimpleNamespace(
            calculate_dynamic_interval=lambda *args, **kwargs: 600
        ),
        consecutive_non_responses=0,
        checker=SimpleNamespace(next_decision_ts=time.time() + 45, last_skip_reason="manual_delay"),
    )
    runner = ProactiveLoopRunner(service)
    runner.is_quiet_mode = AsyncMock(return_value=False)
    runner._get_seconds_until_next_pending_reminder = AsyncMock(return_value=1.0)

    sleep_seconds = await runner.calculate_sleep_interval()

    assert 40.0 <= sleep_seconds <= 45.5


@pytest.mark.asyncio
async def test_calculate_sleep_interval_sleeps_until_next_decision_during_manual_delay():
    service = SimpleNamespace(
        life_sim_service=None,
        emotion_manager=SimpleNamespace(get_effective_state=lambda user_id: None),
        scheduler_logic=SimpleNamespace(
            calculate_dynamic_interval=lambda *args, **kwargs: 600
        ),
        consecutive_non_responses=0,
        checker=SimpleNamespace(next_decision_ts=time.time() + 3600, last_skip_reason="manual_delay"),
    )
    runner = ProactiveLoopRunner(service)
    runner.is_quiet_mode = AsyncMock(return_value=False)
    runner._get_seconds_until_next_pending_reminder = AsyncMock(return_value=None)

    sleep_seconds = await runner.calculate_sleep_interval()

    assert 3595.0 <= sleep_seconds <= 3600.5


def test_repair_stale_next_decision_ts_updates_overdue_personas():
    checker = ProactiveChecker.__new__(ProactiveChecker)
    checker._init_state = SimpleNamespace(
        next_decision_ts=100.0,
        _next_llm_decision_ts=100.0,
        _next_decision_ts_by_persona={
            "aveline": 90.0,
            "ling": 900.0,
        },
        _next_llm_decision_ts_by_persona={
            "aveline": 90.0,
            "ling": 900.0,
        },
    )
    checker._get_config_value = lambda key, default=None: 300

    checker._repair_stale_next_decision_ts(200.0)

    assert checker.next_decision_ts == 500.0
    assert checker._next_llm_decision_ts == 500.0
    assert checker._next_decision_ts_by_persona["aveline"] == 500.0
    assert checker._next_llm_decision_ts_by_persona["aveline"] == 500.0
    assert checker._next_decision_ts_by_persona["ling"] == 900.0


def test_build_persona_schedule_snapshot_returns_remaining_waits():
    service = SimpleNamespace(
        checker=SimpleNamespace(
            get_all_persona_keys=lambda: ["aveline", "ling"],
            _next_decision_ts_by_persona={
                "aveline": 140.0,
                "ling": 320.0,
            },
        ),
    )
    runner = ProactiveLoopRunner(service)

    snapshot = runner._build_persona_schedule_snapshot(100.0)

    assert snapshot == {"aveline": 40, "ling": 220}


@pytest.mark.asyncio
async def test_old_user_message_is_deduped_after_first_skip():
    old_ts = time.time() - 3600
    service = SimpleNamespace(
        context=SimpleNamespace(
            get_latest_history=AsyncMock(return_value=[
                {"role": "user", "content": "很久以前的消息", "timestamp": old_ts}
            ]),
            resolve_primary_conversation_id=AsyncMock(return_value="cid_1"),
            get_recent_user_message=lambda _cid: {},
        ),
        state_manager=SimpleNamespace(process_user_message=AsyncMock()),
        _last_processed_user_msg_signatures={},
        checker=None,
        storage=None,
        executor=SimpleNamespace(consecutive_non_responses={}),
        consecutive_non_responses=0,
    )
    handler = UserResponseHandler(service)

    await handler._process_user_response_for_persona("qq/Aveline_QQ_Master.json")
    first_signature = service._last_processed_user_msg_signatures["qq/Aveline_QQ_Master.json"]
    await handler._process_user_response_for_persona("qq/Aveline_QQ_Master.json")

    assert first_signature
    assert service._last_processed_user_msg_signatures["qq/Aveline_QQ_Master.json"] == first_signature
    service.state_manager.process_user_message.assert_not_called()


@pytest.mark.asyncio
async def test_old_user_message_dedup_is_isolated_per_persona():
    old_ts = time.time() - 3600
    history = [{"role": "user", "content": "很久以前的消息", "timestamp": old_ts}]
    service = SimpleNamespace(
        context=SimpleNamespace(
            get_latest_history=AsyncMock(return_value=history),
            resolve_primary_conversation_id=AsyncMock(return_value="cid_1"),
            get_recent_user_message=lambda _cid: {},
        ),
        state_manager=SimpleNamespace(process_user_message=AsyncMock()),
        _last_processed_user_msg_signatures={},
        checker=None,
        storage=None,
        executor=SimpleNamespace(consecutive_non_responses={}),
        consecutive_non_responses=0,
    )
    handler = UserResponseHandler(service)

    await handler._process_user_response_for_persona("qq/Aveline_QQ_Master.json")
    await handler._process_user_response_for_persona("qq/Ling_QQ_Master.json")
    first_snapshot = dict(service._last_processed_user_msg_signatures)
    await handler._process_user_response_for_persona("qq/Aveline_QQ_Master.json")
    await handler._process_user_response_for_persona("qq/Ling_QQ_Master.json")

    assert first_snapshot == service._last_processed_user_msg_signatures
    service.state_manager.process_user_message.assert_not_called()
