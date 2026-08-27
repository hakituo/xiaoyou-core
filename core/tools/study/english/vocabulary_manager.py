"""VocabularyManager —— 对外门面（Facade）。

原 1000+ 行的 God Class 已按职责解耦为：
- loader.py        : VocabDataStore   数据加载与持久化
- fsrs_scheduler.py: FSRS / SM-2 调度
- quiz.py          : 每日取词 / 测验生成
- stats.py         : 统计 / 记忆曲线 / 总览

本模块只负责组合这些组件、保留对外 API 与单例，不内联业务逻辑。
"""

import threading
from typing import Dict, List, Optional, Any

from core.utils.logger import get_logger

from .loader import VocabDataStore
from . import fsrs_scheduler as _fsrs
from . import quiz as _quiz
from . import stats as _stats

logger = get_logger("VocabularyManager")

_vocabulary_manager_instance = None
# 使用 threading.Lock + double-check 保护单例，防止多线程并发重复创建
_vocabulary_manager_lock = threading.Lock()


def get_vocabulary_manager():
    """获取单例 VocabularyManager。"""
    global _vocabulary_manager_instance
    if _vocabulary_manager_instance is None:
        with _vocabulary_manager_lock:
            if _vocabulary_manager_instance is not None:
                return _vocabulary_manager_instance
            _vocabulary_manager_instance = VocabularyManager()
    return _vocabulary_manager_instance


class VocabularyManager:
    """组合各职责模块，对外暴露原有 API。"""

    def __init__(self, dictionary_path: str = None, progress_path: str = None):
        self.store = VocabDataStore(dictionary_path, progress_path)

    # ---------------- 透传数据层 ----------------
    def _ensure_loaded(self):
        self.store._ensure_loaded()

    @property
    def dictionary_path(self):
        return self.store.dictionary_path

    def import_from_file(self, file_path: str) -> int:
        return self.store.import_from_file(file_path)

    def get_word_info(self, word: str) -> Optional[Dict]:
        return self.store.get_word_info(word)

    def get_sentence_info(self, word: str) -> Optional[Dict]:
        return self.store.get_sentence_info(word)

    def get_definition(self, word: str) -> Optional[List[Dict[str, str]]]:
        return self.store.get_definition(word)

    def switch_dictionary(self, filename: str, is_sentence: bool = False) -> bool:
        return self.store.switch_dictionary(filename, is_sentence)

    # ---------------- 调度 ----------------
    def update_word_progress(self, word: str, quality: int):
        return _fsrs.apply_progress(self.store, word, quality)

    # ---------------- 每日取词 / 测验 ----------------
    def get_daily_words(self, limit: int = 0, order: str = "sequential"):
        return _quiz.get_daily_words(self.store, limit, order)

    def get_new_words(self, count: int = 20, order: str = "sequential"):
        return _quiz.get_new_words(self.store, count, order)

    def generate_quiz(self, mode: str = "multiple_choice", count: int = 20,
                      source: str = "all") -> List[Dict]:
        return _quiz.generate_quiz(self.store, mode, count, source)

    def check_quiz_answer(self, question: Dict, user_answer: str) -> Dict:
        return _quiz.check_quiz_answer(self.store, question, user_answer)

    def add_to_learning(self, word: str) -> bool:
        return _quiz.add_to_learning(self.store, word)

    # ---------------- 统计 / 总览 ----------------
    def get_stats(self) -> Dict:
        return _stats.get_stats(self.store)

    def get_mistakes(self, limit: int = 20) -> List[Dict]:
        return _stats.get_mistakes(self.store, limit)

    def get_linked_unfamiliar_words(self) -> List[Dict[str, Any]]:
        """返回 unfamiliar 文件与 App 历史错题的只读合并词池。"""
        return _stats.get_linked_unfamiliar_words(self.store)

    def get_weak_words(self, limit: int = 50) -> List[Dict]:
        return _stats.get_weak_words(self.store, limit)

    def get_retention_curve(self) -> List[int]:
        return _stats.get_retention_curve(self.store)

    def get_memory_curve_data(self) -> Dict:
        return _stats.get_memory_curve_data(self.store)

    def get_review_overview(self) -> Dict:
        return _stats.get_review_overview(self.store)

    def get_today_review_status(self) -> Dict[str, Any]:
        """获取今日词汇复习的实时完成状态。"""
        return _stats.get_today_review_status(self.store)

    def get_manual_study_stats(self, days: int = 7, date: str = None) -> Dict[str, Any]:
        return _stats.get_manual_study_stats(self.store, days, date)

    def add_manual_study(self, count: int, date: str = None) -> Dict[str, Any]:
        return _stats.add_manual_study(self.store, count, date)
