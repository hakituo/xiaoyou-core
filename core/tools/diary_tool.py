from __future__ import annotations
from typing import Optional

from pydantic import BaseModel, Field
from core.tools.base import BaseTool
from core.services.workspace.service import get_workspace_service


class DiaryInput(BaseModel):
    content: str = Field(description="日记内容")
    mood: str = Field(
        default="neutral", description="心情 (happy, sad, neutral, excited, etc.)"
    )
    thought: Optional[str] = Field(default=None, description="相关的思考或上下文")


class WriteDiaryTool(BaseTool):
    name = "write_diary"
    description = "写一篇日记到个人工作区。当你想要记录今天发生的事情、感受或者对未来的规划时使用。"
    short_description = "写日记记录感受"
    category = "daily"
    args_schema = DiaryInput

    async def _run(
        self, content: str, mood: str = "neutral", thought: Optional[str] = None
    ) -> str:
        try:
            ws = get_workspace_service()
            path = await ws.write_diary(
                content, mood=mood, thought=thought, type="proactive"
            )
            return f"日记已保存: {path}"
        except Exception as e:
            return f"写日记失败: {str(e)}"


class ReadDiaryInput(BaseModel):
    date: Optional[str] = Field(
        default=None,
        description="要读取的日期 YYYY-MM-DD。留空默认读取今天的日记。",
    )
    days_back: Optional[int] = Field(
        default=0,
        description="向前读取几天。0 表示只读当天，3 表示读最近 3 天的日记。",
    )


class ReadDiaryTool(BaseTool):
    name = "read_diary"
    description = (
        "阅读你自己的历史日记。可以指定日期，默认读取今天的日记。"
        "你只能读到自己角色视角下的日记（Aveline 读 Aveline 的，Ling读Ling的）。"
    )
    short_description = "阅读自己的历史日记"
    category = "daily"
    args_schema = ReadDiaryInput

    async def _run(
        self, date: Optional[str] = None, days_back: int = 0
    ) -> str:
        try:
            from core.services.journal.service import get_journal_service
            from core.utils.data_paths import (
                _resolve_scope_from_active_persona,
                resolve_data_scope_from_source,
            )
            from datetime import datetime, timedelta

            svc = get_journal_service()
            scope = _resolve_scope_from_active_persona()

            # 解析起始日期
            if date:
                try:
                    start_dt = datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    return "日期格式错误，请使用 YYYY-MM-DD 格式"
            else:
                from core.utils.time_utils import get_diary_target_date
                start_dt = get_diary_target_date()

            days_back = max(0, min(int(days_back or 0), 30))  # 最多读 30 天

            results = []
            for i in range(days_back + 1):
                dt = start_dt - timedelta(days=i)
                # storage.get_entries 已遍历所有 scope 目录，这里按当前 persona 过滤
                all_entries = await svc.storage.get_entries(dt)
                entries = [
                    e for e in all_entries
                    if resolve_data_scope_from_source(
                        getattr(e, "source", None), default="user"
                    ) == scope
                ]
                if not entries:
                    continue
                date_str = dt.strftime("%Y-%m-%d")
                day_lines = [f"--- {date_str} ---"]
                for e in entries:
                    line = f"[{e.time_str}] {e.content}"
                    if e.mood and e.mood != "neutral":
                        line += f" (心情: {e.mood})"
                    day_lines.append(line)
                results.append("\n".join(day_lines))

            if not results:
                target = date or "今天"
                return f"没有找到{target}的日记记录。"

            header = f"📖 日记记录（scope: {scope}）："
            return header + "\n\n" + "\n\n".join(results)
        except Exception as e:
            return f"读取日记失败: {str(e)}"


class ReadDailySummaryInput(BaseModel):
    date: Optional[str] = Field(
        default=None,
        description="要读取的日期 YYYY-MM-DD。留空默认读取今天的每日总结。",
    )
    days_back: Optional[int] = Field(
        default=0,
        description="向前读取几天。0 表示只读当天，3 表示读最近 3 天的每日总结。",
    )


class ReadDailySummaryTool(BaseTool):
    """读取每日总结（DailySummary）。

    与 read_diary 不同：read_diary 读的是手写/自动追加的日记条目（JournalEntry），
    本工具读的是夜间任务生成的 LLM 每日总结（diary_summary.json）。
    仅读取当前 persona scope 下的总结，避免跨角色读取。
    """

    name = "read_daily_summary"
    description = (
        "阅读自己角色视角下的每日总结（夜间任务自动生成的 LLM 日回顾）。"
        "可以指定日期，默认读取今天的总结；也可用 days_back 读最近几天。"
        "你只能读到自己角色视角下的总结（Aveline 读 Aveline 的，Ling读Ling的）。"
    )
    short_description = "阅读自己的每日总结"
    category = "daily"
    args_schema = ReadDailySummaryInput

    async def _run(
        self, date: Optional[str] = None, days_back: int = 0
    ) -> str:
        try:
            from core.services.journal.service import get_journal_service
            from core.utils.data_paths import _resolve_scope_from_active_persona
            from datetime import datetime, timedelta

            svc = get_journal_service()
            scope = _resolve_scope_from_active_persona()

            # 解析起始日期
            if date:
                try:
                    start_dt = datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    return "日期格式错误，请使用 YYYY-MM-DD 格式"
            else:
                from core.utils.time_utils import get_diary_target_date
                start_dt = get_diary_target_date()

            days_back = max(0, min(int(days_back or 0), 30))  # 最多读 30 天

            results = []
            for i in range(days_back + 1):
                dt = start_dt - timedelta(days=i)
                # 显式传 scope，确保只读当前 persona 的总结
                summary = await svc.storage.get_daily_summary(dt, scope=scope)
                if not summary:
                    continue
                date_str = dt.strftime("%Y-%m-%d")
                lines = [f"--- {date_str} ---"]
                lines.append(f"总结：{summary.summary}")
                if summary.tomorrow_tone:
                    lines.append(f"明日基调：{summary.tomorrow_tone}")
                stats = summary.stats or {}
                if stats:
                    # 只挑几个对 AI 有用的字段，避免过长
                    chat_turns = stats.get("chat_turn_count")
                    entries = stats.get("entry_count")
                    if chat_turns is not None:
                        lines.append(f"对话轮数：{chat_turns}")
                    if entries is not None:
                        lines.append(f"日记条目数：{entries}")
                results.append("\n".join(lines))

            if not results:
                target = date or "今天"
                return f"没有找到{target}的每日总结。"

            header = f"📋 每日总结（scope: {scope}）："
            return header + "\n\n" + "\n\n".join(results)
        except Exception as e:
            return f"读取每日总结失败: {str(e)}"


