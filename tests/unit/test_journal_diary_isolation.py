from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest import mock

from core.services.journal.journal_helpers import (
    build_daily_summary_messages,
    format_diary_context,
)
from core.services.journal.models import JournalEntry
from core.services.journal.summary_context import SummaryContextLoader
from core.services.journal.summary_guard import (
    daily_summary_similarity,
    is_overly_similar_daily_summary,
)


def _entry(*, source: str, entry_type: str, content: str, thought: str | None = None):
    return JournalEntry(
        timestamp=1.0,
        time_str="00:00:01",
        source=source,
        type=entry_type,
        content=content,
        thought=thought,
    )


def test_diary_context_only_keeps_user_and_current_persona_raw_fragments():
    entries = [
        _entry(source="user", entry_type="daily", content="主人手写内容"),
        _entry(source="ling", entry_type="daily", content="Ling自己的片段"),
        _entry(source="aveline", entry_type="daily", content="Aveline 自己的片段"),
        _entry(
            source="aveline",
            entry_type="daily_summary",
            content="Aveline 自动总结正文",
            thought="auto_generated_daily_summary",
        ),
    ]

    ling_context = format_diary_context(entries, persona="ling")
    assert "主人手写内容" in ling_context
    assert "Ling自己的片段" in ling_context
    assert "Aveline 自己的片段" not in ling_context
    assert "Aveline 自动总结正文" not in ling_context

    aveline_context = format_diary_context(entries, persona="aveline")
    assert "主人手写内容" in aveline_context
    assert "Aveline 自己的片段" in aveline_context
    assert "Ling自己的片段" not in aveline_context
    assert "Aveline 自动总结正文" not in aveline_context


def test_role_prompts_use_different_structure_and_identity_boundaries():
    kwargs = dict(
        date_str="2026-08-23",
        diary_context="手记",
        chat_context="直接聊天",
        active_care_context="主动行为",
        user_status_summary="状态",
        study_context="学习",
        daily_context="生活",
        peer_chat_context="室友互动",
        user_diary_context="主人日记",
        character_daily_context="角色节奏",
    )
    aveline = build_daily_summary_messages(**kwargs, persona="aveline")
    ling = build_daily_summary_messages(**kwargs, persona="ling")

    assert aveline[0]["content"] != ling[0]["content"]
    assert "语气克制、敏锐" in aveline[0]["content"]
    assert "临睡前想到哪写到哪" in ling[0]["content"]
    assert "绝不把她的经历" in aveline[0]["content"]
    assert "不能换个口气算到我头上" in ling[0]["content"]


def test_chat_loader_excludes_other_scope_proactive_and_system_greeting(tmp_path: Path):
    day_dir = tmp_path / "2026" / "08" / "23"
    day_dir.mkdir(parents=True)
    rows = [
        {
            "event_id": "direct",
            "role": "user",
            "content": "玲玲，今天聊这个",
            "timestamp": datetime(2026, 8, 23, 12, 0).timestamp(),
            "storage_scope": "ling",
            "event_type": "chat_message",
        },
        {
            "event_id": "wrong-scope",
            "role": "assistant",
            "content": "这是 Aveline 的内容",
            "timestamp": datetime(2026, 8, 23, 12, 1).timestamp(),
            "storage_scope": "aveline",
            "event_type": "chat_reply",
        },
        {
            "event_id": "proactive",
            "role": "assistant",
            "content": "主动关怀重复内容",
            "timestamp": datetime(2026, 8, 23, 12, 2).timestamp(),
            "storage_scope": "ling",
            "event_type": "proactive_message",
            "metadata": {"is_proactive": True},
        },
        {
            "event_id": "greeting",
            "role": "user",
            "content": "[SYSTEM_GREETING]",
            "timestamp": datetime(2026, 8, 23, 12, 3).timestamp(),
            "storage_scope": "ling",
            "event_type": "chat_message",
        },
    ]
    (day_dir / "chat.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    loader = SummaryContextLoader(mock.Mock())
    with mock.patch(
        "core.utils.data.data_paths.get_role_chat_history_dir", return_value=tmp_path
    ):
        loaded = asyncio.run(
            loader.load_chat_history_for_date(
                datetime(2026, 8, 23, 18, 0), persona="ling"
            )
        )

    assert [item["content"] for item in loaded] == ["玲玲，今天聊这个"]


def test_daily_summary_similarity_ignores_punctuation_but_allows_distinct_diaries():
    aveline = "凌晨他问我物理。我陪他聊到很晚，最后提醒他早点睡。" * 4
    copied = "凌晨，他问我物理！我陪他聊到很晚；最后提醒他早点睡。" * 4
    ling = "今天没怎么聊。晚上他突然叫我，我回了两句就困得不想动了。" * 4

    assert daily_summary_similarity(aveline, copied) > 0.95
    assert is_overly_similar_daily_summary(aveline, copied)
    assert daily_summary_similarity(aveline, ling) < 0.78
    assert not is_overly_similar_daily_summary(aveline, ling)
