"""词汇数据加载与持久化层（解耦自 VocabularyManager）。

职责：
- 解析词典 / 例句 / 进度 / meta 的文件路径
- 懒加载词典、例句索引、进度、meta
- 进度与 meta 的落盘
- 单词 / 例句的基础查询、外部文件导入、词典切换

不含任何复习调度（FSRS/SM-2）、统计或测验业务，仅做数据存取。
"""

import json
import os
import threading
import time
from typing import Dict, List, Optional, Any

from core.utils.logger import get_logger

logger = get_logger("VocabDataStore")

# DataIO 兼容 vocab_tester 的外部文件导入格式
try:
    from core.tools.study.common.data_io import DataIO
except ImportError:
    DataIO = None


def resolve_paths(base_dir: str, dictionary_path: str = None, progress_path: str = None):
    """根据工作区根目录解析各类数据文件路径，返回 dict。"""
    study_data_root = os.path.join(base_dir, "data", "study_data", "English")
    words_dir = os.path.join(study_data_root, "Words")
    sentence_dir = os.path.join(study_data_root, "Sentence")

    if not dictionary_path:
        new_path = os.path.join(words_dir, "CET4-顺序.json")
        dictionary_path = (
            new_path if os.path.exists(new_path)
            else os.path.join(study_data_root, "CET4-顺序.json")
        )

    if not progress_path:
        progress_dir = os.path.join(base_dir, "output", "user_data")
        os.makedirs(progress_dir, exist_ok=True)
        progress_path = os.path.join(progress_dir, "vocab_progress.json")
    else:
        progress_dir = os.path.dirname(progress_path)

    meta_path = os.path.join(os.path.dirname(progress_path), "vocab_meta.json")

    return {
        "study_data_root": study_data_root,
        "words_dir": words_dir,
        "sentence_dir": sentence_dir,
        "dictionary_path": dictionary_path,
        "progress_dir": progress_dir,
        "progress_path": progress_path,
        "meta_path": meta_path,
    }


# 全量释义总表文件名（复习释义兜底，不显示在词书选择列表）
MASTER_FILE = "CET-全量.json"


