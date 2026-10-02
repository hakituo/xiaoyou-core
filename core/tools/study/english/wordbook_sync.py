"""词书增量补录：把 daily/生词本里出现但词书未收录的词补进 CET-全量.json。

分级词书（CET4/6、考研、托福、雅思、GRE）只收带考试标签的 ECDICT 词条，
用户手动记录到 daily/YYYY/MM/DD.txt 或生词本里的词可能没有这些标签，
完整重建词书前它们在 App 里会显示「词库未收录」。

本模块在运行时按需只扫一遍 ECDICT（流式、只保留目标词行），把缺失词按
``wordbook_builder._build_entry`` 的同一套释义解析补进全量词书，避免为了
几个词整体重建 77 万行词表。
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from core.utils.logger import get_logger

logger = get_logger("VocabWordbookSync")

# 两次补录之间的最小间隔，避免频繁编辑 daily 文件时反复扫描 ECDICT
_MIN_INTERVAL_SECONDS = 300

_lock = threading.Lock()
_running = False
_last_run_ts = 0.0
_pending: Set[str] = set()


def _import_builder():
    """延迟导入构建期模块（避免启动期就把脚本包拉进来）。"""
    from scripts.study.vocabulary.wordbook_builder import (  # noqa: WPS433
        DEFAULT_ECDICT_PATH,
        MASTER_FILE,
        _build_entry,
        _clean_word,
    )

    return DEFAULT_ECDICT_PATH, MASTER_FILE, _build_entry, _clean_word


def _resolve_master_path(master_path: Optional[Path], master_file: str) -> Path:
    if master_path is not None:
        return Path(master_path)
    project_root = Path(__file__).resolve().parents[4]
    return project_root / "data" / "study_data" / "English" / "Words" / master_file


def _load_master_entries(path: Path) -> Optional[List[Dict[str, Any]]]:
    """读取全量词书；读取失败返回 None（此时不应覆盖原文件）。"""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning(f"读取全量词书失败，跳过补录: {exc}")
        return None  # type: ignore[return-value]
    return data if isinstance(data, list) else []


def _write_master_entries(path: Path, entries: List[Dict[str, Any]]) -> None:
    """原子写回全量词书，避免半写状态。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def collect_missing_entries(
    words: Iterable[str],
    ecdict_path: Optional[Path] = None,
    master_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """流式扫描 ECDICT，返回词书尚未收录的目标词条。"""
    try:
        default_ecdict, master_file, build_entry, clean_word = _import_builder()
    except Exception as exc:  # 构建脚本缺失/ECDICT 未部署时静默降级
        logger.warning(f"词书补录依赖不可用，跳过: {exc}")
        return []

    targets = {clean_word(word) for word in words if clean_word(word)}
    if not targets:
        return []

    master_file_path = _resolve_master_path(master_path, master_file)
    existing = _load_master_entries(master_file_path)
    if existing is None:
        return []
    known = {
        clean_word(entry.get("word"))
        for entry in existing
        if isinstance(entry, dict) and clean_word(entry.get("word"))
    }
    targets -= known
    if not targets:
        return []

    ecdict_file = Path(ecdict_path or default_ecdict)
    if not ecdict_file.exists():
        logger.warning(f"ECDICT 数据不存在，无法补录词书: {ecdict_file}")
        return []

    entries: List[Dict[str, Any]] = []
    found: Set[str] = set()
    try:
        with ecdict_file.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                word = clean_word(row.get("word"))
                if not word or word not in targets:
                    continue
                entry, _ = build_entry(row, {}, None, None)
                entries.append(entry)
                found.add(word)
                if found == targets:
                    break
    except OSError as exc:
        logger.warning(f"扫描 ECDICT 失败，跳过词书补录: {exc}")
        return []
    return entries


def sync_words(
    words: Iterable[str],
    ecdict_path: Optional[Path] = None,
    master_path: Optional[Path] = None,
    store: Any = None,
) -> List[str]:
    """同步补录缺失词到全量词书，返回实际补录的词头。"""
    entries = collect_missing_entries(words, ecdict_path, master_path)
    if not entries:
        return []

    try:
        _, master_file, _, _ = _import_builder()
    except Exception as exc:
        logger.warning(f"词书补录依赖不可用，跳过: {exc}")
        return []

    master_file_path = _resolve_master_path(master_path, master_file)
    existing = _load_master_entries(master_file_path)
    if existing is None:
        return []
    merged = existing + entries
    try:
        _write_master_entries(master_file_path, merged)
    except OSError as exc:
        logger.warning(f"写入全量词书失败: {exc}")
        return []

    added = [str(entry.get("word", "")).strip() for entry in entries]
    # 同步刷新内存里的兜底词表，避免必须重启进程才能查到释义
    if store is not None:
        try:
            store.master = merged
        except Exception:  # store 结构变化时不影响主流程
            pass
    logger.info(f"已把 {len(added)} 个用户词补进 {master_file_path.name}: {added}")
    return added


def sync_user_words_async(words: Iterable[str], store: Any = None) -> None:
    """后台补录缺失词；短时间内重复触发会合并到下一次执行。"""
    global _running, _last_run_ts

    targets = {str(word or "").strip().lower() for word in words if str(word or "").strip()}
    if not targets:
        return

    with _lock:
        if _running:
            _pending.update(targets)
            return
        if time.monotonic() - _last_run_ts < _MIN_INTERVAL_SECONDS:
            _pending.update(targets)
            return
        _running = True

    def _worker() -> None:
        global _running, _last_run_ts
        try:
            current = set(targets)
            while True:
                sync_words(current, store=store)
                with _lock:
                    current = set(_pending)
                    _pending.clear()
                if not current:
                    break
        except Exception as exc:
            logger.warning(f"后台补录用户词失败: {exc}")
        finally:
            with _lock:
                _running = False
                _last_run_ts = time.monotonic()

    threading.Thread(
        target=_worker,
        name="vocab-wordbook-sync",
        daemon=True,
    ).start()
