"""每个目标日期只执行一次的 Nightly 全局任务。"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from core.services.journal.summary_guard import is_valid_daily_summary_obj
from core.utils.logger import get_module_logger
from core.utils.time_utils import get_diary_target_date

from .config import get_nightly_model_routes

logger = get_module_logger(__name__, "nightly_processor.log")


class NightlyGlobalTaskService:
    """编排人物档案、日记计划、数字健康和核心记忆维护。"""

    async def run(
        self,
        target_date: Optional[datetime.date],
        memory_managers: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """执行目标日期的全局任务集合。"""
        logger.info(
            "nightly 模型路由（稳定 system prompt + 动态 user prompt）: %s",
            get_nightly_model_routes(),
        )
        results: Dict[str, Any] = {}
        if memory_managers is not None:
            await self._run_people_profiles(memory_managers, results)
        resolved_target = target_date or get_diary_target_date()
        await self._run_journal_plan_and_wellbeing(resolved_target, results)
        await self._run_core_memory_maintenance(results)
        return results

    @staticmethod
    async def _run_people_profiles(
        memory_managers: Dict[str, Any],
        results: Dict[str, Any],
    ) -> None:
        """全局汇总一次人物档案候选门控。"""
        try:
            from core.character.people.extractor import PeopleProfileExtractor

            extraction_result = await PeopleProfileExtractor().extract_and_update(
                "__global__",
                memory_managers=memory_managers,
            )
            results["people_profiles_extracted"] = extraction_result.get(
                "extracted_count",
                0,
            )
            results["people_profiles_created"] = extraction_result.get(
                "created_count",
                0,
            )
            results["people_profile_llm_batches"] = extraction_result.get(
                "llm_batches",
                0,
            )
            results["people_profiles_skip_reason"] = extraction_result.get(
                "skipped",
                "",
            )
        except Exception as exc:
            logger.error("人物档案门控提取失败: %s", exc)
            results["people_profiles_extracted"] = 0
            results["people_profiles_created"] = 0
            results["people_profiles_skip_reason"] = f"error: {exc}"

    async def _run_journal_plan_and_wellbeing(
        self,
        target_date: datetime.date,
        results: Dict[str, Any],
    ) -> None:
        """生成双角色日记、次日计划、数字健康建议和月报。"""
        try:
            from core.services.journal.service import get_journal_service

            journal_service = get_journal_service()
            target_date_str = target_date.strftime("%Y-%m-%d")
            logger.info("Generating daily summary for %s (force=True)", target_date_str)
            aveline_summary = await journal_service.generate_daily_summary(
                target_date_str,
                force=True,
                persona="aveline",
            )
            results["daily_summary"] = is_valid_daily_summary_obj(aveline_summary)
            aveline_text = str(
                getattr(aveline_summary, "summary", "") or ""
            ).strip()

            ling_summary = await journal_service.generate_daily_summary(
                target_date_str,
                force=True,
                persona="ling",
                distinct_from=aveline_text,
            )
            results["ling_daily_summary"] = is_valid_daily_summary_obj(ling_summary)
            results["ling_daily_summary_retried"] = bool(
                (getattr(ling_summary, "stats", None) or {}).get(
                    "identity_collision_retried"
                )
            )
            self._ensure_diary_file(target_date)
            next_day = target_date + datetime.timedelta(days=1)
            await self._generate_next_day_plan(journal_service, next_day, results)
            self._review_digital_wellbeing(target_date_str, next_day, results)

            if next_day.month != target_date.month:
                logger.info(
                    "End of month detected, generating monthly summary for %s",
                    target_date.strftime("%Y-%m"),
                )
                monthly_summary = await journal_service.generate_monthly_summary(
                    target_date_str
                )
                results["monthly_summary"] = bool(monthly_summary)
            self._mark_roles_nightly_done(target_date, results)
        except Exception as exc:
            logger.error("日记总结生成失败: %s", exc)
            results["global_error"] = f"日记总结生成失败: {exc}"

    @staticmethod
    def _ensure_diary_file(target_date: datetime.date) -> None:
        """确保学习 daily 目录存在 diary.md。"""
        try:
            from core.utils.data_paths import get_study_daily_date_dir

            study_date_dir = get_study_daily_date_dir(target_date)
            study_date_dir.mkdir(parents=True, exist_ok=True)
            diary_md = study_date_dir / "diary.md"
            if not diary_md.exists():
                diary_md.write_text(
                    f"# {target_date.strftime('%Y-%m-%d')} 日记\n\n",
                    encoding="utf-8",
                )
                logger.info("已创建空日记文件: %s", diary_md)
        except Exception as exc:
            logger.warning("创建 diary.md 失败: %s", exc)

    @staticmethod
    async def _generate_next_day_plan(
        journal_service: Any,
        next_day: datetime.date,
        results: Dict[str, Any],
    ) -> None:
        """生成 target_date 后一日的计划，保留已有非空计划。"""
        next_day_str = next_day.strftime("%Y-%m-%d")
        try:
            existing_plan = await journal_service.get_plan(next_day_str)
            if existing_plan and existing_plan.items:
                logger.info(
                    "次日计划已存在（%s，%s 项），跳过自动生成",
                    next_day_str,
                    len(existing_plan.items),
                )
                results["auto_plan"] = "skipped_existing"
                return
            plan = await journal_service.generate_plan_for_date(
                next_day_str,
                force=existing_plan is not None,
            )
            timed_count = sum(1 for item in plan.items if item.time)
            logger.info(
                "次日计划已自动生成：%s，共 %s 项（%s 项有定时提醒）",
                plan.date,
                len(plan.items),
                timed_count,
            )
            results["auto_plan"] = (
                f"generated_{len(plan.items)}_items_{timed_count}_reminders"
            )
        except Exception as exc:
            logger.warning("自动生成次日计划失败: %s", exc)
            results["auto_plan"] = f"error: {exc}"

    @staticmethod
    def _review_digital_wellbeing(
        target_date_str: str,
        next_day: datetime.date,
        results: Dict[str, Any],
    ) -> None:
        """按目标日用量生成下一自然日规则基线。"""
        try:
            from core.services.digital_wellbeing.service import get_wellbeing_service

            wellbeing = get_wellbeing_service()
            usage = wellbeing.get_today_usage(target_date_str)
            if not usage:
                results["digital_wellbeing"] = "no_usage_data"
                return
            baseline = wellbeing.build_limit_suggestion(
                today_date=target_date_str,
                usage=usage,
            )
            next_day_str = next_day.strftime("%Y-%m-%d")
            existing = wellbeing.get_limits(next_day_str)
            if not existing.get("limits") and baseline:
                wellbeing.save_limits(
                    baseline,
                    target_date=next_day_str,
                    source="auto",
                )
                results["digital_wellbeing"] = f"baseline_{len(baseline)}_apps"
            elif existing.get("limits"):
                results["digital_wellbeing"] = (
                    f"skipped_existing_{len(existing['limits'])}"
                )
            else:
                results["digital_wellbeing"] = "skipped_empty_baseline"
        except Exception as exc:
            logger.warning("数字健康复盘失败: %s", exc)
            results["digital_wellbeing"] = f"error: {exc}"

    @staticmethod
    def _mark_roles_nightly_done(
        target_date: datetime.date,
        results: Dict[str, Any],
    ) -> None:
        """写入角色 nightly 睡眠标记。"""
        try:
            from memory.nightly.sleep_hooks import mark_roles_nightly_done

            mark_roles_nightly_done(target_date)
            results["sleep_nightly_marked"] = True
        except Exception as exc:
            logger.warning("写入角色 nightly 睡眠标记失败: %s", exc)
            results["sleep_nightly_marked"] = False

    @staticmethod
    async def _run_core_memory_maintenance(results: Dict[str, Any]) -> None:
        """执行 MEMORY.md 自动瘦身和偏好语义合并。"""
        try:
            from core.services.self_improvement.service import (
                get_self_improvement_service,
            )

            slim_results: Dict[str, Any] = {}
            for scope in ("aveline", "ling", "user"):
                try:
                    service = get_self_improvement_service(scope=scope)
                    session_result = await service.on_session_start()
                    slim_results[scope] = session_result.get("slim_result", {})
                except Exception as exc:
                    logger.warning("scope=%s MEMORY.md 瘦身失败: %s", scope, exc)
                    slim_results[scope] = {"error": str(exc)}
            results["memory_slim"] = slim_results
        except Exception as exc:
            logger.warning("触发 MEMORY.md 瘦身失败: %s", exc)
            results["memory_slim"] = {"error": str(exc)}

        try:
            from core.services.self_improvement.service import (
                get_self_improvement_service,
            )

            merge_results: Dict[str, Any] = {}
            for scope in ("aveline", "ling", "user"):
                try:
                    service = get_self_improvement_service(scope=scope)
                    merge_result = await service.llm_merge_preferences()
                    merge_results[scope] = merge_result
                    removed = merge_result.get("removed", 0)
                    if removed > 0:
                        logger.info(
                            "scope=%s LLM 合并偏好: %d → %d 条（移除 %d）",
                            scope,
                            merge_result.get("before", 0),
                            merge_result.get("after", 0),
                            removed,
                        )
                except Exception as exc:
                    logger.warning("scope=%s LLM 合并偏好失败: %s", scope, exc)
                    merge_results[scope] = {"error": str(exc)}
            results["memory_llm_merge"] = merge_results
        except Exception as exc:
            logger.warning("触发 LLM 合并偏好失败: %s", exc)
            results["memory_llm_merge"] = {"error": str(exc)}
