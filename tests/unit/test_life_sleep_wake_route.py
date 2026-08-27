import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.services.character_daily.activity_model import ActivityType
from routers.v1.life import (
    ActivityInterruptRequest,
    SleepWakeRequest,
    interrupt_current_activity,
    wake_sleeping_role,
)


class _DummyLifeSimulation:
    def __init__(self, summary, wake_result):
        self.summary = dict(summary)
        self.wake_result = dict(wake_result)
        self.wake_calls = []

    def get_sleep_summary(self, role_id):
        return dict(self.summary)

    def notify_sleep_interruption(self, role_id, message="", conversation_id=""):
        self.wake_calls.append((role_id, message, conversation_id))
        return dict(self.wake_result)


class _DummyCharacterDailyEngine:
    def __init__(self, activity=ActivityType.IDLE, window_seconds=600.0):
        self.activity = activity
        self.window_seconds = window_seconds
        self.refresh_calls = []

    def refresh_current_activity(self, role_id):
        self.refresh_calls.append(role_id)
        return self.activity

    def get_reply_policy_config(self):
        return type(
            "ReplyCfg",
            (),
            {"manual_interrupt_window_seconds": self.window_seconds},
        )()


class _DummyStorage:
    def __init__(self, state_data=None):
        self.state_data = dict(state_data or {})
        self.saved = []

    async def get_proactive_state(self, scope=None):
        return dict(self.state_data)

    async def save_proactive_state(self, updates, immediate=False, scope=None):
        self.saved.append((dict(updates), immediate, scope))
        self.state_data.update(updates)
        return dict(self.state_data)


class _DummyActiveCare:
    def __init__(self, storage):
        self.storage = storage


