import asyncio
from typing import Any, Dict


async def collect_study_overview(workspace_service: Any) -> Dict[str, Any]:
    from core.services.study.service import get_study_service

    service = get_study_service()
    session_stats = await asyncio.to_thread(service.get_session_stats)
    daily_summary = await asyncio.to_thread(service.get_daily_study_summary_data)
    tools = await asyncio.to_thread(service.list_tools)
    study_root = await workspace_service.get_study_root_path()
    recent_files = await workspace_service._get_recent_study_files(limit=10)
    streak_days = await workspace_service._get_study_streak_days()
    return {
        "study_root": study_root,
        "session_stats": session_stats,
        "daily_summary": daily_summary,
        "tool_categories": list((tools or {}).keys()),
        "study_data_tools": (tools or {}).get("study_data", []),
        "recent_files": recent_files,
        "study_streak_days": streak_days,
    }
