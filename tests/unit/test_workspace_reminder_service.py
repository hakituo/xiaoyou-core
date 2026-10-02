import asyncio
from unittest.mock import AsyncMock

import pytest

from core.services.workspace.reminder_service import WorkspaceReminderService


class _DummyStore:
    def __init__(self) -> None:
        self.items = []

    async def read(self):
        return list(self.items)

    async def write(self, items):
        self.items = list(items)


@pytest.mark.asyncio
async def test_schedule_message_wakes_active_care(monkeypatch):
    import core.services.active_care.core.service as active_care_service_module

    notify_mock = AsyncMock()
    monkeypatch.setattr(
        active_care_service_module,
        "get_active_care_service",
        lambda: type(
            "_DummyActiveCare",
            (),
            {"notify_workspace_reminder_updated": notify_mock},
        )(),
    )

    service = WorkspaceReminderService(
        store=_DummyStore(),
        lock=asyncio.Lock(),
        append_workspace_memory=AsyncMock(),
    )

    reminder_id = await service.schedule_message(
        message="该开始数学复习了",
        trigger_ts=12345.0,
        metadata={"source": "daily_task"},
    )

    assert reminder_id.startswith("msg_")
    notify_mock.assert_awaited_once_with(trigger_ts=12345.0)
