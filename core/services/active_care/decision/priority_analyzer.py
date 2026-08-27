"""优先级分析模块
负责分析任务优先级、画像补全优先级、每日推送优先级

重构后：
- 每日推送优先级函数委托到 daily_push_priority 模块
- 关键词映射与覆盖检测委托到 portrait_keyword_map 模块
- PriorityAnalyzer 保留核心优先级焦点构建和探测签名/冷却逻辑
"""

from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from config.integrated_config import get_settings
from core.services.active_care.decision.portrait_keyword_map import check_portrait_keyword_coverage
from core.services.active_care.decision.daily_push_priority import (
    build_daily_push_priority_candidates,
    analyze_daily_push_priority as _analyze_daily_push_priority,
    persist_daily_push_priority_analysis as _persist_daily_push_priority_analysis,
)

logger = get_module_logger("ACTIVE_CARE_PRIORITY", "active_care_schedule.log")


class PriorityAnalyzer:
    """优先级分析器，负责构建和分析主动关怀的优先级队列"""
    
    def __init__(self, bert_analyzer=None):
        self.settings = get_settings()
        self.bert_analyzer = bert_analyzer
    
    def build_priority_focus(
        self,
        workspace_snapshot: Dict[str, Any],
        now_dt,
        recent_history: Optional[List[Dict[str, Any]]] = None,
        elapsed_seconds: int = 0,
    ) -> Dict[str, Any]:
        """
        构建优先级焦点，决定当前应该关注什么

        Args:
            workspace_snapshot: 工作区快照
            now_dt: 当前时间
            recent_history: 最近聊天记录
            elapsed_seconds: 用户沉默时长（秒），用于判断是否应降低画像补全优先级

        Returns:
            {
                "must_probe": bool,  # 是否必须探测
                "stage": str,        # 当前阶段
                "task_probe": dict,  # 任务探测信息
                "portrait_priority": list,  # 画像优先级
                "covered_topics": list,     # 已覆盖话题
                "summary": dict,            # 摘要
            }
        """
        snapshot = workspace_snapshot if isinstance(workspace_snapshot, dict) else {}
        daily_tasks = snapshot.get("daily_tasks") or {}
        task_focus = daily_tasks.get("focus") or {}
        task_probe = {}
        stage = "idle"
        must_probe = False

        due_soon = task_focus.get("timed_due_soon") or []
        overdue = task_focus.get("timed_overdue") or []
        timed_pending = int(task_focus.get("timed_pending") or 0)
        untimed_pending = int(task_focus.get("untimed_pending") or 0)

        chosen_task = None
        task_reason = ""
        if overdue:
            chosen_task = overdue[0]
            task_reason = "overdue"
            stage = "task_follow_up"
            must_probe = True
        elif due_soon:
            chosen_task = due_soon[0]
            task_reason = "due_soon"
            stage = "task_follow_up"
            must_probe = True
        else:
            timed = daily_tasks.get("timed") or []
            untimed = daily_tasks.get("untimed") or []
            pending_timed = [
                item for item in timed if str(item.get("status", "pending")) == "pending"
            ]
            pending_untimed = [
                item for item in untimed if str(item.get("status", "pending")) == "pending"
            ]
            if pending_timed:
                chosen_task = pending_timed[0]
                task_reason = "timed_pending"
            elif pending_untimed:
                chosen_task = pending_untimed[0]
                task_reason = "untimed_pending"
            if chosen_task and now_dt.hour >= 9:
                stage = "task_follow_up"
                must_probe = True

        if chosen_task:
            task_probe = {
                "reason": task_reason,
                "task_id": str(chosen_task.get("id") or "").strip(),
                "task_title": str(chosen_task.get("title") or "").strip(),
                "minutes_to_execution": chosen_task.get("minutes_to_execution"),
                "pending_total": timed_pending + untimed_pending,
            }

        quality = snapshot.get("portrait_completeness") or {}
        missing_items = quality.get("missing_items") or []
        if not isinstance(missing_items, list):
            missing_items = []

        # BERT 语义覆盖过滤
        _health_topics = ["wakeup", "sleep", "meal", "activity", "study", "mood", "health"]
        _relevant_missing = [item for item in missing_items if item in _health_topics]
        _covered_topics: List[str] = []
        if _relevant_missing and recent_history and self.bert_analyzer:
            try:
                coverage_result = self.bert_analyzer.analyze_portrait_topic_coverage(
                    recent_messages=recent_history,
                    candidate_topics=_relevant_missing,
                )
                _covered_topics = coverage_result.get("covered_topics") or []
                if _covered_topics:
                    missing_items = [item for item in missing_items if item not in _covered_topics]
                    logger.info(
                        f"Active Care: build_priority_focus BERT过滤已覆盖话题 "
                        f"covered={_covered_topics}, 剩余missing={missing_items}"
                    )
            except Exception as e:
                logger.warning(f"Active Care: build_priority_focus BERT覆盖检测失败: {e}")

        # 关键词兜底检测：BERT 可能漏检时，用关键词直接匹配用户消息
        if _relevant_missing and recent_history:
            _keyword_covered = check_portrait_keyword_coverage(
                recent_history, _relevant_missing, exclude=_covered_topics
            )
            if _keyword_covered:
                _covered_topics.extend(_keyword_covered)
                missing_items = [item for item in missing_items if item not in _keyword_covered]
                logger.info(
                    f"Active Care: build_priority_focus 关键词兜底过滤已覆盖话题 "
                    f"covered={_keyword_covered}, 剩余missing={missing_items}"
                )

        portrait_priority: List[str] = []
        hour = int(getattr(now_dt, "hour", 0))
        if hour < 11:
            for item in ["wakeup", "meal"]:
                if item in missing_items:
                    portrait_priority.append(item)
        elif hour < 17:
            for item in ["meal", "activity", "study"]:
                if item in missing_items:
                    portrait_priority.append(item)
        else:
            for item in ["meal", "activity", "mood", "sleep"]:
                if item in missing_items:
                    portrait_priority.append(item)

        # 用户刚互动过（沉默<20分钟）时，不强制画像补全探测，避免查户口式追问
        _PORTRAIT_PROBE_MIN_SILENCE = 1200  # 20分钟
        if portrait_priority and not must_probe:
            if elapsed_seconds >= _PORTRAIT_PROBE_MIN_SILENCE:
                must_probe = True
                stage = "daily_routine"
            else:
                # 用户刚互动过，画像补全降级为"可选"而非"必须"
                logger.info(
                    f"Active Care: 用户沉默仅{elapsed_seconds}s，画像补全降级为可选 "
                    f"(需>={_PORTRAIT_PROBE_MIN_SILENCE}s才强制探测)"
                )

        return {
            "must_probe": must_probe,
            "stage": stage,
            "task_probe": task_probe,
            "portrait_priority": portrait_priority[:2],
            "covered_topics": _covered_topics,
            "summary": {
                "timed_pending": timed_pending,
                "untimed_pending": untimed_pending,
                "missing_items": missing_items,
            },
        }

    def get_priority_probe_signature(self, focus: Dict[str, Any]) -> str:
        """获取优先级探测签名，用于去重"""
        if not isinstance(focus, dict):
            return "none"
        task_probe = focus.get("task_probe") or {}
        portrait_priority = focus.get("portrait_priority") or []
        if task_probe:
            return (
                f"task:{task_probe.get('reason')}:{task_probe.get('task_id') or ''}:"
                f"{task_probe.get('task_title') or ''}"
            )
        if portrait_priority:
            return "portrait:" + ",".join(str(item) for item in portrait_priority[:2])
        return str(focus.get("stage") or "idle")

    def get_priority_probe_cooldown_seconds(self, focus: Dict[str, Any]) -> int:
        """获取优先级探测冷却时间"""
        if not isinstance(focus, dict):
            return 3600
        task_probe = focus.get("task_probe") or {}
        reason = str(task_probe.get("reason") or "").strip().lower()
        if reason == "overdue":
            return 20 * 60
        if reason == "due_soon":
            return 15 * 60
        if reason in {"timed_pending", "untimed_pending"}:
            return 45 * 60
        if focus.get("portrait_priority"):
            return 90 * 60
        return 3600

    # ── 以下方法委托到 daily_push_priority 模块 ──

    def build_daily_push_priority_candidates(
        self,
        *,
        workspace_snapshot: Dict[str, Any],
        priority_focus: Dict[str, Any],
        urgent_needs: List[str],
    ) -> List[Dict[str, Any]]:
        """构建每日推送优先级候选列表（委托到 daily_push_priority 模块）"""
        return build_daily_push_priority_candidates(
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            urgent_needs=urgent_needs,
        )

    async def analyze_daily_push_priority(
        self,
        *,
        now: float,
        now_dt,
        latest_user_signal_ts: float,
        workspace_snapshot: Dict[str, Any],
        priority_focus: Dict[str, Any],
        urgent_needs: List[str],
        state_data: Dict[str, Any],
        recent_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """分析每日推送优先级（委托到 daily_push_priority 模块）"""
        return await _analyze_daily_push_priority(
            now=now,
            now_dt=now_dt,
            latest_user_signal_ts=latest_user_signal_ts,
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            urgent_needs=urgent_needs,
            state_data=state_data,
            recent_history=recent_history,
        )

    async def persist_daily_push_priority_analysis(
        self,
        *,
        now_dt,
        analysis: Dict[str, Any],
        workspace_snapshot: Dict[str, Any],
        priority_focus: Dict[str, Any],
        runtime_scope: str,
    ) -> None:
        """持久化每日推送优先级分析结果（委托到 daily_push_priority 模块）"""
        await _persist_daily_push_priority_analysis(
            now_dt=now_dt,
            analysis=analysis,
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            runtime_scope=runtime_scope,
        )
