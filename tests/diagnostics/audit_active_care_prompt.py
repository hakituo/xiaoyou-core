import sys
import time
import asyncio
from unittest.mock import patch, AsyncMock

sys.path.append(r"d:\AI\xiaoyou-core")

from core.services.active_care.core.executor import ActiveCareExecutor
import core.services.active_care.executor as executor_mod
from core.tools.study.english.vocabulary_manager import get_vocabulary_manager


class _FakeContext:
    async def resolve_primary_conversation_id(self):
        return "default_user"

    async def get_latest_history_for_conversation(self, conversation_id: str, limit: int = 10):
        _ = (conversation_id, limit)
        return [
            {"role": "user", "content": "我今天有点困"},
            {"role": "assistant", "content": "早点休息"},
            {"role": "user", "content": "我晚点还要背单词"},
        ]

    def get_recent_user_message(self, conversation_id: str):
        _ = conversation_id
        return {"content": "我晚点还要背单词", "timestamp": time.time()}


class _FakeStorage:
    def __init__(self):
        self.state = {}

    async def get_proactive_state(self):
        return dict(self.state)

    async def save_proactive_state(self, data):
        if isinstance(data, dict):
            self.state.update(data)

    async def increment_proactive_count(self, date_key: str):
        _ = date_key


class _FakeAgent:
    def __init__(self, captured: dict):
        self.is_initialized = True
        self._captured = captured

    async def initialize(self):
        return None

    async def handle_message(self, user_id: str, message: str, system_prompt_override: str, save_history: bool):
        self._captured["user_id"] = user_id
        self._captured["message"] = message
        self._captured["system_prompt_override"] = system_prompt_override
        self._captured["save_history"] = save_history
        return {
            "content": "收到，我先提醒你把今天该复习的单词过一遍。",
            "full_content": "收到，我先提醒你把今天该复习的单词过一遍。",
            "message_type": "text",
        }


class _FakeNotificationManager:
    def add_notification(self, user_id: str, type: str, title: str, content: str, payload=None):
        _ = (user_id, type, title, content, payload)


class _FakeAvelineService:
    async def append_proactive_message(self, conversation_id: str, content: str):
        _ = (conversation_id, content)


async def run() -> None:
    user_id = "__diag_active_care__"
    now = time.time()
    try:
        from core.services.user_physiology.service import get_user_physiology_service

        get_user_physiology_service().update(
            user_id,
            {
                "source": "tests",
                "measured_at": now,
                "metrics": {
                    "heart_rate_bpm": 88,
                    "spo2_percent": 97,
                    "sleep_hours_last_night": 6.0,
                    "stress_level": 0.55,
                },
            },
        )
    except Exception:
        pass

    prompt_types = [
        "checking",
        "planned_topic",
        "notification_assistant",
    ]

    for pt in prompt_types:
        captured = {}
        fake_agent = _FakeAgent(captured)
        fake_storage = _FakeStorage()
        fake_context = _FakeContext()
        executor = ActiveCareExecutor(fake_context, fake_storage)
        executor.write_diary_entry = AsyncMock(return_value=None)
        executor_mod._last_active_care_trigger_ts = 0.0

        with patch(
            "core.agents.chat_agent.get_chat_agent",
            return_value=fake_agent,
        ), patch(
            "core.interfaces.websocket.websocket_manager.get_websocket_manager",
            return_value=None,
        ), patch(
            "core.managers.notification_manager.get_notification_manager",
            return_value=_FakeNotificationManager(),
        ), patch(
            "core.core_engine.lifecycle_manager.get_aveline_service",
            return_value=_FakeAvelineService(),
        ):
            await executor.trigger_message(
                sys_prompt_type=pt,
                user_input_mock="[NOTIFICATION_TRIGGER]: 微信消息 2 条" if pt == "notification_assistant" else "[PLANNED_TRIGGER]",
                reminder_msg="晚上十点关灯休息" if pt == "reminder" else None,
                thought="他今天看起来有点累，先轻声问候",
                device_context={
                    "timestamp": now,
                    "battery_level": 0.62,
                    "is_charging": False,
                    "network_type": "WiFi",
                },
                client_type="wechat",
            )

        sys_prompt = str(captured.get("system_prompt_override") or "")
        print(f"\n=== Prompt Type: {pt} ===")
        print(f"[LLM User Input] {captured.get('message', '')}")
        print(f"[System Prompt Length] {len(sys_prompt)}")
        print("[System Prompt Override - Final Sent To LLM]")
        print("=" * 80)
        print(sys_prompt)
        print("=" * 80)

    stats = get_vocabulary_manager().get_stats()
    due_words = int(stats.get("due_words", 0) or 0)
    print("\n[Vocabulary Push Channel]")
    print(f"- due_words（待复习）: {due_words}")
    print("- 说明: 每日单词推送走通知链路（notification/websocket），不是 system_prompt 注入。")
    print("- 说明: 你聊天里看到“还有N个单词没复习”通常来自词汇统计/通知逻辑，而非 Active Care prompt 文本。")


if __name__ == "__main__":
    asyncio.run(run())
