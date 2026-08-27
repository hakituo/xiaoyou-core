from __future__ import annotations

from datetime import datetime

import pytest

from core.services.character_daily.config import RoleScheduleTemplate, SleepProfileConfig
from core.services.character_daily.llm_plan_generator import LLMPlanGenerator
from core.services.life_simulation.sleep_decision import call_llm_sleep_decision
from core.services.life_simulation.sleep_models import SleepPhase, SleepRuntimeState


class _FakeScheduler:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[object, dict]] = []

    async def submit_llm_task(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        yield self.response


@pytest.mark.asyncio
async def test_llm_plan_generator_passes_messages_as_prompt(monkeypatch):
    scheduler = _FakeScheduler(
        '{"slots":[{"activity":"reading","start":"08:00","end":"09:00"}]}'
    )
    template = RoleScheduleTemplate(
        role_id="aveline",
        wake_time="07:00",
        sleep_time="23:00",
    )
    generator = LLMPlanGenerator(
        templates={"aveline": template},
        model_path="cloud:deepseek:qqbot1:deepseek-v4-pro",
    )

    async def _fake_load_user_plan_context(date_str: str) -> str:
        return ""

    monkeypatch.setattr(
        "core.services.scheduler.get_global_scheduler",
        lambda: scheduler,
    )
    monkeypatch.setattr(generator, "_load_user_plan_context", _fake_load_user_plan_context)

    raw = await generator._call_llm("aveline", "2026-06-30", template, None)

    assert raw
    assert len(scheduler.calls) == 1
    prompt, kwargs = scheduler.calls[0]
    assert isinstance(prompt, list)
    assert prompt[0]["role"] == "system"
    assert prompt[1]["role"] == "user"
    assert kwargs["model_path"] == "cloud:deepseek:qqbot1:deepseek-v4-pro"


@pytest.mark.asyncio
async def test_sleep_decision_passes_messages_as_prompt():
    scheduler = _FakeScheduler(
        '{"decision":"return_to_sleep","reason":"还是很困","stay_up_activity":"idle"}'
    )
    state = SleepRuntimeState(
        role_id="aveline",
        date="2026-06-30",
        phase=SleepPhase.NIGHT_AWAKE,
        planned_sleep_time="23:00",
        planned_wake_time="07:00",
    )
    profile = SleepProfileConfig()

    decision = await call_llm_sleep_decision(
        scheduler=scheduler,
        model_path="cloud:deepseek:qqbot1:deepseek-v4-flash",
        role_id="aveline",
        role_name="七濑澪",
        state=state,
        profile=profile,
        now=datetime(2026, 6, 30, 2, 30),
        wake_dt=datetime(2026, 6, 30, 7, 0),
    )

    assert decision is not None
    assert len(scheduler.calls) == 1
    prompt, kwargs = scheduler.calls[0]
    assert isinstance(prompt, list)
    assert prompt[0]["role"] == "system"
    assert prompt[1]["role"] == "user"
    assert kwargs["model_path"] == "cloud:deepseek:qqbot1:deepseek-v4-flash"
