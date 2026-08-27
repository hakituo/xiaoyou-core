r"""验证 Active Care 用户级睡眠状态与数字健康硬事件链路。

运行：
    D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m tests.scripts.active_care.verify_shared_sleep_and_usage_event
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from core.services.active_care.decision.decision_output_parser import (
    _parse_decision_output,
)
from core.services.active_care.postprocess.event_target_guard import (
    enforce_usage_limit_target,
)
from core.services.active_care.prompt.prompt_builder import build_active_care_prompt
from core.services.active_care.shared.constants import StateKeys
from core.services.active_care.state.manager import StateManager
from core.services.active_care.state.mode_state import is_direct_awake_statement
from core.services.active_care.storage.storage import ActiveCareStorage
from core.services.digital_wellbeing.service import DigitalWellbeingService
from core.services.daily.manager import DailyActivityManager
from core.services.daily.extractor import ActivityExtractor
from core.services.dual_role.social_events import SocialEventEngine
from core.services.health_sync.store import _build_events
from core.services.health_sync.wakeup import (
    classify_sleep_session,
    exit_quiet_mode_on_wakeup,
    sync_wakeup_to_daily_record,
)
from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
    build_peer_chat_decision_prompt,
)
from routers.v1 import context_device


class _TemporaryStorage(ActiveCareStorage):
    """把 Active Care 状态完全隔离到临时目录。"""

    def __init__(self, root: Path):
        self._test_root = root
        super().__init__()

    def _get_runtime_dir(self, scope=None) -> str:
        target = self._test_root / str(scope or self.get_runtime_scope())
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def _get_user_sleep_state_file(self) -> str:
        target = self._test_root / "user" / self._USER_SLEEP_STATE_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        return str(target)


async def _verify_shared_sleep_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        manager = StateManager(storage)

        await storage.save_user_sleep_state(
            {
                StateKeys.LAST_GOODNIGHT_TS: 1_000.0,
                StateKeys.LAST_GOODMORNING_TS: 0.0,
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: "goodnight",
                StateKeys.REDUCED_MODE_LABEL: "sleep",
                StateKeys.LAST_SLEEP_SESSION_START_TS: 100.0,
                StateKeys.LAST_SLEEP_SESSION_END_TS: 900.0,
                StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS: 800.0,
                StateKeys.LAST_SLEEP_SESSION_SOURCE: "samsung_health",
                StateKeys.LAST_SLEEP_SESSION_KIND: "main_sleep",
            },
            scope="aveline",
        )
        ling_sleeping = await storage.get_proactive_state(scope="ling")
        assert ling_sleeping[StateKeys.REDUCED_MODE_REASON] == "goodnight"
        assert ling_sleeping[StateKeys.LAST_GOODNIGHT_TS] == 1_000.0

        # 即使语义模型给出 NONE，直接清醒陈述也应退出低打扰；
        # 但绝不能覆盖 Samsung Health 的正式睡眠事实。
        manager.mode._detect_state_event_with_bert_async = AsyncMock(
            return_value=("NONE", 0.1)
        )
        storage.set_runtime_scope("aveline")
        result = await manager.process_user_message("我起来了", now_ts=2_000.0)
        assert result["sleep_changed"] is True

        aveline_awake = await storage.get_proactive_state(scope="aveline")
        ling_awake = await storage.get_proactive_state(scope="ling")
        for state in (aveline_awake, ling_awake):
            assert bool(state.get(StateKeys.REDUCED_MODE_ACTIVE)) is False
            assert state.get(StateKeys.REDUCED_MODE_REASON, "none") == "none"
            assert state[StateKeys.LAST_GOODMORNING_TS] == 0.0
            assert state[StateKeys.LAST_GOODNIGHT_TS] == 0.0
            assert state[StateKeys.LAST_SLEEP_SESSION_END_TS] == 900.0
            assert state[StateKeys.LAST_SLEEP_SESSION_SOURCE] == "samsung_health"
            assert state[StateKeys.LAST_LOW_DISTURBANCE_EXIT_TS] == 2_000.0
            assert state[StateKeys.LAST_LOW_DISTURBANCE_EXIT_SOURCE] == "user_message"

        global_path = Path(storage._get_user_sleep_state_file())
        assert global_path.exists()
        persisted = json.loads(global_path.read_text(encoding="utf-8"))
        assert persisted[StateKeys.LAST_GOODMORNING_TS] == 0.0
        assert persisted[StateKeys.LAST_SLEEP_SESSION_END_TS] == 900.0

        assert is_direct_awake_statement("我起来了")
        assert is_direct_awake_statement("我午睡醒了")
        assert not is_direct_awake_statement("你起来了吗")
        assert not is_direct_awake_statement("我午睡醒了算正式起床吗")


async def _verify_samsung_sleep_authority() -> None:
    main_event = {
        "sleep_start": "2026-08-23T23:30:00+08:00",
        "sleep_end": "2026-08-24T08:00:00+08:00",
        "sleep_minutes": 510,
    }
    nap_event = {
        "sleep_start": "2026-08-24T13:00:00+08:00",
        "sleep_end": "2026-08-24T13:45:00+08:00",
        "sleep_minutes": 45,
    }
    assert classify_sleep_session(main_event) == "main_sleep"
    assert classify_sleep_session(nap_event) == "nap"
    nap_daily = sync_wakeup_to_daily_record(nap_event)
    assert nap_daily["applied"] is False
    assert nap_daily["sleep_kind"] == "nap"

    with tempfile.TemporaryDirectory() as daily_tmp:
        daily_manager = DailyActivityManager()
        daily_manager.root_dir = daily_tmp
        daily_manager.record_sleep(
            "23:30",
            target_date="2026-08-24",
            source="samsung_health",
        )
        ignored = daily_manager.record_sleep(
            "01:00",
            target_date="2026-08-24",
            source="chat_explicit_time",
        )
        assert "Kept existing sleep" in ignored
        daily_data = daily_manager.get_record("2026-08-24")
        assert daily_data["sleep_cycle"]["sleep"] == "23:30"
        assert daily_data["sleep_cycle"]["sleep_source"] == "samsung_health"

    extractor = ActivityExtractor.__new__(ActivityExtractor)
    extractor.manager = Mock()
    extractor._last_record_source = ""
    extractor._apply_fast_record("我起来了")
    extractor._apply_fast_record("晚安")
    extractor.manager.record_wakeup.assert_not_called()
    extractor.manager.record_sleep.assert_not_called()

    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        await storage.save_user_sleep_state(
            {
                StateKeys.LAST_GOODNIGHT_TS: 1_777_130_000.0,
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: "goodnight",
            },
            immediate=True,
        )

        class _Service:
            def __init__(self):
                self.storage = storage

        with (
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=_Service(),
            ),
            patch(
                "core.services.health_sync.wakeup.sync_wakeup_to_daily_record",
                return_value={"applied": True, "sleep_kind": "main_sleep"},
            ),
        ):
            result = await exit_quiet_mode_on_wakeup(main_event)

        assert result["state_synced"] is True
        assert result["sleep_kind"] == "main_sleep"
        state = await storage.get_proactive_state()
        assert state[StateKeys.LAST_SLEEP_SESSION_SOURCE] == "samsung_health"
        assert state[StateKeys.LAST_SLEEP_SESSION_KIND] == "main_sleep"
        assert state[StateKeys.LAST_GOODMORNING_TS] > 0


async def _verify_shared_life_events_and_optional_peer_chat() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = SocialEventEngine("", None, Mock())
        engine._social_events_dir = tmp

        event_type = await engine.record_user_life_event(
            "我午睡醒了",
            learned_by="aveline",
        )
        assert event_type == "nap_wake"
        assert await engine.record_user_life_event(
            "你吃饭没有？",
            learned_by="aveline",
        ) is None
        assert await engine.record_user_life_event(
            "我还没吃饭",
            learned_by="aveline",
        ) == "meal_status"
        engine.record_health_events(
            [{"type": "meal", "foods": ["米饭"], "delta_kcal": 500}],
            learned_by="aveline",
        )
        context = engine.build_recent_events_context(
            "default",
            max_items=4,
            viewer_role_id="ling",
        )
        assert "Aveline 转告" in context
        assert "Samsung Health 实测" in context
        assert "午睡醒了" in context

        prompt = build_peer_chat_decision_prompt(
            role_name="Ling",
            peer_name="Aveline",
            time_str="2026-08-24 14:00",
            energy=60,
            mood="neutral",
            elapsed_seconds=3600,
            recent_topics=[],
            social_events_hint=context,
            bio_state={},
        )
        assert "可选话题，不是触发即必聊" in prompt.system_prompt
        assert "Aveline 转告" in prompt.user_prompt

    # 饮食事件不能依赖 water_intake_ml 同时存在。
    events = _build_events(
        {"nutrition_calories": 500, "nutrition_entries": [{"title": "米饭"}]},
        {"nutrition_calories": 0},
    )
    assert any(event.get("type") == "meal" for event in events)


def _verify_usage_prompt_and_guard() -> None:
    old_history = "助手：又被踢出来了？七夕打算怎么过呀。"
    instruction = (
        "用户的手机应用 抖音 今日已使用 1h20m，超过了设定的每日限额 1h。"
        "系统没有收到强制退出结果。"
    )
    prompt = build_active_care_prompt(
        sys_prompt_type="usage_limit_exceeded",
        user_input_mock=instruction,
        reminder_msg=None,
        thought="接着旧话题问吃什么",
        tod="中午",
        now=2_000.0,
        user_display_name="用户",
        persona_prompt="你是 Aveline。",
        recent_history_text=old_history,
        elapsed_seconds=0.0,
        specific_instruction=instruction,
    )
    assert old_history not in prompt.dynamic_prompt
    assert "抖音" in prompt.dynamic_prompt
    assert "只围绕本次应用超限" in prompt.dynamic_prompt

    corrected = enforce_usage_limit_target(
        "哼，被踢出来还发呆呢。刚好到饭点了，打算吃点什么？",
        instruction,
    )
    assert "抖音" in corrected
    assert "踢出来" not in corrected
    assert "吃点什么" not in corrected

    unchanged = enforce_usage_limit_target("抖音超时了，先歇会儿眼睛。", instruction)
    assert unchanged == "抖音超时了，先歇会儿眼睛。"


def _verify_decision_intent_is_fixed() -> None:
    parsed = _parse_decision_output(
        '{"thought":"随便问问","should_send":true,'
        '"intent":"curious_question","next_check_seconds":900}',
        "user_health_reminder",
    )
    assert parsed["intent"] == "user_health_reminder"

    malformed = _parse_decision_output(
        '"should_send": true, "intent": "curious_question"',
        "user_health_reminder",
    )
    assert malformed["intent"] == "user_health_reminder"


def _verify_usage_window_trust_and_aggregation() -> None:
    server_ts = "2026-08-24T11:24:00+08:00"
    window_start = "2026-08-23T16:00:00Z"
    assert context_device._is_trusted_today_usage_report(
        usage_source="android_today_since_midnight_v1",
        usage_window_start=window_start,
        server_timestamp=server_ts,
    )
    assert not context_device._is_trusted_today_usage_report(
        usage_source=None,
        usage_window_start=window_start,
        server_timestamp=server_ts,
    )
    # 服务端凌晨 01:00+08 时，00:30+08 的最近使用必须算作今天。
    assert context_device._is_plausible_today_usage(
        {
            "usage_time_ms": 60_000,
            "last_used_time": "2026-08-23T16:30:00Z",
            "server_timestamp": "2026-08-24T01:00:00+08:00",
        }
    )

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        usage_dir = base / "2026" / "08" / "24"
        usage_dir.mkdir(parents=True)
        records = [
            {
                "package_name": "com.example.video",
                "app_name": "视频",
                "usage_time_ms": 10_000_000,
                "last_used_time": "2026-08-23T15:00:00Z",
                "server_timestamp": "2026-08-24T00:10:00+08:00",
            },
            {
                "package_name": "com.example.video",
                "app_name": "视频",
                "usage_time_ms": 10_100_000,
                "last_used_time": "2026-08-24T02:00:00Z",
                "server_timestamp": "2026-08-24T10:01:00+08:00",
            },
            {
                "package_name": "com.example.video",
                "app_name": "视频",
                "usage_time_ms": 600_000,
                "last_used_time": "2026-08-24T03:00:00Z",
                "server_timestamp": "2026-08-24T11:00:00+08:00",
                "usage_source": "android_today_since_midnight_v1",
                "usage_window_start": window_start,
            },
            {
                "package_name": "com.example.video",
                "app_name": "视频",
                "usage_time_ms": 11_000_000,
                "last_used_time": "2026-08-24T04:00:00Z",
                "server_timestamp": "2026-08-24T12:00:00+08:00",
            },
        ]
        usage_file = usage_dir / "app_usage.jsonl"
        usage_file.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
            encoding="utf-8",
        )
        with patch.object(context_device, "get_user_daily_dir", return_value=base):
            result = context_device.read_today_app_usage("2026-08-24")
        assert len(result) == 1
        assert result[0]["usage_time_ms"] == 600_000


def _verify_android_usage_contract() -> None:
    project_root = Path(__file__).resolve().parents[3]
    android_root = (
        project_root
        / "clients"
        / "frontend"
        / "aveline-android"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "aveline"
        / "ai"
        / "mobile"
    )
    dto_source = (
        android_root / "data" / "remote" / "dto" / "ContextSyncRequest.kt"
    ).read_text(encoding="utf-8")
    worker_source = (
        android_root / "services" / "worker" / "DataSyncWorker.kt"
    ).read_text(encoding="utf-8")
    assert '@SerialName("usage_window_start")' in dto_source
    assert '@SerialName("usage_source")' in dto_source
    assert "Instant.ofEpochMilli(todayMidnightMs).toString()" in worker_source
    assert 'usageSource = "android_today_since_midnight_v1"' in worker_source


async def _verify_digital_wellbeing_routes_to_aveline() -> None:
    class _Executor:
        def __init__(self):
            self.kwargs = None

        async def trigger_message(self, **kwargs):
            self.kwargs = kwargs
            return True

    class _Service:
        def __init__(self, executor):
            self.executor = executor

    with tempfile.TemporaryDirectory() as tmp:
        wellbeing = DigitalWellbeingService(base_dir=Path(tmp))
        wellbeing.save_limits(
            {
                "com.example.video": {
                    "limit_ms": 60_000,
                    "app_name": "视频",
                }
            },
            target_date="2026-08-24",
        )
        executor = _Executor()
        DigitalWellbeingService._last_care_ts.clear()
        usage = [
            {
                "package_name": "com.example.video",
                "app_name": "视频",
                "usage_time_ms": 120_000,
                "last_used_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=_Service(executor),
        ):
            notified = await wellbeing.maybe_notify_exceeded_via_active_care(
                target_date="2026-08-24",
                usage=usage,
            )
        assert notified == ["视频"]
        assert executor.kwargs["client_type"] == "qq"
        assert executor.kwargs["persona_filename"] == "qq/Aveline_QQ_Master.json"
        assert "强制退出结果" in executor.kwargs["specific_instruction"]


async def _main() -> None:
    await _verify_shared_sleep_state()
    await _verify_samsung_sleep_authority()
    await _verify_shared_life_events_and_optional_peer_chat()
    _verify_usage_prompt_and_guard()
    _verify_decision_intent_is_fixed()
    _verify_usage_window_trust_and_aggregation()
    _verify_android_usage_contract()
    await _verify_digital_wellbeing_routes_to_aveline()
    print("[OK] Active Care 用户级睡眠状态与数字健康硬事件验证通过")


if __name__ == "__main__":
    asyncio.run(_main())
