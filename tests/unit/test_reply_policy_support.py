import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.services.character_daily.reply_policy_support import is_active_care_sleeping


class _DummyStorage:
    def __init__(self, state_data):
        self.state_data = dict(state_data)

    async def get_proactive_state(self, scope=None):
        return dict(self.state_data)


class _DummyActiveCare:
    def __init__(self, storage):
        self.storage = storage


class _DummySleepManager:
    def __init__(self, summary):
        self.summary = dict(summary)

    def get_summary(self, role_id):
        return dict(self.summary)


class TestReplyPolicySupport(unittest.IsolatedAsyncioTestCase):
    async def test_stale_active_care_sleep_is_ignored_after_wake(self):
        storage = _DummyStorage(
            {"last_goodnight_ts": 100.0, "last_goodmorning_ts": 0.0}
        )
        sleep_manager = _DummySleepManager(
            {"phase": "night_awake", "is_sleeping": False}
        )

        with (
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_DummyActiveCare(storage),
            ),
            patch(
                "core.services.life_simulation.get_sleep_manager",
                return_value=sleep_manager,
            ),
        ):
            result = await is_active_care_sleeping("aveline")

        self.assertFalse(result)

    async def test_real_active_care_sleep_keeps_sleeping_state(self):
        storage = _DummyStorage(
            {"last_goodnight_ts": 100.0, "last_goodmorning_ts": 0.0}
        )
        sleep_manager = _DummySleepManager({"phase": "sleeping", "is_sleeping": True})

        with (
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_DummyActiveCare(storage),
            ),
            patch(
                "core.services.life_simulation.get_sleep_manager",
                return_value=sleep_manager,
            ),
        ):
            result = await is_active_care_sleeping("aveline")

        self.assertTrue(result)
