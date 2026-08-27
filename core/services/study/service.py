import os
import time
import asyncio
from typing import List, Dict, Any, Optional
from core.utils.logger import get_logger
from core.utils.saga_manager import SagaTransaction
from core.services.daily.manager import get_daily_manager
from core.services.study import (
    build_tools_metadata,
    build_subject_profiles,
    StudySubjectAnalyzer,
    StudySummaryBuilder,
)
from core.services.study.session import StudySession
from core.services.study.dispatch import ToolDispatcher
from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

logger = get_logger("StudyService")

_EMPTY_VOCAB_STATS = {
    "total_words": 0,
    "learned_words": 0,
    "due_words": 0,
    "to_review": 0,
    "mastered_words": 0,
    "available_word_files": [],
    "available_sentence_files": [],
    "current_dictionary": None,
    "current_sentence_collection": None,
}


class StudyService:
    _instance = None

    def __init__(self):
        self.base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.data_dir = os.path.join(self.base_dir, "data", "study_data")

        self._vocab_manager: Optional[Any] = None
        self._vocab_enabled: Optional[bool] = None

        self.tools_metadata = build_tools_metadata()
        self.subject_profiles = build_subject_profiles()
        self.subject_analyzer = StudySubjectAnalyzer()
        self.summary_builder = StudySummaryBuilder(self.subject_analyzer)

        # 子组件
        self._session = StudySession()
        self._dispatcher: Optional[ToolDispatcher] = None

        # 新增组件（延迟初始化）
        self._student_state_mgr = None
        self._daily_tracker = None
        self._weakness_tracker = None
        self._tutor_engine = None

    # ---- 子组件延迟初始化 ----

    @property
    def dispatcher(self) -> ToolDispatcher:
        if self._dispatcher is None:
            self._dispatcher = ToolDispatcher(self)
        return self._dispatcher

    @property
    def student_state(self):
        """结构化学生状态管理器"""
        if self._student_state_mgr is None:
            from core.services.study.student_state import get_student_state_manager
            self._student_state_mgr = get_student_state_manager()
        return self._student_state_mgr

    @property
    def daily_tracker(self):
        """每日学习状态追踪器"""
        if self._daily_tracker is None:
            from core.services.study.daily_tracker import get_daily_tracker
            self._daily_tracker = get_daily_tracker()
        return self._daily_tracker

    @property
    def weakness_tracker(self):
        """薄弱点追踪器"""
        if self._weakness_tracker is None:
            from core.services.study.weakness_tracker import get_weakness_tracker
            self._weakness_tracker = get_weakness_tracker()
        return self._weakness_tracker

    @property
    def tutor_engine(self):
        """教学决策引擎"""
        if self._tutor_engine is None:
            from core.services.study.tutor_engine import get_tutor_engine
            self._tutor_engine = get_tutor_engine()
        return self._tutor_engine

    # ================================================================
    # 词汇管理
    # ================================================================

    def _is_vocab_enabled(self) -> bool:
        if self._vocab_enabled is None:
            try:
                from config.integrated_config import get_settings
                self._vocab_enabled = get_settings().study.enabled
            except Exception:
                self._vocab_enabled = False
        return self._vocab_enabled

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def vocab_manager(self):
        if not self._is_vocab_enabled():
            return None
        if self._vocab_manager is None:
            self._vocab_manager = get_vocabulary_manager()
        return self._vocab_manager

    # ================================================================
    # 会话管理（委托给 StudySession）
    # ================================================================

    def start_session(self):
        return self._session.start()

    def end_session(self):
        """结束会话，并联动更新 DailyTracker / StudentState / WeaknessTracker"""
        result = self._session.end()
        if not result:
            return result

        # 联动更新结构化数据层
        try:
            self._sync_session_to_trackers(result)
        except Exception as e:
            logger.warning(f"会话数据同步失败: {e}")

        return result

    def _sync_session_to_trackers(self, session_data: Dict[str, Any]) -> None:
        """将会话数据同步到 DailyTracker / StudentState / WeaknessTracker"""
        duration_min = session_data.get("duration_minutes", 0)
        topics_by_subject = session_data.get("topics_by_subject", {})
        struggles_by_subject = session_data.get("struggles_by_subject", {})

        # 背单词只会调用 record_word_review，不会产生 topics_by_subject。
        # 必须单独落入 DailyManager，否则日记与 nightly 学习摘要永远看到 0 次。
        self._sync_vocabulary_session(session_data)

        for subject, topics in topics_by_subject.items():
            # 更新 DailyTracker
            self.daily_tracker.record_session(
                subject=subject,
                topics=topics,
                duration_min=max(1, duration_min // max(1, len(topics_by_subject))),
            )

            # 更新 StudentState
            struggle_topics = struggles_by_subject.get(subject, [])
            self.student_state.update_from_session(
                subject=subject,
                topics=topics,
                duration_min=max(1, duration_min // max(1, len(topics_by_subject))),
                struggles=struggle_topics,
            )

            # 更新 WeaknessTracker（将 struggle 记为薄弱点）
            for struggle_label in struggle_topics:
                # struggle_label 格式可能是 "topic: description" 或 "topic"
                topic_name = struggle_label.split(":")[0].strip() if ":" in struggle_label else struggle_label
                if topic_name:
                    self.weakness_tracker.record_weakness(
                        subject=subject,
                        topic=topic_name,
                        source="chat_detected",
                    )

    def _sync_vocabulary_session(self, session_data: Dict[str, Any]) -> None:
        """把一次词汇复习会话同步到两套每日学习视图。"""
        reviewed_count = int(session_data.get("words_reviewed") or 0)
        if reviewed_count <= 0:
            return

        unique_count = int(session_data.get("unique_words_reviewed") or 0)
        correct_count = int(session_data.get("correct_count") or 0)
        duration_min = max(1, int(session_data.get("duration_minutes") or 0))
        accuracy = float(session_data.get("accuracy") or 0.0)
        detail = (
            f"完成词汇复习：评分 {reviewed_count} 次，涉及 {unique_count} 个单词，"
            f"正确 {correct_count} 次，正确率 {accuracy:.1f}%，用时 {duration_min} 分钟"
        )

        # Journal/计划摘要的权威输入目前来自 DailyManager.study.sessions。
        try:
            get_daily_manager().record_study("英语词汇", detail)
        except Exception as e:
            logger.warning(f"词汇会话同步 DailyManager 失败: {e}")

        # 教学画像与周分析仍读取 DailyTracker，保持两侧一致。
        try:
            self.daily_tracker.record_session(
                subject="english",
                topics=["vocabulary"],
                duration_min=duration_min,
                notes=detail,
            )
        except Exception as e:
            logger.warning(f"词汇会话同步 DailyTracker 失败: {e}")

    def submit_word_review(self, word: str, quality: int) -> Dict[str, Any]:
        if not self.vocab_manager:
            return {"word_update": {}, "session_stats": self.get_session_stats()}
        result = self.vocab_manager.update_word_progress(word, quality)
        self._session.record_word_review(word, quality)
        return {"word_update": result, "session_stats": self.get_session_stats()}

    def get_session_stats(self) -> Dict[str, Any]:
        return self._session.get_stats()

    # ================================================================
    # 学习计划
    # ================================================================

    async def generate_comprehensive_study_plan(
        self, user_id: str, preferences: Dict[str, Any]
    ) -> Dict[str, Any]:
        saga = SagaTransaction(
            transaction_id=f"study_plan_{user_id}_{int(time.time())}"
        )

        async def step_vocab(context):
            count = context.get("vocab_count", 20)
            words = await asyncio.to_thread(self.get_daily_words, count)
            return {"vocabulary_task": words}

        async def compensate_vocab(context):
            logger.info(f"Compensating Vocabulary for {user_id}")

        saga.add_step("allocate_vocabulary", step_vocab, compensate_vocab)

        try:
            result = await saga.execute(initial_context=preferences)
            return {
                "status": "success",
                "plan": {
                    "date": time.strftime("%Y-%m-%d"),
                    "tasks": {
                        "vocabulary": result.get("vocabulary_task"),
                    },
                },
                "transaction_id": saga.transaction_id,
            }
        except Exception as e:
            logger.error(f"Study Plan Saga Failed: {e}")
            return {
                "status": "error",
                "message": f"Failed to generate plan: {str(e)}",
                "transaction_id": saga.transaction_id,
            }

    # ================================================================
    # 词汇与词典
    # ================================================================

    def get_daily_words(self, count: int = 20, order: str = "sequential") -> List[Dict[str, Any]]:
        if not self.vocab_manager:
            return []
        return self.vocab_manager.get_daily_words(count, order=order)

    def get_new_words(self, count: int = 20, order: str = "sequential") -> List[Dict[str, Any]]:
        """从当前词书取从未学过的新词（不在 progress 里的词）。"""
        if not self.vocab_manager:
            return []
        return self.vocab_manager.get_new_words(count, order=order)

    def add_manual_study(self, count: int, date: str = None) -> Dict[str, Any]:
        if not self.vocab_manager:
            return {"status": "error", "message": "词库功能未启用"}
        return self.vocab_manager.add_manual_study(count, date=date)

    def get_manual_study_stats(self, days: int = 7, date: str = None) -> Dict[str, Any]:
        if not self.vocab_manager:
            return {"status": "error", "message": "词库功能未启用"}
        return self.vocab_manager.get_manual_study_stats(days=days, date=date)

    def get_subject_profiles(self) -> List[Dict[str, Any]]:
        return self.subject_profiles

    def get_study_daily_digest(self, date: str = "") -> Dict[str, Any]:
        try:
            date_key = str(date or "").strip() or time.strftime("%Y-%m-%d")
            daily_record = get_daily_manager().get_record(date_key)
            study_sessions = (
                (daily_record.get("study") or {}).get("sessions") or []
                if isinstance(daily_record, dict)
                else []
            )
            return self.summary_builder.build_daily_summary(
                date=date_key,
                dictionary_stats=self.get_dictionary_stats(),
                session_stats=self.get_session_stats(),
                sessions=study_sessions,
            )
        except Exception as e:
            logger.error(f"Failed to get study digest: {e}")
            return {}

    def get_daily_study_summary_data(self, date: str = "") -> Dict[str, Any]:
        """按目标日期返回日记/计划所需的学习摘要。"""
        return self.get_study_daily_digest(date=date)

    def search_dictionary(self, query: str) -> Dict[str, Any]:
        if not query:
            return {}
        if not self.vocab_manager:
            return {"query": query, "matches": [], "match_type": "none"}
        query = query.lower().strip()
        definition = self.vocab_manager.get_definition(query)
        if definition:
            return {"word": query, "definition": definition, "match_type": "exact"}
        # 模糊搜索：当前词书 + 全量释义总表（覆盖用户手动记的跨级别词）
        pools = [self.vocab_manager.dictionary]
        master = getattr(self.vocab_manager.store, "master", None)
        if master and master is not self.vocab_manager.dictionary:
            pools.append(master)
        matches = []
        seen_words = set()
        for pool in pools:
            for item in pool:
                word = item.get("word", "")
                if not word or word in seen_words:
                    continue
                translations = item.get("translations", [])
                if query in word.lower():
                    matches.append({"word": word, "definition": translations})
                    seen_words.add(word)
                else:
                    for trans in translations:
                        if query in trans.get("translation", ""):
                            matches.append({"word": word, "definition": translations})
                            seen_words.add(word)
                            break
                if len(matches) >= 20:
                    break
            if len(matches) >= 20:
                break
        return {"query": query, "matches": matches, "match_type": "fuzzy"}

    def get_word_list(self, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        if not self.vocab_manager:
            return {"total": 0, "page": page, "page_size": page_size, "words": [], "has_more": False}
        total = len(self.vocab_manager.dictionary)
        start = (page - 1) * page_size
        end = start + page_size
        words = self.vocab_manager.dictionary[start:end]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "words": words,
            "has_more": end < total,
        }

    def get_dictionary_stats(self) -> Dict[str, Any]:
        if not self.vocab_manager:
            return _EMPTY_VOCAB_STATS
        return self.vocab_manager.get_stats()

    def switch_vocabulary(
        self, filename: str, is_sentence: bool = False
    ) -> Dict[str, Any]:
        if not self.vocab_manager:
            return {"status": "error", "message": "词库功能未启用"}
        success = self.vocab_manager.switch_dictionary(filename, is_sentence)
        if success:
            if is_sentence:
                return {
                    "status": "success",
                    "message": f"Switched sentence collection to {filename}",
                }
            return {
                "status": "success",
                "message": f"Switched dictionary to {filename}",
            }
        return {"status": "error", "message": f"Failed to switch to {filename}"}

    def add_to_learning(self, word: str) -> Dict[str, Any]:
        if not self.vocab_manager:
            return {"status": "error", "message": "词库功能未启用"}
        success = self.vocab_manager.add_to_learning(word)
        if success:
            return {"status": "success", "message": f"Added '{word}' to learning list"}
        return {"status": "error", "message": f"Word '{word}' not found in dictionary"}

    def get_memory_curve_data(self) -> List[int]:
        if not self.vocab_manager:
            return [100, 80, 60, 45, 35, 28, 25]
        return self.vocab_manager.get_retention_curve()

    def get_review_overview(self) -> Dict[str, Any]:
        """复习总览：今日待复习数、连续天数、到期分布、记忆曲线预测。"""
        if not self.vocab_manager:
            return {
                "due_today_count": 0,
                "streak_days": 0,
                "learned_words": 0,
                "due_words": 0,
                "mastered_words": 0,
                "future_reviews": [],
                "memory_curve": [],
                "new_today": 0,
                "review_today": 0,
            }
        return self.vocab_manager.get_review_overview()

    def get_mistakes(self) -> List[Dict[str, Any]]:
        if not self.vocab_manager:
            return []
        return self.vocab_manager.get_mistakes()

    # ================================================================
    # 工具元数据与调度
    # ================================================================

    def list_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.tools_metadata

    def run_tool(
        self, category: str, tool_id: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """统一工具调度入口，委托给 ToolDispatcher。"""
        return self.dispatcher.dispatch(category, tool_id, params)

    # ================================================================
    # 教学系统新入口（统一 API）
    # ================================================================

    def get_student_state(self) -> Dict[str, Any]:
        """返回结构化学生画像"""
        return self.student_state.to_dict()

    def get_today_status(self) -> Dict[str, Any]:
        """返回今日学习状态"""
        return self.daily_tracker.get_summary_stats()

    def get_today_detailed(self) -> Dict[str, Any]:
        """返回今日详细学习记录"""
        record = self.daily_tracker.get_today()
        return {
            "date": record.date,
            "total_study_minutes": record.total_study_minutes,
            "sessions": [s.model_dump() for s in record.sessions],
            "knowledge_points": [kp.model_dump() for kp in record.knowledge_points],
            "struggles": [s.model_dump() for s in record.struggles],
            "subjects_studied": record.subjects_studied,
            "subject_breakdown": self.daily_tracker.get_subject_breakdown(),
        }

    def get_daily_briefing(self) -> Dict[str, Any]:
        """返回每日教学简报"""
        return self.tutor_engine.generate_daily_briefing()

    def get_study_plan(self) -> Dict[str, Any]:
        """返回今日学习计划"""
        return self.tutor_engine.generate_study_plan()

    def get_weakness_report(self) -> Dict[str, Any]:
        """返回薄弱点报告"""
        return self.weakness_tracker.get_weakness_report()

    def get_review_reminders(self) -> List[Dict[str, Any]]:
        """返回今日复习提醒"""
        return self.tutor_engine.get_review_reminders()

    def get_weekly_analysis(self) -> Dict[str, Any]:
        """返回周学习分析"""
        return self.tutor_engine.get_weekly_analysis()

    def record_topic_learned(
        self, subject: str, topic: str, status: str = "new"
    ) -> Dict[str, Any]:
        """记录知识点学习"""
        # 同步更新 session 和 daily_tracker
        self._session.record_topic(subject, topic, status)
        self.daily_tracker.record_knowledge_point(subject, topic, status)
        return {"status": "success", "subject": subject, "topic": topic, "recorded_status": status}

    def record_weakness(
        self, subject: str, topic: str, source: str = "self_reported"
    ) -> Dict[str, Any]:
        """记录薄弱点"""
        item = self.weakness_tracker.record_weakness(subject, topic, source)
        return {"status": "success", "weakness_id": item.id, "next_review": item.next_review_date}

    def review_weakness(self, item_id: str, quality: int) -> Dict[str, Any]:
        """记录薄弱点复习结果"""
        item = self.weakness_tracker.mark_reviewed(item_id, quality)
        if item is None:
            return {"status": "error", "message": "Weakness item not found"}
        return {
            "status": "success",
            "weakness_id": item.id,
            "confidence": item.confidence,
            "next_review": item.next_review_date,
            "is_mastered": item.is_mastered,
        }

    def mark_topic_mastered(self, subject: str, topic: str) -> Dict[str, Any]:
        """标记知识点已掌握"""
        self.student_state.mark_topic_mastered(subject, topic)
        # 同时尝试标记对应的 weakness item 为 mastered
        item_id = None
        try:
            from core.services.study.weakness_tracker import WeaknessItem
            item_id = WeaknessItem.make_id(subject, topic)
            self.weakness_tracker.promote_to_mastered(item_id)
        except Exception:
            pass
        return {"status": "success", "subject": subject, "topic": topic}


def get_study_service():
    return StudyService.get_instance()
