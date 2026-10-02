# -*- coding: utf-8 -*-
"""专注会话只读查询工具（供 AI 查询当前/历史专注状态）。

隐私约束：
- 工具只返回聚合后的专注状态（专注率、在场/分心秒数、剩余时长、总结等）。
- 绝不返回任何图片 / 视频 / 原始观察帧；只能返回结构化统计。
- 工具不能代为开启摄像头监控，也不能绕过用户 consent 强制开启监控。
- 当前会话、指定历史会话、最近历史统一由一个工具处理，避免模型在两个近义工具间路由。
"""
from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool


class FocusSessionQueryInput(BaseModel):
    user_id: Optional[str] = Field(
        default="default", description="用户标识，缺省为 default。"
    )
    scope: Literal["current", "recent", "session"] = Field(
        default="current",
        description=(
            "查询范围：current=当前进行中的会话；recent=最近已结束会话；"
            "session=指定 session_id 的会话。"
        ),
    )
    session_id: Optional[str] = Field(
        default=None,
        description="scope=session 时要查询的会话 ID。兼容旧调用：传入该字段会自动按 session 查询。",
    )
    limit: int = Field(
        default=5, ge=1, le=20, description="scope=recent 时返回的最近会话条数。"
    )


def _session_public_view(sess: dict, *, effective_seconds: Optional[float] = None) -> dict:
    """把会话裁剪为对 AI 安全可读的视图，并补充实时派生字段。"""
    keys = (
        "session_id", "user_id", "subject", "planned_minutes", "mode",
        "monitoring", "status", "reminders_muted",
        "accumulated_active_seconds", "sec_focused", "sec_possibly_distracted",
        "sec_away", "sec_unknown", "interruption_count",
        "longest_focus_streak_sec", "last_presence", "last_activity",
        "last_confidence", "last_observed_at",
        "self_rating", "note", "summary_text", "created_at",
        "started_at", "finished_at",
    )
    view = {k: sess.get(k) for k in keys if k in sess}

    if effective_seconds is None:
        effective_seconds = float(sess.get("accumulated_active_seconds", 0.0) or 0.0)
    effective_seconds = max(0.0, float(effective_seconds))
    planned = int(sess.get("planned_minutes", 0) or 0)
    view["effective_minutes"] = round(effective_seconds / 60, 1)
    view["remaining_seconds"] = max(0.0, planned * 60 - effective_seconds)

    total = (
        float(sess.get("sec_focused", 0.0) or 0.0)
        + float(sess.get("sec_possibly_distracted", 0.0) or 0.0)
        + float(sess.get("sec_away", 0.0) or 0.0)
        + float(sess.get("sec_unknown", 0.0) or 0.0)
    )
    view["focus_rate"] = (
        round(float(sess.get("sec_focused", 0.0) or 0.0) / total * 100, 1)
        if total > 0
        else 0.0
    )
    view["nudge_count"] = len(sess.get("nudge_events", []) or [])
    return view


class GetFocusSessionTool(BaseTool):
    # 保留原 current 工具名作为稳定协议名；功能已覆盖 current/recent/session 三种查询。
    name = "get_current_focus_session"
    description = (
        "统一只读查询用户的专注番茄钟会话。可查当前会话、最近已结束会话，"
        "或按 session_id 查询某次会话；返回学科、计划/有效/剩余时长、专注率、"
        "分心/离开、中断次数和总结等聚合数据。绝不返回图片或原始画面，"
        "也不能开启摄像头监控。"
    )
    short_description = "查询当前或历史专注会话（只读，不含画面）"
    category = "study"
    args_schema = FocusSessionQueryInput

    async def _run(
        self,
        user_id: str = "default",
        scope: str = "current",
        session_id: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        try:
            from core.services.study.focus_session_service import get_focus_session_service

            svc = get_focus_session_service()
            uid = str(user_id or "default")
            resolved_scope = "session" if session_id else str(scope or "current").strip().lower()

            if resolved_scope == "current":
                sess = svc.get_current(uid)
                if not sess:
                    return "当前没有进行中的专注会话。"
                return json.dumps(
                    _session_public_view(
                        sess.to_dict(), effective_seconds=sess.effective_elapsed()
                    ),
                    ensure_ascii=False,
                )

            if resolved_scope == "session":
                if not session_id:
                    return "Error: scope=session 时必须提供 session_id。"
                data = svc.get_summary(uid, session_id)
                if not data:
                    return f"未找到会话 {session_id}。"
                return json.dumps(_session_public_view(data), ensure_ascii=False)

            if resolved_scope == "recent":
                history = svc.get_history(uid, limit=max(1, min(20, int(limit))))
                if not history:
                    return "用户还没有已结束的专注会话记录。"
                return json.dumps(
                    [_session_public_view(item) for item in history],
                    ensure_ascii=False,
                )

            return f"Error: 不支持的查询范围 {resolved_scope}。"
        except Exception as e:  # pragma: no cover
            return f"Error: 查询专注会话失败: {e}"


# registry.py 仍使用旧类名导入；current 名直接指向统一工具。
GetCurrentFocusSessionTool = GetFocusSessionTool


class GetFocusSessionSummaryTool(GetFocusSessionTool):
    """旧工具名的禁用兼容壳。

    保留注册条目是为了不让历史 tool profile / 配置引用变成悬空引用；
    enabled_by_default=False 保证模型侧只暴露统一后的 get_current_focus_session。
    """

    name = "get_focus_session_summary"
    enabled_by_default = False
    short_description = "已合并到 get_current_focus_session（兼容占位，不加载）"


__all__ = [
    "FocusSessionQueryInput",
    "GetFocusSessionTool",
    "GetCurrentFocusSessionTool",
    "GetFocusSessionSummaryTool",
]
