"""验证 Active Care 硬提醒边界、双角色分工与 Peer Chat 素材。"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clients.bots.qq.peer_chat import PeerChatManager  # noqa: E402
from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (  # noqa: E402
    build_script_generation_prompt,
)
from core.services.active_care.checker.checker_event_handler import (  # noqa: E402
    is_legacy_auto_plan_reminder,
)
from core.services.character_daily.activity_model import ActivityType, DailyPlan  # noqa: E402
from core.services.character_daily.peer_chat_gate import build_situation_context  # noqa: E402
from scripts.cleanup.clean_active_care_dirty_records import (  # noqa: E402
    _cancel_legacy_auto_plan_reminders,
)


def verify_reminder_delivery_boundary() -> None:
    assert is_legacy_auto_plan_reminder({"source": "daily_task"})
    assert not is_legacy_auto_plan_reminder(
        {"source": "daily_task", "delivery_mode": "hard"}
    )
    assert not is_legacy_auto_plan_reminder({"source": "workspace"})

    reminders = [
        {
            "id": "legacy",
            "status": "pending",
            "message": "旧自动计划",
            "metadata": {"source": "daily_task"},
        },
        {
            "id": "explicit",
            "status": "pending",
            "message": "用户明确设置",
            "metadata": {"source": "daily_task", "delivery_mode": "hard"},
        },
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "reminders.json"
        path.write_text(json.dumps(reminders, ensure_ascii=False), encoding="utf-8")
        findings = []
        cleaned, changed = _cancel_legacy_auto_plan_reminders(path, findings)
    assert changed and len(findings) == 1
    assert cleaned[0]["status"] == "completed"
    assert cleaned[1]["status"] == "pending"


def verify_peer_chat_situation() -> None:
    plan_a = DailyPlan(
        role_id="aveline",
        date="2026-08-18",
        current_activity=ActivityType.IDLE,
        today_peer_chat_count=0,
    )
    plan_l = DailyPlan(
        role_id="ling",
        date="2026-08-18",
        current_activity=ActivityType.READING,
        today_peer_chat_count=2,
    )
    context = build_situation_context("aveline", plan_a, plan_l)
    assert context.startswith("七濑 澪刚发了会呆")
    assert "Ling" in context
    assert "今天已经聊过2次" in context
    assert "今天还没聊过" not in context


class _HistoryContext:
    async def get_latest_history_for_conversation(self, _conversation_id, limit=20):
        del limit
        return [
            {"role": "user", "content": "我刚做完一道很有意思的题"},
            {"role": "assistant", "content": "那题的反例挺巧的"},
            {
                "role": "assistant",
                "content": "到时间了",
                "metadata": {"source": "active_care"},
            },
        ]


async def verify_peer_chat_material() -> None:
    history = await PeerChatManager.get_recent_master_history(
        _HistoryContext(), "persona_aveline", speaker_name="七濑 澪"
    )
    assert "主人: 我刚做完一道很有意思的题" in history
    assert "七濑 澪: 那题的反例挺巧的" in history
    assert "到时间了" not in history

    prompt = build_script_generation_prompt(
        role_name="七濑 澪",
        peer_name="Ling",
        role_id="aveline",
        peer_role_id="ling",
        topic="最近的小事",
        situation="两人都有空",
        opening_idea="分享一个具体细节",
        recent_master_history=history,
        recent_peer_scripts="七濑 澪: 上次说的书看完了",
        time_str="2026-08-18 14:00",
    )
    assert "主人Master是你们共同生活的一部分" in prompt.system_prompt
    assert "优先挑一个具体、有趣" in prompt.user_prompt
    assert "上次互聊的结尾" in prompt.user_prompt


async def main() -> int:
    verify_reminder_delivery_boundary()
    verify_peer_chat_situation()
    await verify_peer_chat_material()
    print("PASS: Active Care 分工、提醒边界与 Peer Chat 素材验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
