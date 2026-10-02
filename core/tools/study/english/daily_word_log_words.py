"""daily_word_log 的单日文件访问、单词读取与抽查（混入 DailyWordLogManager）。

从 ``core/tools/study/english/daily_word_log.py`` 拆出。单文件解析统一复用
``UnfamiliarWordBook``，保证与生词本（unfamiliar_word.txt）格式行为一致。
"""
from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional

from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook


class DailyWordLogWordsMixin:
    """按日期读写单词文件与随机抽查。"""

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
