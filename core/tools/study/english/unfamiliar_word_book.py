"""生词本（unfamiliar_word.txt）读写管理

独立于 VocabularyManager（CET4 词典 + SM-2 进度），
专门负责 data/study_data/English/Words/unfamiliar_word.txt 的解析与计数维护。

文件格式：每行一个单词，可选尾部数字表示"不认识次数"，例如：
    absorb
    comprehensive 2
    comprise 1

空行作为分组分隔，会被保留。
重复词合并计数（取较大值），只更新首次出现的位置。

所有 mark 操作直接写回源文件，保证 AI 与用户手动编辑看到的是同一份数据。
"""
from __future__ import annotations

import os
import random
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger("UnfamiliarWordBook")

_instance: Optional["UnfamiliarWordBook"] = None
_instance_lock = threading.Lock()


def get_unfamiliar_word_book() -> "UnfamiliarWordBook":
    """单例获取生词本管理器"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is not None:
                return _instance
            _instance = UnfamiliarWordBook()
    return _instance


class _WordEntry:
    """生词本内一条记录的内存表示"""

    __slots__ = ("word", "count", "line_index")

    def __init__(self, word: str, count: int, line_index: int):
        self.word = word
        self.count = count
        self.line_index = line_index


class UnfamiliarWordBook:
    """unfamiliar_word.txt 的读写器"""

    def __init__(self, file_path: Optional[str] = None):
        # core/tools/study/english/unfamiliar_word_book.py -> 项目根
        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
        self.file_path = file_path or os.path.join(
            base_dir, "data", "study_data", "English", "Words", "unfamiliar_word.txt"
        )
        self._lock = threading.Lock()
        self._cache: Optional[List[_WordEntry]] = None
        self._cache_mtime: float = 0.0

    # ------------------------------------------------------------------
    # 文件读写
    # ------------------------------------------------------------------

    def _read_lines_raw(self) -> List[str]:
        if not os.path.exists(self.file_path):
            return []
        with open(self.file_path, "r", encoding="utf-8") as f:
            return f.readlines()

    @staticmethod
    def _parse_line(raw: str) -> Optional[Tuple[str, int]]:
        """解析一行：'word' / 'word 3' / '  ' / ''"""
        stripped = raw.strip()
        if not stripped:
            return None
        # 从右边切一次，兼容词中含空格的极端情况（实际英文单词无空格）
        parts = stripped.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], int(parts[1])
        return parts[0], 0

    def _load_entries(self) -> List[_WordEntry]:
        """加载所有条目（去重，保留首次出现位置）"""
        mtime = (
            os.path.getmtime(self.file_path)
            if os.path.exists(self.file_path)
            else 0.0
        )
        if self._cache is not None and mtime == self._cache_mtime:
            return self._cache

        entries: List[_WordEntry] = []
        seen: Dict[str, int] = {}  # word(小写) -> entries 索引
        for idx, raw in enumerate(self._read_lines_raw()):
            parsed = self._parse_line(raw)
            if parsed is None:
                continue
            word, count = parsed
            key = word.lower()
            if key in seen:
                # 重复词：合并计数（取较大值），不新增条目
                existing = entries[seen[key]]
                if count > existing.count:
                    existing.count = count
                continue
            seen[key] = len(entries)
            entries.append(_WordEntry(word, count, idx))

        self._cache = entries
        self._cache_mtime = mtime
        return entries

    def _invalidate_cache(self) -> None:
        self._cache = None
        self._cache_mtime = 0.0

    def _write_back(self, entries: List[_WordEntry]) -> None:
        """根据 entries 的 line_index 原地更新对应行，保留其他行原样"""
        raw_lines = self._read_lines_raw()
        # 按 line_index 分组（重复词只更新第一次出现的位置）
        updates: Dict[int, _WordEntry] = {}
        for e in entries:
            if e.line_index < 0 or e.line_index in updates:
                continue
            updates[e.line_index] = e

        for idx in range(len(raw_lines)):
            if idx in updates:
                e = updates[idx]
                raw_lines[idx] = (
                    f"{e.word} {e.count}\n" if e.count > 0 else f"{e.word}\n"
                )

        # 原子写回，避免半写状态
        tmp_path = self.file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(raw_lines)
        os.replace(tmp_path, self.file_path)

    def _append_new_word(self, word: str, count: int) -> int:
        """追加新词到文件末尾，返回新行号"""
        line = f"{word} {count}\n" if count > 0 else f"{word}\n"
        # 确保文件末尾有换行
        if os.path.exists(self.file_path):
            with open(self.file_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        line = "\n" + line
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line)
        # 返回新行号（用于缓存更新）
        with open(self.file_path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f) - 1

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    def list_words(self) -> List[Dict[str, Any]]:
        """列出全部生词"""
        with self._lock:
            entries = self._load_entries()
            return [{"word": e.word, "unknown_count": e.count} for e in entries]

    def stats(self) -> Dict[str, Any]:
        """返回统计信息（字段与 VocabularyManager.get_stats 对齐以兼容调用方）"""
        with self._lock:
            entries = self._load_entries()
            total = len(entries)
            untested = sum(1 for e in entries if e.count == 0)
            struggling = sum(1 for e in entries if e.count >= 2)
            max_count = max((e.count for e in entries), default=0)
            return {
                "status": "success",
                "total_words": total,
                # 兼容旧字段：生词本无 learned/mastered 概念，置 0
                "learned_words": 0,
                "due_words": struggling,
                "to_review": struggling,
                "mastered_words": 0,
                # active_care/vocabulary.py 用到
                "struggling_words": struggling,
                "untested_words": untested,
                "max_unknown_count": max_count,
                "available_word_files": ["unfamiliar_word.txt"],
                "available_sentence_files": [],
                "current_dictionary": "unfamiliar_word.txt",
                "current_sentence_collection": None,
            }

    def quiz(
        self,
        count: int = 5,
        word: Optional[str] = None,
        priority: str = "high_count",
        word_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """抽取单词进行测验

        Args:
            count: 抽取数量
            word: 指定单词时直接返回该词（不参与随机）
            priority: high_count 优先抽不认识次数多的；
                      random 完全随机；
                      new 优先抽未测验过的
            word_pool: 可选的外部合并词池；用于把 App 历史错题与本文件计数
                       联动。为空时仍直接读取本文件。
        """
        if word_pool is None:
            with self._lock:
                entries = [
                    {"word": entry.word, "unknown_count": entry.count}
                    for entry in self._load_entries()
                ]
        else:
            entries = [dict(entry) for entry in word_pool]

        if word:
            target_lower = word.lower()
            for e in entries:
                if str(e.get("word") or "").lower() == target_lower:
                    return [e]
            return []

        if not entries:
            return []

        if priority == "high_count":
            # 按 count 降序；同 count 内随机，避免每次抽到完全相同的几个词
            import collections

            groups: "collections.defaultdict[int, list]" = collections.defaultdict(list)
            for e in entries:
                groups[int(e.get("unknown_count") or 0)].append(e)
            ordered: List[Dict[str, Any]] = []
            for cnt in sorted(groups.keys(), reverse=True):
                bucket = list(groups[cnt])
                random.shuffle(bucket)
                ordered.extend(bucket)
            chosen = ordered[: min(count, len(ordered))]
        elif priority == "new":
            untested = [e for e in entries if int(e.get("unknown_count") or 0) == 0]
            pool = untested if untested else entries
            chosen = random.sample(pool, min(count, len(pool)))
        else:  # random
            chosen = random.sample(entries, min(count, len(entries)))

        return chosen

    def mark_unknown(self, word: str) -> Dict[str, Any]:
        """标记不认识：次数 +1，若词不存在则追加到文件末尾"""
        with self._lock:
            entries = self._load_entries()
            target_lower = word.lower()
            for e in entries:
                if e.word.lower() == target_lower:
                    e.count += 1
                    self._write_back(entries)
                    self._invalidate_cache()
                    return {
                        "word": e.word,
                        "unknown_count": e.count,
                        "added": False,
                    }
            # 新词：追加到文件末尾
            new_line_idx = self._append_new_word(word, 1)
            self._invalidate_cache()
            return {"word": word, "unknown_count": 1, "added": True, "line_index": new_line_idx}

    def mark_known(self, word: str) -> Dict[str, Any]:
        """标记认识：次数 -1（最低 0）"""
        with self._lock:
            entries = self._load_entries()
            target_lower = word.lower()
            for e in entries:
                if e.word.lower() == target_lower:
                    if e.count > 0:
                        e.count -= 1
                        self._write_back(entries)
                        self._invalidate_cache()
                    return {
                        "word": e.word,
                        "unknown_count": e.count,
                        "added": False,
                    }
            # 词不在生词本里，视为已掌握，不追加
            return {"word": word, "unknown_count": 0, "added": False}

    def remove(self, word: str) -> Dict[str, Any]:
        """完全移除某词（删除文件中该词的所有出现行）。

        与 mark_known（仅递减、保留词条）不同，remove 用于 daily 生词日志的
        复习流转：词一经复习（会/不会）就从当天的待复习记录里划掉，
        不会的词再由 DailyWordLogManager 写入新的日期文件。其他行（含
        用户手写的空行/分组注释）原样保留。
        """
        with self._lock:
            entries = self._load_entries()
            target_lower = word.lower()
            hits = [e for e in entries if e.word.lower() == target_lower]
            if not hits:
                return {"word": word, "removed": False}

            raw_lines = self._read_lines_raw()
            remove_idx = {e.line_index for e in hits}
            new_lines = [ln for i, ln in enumerate(raw_lines) if i not in remove_idx]

            # 原子写回，避免半写状态
            tmp_path = self.file_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.replace(tmp_path, self.file_path)
            self._invalidate_cache()
            return {"word": word, "removed": True}
