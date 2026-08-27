"""每日新背单词日志（按 YYYY/MM/DD 文件夹组织）

与 unfamiliar_word.txt（历史生词本）互补：
- unfamiliar_word.txt 是用户长期积累的生词
- daily/YYYY/MM/DD.txt 是每天新背的、不会的单词

路径：data/study_data/English/Words/daily/YYYY/MM/DD.txt
格式：与 unfamiliar_word.txt 一致，每行 'word' 或 'word count'

设计要点：
1. lazy 创建：第一次写入时自动 mkdir + 创建文件，不预生成空文件
2. 跨日期查询：默认最近 7 天，可指定天数范围或具体日期
3. mark 操作：单词可能在多天文件里出现，默认改最近一次出现该词的那天；
   指定 date 时只改那个文件
4. 单文件解析复用 UnfamiliarWordBook，保证格式行为一致
"""
from __future__ import annotations

import datetime
import os
import random
import threading
from typing import Any, Dict, List, Optional

from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time_str

logger = get_logger("DailyWordLog")

_instance: Optional["DailyWordLogManager"] = None
_instance_lock = threading.Lock()


def get_daily_word_log() -> "DailyWordLogManager":
    """单例获取每日单词日志管理器"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is not None:
                return _instance
            _instance = DailyWordLogManager()
    return _instance


class DailyWordLogManager:
    """按日期组织的每日新背单词日志"""

    def __init__(self, base_dir: Optional[str] = None):
        # core/tools/study/english/daily_word_log.py -> 项目根
        project_root = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
        self.base_dir = base_dir or os.path.join(
            project_root, "data", "study_data", "English", "Words", "daily"
        )
        # 缓存：date_str -> UnfamiliarWordBook 实例
        self._books: Dict[str, UnfamiliarWordBook] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 日期与路径
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """'2026-08-05' / '2026/08/05' -> '2026/08/05'"""
        return str(date_str or "").replace("-", "/").strip()

    def _date_to_path(self, date_str: str) -> str:
        """'2026/08/05' -> base_dir/2026/08/05.txt"""
        normalized = self._normalize_date(date_str)
        parts = normalized.split("/")
        return os.path.join(self.base_dir, *parts) + ".txt"

    @staticmethod
    def _get_today_str() -> str:
        return get_current_time_str("%Y/%m/%d")

    def get_yesterday_str(self) -> str:
        """返回昨天日期，作为 daily 复习的默认来源。"""
        today = datetime.datetime.strptime(self._get_today_str(), "%Y/%m/%d").date()
        return (today - datetime.timedelta(days=1)).strftime("%Y/%m/%d")

    def ensure_today_file(self) -> str:
        """确保今天的文件存在（创建目录 + 空文件），返回文件路径

        后端启动时调用，避免 AI 第一次写入时才触发文件创建。
        幂等：文件已存在时不覆盖。
        """
        today = self._get_today_str()
        path = self._date_to_path(today)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            # 创建空文件占位，便于用户后续手动追加内容
            open(path, "w", encoding="utf-8").close()
            logger.info(f"Created daily word log: {path}")
        return path

    # ------------------------------------------------------------------
    # 单文件访问（复用 UnfamiliarWordBook）
    # ------------------------------------------------------------------

    def _get_book_for_date(self, date_str: str) -> UnfamiliarWordBook:
        """获取某天的 UnfamiliarWordBook 实例（缓存）"""
        normalized = self._normalize_date(date_str)
        with self._lock:
            if normalized not in self._books:
                path = self._date_to_path(normalized)
                # 懒创建：首次写入任意日期时自动建目录（与 ensure_today_file 的
                # lazy 设计一致，mark_unknown 指定历史日期回填时不至于炸目录缺失）
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._books[normalized] = UnfamiliarWordBook(file_path=path)
            return self._books[normalized]

    # ------------------------------------------------------------------
    # 日期列表
    # ------------------------------------------------------------------

    def list_dates(self) -> List[str]:
        """列出所有有记录的日期（降序，最新在前）"""
        dates: List[str] = []
        if not os.path.exists(self.base_dir):
            return dates

        try:
            for year in sorted(os.listdir(self.base_dir), reverse=True):
                year_path = os.path.join(self.base_dir, year)
                if not os.path.isdir(year_path) or not year.isdigit():
                    continue
                for month in sorted(os.listdir(year_path), reverse=True):
                    month_path = os.path.join(year_path, month)
                    if not os.path.isdir(month_path) or not month.isdigit():
                        continue
                    for day_file in sorted(os.listdir(month_path), reverse=True):
                        if not day_file.endswith(".txt"):
                            continue
                        day = day_file[:-4]
                        if day.isdigit():
                            dates.append(f"{year}/{month}/{day}")
        except OSError as e:
            logger.warning(f"Failed to list daily dates: {e}")

        return dates

    def get_recent_dates(self, days: int = 7) -> List[str]:
        """获取最近 N 天的日期列表（含今天，降序）"""
        today_str = self._get_today_str()
        y, m, d = map(int, today_str.split("/"))
        today = datetime.date(y, m, d)
        return [
            (today - datetime.timedelta(days=i)).strftime("%Y/%m/%d")
            for i in range(max(1, days))
        ]

    # ------------------------------------------------------------------
    # 单词读取
    # ------------------------------------------------------------------

    def get_words_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        """读取某天的单词，每条带 date 字段"""
        book = self._get_book_for_date(date_str)
        words = book.list_words()
        normalized = self._normalize_date(date_str)
        for w in words:
            w["date"] = normalized
        return words

    def get_words_for_recent_days(self, days: int = 7) -> List[Dict[str, Any]]:
        """读取最近 N 天的单词（带 date 字段）"""
        all_words: List[Dict[str, Any]] = []
        for date_str in self.get_recent_dates(days):
            all_words.extend(self.get_words_for_date(date_str))
        return all_words

    def get_merged_recent_words(self, days: int = 7) -> List[Dict[str, Any]]:
        """读取最近 N 天的单词，跨天按单词去重合并计数。

        与 unfamiliar_word.txt 的语义对齐：同一单词在多个日期出现时，
        unknown_count 求和（即"不认识次数"累加，相当于尾部数字相加），
        并记录它在哪些天出现过。这样 quiz 时不会把同一单词重复铺开，
        且 count 越高的词越优先被抽到。
        """
        merged: Dict[str, Dict[str, Any]] = {}
        for date_str in self.get_recent_dates(days):
            for w in self.get_words_for_date(date_str):
                key = w["word"].lower()
                if key not in merged:
                    merged[key] = {
                        "word": w["word"],
                        "unknown_count": 0,
                        "occurrence_count": 0,
                        "dates": [],
                    }
                entry = merged[key]
                entry["unknown_count"] += w["unknown_count"]
                # 出现次数与“不认识次数”分开记录，不能把 0 强改为 1；
                # 否则 priority=new 永远找不到尚未测验的词。
                entry["occurrence_count"] += 1
                if date_str not in entry["dates"]:
                    entry["dates"].append(date_str)
        return list(merged.values())

    def get_words_for_all_dates(self) -> List[Dict[str, Any]]:
        """读取所有已有日期文件的单词"""
        all_words: List[Dict[str, Any]] = []
        for date_str in self.list_dates():
            all_words.extend(self.get_words_for_date(date_str))
        return all_words

    # ------------------------------------------------------------------
    # 抽查
    # ------------------------------------------------------------------

    def quiz(
        self,
        count: int = 5,
        days: int = 7,
        date: Optional[str] = None,
        priority: str = "high_count",
    ) -> List[Dict[str, Any]]:
        """抽查单词

        Args:
            count: 抽取数量
            days: 最近 N 天（仅当 date 未指定时生效，默认 7 天）
            date: 指定某天（'2026/08/05' 或 '2026-08-05'）
            priority: high_count / random / new
        """
        if date:
            words = self.get_words_for_date(date)
        else:
            words = self.get_merged_recent_words(days)

        if not words:
            return []

        if priority == "high_count":
            # 按 count 降序；同 count 内随机
            groups: Dict[int, List[Dict[str, Any]]] = {}
            for w in words:
                groups.setdefault(w["unknown_count"], []).append(w)
            ordered: List[Dict[str, Any]] = []
            for cnt in sorted(groups.keys(), reverse=True):
                bucket = list(groups[cnt])
                random.shuffle(bucket)
                ordered.extend(bucket)
            return ordered[: min(count, len(ordered))]

        if priority == "new":
            untested = [w for w in words if w["unknown_count"] == 0]
            pool = untested if untested else words
            return random.sample(pool, min(count, len(pool)))

        # random
        return random.sample(words, min(count, len(words)))

    # ------------------------------------------------------------------
    # 标记
    # ------------------------------------------------------------------

    def _find_latest_date_containing(self, word: str) -> Optional[str]:
        """在所有已有日期里找最近一次出现该词的日期"""
        target = word.lower()
        for date_str in self.list_dates():
            for w in self.get_words_for_date(date_str):
                if w["word"].lower() == target:
                    return date_str
        return None

    def mark_unknown(
        self, word: str, date: Optional[str] = None
    ) -> Dict[str, Any]:
        """标记不认识：在指定日期文件 +1；未指定时找最近出现该词的那天；
        都没有则追加到今天的文件（自动创建）。"""
        if date:
            book = self._get_book_for_date(date)
            result = book.mark_unknown(word)
            result["date"] = self._normalize_date(date)
            return result

        # 找最近一次出现该词的那天
        latest = self._find_latest_date_containing(word)
        if latest:
            book = self._get_book_for_date(latest)
            result = book.mark_unknown(word)
            result["date"] = latest
            return result

        # 没找到：追加到今天的文件
        # 正常情况启动时已 ensure_today_file，这里兜底跨天后后端未重启的场景
        self.ensure_today_file()
        today = self._get_today_str()
        book = self._get_book_for_date(today)
        result = book.mark_unknown(word)
        result["date"] = today
        return result

    def mark_known(
        self, word: str, date: Optional[str] = None
    ) -> Dict[str, Any]:
        """标记认识：在指定日期文件 -1；未指定时找最近出现该词的那天；
        都没有则视为已掌握，不追加。"""
        if date:
            book = self._get_book_for_date(date)
            result = book.mark_known(word)
            result["date"] = self._normalize_date(date)
            return result

        latest = self._find_latest_date_containing(word)
        if latest:
            book = self._get_book_for_date(latest)
            result = book.mark_known(word)
            result["date"] = latest
            return result

        return {"word": word, "unknown_count": 0, "added": False, "date": None}

    def remove(
        self, word: str, date: Optional[str] = None
    ) -> Dict[str, Any]:
        """完全移除某词（删除文件中该词的所有出现行）。

        用于复习流转：词一经复习就划掉旧记录，避免当天重新拉取复习词时
        又出现刚复习过的词。指定 date 时只改那个文件；未指定时找最近出现
        该词的那天；都没有则视为无记录，返回 removed=False。
        """
        if date:
            book = self._get_book_for_date(date)
            result = book.remove(word)
            result["date"] = self._normalize_date(date)
            return result

        latest = self._find_latest_date_containing(word)
        if latest:
            book = self._get_book_for_date(latest)
            result = book.remove(word)
            result["date"] = latest
            return result

        return {"word": word, "removed": False, "date": None}

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(self, days: int = 7) -> Dict[str, Any]:
        """返回最近 N 天的统计（默认 7 天）"""
        recent_dates = self.get_recent_dates(days)
        all_words = self.get_merged_recent_words(days)
        total = len(all_words)
        untested = sum(1 for w in all_words if w["unknown_count"] == 0)
        struggling = sum(1 for w in all_words if w["unknown_count"] >= 2)
        max_count = max((w["unknown_count"] for w in all_words), default=0)

        # 哪些天有数据
        dates_with_words = [
            d for d in recent_dates if self.get_words_for_date(d)
        ]

        # 所有历史日期数
        all_history_dates = self.list_dates()

        return {
            "status": "success",
            "total_words": total,
            # 字段对齐 VocabularyManager.get_stats
            "learned_words": 0,
            "due_words": struggling,
            "to_review": struggling,
            "mastered_words": 0,
            "struggling_words": struggling,
            "untested_words": untested,
            "max_unknown_count": max_count,
            "available_word_files": [f"daily/{d}.txt" for d in dates_with_words],
            "available_sentence_files": [],
            "current_dictionary": f"daily (recent {days} days)",
            "current_sentence_collection": None,
            # 额外字段
            "dates_with_words": dates_with_words,
            "days_covered": days,
            "total_history_dates": len(all_history_dates),
            "earliest_date": all_history_dates[-1] if all_history_dates else None,
            "latest_date": all_history_dates[0] if all_history_dates else None,
        }