class VocabDataStore:
    """词汇数据的加载与持久化。"""

    def __init__(self, dictionary_path: str = None, progress_path: str = None):
        # base_dir：本文件所在 core/tools/study/english 向上 5 级即工作区根
        self.base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
        paths = resolve_paths(self.base_dir, dictionary_path, progress_path)
        self.study_data_root = paths["study_data_root"]
        self.words_dir = paths["words_dir"]
        self.sentence_dir = paths["sentence_dir"]
        self.dictionary_path = paths["dictionary_path"]
        self.progress_path = paths["progress_path"]
        self.meta_path = paths["meta_path"]
        # 全量释义总表（复习兜底用）：始终指向 Words 目录下的 CET-全量.json
        self.master_path = os.path.join(self.words_dir, MASTER_FILE)

        os.makedirs(os.path.dirname(self.dictionary_path), exist_ok=True)
        os.makedirs(self.words_dir, exist_ok=True)
        os.makedirs(self.sentence_dir, exist_ok=True)

        # 例句集合（取目录下首个 json）
        self.sentence_path = None
        try:
            if os.path.exists(self.sentence_dir):
                sentence_files = sorted(
                    f for f in os.listdir(self.sentence_dir) if f.endswith(".json")
                )
                if sentence_files:
                    self.sentence_path = os.path.join(
                        self.sentence_dir, sentence_files[0]
                    )
        except Exception:
            self.sentence_path = None

        self._loaded = False
        self._lock = threading.Lock()
        self.dictionary: List[Dict] = []
        self.master: List[Dict] = []
        self.sentences: List[Dict] = []
        self._sentence_index: Dict[str, Dict] = {}
        self.progress: Dict[str, Dict] = {}
        self.meta: Dict[str, Any] = {}

    # ---------------- 加载 ----------------
    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load_data()
            self._loaded = True

    def _load_data(self):
        try:
            if os.path.exists(self.dictionary_path):
                with open(self.dictionary_path, "r", encoding="utf-8") as f:
                    self.dictionary = json.load(f)
                logger.info(
                    f"Loaded {len(self.dictionary)} words from {self.dictionary_path}"
                )
            else:
                logger.warning(
                    f"Dictionary file not found: {self.dictionary_path}. "
                    f"Initializing empty dictionary."
                )
                self.dictionary = []

            # 全量释义总表：复习释义兜底用。与当前词书同文件时直接复用，
            # 否则独立加载（覆盖用户手动记的、不属于当前词书级别的词）。
            if os.path.abspath(self.master_path) == os.path.abspath(self.dictionary_path):
                self.master = self.dictionary
            else:
                self.master = []
                if os.path.exists(self.master_path):
                    try:
                        with open(self.master_path, "r", encoding="utf-8") as f:
                            self.master = json.load(f)
                    except Exception as e:
                        logger.error(f"Failed to load master dictionary: {e}")

            self.sentences = []
            self._sentence_index = {}
            if self.sentence_path and os.path.exists(self.sentence_path):
                try:
                    with open(self.sentence_path, "r", encoding="utf-8") as f:
                        self.sentences = json.load(f)
                    self._sentence_index = {
                        e.get("word", "").lower().strip(): e
                        for e in self.sentences
                        if isinstance(e, dict) and e.get("word")
                    }
                    logger.info(
                        f"Loaded {len(self.sentences)} sentence entries "
                        f"from {self.sentence_path}"
                    )
                except Exception as e:
                    logger.error(f"Failed to load sentence data: {e}")

            if os.path.exists(self.progress_path):
                with open(self.progress_path, "r", encoding="utf-8") as f:
                    self.progress = json.load(f)
                logger.info(f"Loaded progress for {len(self.progress)} words")
            else:
                self.progress = {}

            if os.path.exists(self.meta_path):
                try:
                    with open(self.meta_path, "r", encoding="utf-8") as f:
                        self.meta = json.load(f)
                except Exception:
                    self.meta = {}
            else:
                self.meta = {}
        except Exception as e:
            logger.error(f"Failed to load vocabulary data: {e}")

    # ---------------- 持久化 ----------------
    def save_progress(self):
        try:
            with open(self.progress_path, "w", encoding="utf-8") as f:
                json.dump(self.progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save vocabulary progress: {e}")
        try:
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(self.meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save vocabulary meta: {e}")

    # ---------------- 只读统计辅助（不触发全量加载）----------------
    def get_word_count_from_file(self) -> int:
        try:
            if not os.path.exists(self.dictionary_path):
                return 0
            with open(self.dictionary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return len(data) if isinstance(data, list) else 0
        except Exception:
            return 0

    def get_progress_stats(self) -> Dict[str, int]:
        try:
            if not os.path.exists(self.progress_path):
                return {"learned": 0, "due": 0, "mastered": 0}
            with open(self.progress_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
            now = time.time()
            learned = len(progress)
            due = sum(1 for d in progress.values() if d.get("next_review", 0) <= now)
            mastered = sum(1 for d in progress.values() if d.get("interval", 0) > 21)
            return {"learned": learned, "due": due, "mastered": mastered}
        except Exception:
            return {"learned": 0, "due": 0, "mastered": 0}

    # ---------------- 查询 ----------------
    def get_word_info(self, word: str) -> Optional[Dict]:
        self._ensure_loaded()
        target = str(word or "").strip()
        if not target:
            return None
        for entry in self.dictionary:
            if entry["word"] == target:
                return entry
        target_lower = target.lower()
        for entry in self.dictionary:
            if str(entry.get("word", "")).strip().lower() == target_lower:
                return entry
        # 当前词书未收录时回退到全量释义总表：用户手动记的词可能属于
        # 其他级别（如六级/考研词在四级书里），保证复习时都能查到释义。
        if self.master is not self.dictionary:
            for entry in self.master:
                if entry.get("word") == target:
                    return entry
            for entry in self.master:
                if str(entry.get("word", "")).strip().lower() == target_lower:
                    return entry
        return None

    def get_sentence_info(self, word: str) -> Optional[Dict]:
        self._ensure_loaded()
        return self._sentence_index.get(word.lower().strip())

    def get_definition(self, word: str) -> Optional[List[Dict[str, str]]]:
        self._ensure_loaded()
        word = word.lower().strip()
        for item in self.dictionary:
            if item.get("word", "").lower() == word:
                return item.get("translations", [])
        # 同 get_word_info：当前词书查不到时回退全量释义总表
        if self.master is not self.dictionary:
            for item in self.master:
                if item.get("word", "").lower() == word:
                    return item.get("translations", [])
        return None

    # ---------------- 导入 / 切换 ----------------
    def import_from_file(self, file_path: str) -> int:
        self._ensure_loaded()
        if not DataIO:
            logger.warning("DataIO not available, cannot import external files")
            return 0
        try:
            data = DataIO.import_data(file_path)
            if not data:
                return 0

            new_words = []
            for item in data:
                if isinstance(item, dict):
                    word = item.get("单词") or item.get("word")
                    meaning = (
                        item.get("中文释义")
                        or item.get("meaning")
                        or item.get("translation")
                    )
                    pos = item.get("词性", "") or item.get("pos", "")
                    if word and meaning:
                        new_words.append(
                            {
                                "word": str(word).strip(),
                                "translations": [
                                    {
                                        "type": str(pos).strip(),
                                        "translation": str(meaning).strip(),
                                    }
                                ],
                            }
                        )

            existing_words = {w["word"] for w in self.dictionary}
            count = 0
            for w in new_words:
                if w["word"] not in existing_words:
                    self.dictionary.append(w)
                    existing_words.add(w["word"])
                    count += 1

            if count > 0:
                logger.info(f"Imported {count} new words from {file_path}")
            return count
        except Exception as e:
            logger.error(f"Failed to import data: {e}")
            return 0

    def switch_dictionary(self, filename: str, is_sentence: bool = False) -> bool:
        self._ensure_loaded()
        if is_sentence:
            possible_paths = [
                os.path.join(self.sentence_dir, filename),
                os.path.join(self.study_data_root, filename),
            ]
        else:
            possible_paths = [
                os.path.join(self.words_dir, filename),
                os.path.join(self.study_data_root, filename),
            ]
        for target_path in possible_paths:
            if os.path.exists(target_path):
                if is_sentence:
                    self.sentence_path = target_path
                else:
                    self.dictionary_path = target_path
                self._load_data()
                return True
        return False
