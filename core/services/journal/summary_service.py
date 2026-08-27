"""日记总结服务（每日总结 / 每月总结 / 记忆蒸馏）

从 core/services/journal/service.py 拆分而来，承担 JournalService 中
与"总结生成"相关的全部职责。JournalService 作为门面，把调用委托给本模块。

设计原则：
- 依赖注入：构造时接收 JournalService 实例，避免循环引用
- 上下文加载委托给 SummaryContextLoader
- 格式化函数复用 journal_helpers，不重复造轮子
- 保持外部 API 完全兼容（通过 JournalService 门面转发）
"""
import asyncio
import json
import aiofiles
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time
from core.utils.data_paths import get_user_daily_dir
from core.utils.json_utils import extract_json_object
from core.services.journal.models import (
    DailySummary,
    JournalEntry,
    MonthlySummary,
)
from core.services.journal.storage import JournalStorage
from core.services.journal.summary_context import SummaryContextLoader
from core.services.journal.summary_guard import (
    daily_summary_similarity,
    is_overly_similar_daily_summary,
    is_valid_daily_summary_obj,
    is_valid_daily_summary_text,
)
from core.services.journal.summary_parse_support import parse_daily_summary_payload
from core.services.journal.journal_helpers import (
    build_daily_summary_messages,
    build_study_digest_text,
    call_llm_stream,
    format_active_care_context,
    format_character_daily_context,
    format_chat_context,
    format_diary_context,
    format_peer_chat_context,
    load_user_diary_from_study,
)

if TYPE_CHECKING:
    # 仅用于类型注解，避免运行时循环导入
    from core.services.journal.service import JournalService

logger = get_logger("JournalSummaryService")


