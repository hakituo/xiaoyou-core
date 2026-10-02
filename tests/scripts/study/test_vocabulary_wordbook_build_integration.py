# -*- coding: utf-8 -*-
"""构建级回归：真实走临时 ECDICT CSV -> build_wordbooks。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.study.vocabulary.wordbook_builder import build_wordbooks


ECDICT_FIELDS = [
    "word",
    "phonetic",
    "definition",
    "translation",
    "pos",
    "collins",
    "oxford",
    "tag",
    "bnc",
    "frq",
    "exchange",
    "detail",
    "audio",
]


def _write_fixture(path: Path) -> None:
    rows = [
        {
            "word": "perspective",
            "phonetic": "pə'spektiv",
            "translation": "n. 远景\nn. 透视；透视法\nn. 观点；视角",
            "pos": "n:100",
            "tag": "cet4",
            "bnc": "3000",
            "frq": "2500",
        },
        {
            "word": "unrankedfixture",
            "phonetic": "",
            "translation": "n. 原始第一义\nn. 原始第二义",
            "pos": "n:100",
            "tag": "cet4",
            "bnc": "0",
            "frq": "0",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ECDICT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _find(entries: list[dict], word: str) -> dict:
    return next(entry for entry in entries if entry["word"] == word)


def test_wordbook_build_is_deterministic_and_applies_ranking(tmp_path: Path) -> None:
    ecdict = tmp_path / "ecdict.csv"
    words_dir = tmp_path / "Words"
    sentence_dir = tmp_path / "Sentence"
    progress = tmp_path / "missing_progress.json"
    overrides = tmp_path / "missing_overrides.json"
    _write_fixture(ecdict)

    kwargs = {
        "ecdict_path": ecdict,
        "words_dir": words_dir,
        "sentence_dir": sentence_dir,
        "overrides_path": overrides,
        "progress_path": progress,
    }
    first_books, first_report = build_wordbooks(**kwargs)
    second_books, second_report = build_wordbooks(**kwargs)

    # 整个构建结果和 report 都必须可重复，而不是只验证单个排序函数。
    assert json.dumps(first_books, ensure_ascii=False, sort_keys=True) == json.dumps(
        second_books, ensure_ascii=False, sort_keys=True
    )
    assert first_report == second_report

    master = first_books["CET-全量.json"]
    perspective = _find(master, "perspective")
    assert [item["translation"] for item in perspective["translations"]] == [
        "观点；视角",
        "透视；透视法",
        "远景",
    ]

    # 没有 ranking 数据的词仍严格保留 source dictionary order。
    unranked = _find(master, "unrankedfixture")
    assert [item["translation"] for item in unranked["translations"]] == [
        "原始第一义",
        "原始第二义",
    ]
