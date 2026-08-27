# -*- coding: utf-8 -*-
"""专注会话只读查询工具（供 AI 查询当前/历史专注状态）。

隐私约束（来自施工计划）：
- 工具只返回聚合后的专注状态（专注率、在场/分心秒数、剩余时长、总结等）。
- 绝不返回任何图片 / 视频 / 原始观察帧；只能返回结构化统计。
- 工具不能代为开启摄像头监控，也不能绕过用户 consent 强制开启监控。
  "能否开启监控" 由前端 UI 与用户显式交互决定，AI 只做只读查询与建议。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool


class FocusSessionCurrentInput(BaseModel):
    user_id: Optional[str] = Field(
        default="default", description="用户标识，缺省为 default。"
    )


class FocusSessionSummaryInput(BaseModel):
    user_id: Optional[str] = Field(
        default="default", description="用户标识，缺省为 default。"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="要查询的会话 ID；缺省时返回最近一条已结束会话的总结。",
    )
    limit: Optional[int] = Field(
        default=5, description="当不指定 session_id、查询历史列表时返回的最近会话条数。"
    )


def _session_public_view(sess: dict) -> dict:
    """把会话裁剪为对 AI 安全可读的视图（剔除任何媒体/原始帧）。"""
    keys = (
        "session_id", "user_id", "subject", "planned_minutes", "mode",
        "monitoring", "status", "reminders_muted",
        "accumulated_active_seconds", "sec_focused", "sec_possibly_distracted",
        "sec_away", "sec_unknown", "interruption_count",
        "longest_focus_streak_sec", "last_presence", "last_activity",
        "last_confidence", "last_observed_at", "nudge_events",
        "self_rating", "note", "summary_text", "created_at",
        "started_at", "finished_at", "planned_minutes",
    )
    view = {k: sess.get(k) for k in keys if k in sess}
    # 计算展示用派生字段
    acc = float(sess.get("accumulated_active_seconds", 0.0) or 0.0)
    planned = int(sess.get("planned_minutes", 0) or 0)
    view["effective_minutes"] = round(acc / 60, 1)
    view["remaining_seconds"] = max(0.0, planned * 60 - acc)
    # 专注率（基于聚合秒数）
    total = (float(sess.get("sec_focused", 0.0) or 0.0)
             + float(sess.get("sec_possibly_distracted", 0.0) or 0.0)
             + float(sess.get("sec_away", 0.0) or 0.0)
             + float(sess.get("sec_unknown", 0.0) or 0.0))
    view["focus_rate"] = round(sess.get("sec_focused", 0.0) / total * 100, 1) if total > 0 else 0.0
    # nudge 只暴露计数与 reason，不暴露完整消息内容（避免噪声）
    nudge_events = sess.get("nudge_events", []) or []
    view["nudge_count"] = len(nudge_events)
    return view


class GetCurrentFocusSessionTool(BaseTool):
    name = "get_current_focus_session"
    description = (
        "只读查询用户当前进行中的专注番茄钟会话状态（若有）。"
        "返回聚合后的专注统计：学科、计划/已用/剩余时长、在场/分心率、"
        "是否开启摄像头监控、当前状态（active/paused/无会话）。"
        "绝不返回任何图片或原始画面数据；该工具不能开启摄像头监控。"
    )
    short_description = "查询当前专注会话状态（只读，不含画面）"
    category = "study"
    args_schema = FocusSessionCurrentInput

    async def _run(self, user_id: str = "default") -> str:
        try:
            from core.services.study.focus_session_service import get_focus_session_service
            svc = get_focus_session_service()
            sess = svc.get_current(user_id)
            if not sess:
                return "当前没有进行中的专注会话。"
            return _session_public_view(sess.to_dict()).__str__()
        except Exception as e:  # pragma: no cover
            return f"Error: 查询当前专注会话失败: {e}"


class GetFocusSessionSummaryTool(BaseTool):
    name = "get_focus_session_summary"
    description = (
        "只读查询专注会话总结：可指定 session_id 查询某次会话的总结与统计，"
        "或不指定而返回最近若干次已结束会话的总结列表。"
        "返回自然语言总结、专注率、时长分布、中断次数等聚合数据，不含任何画面。"
    )
    short_description = "查询专注会话总结（只读，不含画面）"
    category = "study"
    args_schema = FocusSessionSummaryInput

    async def _run(self, user_id: str = "default", session_id: Optional[str] = None,
                   limit: int = 5) -> str:
        try:
            import json
            from core.services.study.focus_session_service import get_focus_session_service
            svc = get_focus_session_service()
            if session_id:
                data = svc.get_summary(user_id, session_id)
                if not data:
                    return f"未找到会话 {session_id} 的总结。"
                return json.dumps(_session_public_view(data), ensure_ascii=False)
            history = svc.get_history(user_id, limit=max(1, int(limit)))
            if not history:
                return "用户还没有已结束的专注会话记录。"
            return json.dumps([_session_public_view(h) for h in history], ensure_ascii=False)
        except Exception as e:  # pragma: no cover
            return f"Error: 查询专注会话总结失败: {e}"
