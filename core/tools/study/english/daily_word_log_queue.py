"""daily_word_log 的最终复习队列（混入 DailyWordLogManager）。

从 ``core/tools/study/english/daily_word_log.py`` 拆出：把 daily 批次与
FSRS 到期词合并成「当天已锁定的最终队列」，并在用户手动编辑后同步新词。

⚠️ 模块级 patch 语义：历史测试会 patch 门面模块的 ``safe_json_dump`` /
``safe_json_load`` / ``get_current_time_str``，因此这些名字必须在调用期
从门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.tools.study.english import daily_word_log as _facade
from core.utils.logger import get_logger

logger = get_logger("DailyWordLog")


class DailyWordLogQueueMixin:
    """当天最终复习队列的读取、锁定与同步。"""

    def _normalize_review_queue_entries(
        self,
        entries: Any,
    ) -> List[Dict[str, Any]]:
        """规范化持久化的最终队列条目。"""
        if not isinstance(entries, list):
            return []
        result: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            word = str(entry.get("word") or "").strip()
            source = str(entry.get("review_source") or "").strip()
            key = word.lower()
            if not word or key in seen:
                continue
            if source not in {"daily_backlog", "fsrs"}:
                continue
            result.append(
                {
                    "word": word,
                    "review_source": source,
                    "source_date": self._normalize_date(
                        entry.get("source_date", "")
                    )
                    or None,
                }
            )
            seen.add(key)
        return result

    def get_persisted_review_queue(self) -> Optional[List[Dict[str, Any]]]:
        """读取今天已经锁定的最终合并复习队列；尚未领取时返回 None。"""
        today_str = self._normalize_date(self._get_today_str())
        with self._review_state_lock:
            state = _facade.safe_json_load(self._review_queue_state_path, default={})
        if not isinstance(state, dict) or state.get("version") != 5:
            return None
        if state.get("review_date") != today_str:
            return None
        return self._normalize_review_queue_entries(state.get("entries"))

    def persist_review_queue(
        self,
        entries: List[Dict[str, Any]],
        batch_size: int,
    ) -> List[Dict[str, Any]]:
        """首次原子锁定今天的最终合并队列，并返回权威条目。"""
        existing = self.get_persisted_review_queue()
        if existing is not None:
            return existing

        today_str = self._normalize_date(self._get_today_str())
        normalized: List[Dict[str, Any]] = []
        seen: set[str] = set()
        safe_batch_size = max(0, int(batch_size or 0))
        selected_entries = entries[:safe_batch_size] if safe_batch_size else entries
        for entry in selected_entries:
            word = str(entry.get("word") or "").strip()
            source = str(entry.get("review_source") or "").strip()
            key = word.lower()
            if not word or key in seen:
                continue
            if source not in {"daily_backlog", "fsrs"}:
                continue
            normalized.append(
                {
                    "word": word,
                    "review_source": source,
                    "source_date": self._normalize_date(
                        entry.get("source_date", "")
                    )
                    or None,
                }
            )
            seen.add(key)

        with self._review_state_lock:
            # 另一线程可能在上一次读取后先完成写入；写前再核对一次。
            state = _facade.safe_json_load(self._review_queue_state_path, default={})
            if (
                isinstance(state, dict)
                and state.get("version") == 5
                and state.get("review_date") == today_str
                and isinstance(state.get("entries"), list)
            ):
                return self._normalize_review_queue_entries(state.get("entries"))
            try:
                _facade.safe_json_dump(
                    {
                        "version": 5,
                        "review_date": today_str,
                        "batch_size": safe_batch_size,
                        "entries": normalized,
                        "selected_at": _facade.get_current_time_str(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    },
                    self._review_queue_state_path,
                )
            except OSError as exc:
                logger.warning(f"持久化 daily 最终复习队列失败: {exc}")
        return normalized

    def sync_review_queue(
        self,
        entries: List[Dict[str, Any]],
        batch_size: int = 0,
    ) -> List[Dict[str, Any]]:
        """返回今天的最终复习队列；已锁定时同步 daily 侧新增候选。

        ``get_review_batch`` 感知到用户手动编辑后会把新词补进当天批次，
        这里再把这批新词同步进最终队列，保证当天推送能覆盖手加的词。
        已完成项（不再出现在候选里）保留在队列中，由上层按候选过滤掉。
        """
        existing = self.get_persisted_review_queue()
        if existing is None:
            return self.persist_review_queue(entries, batch_size)

        current_by_word: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            word = str(entry.get("word") or "").strip()
            source = str(entry.get("review_source") or "").strip()
            if not word or source not in {"daily_backlog", "fsrs"}:
                continue
            current_by_word.setdefault(
                word.lower(),
                {
                    "word": word,
                    "review_source": source,
                    "source_date": self._normalize_date(
                        entry.get("source_date", "")
                    )
                    or None,
                },
            )

        merged: List[Dict[str, Any]] = []
        locked_keys: set[str] = set()
        changed = False
        for item in existing:
            key = item["word"].lower()
            locked_keys.add(key)
            current = current_by_word.get(key)
            if (
                current is not None
                and current["review_source"] != item["review_source"]
            ):
                # 来源从 daily 补漏变成 FSRS 到期（或反之）：同步最新来源，
                # 保持队列位置不变，避免该词因来源漂移被静默跳过。
                merged.append(current)
                changed = True
            else:
                merged.append(item)

        added = [
            item
            for key, item in current_by_word.items()
            if key not in locked_keys and item["review_source"] == "daily_backlog"
        ]
        if added:
            inserted = False
            for index in range(len(merged) - 1, -1, -1):
                if merged[index]["review_source"] == "daily_backlog":
                    merged[index + 1 : index + 1] = added
                    inserted = True
                    break
            if not inserted:
                merged = added + merged
            changed = True

        if changed:
            self._write_review_queue_state(merged, batch_size)
        return merged

    def _write_review_queue_state(
        self,
        entries: List[Dict[str, Any]],
        batch_size: int,
    ) -> None:
        """覆写今天已锁定的最终队列（仅在同步新增候选时使用）。"""
        today_str = self._normalize_date(self._get_today_str())
        safe_batch_size = max(0, int(batch_size or 0))
        with self._review_state_lock:
            state = _facade.safe_json_load(self._review_queue_state_path, default={})
            if (
                isinstance(state, dict)
                and state.get("version") == 5
                and state.get("review_date") == today_str
                and self._normalize_review_queue_entries(state.get("entries"))
                == entries
            ):
                return
            try:
                _facade.safe_json_dump(
                    {
                        "version": 5,
                        "review_date": today_str,
                        "batch_size": safe_batch_size,
                        "entries": entries,
                        "selected_at": _facade.get_current_time_str("%Y-%m-%d %H:%M:%S"),
                    },
                    self._review_queue_state_path,
                )
            except OSError as exc:
                logger.warning(f"同步 daily 最终复习队列失败: {exc}")