class JournalSummaryService:
    """日记总结生成服务

    负责每日总结、每月总结、记忆蒸馏三类 LLM 驱动的总结任务。
    通过 service 引用回写日记条目、调用记忆联动等。
    上下文加载委托给 SummaryContextLoader，格式化复用 journal_helpers。
    """

    def __init__(self, service: "JournalService"):
        self.service = service
        self.storage: JournalStorage = service.storage
        self.settings = service.settings
        # 上下文加载器，负责从磁盘各类数据源加载当日上下文
        self._context_loader = SummaryContextLoader(service.storage)

    # ── 每日总结 ──────────────────────────────────────────────

    async def _append_daily_summary_diary_entry(
        self,
        *,
        dt: datetime,
        summary_obj: DailySummary,
        study_stats: Dict[str, Any],
        persona: str = "aveline",
    ) -> None:
        try:
            if not is_valid_daily_summary_obj(summary_obj):
                logger.warning("跳过写入无效每日总结日记: %s", summary_obj.date)
                return
            if not getattr(
                self.settings.memory,
                "append_auto_daily_summary_to_user_journal",
                False,
            ):
                return
            from core.utils.data_paths import resolve_data_scope_from_source

            entries = await self.storage.get_entries(dt)
            existing_entry = next(
                (
                    e
                    for e in entries
                    if str(e.type) == "daily_summary"
                and resolve_data_scope_from_source(
                    getattr(e, "source", None), default="user"
                )
                == persona
                ),
                None,
            )
            digest = build_study_digest_text(study_stats)
            content = str(summary_obj.summary or "").strip()
            if digest:
                content = f"{content}\n\n【学习总结】\n{digest}"
            tags = ["每日总结"]
            if digest and "学习总结" not in tags:
                tags.append("学习总结")
            # source 必须用 persona 本身，不能用"当前活跃 persona"：
            # nightly 运行时活跃 persona 通常落在 aveline，旧逻辑会把Ling的
            # 总结记成 source=aveline 并落盘到 aveline 目录，
            # 导致安卓端按 source 分组时永远看不到Ling的日记。
            entry = JournalEntry(
                timestamp=get_current_time().timestamp(),
                time_str=get_current_time().strftime("%H:%M:%S"),
                type="daily_summary",
                content=content,
                thought="auto_generated_daily_summary",
                tags=tags,
                source=persona,
            )
            if existing_entry is not None:
                # force=True 重生成时原位替换旧自动总结，避免摘要文件与条目正文不一致。
                entry.id = existing_entry.id
                entry.timestamp = existing_entry.timestamp
                entry.time_str = existing_entry.time_str
                await self.storage.replace_entry(entry, dt)
            else:
                await self.storage.save_entry(entry, dt)
            try:
                from core.services.journal.persona_exports import (
                    get_persona_journal_export_service,
                )
                await get_persona_journal_export_service().export_after_entry(entry, dt)
            except Exception as e:
                logger.warning(f"更新 persona 每日总结导出失败: {e}")
            if existing_entry is None:
                await self.service._append_journal_memory(entry)
        except Exception as e:
            logger.warning(f"追加每日总结到日记失败: {e}")

    @staticmethod
    def _build_failed_daily_summary(
        date_str: str,
        *,
        reason: str,
        error: Any = None,
        raw_output: str = "",
    ) -> DailySummary:
        """构造失败态 DailySummary，但不做任何持久化。"""
        stats: Dict[str, Any] = {"generated": False, "reason": reason}
        if error is not None:
            stats["error"] = str(error)
        if raw_output:
            stats["raw_output_excerpt"] = str(raw_output)[:500]
            stats["raw_output_len"] = len(str(raw_output))
        return DailySummary(
            date=date_str,
            summary="自动生成失败，请稍后重试。",
            stats=stats,
        )

    async def _persist_study_summary_artifact(
        self, *, dt: datetime, summary_obj: DailySummary, study_stats: Dict[str, Any]
    ) -> None:
        try:
            target_dir = (
                get_user_daily_dir()
                / dt.strftime("%Y")
                / dt.strftime("%m")
                / dt.strftime("%d")
            )
            payload = {
                "date": dt.strftime("%Y-%m-%d"),
                "daily_summary": summary_obj.model_dump() if summary_obj else None,
                "study_summary": study_stats or {},
                "generated_at": get_current_time().isoformat(),
            }
            await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(
                (target_dir / "learning_summary.json").write_text,
                json.dumps(payload, ensure_ascii=False, indent=2),
                "utf-8",
            )
        except Exception as e:
            logger.warning(f"写入学习总结制品失败: {e}")

    async def get_daily_summary(
        self, date: Optional[str] = None, persona: str = "aveline"
    ) -> Optional[DailySummary]:
        dt = self.service._parse_date(date)
        # 显式传 scope：Aveline / Ling / 主人 的每日总结各自独立，
        # 未指定时 storage 默认按 aveline/ling/user 顺序找（保持旧行为兼容）。
        if persona in ("aveline", "ling", "user"):
            return await self.storage.get_daily_summary(dt, scope=persona)
        return await self.storage.get_daily_summary(dt)

    async def get_tomorrow_tone(self) -> Optional[str]:
        try:
            yesterday = get_current_time() - timedelta(days=1)
            summary = await self.storage.get_daily_summary(yesterday)
            if summary and summary.tomorrow_tone:
                return summary.tomorrow_tone
        except Exception as e:
            logger.warning(f"Failed to get tomorrow_tone: {e}")
        return None

    async def generate_daily_summary(
        self,
        date: Optional[str] = None,
        force: bool = False,
        persona: str = "aveline",
        temperature: float = 0.3,
        distinct_from: Optional[str] = None,
    ) -> DailySummary:
        dt = self.service._parse_date(date)
        date_str = dt.strftime("%Y-%m-%d")

        if not getattr(
            self.settings.memory,
            "enable_user_daily_summary_generation",
            False,
        ):
            existing = await self.storage.get_daily_summary(dt, scope=persona)
            if existing:
                return existing
            return DailySummary(
                date=date_str,
                summary="用户侧自动每日总结已禁用。",
                stats={"disabled": True, "reason": "user_daily_summary_disabled"},
            )

        if not force:
            existing = await self.storage.get_daily_summary(dt, scope=persona)
            if existing:
                if not is_valid_daily_summary_obj(existing):
                    logger.warning(
                        "检测到已存在的无效每日总结，忽略旧文件并重新生成: %s (%s)",
                        date_str,
                        persona,
                    )
                else:
                    await self._persist_study_summary_artifact(
                        dt=dt,
                        summary_obj=existing,
                        study_stats=(existing.stats or {}).get("study") or {},
                    )
                    await self._append_daily_summary_diary_entry(
                        dt=dt,
                        summary_obj=existing,
                        study_stats=(existing.stats or {}).get("study") or {},
                        persona=persona,
                    )
                    return existing

        entries = await self.storage.get_entries(dt)
        # 上下文加载委托给 SummaryContextLoader
        ctx = await self._context_loader.gather_daily_context(dt, entries, persona=persona)

        # 格式化复用 journal_helpers 中的函数
        diary_context = format_diary_context(entries, persona=persona)
        chat_context = format_chat_context(ctx["chat_history"], persona=persona)
        active_care_context = format_active_care_context(ctx["active_care_events"])
        peer_chat_context = format_peer_chat_context(ctx.get("peer_chat_history", []), persona=persona)
        study_context = (
            json.dumps(ctx["study_stats"], ensure_ascii=False) if ctx["study_stats"] else "无学习数据"
        )
        daily_context = (
            json.dumps(ctx["daily_record"], ensure_ascii=False)
            if ctx["daily_record"]
            else "无生活画像数据"
        )

        # 加载用户手写日记
        user_diary_context = load_user_diary_from_study(dt)

        # 格式化角色日常活动上下文
        character_daily_context = format_character_daily_context(
            ctx.get("character_daily", {}), persona=persona
        )

        messages = build_daily_summary_messages(
            date_str=date_str,
            diary_context=diary_context,
            chat_context=chat_context,
            active_care_context=active_care_context,
            user_status_summary=ctx["user_status_summary"],
            study_context=study_context,
            daily_context=daily_context,
            peer_chat_context=peer_chat_context,
            persona=persona,
            user_diary_context=user_diary_context,
            character_daily_context=character_daily_context,
        )

        try:
            raw_out = await call_llm_stream(
                messages, self.settings, max_tokens=2048, temperature=temperature
            )
        except Exception as e:
            logger.error(f"LLM generation for daily summary failed: {e}")
            return self._build_failed_daily_summary(
                date_str,
                reason="llm_generation_failed",
                error=e,
            )

        # 空输出通常为上游 API 瞬时故障，单独标记便于区分，避免走解析路径产生误导性的 ERROR 日志
        if not raw_out or not str(raw_out).strip():
            logger.warning("每日总结 LLM 返回空输出，跳过解析（多为上游 API 瞬时故障）")
            return self._build_failed_daily_summary(
                date_str,
                reason="empty_llm_output",
            )

        def _build_summary_from_output(
            output: str, *, identity_collision_retried: bool = False
        ) -> DailySummary:
            data = parse_daily_summary_payload(output)
            data.setdefault("stats", {})
            data["stats"]["entry_count"] = len(entries)
            data["stats"]["chat_turn_count"] = len(ctx["chat_history"])
            data["stats"]["active_care_action_count"] = len(ctx["active_care_events"])
            data["stats"]["user_status"] = ctx["user_status_summary"]
            if ctx["study_stats"]:
                data["stats"]["study"] = ctx["study_stats"]
            data["stats"]["generated"] = True
            if identity_collision_retried:
                data["stats"]["identity_collision_retried"] = True
            return DailySummary(**data)

        try:
            summary_obj = _build_summary_from_output(raw_out)
            if not is_valid_daily_summary_text(summary_obj.summary):
                logger.warning("LLM 返回了无效每日总结，占位文案已被拦截: %s", raw_out[:200])
                return self._build_failed_daily_summary(
                    date_str,
                    reason="invalid_summary_placeholder",
                    raw_output=raw_out,
                )

            if distinct_from and is_overly_similar_daily_summary(
                summary_obj.summary, distinct_from
            ):
                similarity = daily_summary_similarity(summary_obj.summary, distinct_from)
                logger.warning(
                    "%s 日记与另一个角色日记过度相似 (similarity=%.3f)，按角色证据边界重写",
                    persona,
                    similarity,
                )
                retry_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "上一版和室友的日记过度相似，不能采用。请重新输出 JSON："
                            "只从【我和他的直接聊天】【我今天的行为】【我的随手记】中选择"
                            "第一人称经历；共享客观资料只能作为背景，绝不能把室友说过或做过的事"
                            "改写成我的经历。宁可少写，也不要补齐室友的故事。"
                        ),
                    },
                ]
                retry_raw = await call_llm_stream(
                    retry_messages,
                    self.settings,
                    max_tokens=2048,
                    temperature=temperature,
                )
                if not retry_raw or not str(retry_raw).strip():
                    return self._build_failed_daily_summary(
                        date_str,
                        reason="identity_collision_retry_empty",
                    )
                summary_obj = _build_summary_from_output(
                    retry_raw, identity_collision_retried=True
                )
                if not is_valid_daily_summary_text(summary_obj.summary):
                    return self._build_failed_daily_summary(
                        date_str,
                        reason="identity_collision_retry_invalid",
                        raw_output=retry_raw,
                    )
                if is_overly_similar_daily_summary(summary_obj.summary, distinct_from):
                    return self._build_failed_daily_summary(
                        date_str,
                        reason="identity_collision_persisted",
                        raw_output=retry_raw,
                    )

            await self.storage.save_daily_summary(summary_obj, dt, scope=persona)
            try:
                from core.services.journal.persona_exports import (
                    get_persona_journal_export_service,
                )
                await get_persona_journal_export_service().export_date(dt)
            except Exception as e:
                logger.warning(f"更新 persona 日汇总导出失败: {e}")
            await self._persist_study_summary_artifact(
                dt=dt,
                summary_obj=summary_obj,
                study_stats=ctx["study_stats"],
            )
            await self._append_daily_summary_diary_entry(
                dt=dt,
                summary_obj=summary_obj,
                study_stats=ctx["study_stats"],
                persona=persona,
            )
            try:
                from core.services.study.summary_generator import StudySummaryGenerator
                study_gen = StudySummaryGenerator()
                study_summary = await study_gen.generate(date=date_str)
                if study_summary:
                    logger.info(f"[Study Summary] 学习专项总结已生成: {date_str}")
            except Exception as se:
                logger.warning(f"[Study Summary] 学习专项总结生成异常（不影响主流程）: {se}")

            return summary_obj
        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}\nOutput: {raw_out}")
            return self._build_failed_daily_summary(
                date_str,
                reason="daily_summary_parse_failed",
                error=e,
                raw_output=raw_out,
            )

    async def generate_study_daily_summary(
        self, date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """向后兼容：委托给 StudySummaryGenerator。"""
        from core.services.study.summary_generator import StudySummaryGenerator
        return await StudySummaryGenerator().generate(date=date)

    # ── 每月总结 + 记忆蒸馏 ───────────────────────────────────

    async def get_monthly_summary(
        self, date: Optional[str] = None
    ) -> Optional[MonthlySummary]:
        dt = self.service._parse_date(date)
        return await self.storage.get_monthly_summary(dt)

    async def _collect_daily_summaries(self, dt: datetime) -> List[DailySummary]:
        start_date = dt.replace(day=1)
        if dt.month == 12:
            next_month = dt.replace(year=dt.year + 1, month=1, day=1)
        else:
            next_month = dt.replace(month=dt.month + 1, day=1)
        days_count = (next_month - start_date).days
        summaries = []
        today = get_current_time().date()
        for i in range(days_count):
            current_day = start_date + timedelta(days=i)
            if current_day.date() > today:
                break
            summary = await self.storage.get_daily_summary(current_day)
            if summary:
                summaries.append(summary)
        return summaries

    async def generate_monthly_summary(
        self, date: Optional[str] = None, force: bool = False
    ) -> MonthlySummary:
        dt = self.service._parse_date(date)
        month_str = dt.strftime("%Y-%m")

        if not force:
            existing = await self.storage.get_monthly_summary(dt)
            if existing:
                return existing

        daily_summaries = await self._collect_daily_summaries(dt)

        if not daily_summaries:
            return MonthlySummary(
                month=month_str, summary="本月暂无数据。", mood_trend="未知"
            )

        context_parts = []
        for s in daily_summaries:
            part = f"[{s.date}] 摘要: {s.summary}"
            context_parts.append(part)
        full_context = "\n".join(context_parts)

        from core.agents.chat_agent_components.persona_system.prompt.components import JOURNAL_MONTHLY_SUMMARY_PROMPT_TEMPLATE
        prompt = JOURNAL_MONTHLY_SUMMARY_PROMPT_TEMPLATE.format(
            month_str=month_str,
            full_context=full_context,
            total_days=len(daily_summaries),
        )
        try:
            raw_out = await call_llm_stream(prompt, self.settings, max_tokens=2048, temperature=0.4)
            data = extract_json_object(raw_out)

            if "month" not in data:
                data["month"] = month_str
            if "summary" not in data:
                data["summary"] = raw_out[:500]

            summary_obj = MonthlySummary(**data)
            await self.storage.save_monthly_summary(summary_obj, dt)

            if "persona_evolution" in data:
                try:
                    from core.character.managers.persona_manager import (
                        get_persona_manager,
                    )
                    pm = get_persona_manager()
                    pm.update_dynamic_traits(data["persona_evolution"])
                except Exception as pe:
                    logger.warning(f"Failed to update persona evolution: {pe}")

            await self.distill_memory(summary_obj, dt)
            return summary_obj
        except Exception as e:
            logger.error(f"Failed to generate monthly summary: {e}")
            return MonthlySummary(
                month=month_str, summary=f"生成失败: {e}", mood_trend="未知"
            )

    async def distill_memory(self, monthly_summary: MonthlySummary, date: datetime):
        try:
            logger.info(f"Starting memory distillation for {monthly_summary.month}")

            year = date.strftime("%Y")
            month = date.strftime("%m")

            from core.agents.chat_agent_components.persona_system.prompt.components import JOURNAL_MEMORY_DISTILL_PROMPT_TEMPLATE
            prompt = JOURNAL_MEMORY_DISTILL_PROMPT_TEMPLATE.format(
                monthly_summary_json=monthly_summary.model_dump_json(indent=2, ensure_ascii=False)
            )
            distilled_content = await call_llm_stream(
                prompt, self.settings, max_tokens=1024, temperature=0.3
            )

            from core.utils.common import get_project_root

            base_dir = (
                get_project_root()
                / "core"
                / "character"
                / "configs"
                / "extra"
                / year
                / month
            )
            base_dir.mkdir(parents=True, exist_ok=True)

            file_path = base_dir / "distilled_profile.md"
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(
                    f"# {year}-{month} Distilled Memory\n\n{distilled_content}"
                )

            logger.info(f"Distilled memory saved to {file_path}")

        except Exception as e:
            logger.error(f"Memory distillation failed: {e}")
