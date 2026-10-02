"""daily_word_log 的标记、移除与统计（混入 DailyWordLogManager）。

从 ``core/tools/study/english/daily_word_log.py`` 拆出：单词可能在多天文件里
出现，默认改最近一次出现该词的那天；指定 date 时只改那个文件。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class DailyWordLogMarksMixin:
    """标记认识/不认识、移除记录与最近 N 天统计。"""

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
            self._record_self_write(date)
            return result

        # 找最近一次出现该词的那天
        latest = self._find_latest_date_containing(word)
        if latest:
            book = self._get_book_for_date(latest)
            result = book.mark_unknown(word)
            result["date"] = latest
            self._record_self_write(latest)
            return result

        # 没找到：追加到今天的文件
        # 正常情况启动时已 ensure_today_file，这里兜底跨天后后端未重启的场景
        self.ensure_today_file()
        today = self._get_today_str()
        book = self._get_book_for_date(today)
        result = book.mark_unknown(word)
        result["date"] = today
        self._record_self_write(today)
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
            self._record_self_write(date)
            return result

        latest = self._find_latest_date_containing(word)
        if latest:
            book = self._get_book_for_date(latest)
            result = book.mark_known(word)
            result["date"] = latest
            self._record_self_write(latest)
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
            self._record_self_write(date)
            return result

        latest = self._find_latest_date_containing(word)
        if latest:
            book = self._get_book_for_date(latest)
            result = book.remove(word)
            result["date"] = latest
            self._record_self_write(latest)
            return result

        return {"word": word, "removed": False, "date": None}

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
