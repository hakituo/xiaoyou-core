"""基于 ECDICT 可复现地生成分级英语词书。

本模块只负责数据构建，不参与运行时词书加载。例句库可以提供例句、短语与
英美音标等展示字段，但其 ``translations`` 字段不会进入词书释义。
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ECDICT_PATH = PROJECT_ROOT / "external" / "ECDICT-master" / "ecdict.csv"
DEFAULT_WORDS_DIR = (
    PROJECT_ROOT / "data" / "study_data" / "English" / "Words"
)
DEFAULT_SENTENCE_DIR = (
    PROJECT_ROOT / "data" / "study_data" / "English" / "Sentence"
)
DEFAULT_OVERRIDES_PATH = (
    PROJECT_ROOT / "config" / "study" / "vocabulary_sense_overrides.json"
)
DEFAULT_PROGRESS_PATH = PROJECT_ROOT / "output" / "user_data" / "vocab_progress.json"

MASTER_FILE = "CET-全量.json"
BOOK_TAGS: OrderedDict[str, frozenset[str]] = OrderedDict(
    [
        ("CET4-顺序.json", frozenset({"zk", "gk", "cet4"})),
        ("CET6-顺序.json", frozenset({"zk", "gk", "cet4", "cet6"})),
        ("考研-顺序.json", frozenset({"zk", "gk", "cet4", "cet6", "ky"})),
        ("托福-顺序.json", frozenset({"zk", "gk", "cet4", "cet6", "toefl"})),
        ("雅思-顺序.json", frozenset({"zk", "gk", "cet4", "cet6", "ielts"})),
        ("GRE-顺序.json", frozenset({"zk", "gk", "cet4", "cet6", "gre"})),
    ]
)
ALL_EXAM_TAGS = frozenset().union(*BOOK_TAGS.values())

# 仅识别 ECDICT 中确认属于学科、语域或专名的行首标签。
# 不能把任意 ``[...]`` 都当标签，否则会误伤 ``[无芽胞]杆菌`` 等释义正文。
DOMAIN_LABELS = frozenset(
    {
        "医",
        "计",
        "法",
        "化",
        "经",
        "机",
        "电",
        "建",
        "乐",
        "植",
        "古",
        "动",
        "人名",
        "俚",
        "物",
        "眼科",
        "生态",
        "律",
        "表",
        "地",
        "口",
    }
)
POS_PREFIX_RE = re.compile(
    r"^(?P<pos>vt|vi|adj|adv|prep|conj|pron|art|num|int|abbr|aux|n|v|a)\.\s*",
    re.IGNORECASE,
)
DOMAIN_PREFIX_RE = re.compile(r"^\[([^]]+)]\s*")
ENRICHMENT_FIELDS = ("sentences", "phrases", "us", "uk", "audio")


def _clean_word(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _split_translation_lines(raw: Any) -> list[str]:
    """同时兼容真实换行和 CSV 中字面量 ``\\n`` / ``\\r``。"""
    text = str(raw or "").replace("\\r", "").replace("\r", "")
    return [line.strip() for line in re.split(r"\\n|\n", text) if line.strip()]


def _normalize_pos(value: str) -> str:
    pos = value.strip().lower()
    return "adj" if pos == "a" else pos


def _deduplicate_translations(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for item in items:
        translation = str(item.get("translation", "")).strip()
        if not translation:
            continue
        normalized = {
            "type": _normalize_pos(str(item.get("type", ""))),
            "translation": translation,
        }
        domains = tuple(str(value).strip() for value in item.get("domains", []) if value)
        if domains:
            normalized["domains"] = list(domains)
        if item.get("primary"):
            normalized["primary"] = True
        key = (normalized["type"], translation, domains)
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def parse_translations(
    raw: Any,
    override: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """解析 ECDICT 中文释义并分离普通义与专业/扩展义。

    返回 ``(普通释义, 扩展释义, 是否发生全专业义回退)``。如果某词只有带
    领域标签的释义，为避免生成空卡片，会把这些释义保留在普通区，同时保留
    ``domains`` 元数据。
    """
    general: list[dict[str, Any]] = []
    extended: list[dict[str, Any]] = []
    for raw_line in _split_translation_lines(raw):
        line = raw_line
        pos = ""
        pos_match = POS_PREFIX_RE.match(line)
        if pos_match:
            pos = _normalize_pos(pos_match.group("pos"))
            line = line[pos_match.end() :].strip()

        domains: list[str] = []
        while True:
            domain_match = DOMAIN_PREFIX_RE.match(line)
            if not domain_match or domain_match.group(1) not in DOMAIN_LABELS:
                break
            domains.append(domain_match.group(1))
            line = line[domain_match.end() :].strip()

        # ECDICT 还用方括号表示可省略构词片段，如“适应[作用]”“[方]法”。
        # 领域标签已经在上面结构化提取，此处只移除括号字符并保留括号内文字。
        line = line.replace("[", "").replace("]", "").strip()
        if not line:
            continue
        item: dict[str, Any] = {"type": pos, "translation": line}
        if domains:
            item["domains"] = domains
            extended.append(item)
        else:
            general.append(item)

    override = override or {}
    primary_items = [
        {**item, "primary": True}
        for item in override.get("primary_translations", [])
        if isinstance(item, dict)
    ]
    if override.get("replace_general"):
        general = []
    if override.get("collapse_source_translations") and primary_items:
        extended = [*general, *extended]
        general = []
    general = _deduplicate_translations([*primary_items, *general])
    extended = _deduplicate_translations(extended)

    domain_only_fallback = False
    if not general and extended:
        general = extended
        extended = []
        domain_only_fallback = True
    return general, extended, domain_only_fallback


def load_overrides(path: Path = DEFAULT_OVERRIDES_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("version") != 1 or not isinstance(payload.get("words"), dict):
        raise ValueError(f"义项覆盖文件结构无效: {path}")
    return {
        _clean_word(word): data
        for word, data in payload["words"].items()
        if _clean_word(word) and isinstance(data, dict)
    }


def load_ecdict_rows(path: Path = DEFAULT_ECDICT_PATH) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"ECDICT 数据不存在: {path}")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            word = _clean_word(row.get("word"))
            if not word or word in seen:
                continue
            seen.add(word)
            rows.append(row)
    return rows


def _merge_enrichment(
    target: dict[str, dict[str, Any]],
    entries: Iterable[dict[str, Any]],
) -> None:
    for entry in entries:
        word = _clean_word(entry.get("word"))
        if not word:
            continue
        current = target.setdefault(word, {})
        for field in ENRICHMENT_FIELDS:
            value = entry.get(field)
            if value not in (None, "", []) and current.get(field) in (None, "", []):
                current[field] = value


def load_enrichment(
    words_dir: Path = DEFAULT_WORDS_DIR,
    sentence_dir: Path = DEFAULT_SENTENCE_DIR,
) -> dict[str, dict[str, Any]]:
    """读取既有展示元数据，明确忽略所有来源的 ``translations``。"""
    enrichment: dict[str, dict[str, Any]] = {}
    preferred_word_files = [words_dir / MASTER_FILE]
    preferred_word_files.extend(words_dir / name for name in BOOK_TAGS)
    for path in preferred_word_files:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            _merge_enrichment(enrichment, payload)

    if sentence_dir.exists():
        for path in sorted(sentence_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, list):
                _merge_enrichment(enrichment, payload)
    return enrichment


def _parse_word_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    parts = stripped.rsplit(None, 1)
    if len(parts) == 2 and parts[1].isdigit():
        return _clean_word(parts[0])
    return _clean_word(stripped)


def collect_user_words(
    words_dir: Path = DEFAULT_WORDS_DIR,
    progress_path: Path = DEFAULT_PROGRESS_PATH,
) -> set[str]:
    """收集进度、daily 和 unfamiliar 中出现过的词头。"""
    words: set[str] = set()
    if progress_path.exists():
        with progress_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            words.update(_clean_word(word) for word in payload if _clean_word(word))

    text_files = [words_dir / "unfamiliar_word.txt"]
    daily_dir = words_dir / "daily"
    if daily_dir.exists():
        text_files.extend(sorted(daily_dir.rglob("*.txt")))
    for path in text_files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            word = _parse_word_line(line)
            if word:
                words.add(word)
    return words


def _build_entry(
    row: dict[str, str],
    enrichment: dict[str, Any],
    override: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    translations, extended, domain_only_fallback = parse_translations(
        row.get("translation", ""), override
    )
    entry: dict[str, Any] = {
        "word": str(row.get("word", "")).strip(),
        "phonetic": str(row.get("phonetic", "")).strip(),
        "translations": translations,
        "pos": str(row.get("pos", "")).strip(),
        "collins": _to_int(row.get("collins")),
        "oxford": _to_int(row.get("oxford")),
        "bnc": _to_int(row.get("bnc")),
        "frq": _to_int(row.get("frq")),
        "tags": sorted(set(str(row.get("tag", "")).split())),
        "audio": str(row.get("audio", "")).strip(),
    }
    if extended:
        entry["extended_translations"] = extended
    for field in ENRICHMENT_FIELDS:
        value = enrichment.get(field)
        if value not in (None, "", []) and entry.get(field) in (None, "", []):
            entry[field] = value
    return entry, domain_only_fallback


def build_wordbooks(
    ecdict_path: Path = DEFAULT_ECDICT_PATH,
    words_dir: Path = DEFAULT_WORDS_DIR,
    sentence_dir: Path = DEFAULT_SENTENCE_DIR,
    overrides_path: Path = DEFAULT_OVERRIDES_PATH,
    progress_path: Path = DEFAULT_PROGRESS_PATH,
) -> tuple[OrderedDict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows = load_ecdict_rows(ecdict_path)
    overrides = load_overrides(overrides_path)
    enrichment = load_enrichment(words_dir, sentence_dir)
    user_words = collect_user_words(words_dir, progress_path)
    row_words = {_clean_word(row.get("word")) for row in rows}
    tagged_words = {
        _clean_word(row.get("word"))
        for row in rows
        if set(str(row.get("tag", "")).split()) & ALL_EXAM_TAGS
    }
    extra_words = sorted((user_words & row_words) - tagged_words)
    master_words = tagged_words | set(extra_words)

    entry_by_word: dict[str, dict[str, Any]] = {}
    domain_only_fallback_count = 0
    for row in rows:
        word = _clean_word(row.get("word"))
        if word not in master_words:
            continue
        entry, fallback = _build_entry(
            row,
            enrichment.get(word, {}),
            overrides.get(word),
        )
        entry_by_word[word] = entry
        domain_only_fallback_count += int(fallback)

    books: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    books[MASTER_FILE] = [
        entry_by_word[_clean_word(row.get("word"))]
        for row in rows
        if _clean_word(row.get("word")) in master_words
    ]
    for filename, accepted_tags in BOOK_TAGS.items():
        books[filename] = [
            entry_by_word[_clean_word(row.get("word"))]
            for row in rows
            if set(str(row.get("tag", "")).split()) & accepted_tags
        ]

    master = books[MASTER_FILE]
    report = {
        "source_rows": len(rows),
        "extra_words": extra_words,
        "book_counts": {name: len(entries) for name, entries in books.items()},
        "primary_words": sorted(
            entry["word"]
            for entry in master
            if any(item.get("primary") for item in entry.get("translations", []))
        ),
        "entries_with_extended_translations": sum(
            bool(entry.get("extended_translations")) for entry in master
        ),
        "extended_translation_rows": sum(
            len(entry.get("extended_translations", [])) for entry in master
        ),
        "domain_only_fallback_words": domain_only_fallback_count,
        "entries_without_translation": sum(
            not entry.get("translations") for entry in master
        ),
    }
    return books, report


def write_wordbooks(
    books: OrderedDict[str, list[dict[str, Any]]],
    output_dir: Path,
    backup_dir: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
    for filename, entries in books.items():
        target = output_dir / filename
        if backup_dir is not None and target.exists():
            shutil.copy2(target, backup_dir / filename)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(entries, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, target)