class ReadMonthlySummaryInput(BaseModel):
    month: Optional[str] = Field(
        default=None,
        description=(
            "要读取的月份 YYYY-MM（如 2026-06）。"
            "留空默认读取上一个月的月度总结。"
        ),
    )


class ReadMonthlySummaryTool(BaseTool):
    """读取月度总结（MonthlySummary）。

    让 AI 在对话中查看自己角色视角下的月度回顾，
    与 read_diary / read_daily_summary 形成日/月两级回顾读取能力。
    仅读取当前 persona scope 下的总结。
    """

    name = "read_monthly_summary"
    description = (
        "阅读自己角色视角下的月度总结（月末夜间任务自动生成的 LLM 月度回顾）。"
        "可以指定月份 YYYY-MM，默认读取上一个月的月度总结。"
        "你只能读到自己角色视角下的总结（Aveline 读 Aveline 的，Ling读Ling的）。"
    )
    short_description = "阅读自己的月度总结"
    category = "daily"
    args_schema = ReadMonthlySummaryInput

    async def _run(self, month: Optional[str] = None) -> str:
        try:
            from core.services.journal.service import get_journal_service
            from core.utils.data_paths import _resolve_scope_from_active_persona
            from core.utils.time_utils import get_current_time
            from datetime import datetime, timedelta

            svc = get_journal_service()
            scope = _resolve_scope_from_active_persona()

            # 解析月份：YYYY-MM → 取该月任意一天作为定位日期
            if month:
                try:
                    # 用该月 1 号作为定位
                    dt = datetime.strptime(month, "%Y-%m")
                    # 改成该月最后一天，与 storage 按 YYYY/MM 路径定位一致
                    if dt.month == 12:
                        next_month = dt.replace(year=dt.year + 1, month=1, day=1)
                    else:
                        next_month = dt.replace(month=dt.month + 1, day=1)
                    dt = next_month - timedelta(days=1)
                except ValueError:
                    return "月份格式错误，请使用 YYYY-MM 格式（如 2026-06）"
            else:
                # 默认上一个月：当月 1 号减 1 天，再取该月最后一天
                now = get_current_time()
                first_of_this_month = now.replace(day=1)
                dt = first_of_this_month - timedelta(days=1)

            # 显式按 scope 路径读取，避免读到其他角色
            monthly_dir = svc.storage._get_monthly_dir(dt, scope=scope)
            summary_file = monthly_dir / "summary.json"
            if not summary_file.exists():
                month_str = dt.strftime("%Y-%m")
                return (
                    f"没有找到 {month_str} 的月度总结。"
                    f"（路径：{monthly_dir}）"
                )

            # 直接读文件并解析，避免 service 层重新解析 scope 造成不一致
            from core.services.journal.models import MonthlySummary as _MS
            try:
                raw = summary_file.read_text(encoding="utf-8")
                summary = _MS.model_validate_json(raw)
            except Exception as parse_err:
                return f"月度总结文件解析失败（{summary_file}）: {parse_err}"

            month_str = summary.month or dt.strftime("%Y-%m")
            lines = [f"📅 月度总结 {month_str}（scope: {scope}）："]
            lines.append("")
            lines.append("【总览】")
            lines.append(summary.summary)
            if summary.key_events:
                lines.append("")
                lines.append("【本月大事记】")
                for i, ev in enumerate(summary.key_events, 1):
                    lines.append(f"{i}. {ev}")
            if summary.mood_trend:
                lines.append("")
                lines.append("【心情趋势】")
                lines.append(summary.mood_trend)
            if summary.persona_evolution:
                lines.append("")
                lines.append("【人设进化】")
                pe = summary.persona_evolution
                if pe.get("new_traits"):
                    lines.append("新特征：" + "；".join(pe["new_traits"]))
                if pe.get("new_interests"):
                    lines.append("新兴趣：" + "；".join(pe["new_interests"]))
                if pe.get("relationship_change"):
                    lines.append("关系变化：" + str(pe["relationship_change"]))
            return "\n".join(lines)
        except Exception as e:
            return f"读取月度总结失败: {str(e)}"
