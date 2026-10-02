"""daily_word_log 的待复习判定与批次生成（混入 DailyWordLogManager）。

从 ``core/tools/study/english/daily_word_log.py`` 拆出。本模块负责：
- 复习事件判定（``_latest_review_event`` / ``_pending_reason`` / ``_is_pending_for_review``）
- 当天固定批次的领取、过滤与扫描（``get_review_batch`` / ``_scan_review_entries`` 等）

⚠️ 模块级 patch 语义：历史测试会 patch 门面模块的 ``safe_json_load``、
``get_current_time``（``test_daily_word_log.py`` 的 ``_patch_today``），
因此这些名字必须在调用期从门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from core.tools.study.english import daily_word_log as _facade


class DailyWordLogReviewMixin:
    """历史 daily 记录的待复习判定与当天批次生成。"""

    @staticmethod
    def _latest_review_event(progress_data: Any) -> Optional[Dict[str, Any]]:
        """返回某词最后一次带有效时间戳的复习事件。"""
        if not isinstance(progress_data, dict):
            return None
        latest: Optional[tuple[float, Dict[str, Any]]] = None
        for item in progress_data.get("history", []):
            if not isinstance(item, dict):
                continue
            try:
                timestamp = float(item.get("timestamp", 0) or 0)
            except (TypeError, ValueError):
                continue
            if timestamp > 0 and (latest is None or timestamp > latest[0]):
                latest = (timestamp, item)
        if latest is None:
            return None
        return {**latest[1], "timestamp": latest[0]}

    @classmethod
    def _pending_reason(
        cls,
        source_date: str,
        progress_data: Any,
    ) -> Optional[str]:
        """返回 daily 记录待处理原因，已处理则返回 None。"""
        latest = cls._latest_review_event(progress_data)
        if latest is None:
            return "historical_backlog"
        try:
            source_day = datetime.datetime.strptime(
                cls._normalize_date(source_date), "%Y/%m/%d"
            ).date()
            # 必须显式带上配置时区：naive fromtimestamp 会按服务器本地时区
            # 取日期，部署到非 Asia/Shanghai 的机器时会与业务日期（source_date）
            # 错位，进而把当天记录误判成 historical_backlog 批量重灌。
            last_review_day = datetime.datetime.fromtimestamp(
                float(latest["timestamp"]), _facade._configured_tz()
            ).date()
        except (TypeError, ValueError, OSError):
            return None
        if source_day > last_review_day:
            return "historical_backlog"
        if source_day == last_review_day:
            # Hard(2) 属于成功回忆，不再当成「刚答错要重来」；历史评分有两套
            # 语义，交给 event_is_lapse 按事件时间判断。
            from .fsrs_scheduler import event_is_lapse

            if event_is_lapse(latest):
                return "recent_retry"
        return None

    @classmethod
    def _is_pending_for_review(
        cls,
        source_date: str,
        progress_data: Any,
    ) -> bool:
        """判断 daily 记录是否比最后一次复习更新。

        从未进入 progress 的词一定待处理；已有历史的词只有在 daily 记录
        日期晚于最后一次复习日期时才重新进入，避免历史文件把已背词重置。
        同日 Again 写回 daily 的词由 FSRS 接管，不重复占用历史补漏名额。
        """
        return cls._pending_reason(source_date, progress_data) is not None

    def _filter_persisted_review_batch(
        self,
        entries: Any,
        progress_by_word: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """过滤当日已领取批次中已经完成或损坏的条目。"""
        result: List[Dict[str, Any]] = []
        seen: set[str] = set()
        if not isinstance(entries, list):
            return result
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            word = str(entry.get("word") or "").strip()
            source_date = self._normalize_date(entry.get("source_date", ""))
            key = word.lower()
            if not word or not source_date or key in seen:
                continue
            if not self._is_pending_for_review(
                source_date,
                progress_by_word.get(key),
            ):
                continue
            result.append(
                {
                    "word": word,
                    "unknown_count": int(entry.get("unknown_count", 0) or 0),
                    "source_date": source_date,
                    "pending_reason": self._pending_reason(
                        source_date,
                        progress_by_word.get(key),
                    ),
                }
            )
            seen.add(key)
        return result

    def get_review_batch(
        self,
        progress: Dict[str, Dict[str, Any]],
        batch_size: int = 0,
    ) -> List[Dict[str, Any]]:
        """领取并返回今天固定的历史 daily 待复习批次。

        候选范围是今天之前的全部 daily 文件，按日期从旧到新、文件内按
        原顺序去重。``batch_size=0`` 表示领取全部候选；正数只用于显式调用。
        首次领取后原子落盘，同一天不会在完成后动态追加新候选；唯一例外是
        用户手动编辑历史 daily 文件（新增/改动词条），此时只把新出现的
        待复习词补进当天批次，已完成项与既有顺序不受影响。
        """
        today_str = self._normalize_date(self._get_today_str())
        today = datetime.datetime.strptime(today_str, "%Y/%m/%d").date()
        safe_batch_size = max(0, int(batch_size or 0))
        progress_by_word = {
            str(word or "").strip().lower(): data
            for word, data in (progress or {}).items()
            if str(word or "").strip()
        }

        with self._review_state_lock:
            state = _facade.safe_json_load(self._review_batch_state_path, default={})
            if (
                isinstance(state, dict)
                and state.get("version") == 5
                and state.get("review_date") == today_str
            ):
                persisted = self._filter_persisted_review_batch(
                    state.get("entries"),
                    progress_by_word,
                )
                # 限量批次保持固定：背空后不翻下一批，也不吸收新写入的记录
                if safe_batch_size:
                    return persisted
                # 全量批次（App 每日复习使用）：用户手动编辑历史 daily 文件时，
                # 只把新出现的待复习词补进当天批次，避免手加的词当天无人安排
                if not self._sync_source_signatures(state):
                    return persisted
                candidates = self._scan_review_entries(
                    progress_by_word,
                    self._collect_dated_sources(today),
                    0,
                )
                merged = self._merge_new_entries(persisted, candidates)
                self._write_review_batch_state(merged, safe_batch_size, today_str)
                return merged

            dated_sources = self._collect_dated_sources(today)
            entries = self._scan_review_entries(
                progress_by_word,
                dated_sources,
                safe_batch_size,
            )
            self._write_review_batch_state(entries, safe_batch_size, today_str)
            return entries

    def _scan_review_entries(
        self,
        progress_by_word: Dict[str, Dict[str, Any]],
        dated_sources: List[tuple],
        safe_batch_size: int,
    ) -> List[Dict[str, Any]]:
        """扫描历史 daily 文件，生成待复习候选（recent_retry 优先）。"""
        recent_retries: List[Dict[str, Any]] = []
        historical_backlog: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # 昨天/最近一次仍不会的词优先，避免历史补漏抢在刚学失败词前面。
        for _, source_date in sorted(dated_sources, reverse=True):
            for item in self.get_words_for_date(source_date):
                word = str(item.get("word") or "").strip()
                key = word.lower()
                if not word or key in seen:
                    continue
                reason = self._pending_reason(
                    source_date,
                    progress_by_word.get(key),
                )
                if reason != "recent_retry":
                    continue
                seen.add(key)
                recent_retries.append(
                    {
                        "word": word,
                        "unknown_count": int(item.get("unknown_count", 0) or 0),
                        "source_date": source_date,
                        "pending_reason": reason,
                    }
                )
                if safe_batch_size and len(recent_retries) >= safe_batch_size:
                    break
            if safe_batch_size and len(recent_retries) >= safe_batch_size:
                break

        # 剩余名额再按日期从旧到新补历史漏推/后来手动重记的词。
        if not safe_batch_size or len(recent_retries) < safe_batch_size:
            for _, source_date in sorted(dated_sources):
                for item in self.get_words_for_date(source_date):
                    word = str(item.get("word") or "").strip()
                    key = word.lower()
                    if not word or key in seen:
                        continue
                    reason = self._pending_reason(
                        source_date,
                        progress_by_word.get(key),
                    )
                    if reason != "historical_backlog":
                        continue
                    seen.add(key)
                    historical_backlog.append(
                        {
                            "word": word,
                            "unknown_count": int(item.get("unknown_count", 0) or 0),
                            "source_date": source_date,
                            "pending_reason": reason,
                        }
                    )
                    if safe_batch_size and (
                        len(recent_retries) + len(historical_backlog)
                        >= safe_batch_size
                    ):
                        break
                if safe_batch_size and (
                    len(recent_retries) + len(historical_backlog) >= safe_batch_size
                ):
                    break

        entries = recent_retries + historical_backlog
        if safe_batch_size:
            entries = entries[:safe_batch_size]
        return entries