class TestLifeSleepWakeRoute(unittest.IsolatedAsyncioTestCase):
    async def test_wake_sleeping_role(self):
        dummy = _DummyLifeSimulation(
            summary={"phase": "sleeping", "is_sleeping": True},
            wake_result={"phase": "night_awake", "is_sleeping": False},
        )
        storage = _DummyStorage(
            {"last_goodnight_ts": 100.0, "last_goodmorning_ts": 0.0}
        )

        with (
            patch("routers.v1.life._get_life_simulation_service", return_value=dummy),
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_DummyActiveCare(storage),
            ),
        ):
            result = await wake_sleeping_role(
                SleepWakeRequest(
                    role_id="ling",
                    conversation_id="private_1__persona__core_ling",
                    message="马上起来",
                )
            )

        self.assertEqual(result["action"], "woken_up")
        self.assertEqual(result["role_id"], "ling")
        self.assertEqual(result["sleep_summary"]["phase"], "night_awake")
        self.assertTrue(result["active_care_cleared"])
        self.assertEqual(
            dummy.wake_calls,
            [("ling", "马上起来", "private_1__persona__core_ling")],
        )
        self.assertEqual(len(storage.saved), 1)
        self.assertEqual(storage.saved[0][2], "ling")

    async def test_skip_wake_when_role_already_awake(self):
        dummy = _DummyLifeSimulation(
            summary={"phase": "fully_awake", "is_sleeping": False},
            wake_result={"phase": "fully_awake", "is_sleeping": False},
        )
        storage = _DummyStorage(
            {"last_goodnight_ts": 200.0, "last_goodmorning_ts": 0.0}
        )

        with (
            patch("routers.v1.life._get_life_simulation_service", return_value=dummy),
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_DummyActiveCare(storage),
            ),
        ):
            result = await wake_sleeping_role(SleepWakeRequest(role_id="aveline"))

        self.assertEqual(result["action"], "woken_up")
        self.assertEqual(result["role_id"], "aveline")
        self.assertEqual(dummy.wake_calls, [])
        self.assertEqual(len(storage.saved), 1)

    async def test_wake_auto_interrupts_dnd_activity_when_already_awake(self):
        """sleep_manager 判定未在睡，但 character_daily 仍处于 DND 活动（午睡）时，
        /wake 应自动激活中断窗口，避免 reply_policy 静默累积消息。"""
        dummy = _DummyLifeSimulation(
            summary={"phase": "fully_awake", "is_sleeping": False},
            wake_result={"phase": "fully_awake", "is_sleeping": False},
        )
        # 无残留晚安态 → ac_cleared=False → 走 already_awake 分支
        storage = _DummyStorage({})
        engine = _DummyCharacterDailyEngine(activity=ActivityType.NAPPING, window_seconds=600.0)

        with (
            patch("routers.v1.life._get_life_simulation_service", return_value=dummy),
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_DummyActiveCare(storage),
            ),
            patch(
                "core.services.character_daily.engine.get_character_daily_engine",
                return_value=engine,
            ),
            patch(
                "routers.v1.life.activate_manual_interrupt_window",
                return_value={"expire_ts": 9999.0},
            ) as activate_mock,
        ):
            result = await wake_sleeping_role(
                SleepWakeRequest(
                    role_id="ling",
                    conversation_id="private_1__persona__ling_love",
                    message="醒醒",
                )
            )

        self.assertEqual(result["action"], "woken_up")
        self.assertEqual(result["role_id"], "ling")
        self.assertEqual(result["activity"], "napping")
        self.assertEqual(len(engine.refresh_calls), 1)
        self.assertEqual(engine.refresh_calls[0], "ling")
        activate_mock.assert_called_once()
        call_kwargs = activate_mock.call_args.kwargs
        self.assertEqual(call_kwargs["conversation_id"], "private_1__persona__ling_love")
        self.assertEqual(call_kwargs["role_id"], "ling")
        self.assertEqual(call_kwargs["activity"], "napping")
        self.assertEqual(call_kwargs["source"], "wake_auto_interrupt_dnd")

    async def test_wake_already_awake_when_character_daily_idle(self):
        """sleep_manager 未在睡、character_daily 也是非 DND 活动时，
        /wake 走 already_awake 分支，不激活中断窗口。"""
        dummy = _DummyLifeSimulation(
            summary={"phase": "fully_awake", "is_sleeping": False},
            wake_result={"phase": "fully_awake", "is_sleeping": False},
        )
        storage = _DummyStorage({})
        engine = _DummyCharacterDailyEngine(activity=ActivityType.IDLE, window_seconds=600.0)

        with (
            patch("routers.v1.life._get_life_simulation_service", return_value=dummy),
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_DummyActiveCare(storage),
            ),
            patch(
                "core.services.character_daily.engine.get_character_daily_engine",
                return_value=engine,
            ),
            patch(
                "routers.v1.life.activate_manual_interrupt_window",
            ) as activate_mock,
        ):
            result = await wake_sleeping_role(
                SleepWakeRequest(role_id="aveline")
            )

        self.assertEqual(result["action"], "already_awake")
        self.assertEqual(result["role_id"], "aveline")
        self.assertEqual(len(engine.refresh_calls), 1)
        activate_mock.assert_not_called()

    async def test_interrupt_current_busy_activity(self):
        dummy = _DummyLifeSimulation(
            summary={"phase": "fully_awake", "is_sleeping": False},
            wake_result={"phase": "fully_awake", "is_sleeping": False},
        )
        engine = _DummyCharacterDailyEngine(activity=ActivityType.STUDYING, window_seconds=480.0)

        with (
            patch("routers.v1.life._get_life_simulation_service", return_value=dummy),
            patch("routers.v1.life._get_character_daily_engine", return_value=engine),
            patch(
                "routers.v1.life.activate_manual_interrupt_window",
                return_value={"expire_ts": 1234.5},
            ) as activate_mock,
        ):
            result = await interrupt_current_activity(
                ActivityInterruptRequest(
                    role_id="ling",
                    conversation_id="private_1__persona__core_ling",
                    message="先陪我聊会",
                )
            )

        self.assertEqual(result["action"], "interrupted")
        self.assertEqual(result["role_id"], "ling")
        self.assertEqual(result["activity"], "studying")
        self.assertEqual(result["window_seconds"], 480)
        activate_mock.assert_called_once()

    async def test_interrupt_sleeping_role_requires_wake_command(self):
        dummy = _DummyLifeSimulation(
            summary={"phase": "sleeping", "is_sleeping": True},
            wake_result={"phase": "sleeping", "is_sleeping": True},
        )
        engine = _DummyCharacterDailyEngine(activity=ActivityType.STUDYING)

        with (
            patch("routers.v1.life._get_life_simulation_service", return_value=dummy),
            patch("routers.v1.life._get_character_daily_engine", return_value=engine),
        ):
            result = await interrupt_current_activity(
                ActivityInterruptRequest(
                    role_id="aveline",
                    conversation_id="private_1__persona__aveline",
                )
            )

        self.assertEqual(result["action"], "sleeping_use_wake")
