"""学习日报生成器 —— 从 journal/service.py 中独立出来的学习专项总结模块

职责：
- 从当日对话中筛选学习类消息
- 调用 LLM 生成学习专项总结和明日教学计划
- 将总结写入 Study/Daily/ 目录
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.integrated_config import get_settings
from core.services.scheduler.task.task_scheduler import get_global_scheduler
from core.utils.json_utils import extract_json_object
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, get_diary_target_date, ts_to_str

logger = get_logger("StudySummaryGenerator")


def _get_study_root() -> Path:
    """从配置读取 Study 文件夹根路径，消除硬编码。"""
    try:
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            p = Path(study_root).expanduser()
            if not p.is_absolute():
                from core.utils.common import get_project_root
                p = get_project_root() / p
            return p.resolve()
    except Exception:
        pass
    # 兜底：使用默认路径
    return Path("D:/AI/Study").resolve()


class StudySummaryGenerator:
    """学习日报生成器，独立于 journal 模块。"""

    async def generate(
        self,
        date: Optional[str] = None,
        *,
        study_stats: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """生成指定日期的学习专项总结。

        Args:
            date: 日期字符串 YYYY-MM-DD，默认今天。
            study_stats: 可选，由 StudyService 提供的学习系统数据。

        Returns:
            总结 dict，或 None（当天无学习对话时）。
        """
        dt = self._parse_date(date)
        date_str = dt.strftime("%Y-%m-%d")

        chat_history = await self._load_chat_history_for_date(dt, limit=500)
        study_messages = self._filter_study_messages(chat_history)
        if not study_messages:
            logger.info(f"[Study Summary] {date_str} 无学习类对话，跳过学习专项总结")
            return None

        if study_stats is None:
            study_stats = {}
            try:
                from core.services.study.service import get_study_service
                study_stats = get_study_service().get_daily_study_summary_data()
            except Exception:
                pass

        student_profile = self._load_student_profile()
        study_chat_context = self._format_study_chat_context(study_messages)
        study_stats_context = (
            json.dumps(study_stats, ensure_ascii=False) if study_stats else "无学习系统数据"
        )

        # 注入结构化学生画像和薄弱点数据
        structured_context = self._build_structured_context(date_str)
        if structured_context:
            study_stats_context = study_stats_context + "\n\n" + structured_context

        from core.agents.chat_agent_components.persona_system.prompt.components import (
            STUDY_DAILY_SUMMARY_PROMPT_TEMPLATE,
        )

        prompt = STUDY_DAILY_SUMMARY_PROMPT_TEMPLATE.format(
            date_str=date_str,
            study_chat_context=study_chat_context,
            study_stats_context=study_stats_context,
            student_profile=student_profile,
        )

        try:
            raw_out = await self._call_llm(prompt, max_tokens=1024, temperature=0.3)
            data = extract_json_object(raw_out)
            if not isinstance(data, dict):
                raise ValueError("LLM returned non-JSON")
            data["generated_at"] = get_current_time().isoformat()
            data["source"] = "xiaoyou_study_summary"
        except Exception as e:
            logger.error(f"[Study Summary] 生成失败: {e}")
            data = {
                "date": date_str,
                "today_summary": f"学习总结生成失败: {e}",
                "breakthroughs": [],
                "struggles": [],
                "knowledge_gaps": [],
                "tomorrow_plan": {
                    "review_topics": [],
                    "new_topics": [],
                    "teaching_strategy": "生成失败，建议手动回顾今天的学习内容",
                    "priority": "medium",
                    "estimated_duration_minutes": 30,
                },
                "emotional_state": "unknown",
                "confidence_level": 5,
                "generated_at": get_current_time().isoformat(),
                "source": "xiaoyou_study_summary",
                "error": str(e),
            }

        await self._persist_to_study_dir(dt, data)
        return data

    # ================================================================
    # 消息过滤
    # ================================================================

    def _filter_study_messages(
        self, chat_history: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        study_messages = []
        for msg in chat_history:
            content = str(msg.get("content") or "")
            category = str(msg.get("category") or "")
            if category == "learning":
                study_messages.append(msg)
                continue
            try:
                from core.services.study.mode_detector import is_study_mode
                if is_study_mode(content):
                    study_messages.append(msg)
                    continue
            except Exception:
                pass
            try:
                from memory.core.taxonomy import classify_category
                if classify_category(content) == "learning":
                    study_messages.append(msg)
            except Exception:
                pass
        return study_messages

    def _format_study_chat_context(self, messages: List[Dict[str, Any]]) -> str:
        lines = []
        for msg in messages:
            ts = float(msg.get("timestamp") or 0.0)
            time_str = (
                ts_to_str(ts, "%H:%M:%S") if ts > 0 else "--:--:--"
            )
            role = "学生" if str(msg.get("role")) == "user" else "Aveline"
            content = str(msg.get("content") or "").strip()
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"[{time_str}] {role}: {content}")
        return "\n".join(lines) if lines else "无学习对话记录。"

    # ================================================================
    # 学生画像
    # ================================================================

    def _build_structured_context(self, date_str: str) -> str:
        """构建结构化学生画像 + 薄弱点上下文，注入 LLM prompt"""
        parts = []

        # 结构化学生画像
        try:
            from core.services.study.student_state import get_student_state_manager
            ss_mgr = get_student_state_manager()
            state = ss_mgr.get_state()
            if state.subjects:
                lines = ["【结构化学生画像】"]
                lines.append(f"连续学习天数: {state.streak_days}，总会话数: {state.total_sessions}")
                for subj_key, subj in state.subjects.items():
                    lines.append(
                        f"- {subj_key}: 掌握度 {subj.confidence:.1f}/10, "
                        f"累计 {subj.total_sessions} 次/{subj.total_minutes} 分钟, "
                        f"困难点: {', '.join(subj.struggling_topics[:5]) or '无'}"
                    )
                parts.append("\n".join(lines))
        except Exception as e:
            logger.debug(f"构建结构化画像失败: {e}")

        # 薄弱点报告
        try:
            from core.services.study.weakness_tracker import get_weakness_tracker
            wt = get_weakness_tracker()
            report = wt.get_weakness_report()
            if report.get("total_active", 0) > 0:
                lines = ["【薄弱点追踪】"]
                lines.append(f"活跃薄弱点: {report['total_active']}个, 今日待复习: {report['due_today']}个")
                for subj, items in report.get("by_subject", {}).items():
                    topic_names = [i["topic"] for i in items[:5]]
                    lines.append(f"- {subj}: {', '.join(topic_names)}")
                parts.append("\n".join(lines))
        except Exception as e:
            logger.debug(f"构建薄弱点报告失败: {e}")

        # 今日学习状态
        try:
            from core.services.study.daily_tracker import get_daily_tracker
            dt = get_daily_tracker()
            stats = dt.get_summary_stats(date_str)
            if stats.get("sessions_count", 0) > 0:
                lines = ["【今日学习统计】"]
                lines.append(
                    f"会话数: {stats['sessions_count']}, "
                    f"总时长: {stats['total_study_minutes']}分钟, "
                    f"新学知识点: {stats['knowledge_points_new']}, "
                    f"已掌握: {stats['knowledge_points_mastered']}, "
                    f"困难: {stats['knowledge_points_struggling']}"
                )
                parts.append("\n".join(lines))
        except Exception as e:
            logger.debug(f"构建今日统计失败: {e}")

        return "\n\n".join(parts)

    def _load_student_profile(self) -> str:
        study_root = _get_study_root()
        profile_parts = []

        monitor_path = study_root / "Mathematics" / "Aveline_Math_Monitor.md"
        if monitor_path.exists():
            try:
                content = monitor_path.read_text(encoding="utf-8")[:2000]
                profile_parts.append(f"【数学监控记录】:\n{content}")
            except Exception:
                pass

        handover_path = study_root / "Mathematics" / "Gaokao_Math_Progress_Handover.md"
        if handover_path.exists():
            try:
                content = handover_path.read_text(encoding="utf-8")[:2000]
                profile_parts.append(f"【数学交接文档】:\n{content}")
            except Exception:
                pass

        return "\n\n".join(profile_parts) if profile_parts else "暂无学生画像数据。"

    # ================================================================
    # 持久化
    # ================================================================

    async def _persist_to_study_dir(
        self, dt: datetime, data: Dict[str, Any]
    ) -> None:
        try:
            study_dir = _get_study_root() / "Daily"
            # 使用数字月份 (%m) 而不是英文月份缩写 (%b)
            month_dir = study_dir / dt.strftime("%Y") / dt.strftime("%m")
            month_dir.mkdir(parents=True, exist_ok=True)

            # 使用补零日格式 (%d) 而不是去零日
            filename = f"{dt.strftime('%d')}.md"
            filepath = month_dir / filename

            md_content = self._format_markdown(dt, data)
            await asyncio.to_thread(
                lambda: filepath.write_text(md_content, encoding="utf-8")
            )
            logger.info(f"[Study Summary] 已写入学习总结: {filepath}")

            # 确保当日子目录和 diary.md 存在
            date_subdir = month_dir / dt.strftime("%d")
            date_subdir.mkdir(parents=True, exist_ok=True)
            diary_md = date_subdir / "diary.md"
            if not diary_md.exists():
                date_str = dt.strftime("%Y-%m-%d")
                await asyncio.to_thread(
                    diary_md.write_text, f"# {date_str} 日记\n\n", "utf-8"
                )
                logger.info(f"[Study Summary] 已创建空日记文件: {diary_md}")
        except Exception as e:
            logger.warning(f"[Study Summary] 写入Study目录失败: {e}")

    def _format_markdown(self, dt: datetime, data: Dict[str, Any]) -> str:
        date_str = dt.strftime("%Y-%m-%d")
        tomorrow = data.get("tomorrow_plan", {})

        lines = [
            f"# 学习日报 - {date_str}",
            "",
            "## 今日学习总结",
            data.get("today_summary", "无记录"),
            "",
        ]

        breakthroughs = data.get("breakthroughs", [])
        if breakthroughs:
            lines.append("## 突破点")
            for b in breakthroughs:
                lines.append(f"- {b}")
            lines.append("")

        struggles = data.get("struggles", [])
        if struggles:
            lines.append("## 卡住的地方")
            for s in struggles:
                lines.append(f"- {s}")
            lines.append("")

        gaps = data.get("knowledge_gaps", [])
        if gaps:
            lines.append("## 知识漏洞")
            for g in gaps:
                lines.append(f"- {g}")
            lines.append("")

        lines.append("## 明日教学计划")
        review = tomorrow.get("review_topics", [])
        if review:
            lines.append("**复习重点**:")
            for r in review:
                lines.append(f"- {r}")
            lines.append("")

        new_topics = tomorrow.get("new_topics", [])
        if new_topics:
            lines.append("**新内容**:")
            for n in new_topics:
                lines.append(f"- {n}")
            lines.append("")

        strategy = tomorrow.get("teaching_strategy", "")
        if strategy:
            lines.append(f"**教学策略**: {strategy}")
            lines.append("")

        priority = tomorrow.get("priority", "medium")
        duration = tomorrow.get("estimated_duration_minutes", 30)
        lines.append(f"**优先级**: {priority} | **预计时长**: {duration}分钟")
        lines.append("")

        emotional = data.get("emotional_state", "unknown")
        confidence = data.get("confidence_level", 5)
        lines.append("## 状态评估")
        lines.append(f"- 学习情绪: {emotional}")
        lines.append(f"- 自信度: {confidence}/10")
        lines.append("")

        return "\n".join(lines)

    # ================================================================
    # 辅助方法
    # ================================================================

    async def _load_chat_history_for_date(
        self, dt: datetime, limit: int = 200
    ) -> List[Dict[str, Any]]:
        try:
            from memory.weighted_memory_manager import get_weighted_memory_manager

            mm = await asyncio.to_thread(get_weighted_memory_manager, "default_user")
            if not mm:
                return []
            raw_history = await asyncio.to_thread(mm.get_history, max(20, limit))
            if not isinstance(raw_history, list):
                return []
            day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            day_end = day_start + 86400
            result: List[Dict[str, Any]] = []
            for item in raw_history:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                if role not in {"user", "assistant"}:
                    continue
                ts = float(item.get("timestamp") or 0.0)
                if ts > 1e12:
                    ts = ts / 1000.0
                if ts < day_start or ts >= day_end:
                    continue
                result.append({
                    "timestamp": ts,
                    "role": role,
                    "content": str(item.get("content") or "").strip(),
                })
            result.sort(key=lambda x: float(x.get("timestamp") or 0.0))
            return result[-limit:]
        except Exception as e:
            logger.warning(f"Failed to fetch chat history for study summary: {e}")
            return []

    async def _call_llm(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.3
    ) -> str:
        scheduler = get_global_scheduler()
        model_hint = self._get_model_hint()

        for attempt in range(3):
            raw_out = ""
            try:
                async for chunk in scheduler.submit_llm_task(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model_hint=model_hint,
                ):
                    if isinstance(chunk, str):
                        raw_out += chunk
                    elif isinstance(chunk, dict) and chunk.get("content"):
                        raw_out += str(chunk.get("content") or "")
            except Exception as e:
                logger.warning(f"Study Summary LLM 调用异常 (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return ""

            if raw_out.strip():
                return raw_out

            logger.warning(f"Study Summary LLM 返回空内容 (attempt {attempt + 1})")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

        return ""

    @staticmethod
    def _get_model_hint() -> str:
        try:
            from config.model_config import get_journal_model
            hint = get_journal_model()
            if hint:
                return hint
        except Exception:
            pass
        try:
            settings = get_settings()
            return str(
                getattr(settings.model, "journal_model_hint", "") or ""
            ).strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> datetime:
        """解析日期字符串；未提供时走统一凌晨归属逻辑"""
        if not date_str:
            return get_diary_target_date()
        try:
            if " " in date_str:
                date_str = date_str.split(" ")[0]
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"Invalid date format {date_str}, using diary target date")
            return get_diary_target_date()
