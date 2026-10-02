# -*- coding: utf-8 -*-
"""验证 ECDICT 词书可复现生成、释义分层与 Android 字段接入。"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.study.vocabulary.wordbook_builder import (  # noqa: E402
    BOOK_TAGS,
    MASTER_FILE,
    build_wordbooks,
    load_enrichment,
)


EXPECTED_COUNTS = {
    "CET4-顺序.json": 5361,
    "CET6-顺序.json": 7116,
    "考研-顺序.json": 7422,
    "托福-顺序.json": 10528,
    "雅思-顺序.json": 8518,
    "GRE-顺序.json": 12585,
}
PRIMARY_WORDS = {"a", "account", "address", "conduct", "issue"}


def _check_counts_and_uniqueness(
    books: dict[str, list[dict]], problems: list[str]
) -> None:
    for filename, expected in EXPECTED_COUNTS.items():
        entries = books.get(filename, [])
        if len(entries) != expected:
            problems.append(f"{filename} 数量应为 {expected}，实际 {len(entries)}")
        words = [str(entry.get("word", "")).lower() for entry in entries]
        if len(words) != len(set(words)):
            problems.append(f"{filename} 存在重复词头")

    master = books.get(MASTER_FILE, [])
    master_words = {str(entry.get("word", "")).lower() for entry in master}
    for filename in BOOK_TAGS:
        level_words = {
            str(entry.get("word", "")).lower() for entry in books.get(filename, [])
        }
        if not level_words <= master_words:
            problems.append(f"{filename} 有词头未进入全量释义总表")


def _check_translation_contract(
    books: dict[str, list[dict]], problems: list[str]
) -> None:
    master = books[MASTER_FILE]
    by_word = {str(entry["word"]).lower(): entry for entry in master}
    for entry in master:
        all_translations = [
            *entry.get("translations", []),
            *entry.get("extended_translations", []),
        ]
        if not entry.get("translations"):
            problems.append(f"{entry['word']} 普通释义为空")
        for translation in all_translations:
            text = str(translation.get("translation", ""))
            if "\\r" in text or "\r" in text:
                problems.append(f"{entry['word']} 残留回车转义")
            if re.match(r"^[it]\.\s", text):
                problems.append(f"{entry['word']} 仍把 vt/vi 残片写入释义")
            if "[" in text or "]" in text:
                problems.append(f"{entry['word']} 释义正文仍有未结构化方括号")

    primary_words = {
        word
        for word, entry in by_word.items()
        if any(item.get("primary") for item in entry.get("translations", []))
    }
    if primary_words != PRIMARY_WORDS:
        problems.append(
            f"人工主释义词应为 {sorted(PRIMARY_WORDS)}，实际 {sorted(primary_words)}"
        )

    a_entry = by_word.get("a", {})
    if not any(item.get("type") == "art" for item in a_entry.get("translations", [])):
        problems.append("a 缺少人工核对的冠词主释义")
    if not any(
        "计" in item.get("domains", [])
        for item in a_entry.get("extended_translations", [])
    ):
        problems.append("a 的计算机缩写义未进入扩展释义")
    if not any(
        item.get("type") == "vt" for item in by_word["abandon"].get("translations", [])
    ):
        problems.append("abandon 的 vt 词性未正确保留")


def _check_sentence_translation_isolation(problems: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="vocab_sentence_isolation_") as temp:
        root = Path(temp)
        words_dir = root / "Words"
        sentence_dir = root / "Sentence"
        words_dir.mkdir()
        sentence_dir.mkdir()
        sentence_payload = [
            {
                "word": "example",
                "translations": [
                    {"type": "n", "translation": "不得进入词书的例句附属释义"}
                ],
                "sentences": [
                    {"sentence": "An example.", "translation": "一个例子。"}
                ],
            }
        ]
        (sentence_dir / "CET4_2.json").write_text(
            json.dumps(sentence_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        enrichment = load_enrichment(words_dir, sentence_dir)
        example = enrichment.get("example", {})
        if "translations" in example:
            problems.append("Sentence translations 泄漏进词书 enrichment")
        if not example.get("sentences"):
            problems.append("Sentence 例句字段未被保留")


def _check_android_static_contract(problems: list[str]) -> None:
    study_dir = (
        PROJECT_ROOT
        / "clients"
        / "frontend"
        / "aveline-android"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "aveline"
        / "ai"
        / "mobile"
        / "presentation"
        / "study"
    )
    model_text = (study_dir / "StudyViewModel.kt").read_text(encoding="utf-8")
    manager_text = (study_dir / "StudyVocabReviewManager.kt").read_text(
        encoding="utf-8"
    )
    review_text = (study_dir / "StudyVocabReview.kt").read_text(encoding="utf-8")
    required = {
        "Android model primary 字段": "val primary: Boolean = false" in model_text,
        "Android model 扩展释义字段": "val extendedTranslations:" in model_text,
        "Android 解析扩展释义": 'parseTranslations("extended_translations")'
        in manager_text,
        "Android 主释义加粗": "translation.primary" in review_text,
        "Android 扩展释义折叠": "showExtendedTranslations" in review_text,
    }
    problems.extend(name for name, passed in required.items() if not passed)


def main() -> int:
    problems: list[str] = []
    books, report = build_wordbooks()
    _check_counts_and_uniqueness(books, problems)
    _check_translation_contract(books, problems)
    _check_sentence_translation_isolation(problems)
    _check_android_static_contract(problems)

    if report.get("entries_without_translation"):
        problems.append(
            f"全量表存在 {report['entries_without_translation']} 个无普通释义词头"
        )
    if report.get("entries_with_extended_translations", 0) <= 0:
        problems.append("没有生成任何扩展释义")

    if problems:
        print("验证失败：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("验证通过：词量、唯一性、vt/vi、主释义、扩展义、例句隔离及 Android 接入均正常")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
