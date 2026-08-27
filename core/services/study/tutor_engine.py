"""教学决策引擎 —— 家庭教师的「大脑」

综合 StudentState（画像）+ DailyTracker（每日状态）+ WeaknessTracker（薄弱点），
做出主动教学决策：每日简报、今日计划、复习提醒、周分析。

设计原则：
- 本身不调 LLM，纯规则 + 数据聚合
- LLM 总结仍由 StudySummaryGenerator 负责
- TutorEngine 输出的结构化数据可注入 SummaryGenerator 的 prompt
"""
import threading
from datetime import timedelta
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str

logger = get_logger("TutorEngine")


class TutorEngine:
    """教学决策引擎 - 串联所有数据源，做出教学决策"""

    _instance: Optional["TutorEngine"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        # 依赖延迟获取，避免循环导入
        pass

    @classmethod
    def get_instance(cls) -> "TutorEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 依赖获取辅助 ----

    @staticmethod
    def _get_student_state():
        from core.services.study.student_state import get_student_state_manager
        return get_student_state_manager()

    @staticmethod
    def _get_daily_tracker():
        from core.services.study.daily_tracker import get_daily_tracker
        return get_daily_tracker()

    @staticmethod
    def _get_weakness_tracker():
        from core.services.study.weakness_tracker import get_weakness_tracker
        return get_weakness_tracker()

    @staticmethod
    def _get_study_settings():
        try:
            from config.integrated_config import get_settings
            return get_settings().study
        except Exception:
            return None

    # ================================================================
    # 每日简报
    # ================================================================

    def generate_daily_briefing(self) -> Dict[str, Any]:
        """
        生成每日学习简报（供 Active Care 推送 + API 查询）。

        返回：
        {
            "date": "2026-06-15",
            "yesterday_review": {学了什么, 掌握了什么, 遇到了什么困难},
            "today_plan": {建议学什么, 时间分配, 优先级排序},
            "review_reminders": [今天该复习的知识点],
            "encouragement": "基于 streak 和状态的鼓励/提醒",
            "streak_info": {当前连续天数, 历史最长},
        }
        """
        today = now_str("%Y-%m-%d")
        yesterday = (get_current_time() - timedelta(days=1)).strftime("%Y-%m-%d")

        ss_mgr = self._get_student_state()
        dt = self._get_daily_tracker()
        wt = self._get_weakness_tracker()

        state = ss_mgr.get_state()
        yday = dt.get_date(yesterday)
        due_reviews = wt.get_due_reviews(today)

        # 昨天回顾
        yesterday_review = self._build_yesterday_review(yday)

        # 今日计划
        today_plan = self._build_today_plan(state, due_reviews)

        # 复习提醒
        review_reminders = [
            {"subject": item.subject, "topic": item.topic, "confidence": item.confidence}
            for item in due_reviews[:10]
        ]

        # 鼓励语
        encouragement = self._generate_encouragement(state, yesterday_review)

        # streak 信息
        streak_info = ss_mgr.get_streak_info()

        return {
            "date": today,
            "yesterday_review": yesterday_review,
            "today_plan": today_plan,
            "review_reminders": review_reminders,
            "encouragement": encouragement,
            "streak_info": streak_info,
        }

    # ================================================================
    # 今日学习计划
    # ================================================================

    def generate_study_plan(self) -> Dict[str, Any]:
        """
        生成今日学习计划。

        - 薄弱科目优先（confidence 最低排前面）
        - 间隔复习到期项优先
        - 时间分配基于历史习惯
        """
        ss_mgr = self._get_student_state()
        wt = self._get_weakness_tracker()
        dt = self._get_daily_tracker()

        state = ss_mgr.get_state()
        due_reviews = wt.get_due_reviews()
        settings = self._get_study_settings()
        goal_minutes = settings.daily_study_goal_minutes if settings else 120

        # 计算历史平均学习时长（用作参考）
        recent_days = dt.get_recent_days(7)
        if recent_days:
            avg_minutes = sum(d.total_study_minutes for d in recent_days) / len(recent_days)
            # 不超过目标的 1.2 倍，不低于目标的 0.5 倍
            avg_minutes = max(goal_minutes * 0.5, min(goal_minutes * 1.2, avg_minutes))
        else:
            avg_minutes = goal_minutes

        # 优先级排序：薄弱科目优先
        priority_subjects = ss_mgr.get_priority_subjects()

        # 构建计划项
        plan_items = []

        # 1. 间隔复习（最高优先级）
        if due_reviews:
            review_minutes = min(30, int(avg_minutes * 0.25))
            plan_items.append({
                "type": "review",
                "title": f"间隔复习（{len(due_reviews)}个知识点）",
                "duration_minutes": review_minutes,
                "priority": "high",
                "items": [
                    {"subject": r.subject, "topic": r.topic}
                    for r in due_reviews[:8]
                ],
            })

        # 2. 薄弱科目强化
        for subj_info in priority_subjects[:3]:
            subj = subj_info["subject"]
            conf = subj_info["confidence"]
            if conf < 6.0:
                block_minutes = max(30, int(avg_minutes * 0.3))
                plan_items.append({
                    "type": "strengthen",
                    "title": f"{subj} 强化训练",
                    "subject": subj,
                    "duration_minutes": block_minutes,
                    "priority": "high" if conf < 4.0 else "medium",
                    "reason": f"当前掌握度 {conf:.1f}/10",
                })

        # 3. 常规学习块
        remaining_minutes = max(20, int(avg_minutes) - sum(i["duration_minutes"] for i in plan_items))
        if remaining_minutes > 20:
            # 选择最久未学习的科目
            stale_subject = self._find_stale_subject(priority_subjects)
            plan_items.append({
                "type": "regular",
                "title": f"{stale_subject or '自选科目'} 学习",
                "subject": stale_subject or "general",
                "duration_minutes": remaining_minutes,
                "priority": "normal",
            })

        return {
            "date": now_str("%Y-%m-%d"),
            "total_planned_minutes": sum(i["duration_minutes"] for i in plan_items),
            "goal_minutes": goal_minutes,
            "items": plan_items,
        }

    # ================================================================
    # 复习提醒
    # ================================================================

    def get_review_reminders(self) -> List[Dict[str, Any]]:
        """获取今天该复习的薄弱点列表"""
        wt = self._get_weakness_tracker()
        due = wt.get_due_reviews()
        return [
            {
                "id": item.id,
                "subject": item.subject,
                "topic": item.topic,
                "confidence": item.confidence,
                "review_count": item.review_count,
                "last_reviewed": item.last_reviewed,
            }
            for item in due
        ]

    # ================================================================
    # 周分析
    # ================================================================

    def get_weekly_analysis(self) -> Dict[str, Any]:
        """
        过去 7 天的学习趋势分析。

        - 每日学习时长趋势
        - 科目分布
        - 进步最大的科目（confidence 变化趋势，暂用当前值）
        - 持续薄弱的知识点
        - 学习节奏（哪个时段学习最多）
        """
        dt = self._get_daily_tracker()
        ss_mgr = self._get_student_state()
        wt = self._get_weakness_tracker()

        recent = dt.get_recent_days(7)
        state = ss_mgr.get_state()

        # 每日趋势
        daily_trend = []
        total_minutes = 0
        total_sessions = 0
        subject_minutes: Dict[str, int] = {}

        for day in recent:
            daily_trend.append({
                "date": day.date,
                "minutes": day.total_study_minutes,
                "sessions": len(day.sessions),
                "subjects": day.subjects_studied,
            })
            total_minutes += day.total_study_minutes
            total_sessions += len(day.sessions)
            for session in day.sessions:
                subj = session.subject or "general"
                subject_minutes[subj] = subject_minutes.get(subj, 0) + session.duration_minutes

        # 科目分布
        subject_distribution = [
            {"subject": subj, "minutes": mins}
            for subj, mins in sorted(subject_minutes.items(), key=lambda x: -x[1])
        ]

        # 薄弱科目
        weak_subjects = ss_mgr.get_priority_subjects()[:5]

        # 持续薄弱知识点
        weakness_report = wt.get_weakness_report()
        persistent_struggles = [
            {"subject": item["subject"], "topic": item["topic"], "confidence": item["confidence"]}
            for items in weakness_report.get("by_subject", {}).values()
            for item in items
            if item.get("review_count", 0) >= 2 and item.get("confidence", 5) < 5.0
        ][:10]

        # 活跃度
        active_days = len([d for d in daily_trend if d["minutes"] > 0])

        return {
            "period": "7days",
            "active_days": active_days,
            "total_minutes": total_minutes,
            "total_sessions": total_sessions,
            "avg_daily_minutes": round(total_minutes / max(1, active_days), 1),
            "daily_trend": daily_trend,
            "subject_distribution": subject_distribution,
            "weak_subjects": weak_subjects,
            "persistent_struggles": persistent_struggles,
            "streak": ss_mgr.get_streak_info(),
        }

    # ================================================================
    # 内部辅助方法
    # ================================================================

    @staticmethod
    def _build_yesterday_review(yday_record) -> Dict[str, Any]:
        """构建昨日学习回顾"""
        if not yday_record or not yday_record.sessions:
            return {
                "studied": False,
                "subjects": [],
                "total_minutes": 0,
                "topics_learned": 0,
                "topics_mastered": 0,
                "struggles": [],
            }

        topics_learned = len(yday_record.knowledge_points)
        topics_mastered = sum(
            1 for kp in yday_record.knowledge_points if kp.status == "mastered"
        )
        struggles = [
            {"subject": s.subject, "topic": s.topic, "description": s.description}
            for s in yday_record.struggles
        ]

        return {
            "studied": True,
            "subjects": yday_record.subjects_studied,
            "total_minutes": yday_record.total_study_minutes,
            "sessions_count": len(yday_record.sessions),
            "topics_learned": topics_learned,
            "topics_mastered": topics_mastered,
            "struggles": struggles,
        }

    def _build_today_plan(self, state, due_reviews) -> Dict[str, Any]:
        """构建今日计划建议"""
        plan = self.generate_study_plan()
        return {
            "items": plan["items"],
            "total_minutes": plan["total_planned_minutes"],
            "review_count": len(due_reviews),
            "priority_subjects": [
                s["subject"] for s in self._get_student_state().get_priority_subjects()[:3]
            ],
        }

    @staticmethod
    def _generate_encouragement(state, yesterday_review: Dict) -> str:
        """基于 streak 和昨日状态生成鼓励语"""
        streak = state.streak_days
        studied_yesterday = yesterday_review.get("studied", False)

        if not studied_yesterday and streak == 0:
            return "今天开始新的学习吧！哪怕只学 20 分钟也是好的开始。"

        if not studied_yesterday and streak > 0:
            return f"连续学习 {streak} 天后昨天休息了一下，今天继续加油！"

        if streak >= 30:
            return f"已经坚持 {streak} 天了！你的毅力令人佩服，保持这个节奏。"
        elif streak >= 14:
            return f"连续 {streak} 天学习，习惯已经形成了！继续保持。"
        elif streak >= 7:
            return f"一周连续打卡 {streak} 天，节奏很好，继续！"
        elif streak >= 3:
            return f"连续学习 {streak} 天了，势头不错！"

        # 昨天学了但 streak 不高
        minutes = yesterday_review.get("total_minutes", 0)
        if minutes >= 120:
            return "昨天学了很久，今天可以适度放松，但不要完全停下来。"
        elif minutes >= 60:
            return "昨天学了不少，今天继续保持这个节奏。"
        else:
            return "昨天学习量不多，今天试试多投入一点时间？"

    @staticmethod
    def _find_stale_subject(priority_subjects: List[Dict]) -> Optional[str]:
        """找到最久未学习的科目"""
        if not priority_subjects:
            return None
        # 按 last_studied 排序，找最久没学的
        stale = sorted(
            [s for s in priority_subjects if s.get("last_studied")],
            key=lambda x: x.get("last_studied", ""),
        )
        return stale[0]["subject"] if stale else None


def get_tutor_engine() -> TutorEngine:
    """工厂函数，获取全局单例"""
    return TutorEngine.get_instance()
