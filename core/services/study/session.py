"""学习会话管理 —— 跟踪单次学习过程的状态

增强版：在原有词汇追踪基础上，新增知识点级追踪和困难记录。
会话结束时可联动 DailyTracker / StudentState / WeaknessTracker。

统计口径说明（2026-09-02 修正）：
    正确率按「单词」算，不按「评分次数」算。同一个单词一次复习里可能被
    重复推送多次（答错再来），若按次数统计，一个词连续错三次会把分母撑大
    三倍，正确率被严重低估——实测 8/30 真实掌握率 77.4%，按次数只有 49.2%。
    因此以每个单词**最后一次**评分作为该词的掌握状态：>=3 视为掌握。
    `words_reviewed` / `correct_count` 仍保留评分次数口径，但只作为辅助信息，
    不参与 accuracy 计算。
"""
import time
from typing import Any, Dict, List, Optional


class StudySession:
    """管理一次学习会话的生命周期与统计数据。"""

    # 超过此秒数无活动则认为会话已结束
    IDLE_TIMEOUT = 3600

    def __init__(self):
        self._state = self._empty_state()

    # ---- 公共 API ----

    def start(self) -> Dict[str, Any]:
        now = time.time()
        self._state = {
            "active": True,
            "start_time": now,
            "last_activity": now,
            "words_reviewed": 0,
            "correct_count": 0,
            "current_streak": 0,
            "words_learned_today": set(),
            # 每个单词的最后一次评分，用于按单词口径计算正确率
            "word_last_quality": {},
            # 新增：知识点级追踪
            "topics": [],          # [(subject, topic, status)]
            "struggles": [],       # [(subject, topic, description)]
            "current_subject": "", # 当前学习的科目
        }
        return self._state_to_dict()

    def end(self) -> Dict[str, Any]:
        """结束会话，返回完整会话数据（含知识点和困难列表）"""
        if not self._state["active"]:
            return {}
        now = time.time()
        duration = now - self._state["start_time"]
        duration_min = max(1, int(duration / 60))
        self._state["active"] = False

        # 汇总本次会话数据
        topics_by_subject: Dict[str, List[str]] = {}
        for subj, topic, _status in self._state["topics"]:
            topics_by_subject.setdefault(subj, []).append(topic)

        struggles_by_subject: Dict[str, List[str]] = {}
        for subj, topic, desc in self._state["struggles"]:
            label = f"{topic}: {desc}" if desc else topic
            struggles_by_subject.setdefault(subj, []).append(label)

        words_reviewed = int(self._state["words_reviewed"] or 0)
        correct_count = int(self._state["correct_count"] or 0)
        reviewed_words = sorted(self._state["words_learned_today"])

        # 按单词口径：以每个词最后一次评分判定掌握（>=3 视为掌握）
        word_last_quality = self._state.get("word_last_quality") or {}
        words_total = len(word_last_quality) or len(reviewed_words)
        words_mastered = sum(
            1 for q in word_last_quality.values() if int(q or 0) >= 3
        )

        return {
            "started_at": self._state["start_time"],
            "ended_at": now,
            "duration": duration,
            "duration_minutes": duration_min,
            "words_reviewed": words_reviewed,
            "unique_words_reviewed": len(reviewed_words),
            "reviewed_words": reviewed_words,
            "correct_count": correct_count,
            # 按单词算的正确率（权威口径，与背单词 app 结算界面一致）
            "accuracy": (
                words_mastered / words_total * 100 if words_total > 0 else 0.0
            ),
            "words_total": words_total,
            "words_mastered": words_mastered,
            # 评分次数口径，仅作辅助展示，不参与 accuracy
            "review_events": words_reviewed,
            "correct_events": correct_count,
            "topics": list(self._state["topics"]),
            "struggles": list(self._state["struggles"]),
            "topics_by_subject": topics_by_subject,
            "struggles_by_subject": struggles_by_subject,
            "subjects_studied": list(topics_by_subject.keys()),
        }

    def record_word_review(self, word: str, quality: int) -> Optional[Dict[str, Any]]:
        """记录一次单词复习。

        Returns:
            被超时挤掉、需要调用方落盘的旧会话数据；没有则 None。

        修复（2026-09-02）：以前会话空闲超时后直接 `start()` 重置，已累积的
        复习数据被静默丢弃且永不结算。典型后果是 9/1 全天 106 次评分只落盘了
        最后一段 21 次，而那 21 次恰好全是答错的，整天被记成「正确率 0.0%」。
        现在改为先把旧会话 end() 返回，由调用方负责落盘。
        """
        expired_session: Optional[Dict[str, Any]] = None
        if self._state["active"] and self._is_expired():
            expired_session = self.end()
        if not self._state["active"]:
            self.start()
        self._state["last_activity"] = time.time()
        self._state["words_reviewed"] += 1
        # 按单词口径：同一词重复推送时以最后一次评分作为该词的掌握状态
        self._state["word_last_quality"][word] = int(quality)
        # 现行契约 1=Again、2=Hard、3=Good、4=Easy：Hard 属于成功回忆，
        # 只有 Again 算没想起来。
        if quality >= 2:
            self._state["correct_count"] += 1
            self._state["current_streak"] += 1
        else:
            self._state["current_streak"] = 0
        self._state["words_learned_today"].add(word)
        return expired_session

    def record_topic(
        self,
        subject: str,
        topic: str,
        status: str = "new",
    ) -> None:
        """
        记录一个知识点的学习。

        subject: 科目名
        topic: 知识点名称
        status: new(新学) / reviewed(复习) / mastered(掌握) / struggling(困难)
        """
        if not self._state["active"] or self._is_expired():
            self.start()
        if status not in ("new", "reviewed", "mastered", "struggling"):
            status = "new"
        self._state["last_activity"] = time.time()
        self._state["topics"].append(
            (subject.lower().strip(), topic.strip(), status)
        )
        # 自动更新当前科目
        self._state["current_subject"] = subject.lower().strip()

    def record_struggle(
        self,
        subject: str,
        topic: str,
        description: str = "",
    ) -> None:
        """记录学习中遇到的困难。"""
        if not self._state["active"] or self._is_expired():
            self.start()
        self._state["last_activity"] = time.time()
        self._state["struggles"].append(
            (subject.lower().strip(), topic.strip(), description.strip())
        )
        # 困难也作为一种 struggling 知识点记录
        self._state["topics"].append(
            (subject.lower().strip(), topic.strip(), "struggling")
        )

    def get_stats(self) -> Dict[str, Any]:
        # 注意：这里不能再把过期会话直接置为 inactive。
        # 那样会丢掉已累积但未结算的数据（数据只在 end() 时才落盘）。
        # 过期的收尾交给 record_word_review / end()，此处只如实体现"是否已过期"。
        is_active = bool(self._state["active"]) and not self._is_expired()

        reviewed = self._state["words_reviewed"]
        correct = self._state["correct_count"]
        word_last_quality = self._state.get("word_last_quality") or {}
        words_total = len(word_last_quality)
        words_mastered = sum(
            1 for q in word_last_quality.values() if int(q or 0) >= 3
        )
        return {
            "active": is_active,
            "duration": (
                time.time() - self._state["start_time"]
                if is_active
                else 0
            ),
            "words_reviewed": reviewed,
            "correct_count": correct,
            # 按单词口径，与 end() 保持一致
            "accuracy": (
                words_mastered / words_total * 100 if words_total > 0 else 0.0
            ),
            "words_total": words_total,
            "words_mastered": words_mastered,
            "review_events": reviewed,
            "correct_events": correct,
            "streak": self._state["current_streak"],
        }

    def get_detailed_stats(self) -> Dict[str, Any]:
        """返回含知识点级别的详细统计"""
        base = self.get_stats()

        # 按科目统计知识点
        topics_by_subject: Dict[str, Dict[str, int]] = {}
        for subj, topic, status in self._state.get("topics", []):
            if subj not in topics_by_subject:
                topics_by_subject[subj] = {"new": 0, "reviewed": 0, "mastered": 0, "struggling": 0}
            if status in topics_by_subject[subj]:
                topics_by_subject[subj][status] += 1

        base["topics_total"] = len(self._state.get("topics", []))
        base["struggles_total"] = len(self._state.get("struggles", []))
        base["topics_by_subject"] = topics_by_subject
        base["current_subject"] = self._state.get("current_subject", "")
        return base

    # ---- 内部方法 ----

    def _is_expired(self) -> bool:
        return time.time() - self._state["last_activity"] > self.IDLE_TIMEOUT

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        return {
            "active": False,
            "start_time": 0,
            "last_activity": 0,
            "words_reviewed": 0,
            "correct_count": 0,
            "current_streak": 0,
            "words_learned_today": set(),
            "word_last_quality": {},
            "topics": [],
            "struggles": [],
            "current_subject": "",
        }

    @staticmethod
    def _state_to_dict(state: Optional[Dict] = None) -> Dict[str, Any]:
        """将 state 转为可 JSON 序列化的 dict（去掉 set）"""
        if state is None:
            return {}
        result = {}
        for k, v in state.items():
            if isinstance(v, set):
                result[k] = list(v)
            else:
                result[k] = v
        return result
