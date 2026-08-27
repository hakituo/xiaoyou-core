import sys
import asyncio

sys.path.append(r"d:\AI\xiaoyou-core")

from core.services.workspace.service import get_workspace_service


async def run() -> None:
    ws = get_workspace_service()
    data = await ws.get_learning_panel_bundle(
        conversation_id="default_user",
        history_limit=20,
    )
    study_panel = data.get("study_panel") or {}
    daily_summary = study_panel.get("daily_summary") or {}
    vocab = daily_summary.get("vocab") or {}
    session = daily_summary.get("session") or {}
    recent_chat = data.get("recent_chat_history") or []
    print("=== Learning Panel Bundle Audit ===")
    print(f"date: {data.get('date')}")
    print(f"due_words: {int(vocab.get('to_review') or 0)}")
    print(f"daily_quota: {int(vocab.get('daily_quota') or 20)}")
    print(f"words_reviewed_today: {int(session.get('words_reviewed') or 0)}")
    print(f"study_streak_days: {int(study_panel.get('study_streak_days') or 0)}")
    print(f"recent_chat_count: {len(recent_chat)}")
    print(f"user_panel_keys: {sorted(list((data.get('user_panel') or {}).keys()))}")
    print(f"aveline_panel_keys: {sorted(list((data.get('aveline_panel') or {}).keys()))}")
    print(f"journal_context_keys: {sorted(list((data.get('journal_context') or {}).keys()))}")
    print("=== End ===")


if __name__ == "__main__":
    asyncio.run(run())
