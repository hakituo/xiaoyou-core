"""daily_word_log 的源文件签名、自写检测与批次状态落盘（混入 DailyWordLogManager）。

从 ``core/tools/study/english/daily_word_log.py`` 拆出。原单文件里的
``DailyWordLogManager`` 按职责拆成多个 mixin，本模块负责：
- daily 源文件签名采集与「用户手动编辑」识别
- 本管理器自写签名的记录与持久化
- 当天批次状态的原子写入（含签名快照）

⚠️ 模块级 patch 语义：历史测试与排查脚本会 patch 门面模块的
``safe_json_dump`` / ``safe_json_load`` / ``get_current_time_str``（例如
``monkeypatch.setattr(dword, "safe_json_dump", _boom)``），因此这里**不能**
顶层 from-import 这些名字，必须在调用期从门面模块取名。
"""
from __future__ import annotations

import datetime
import hashlib
import os
from typing import Any, Dict, List, Optional

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.tools.study.english import daily_word_log as _facade
from core.utils.logger import get_logger

logger = get_logger("DailyWordLog")


class DailyWordLogSourceMixin:
    """源文件签名、自写检测与批次状态落盘。"""

    @staticmethod
    def _file_signature(path: str) -> str:
        """返回 daily 文件的内容签名；文件不存在时返回空串。"""
        try:
            with open(path, "rb") as file:
                return hashlib.sha1(file.read()).hexdigest()
        except OSError:
            return ""

    def _collect_source_signatures(self) -> Dict[str, str]:
        """采集今天之前所有 daily 文件的内容签名（date -> sha1）。"""
        today_str = self._normalize_date(self._get_today_str())
        try:
            today = datetime.datetime.strptime(today_str, "%Y/%m/%d").date()
        except ValueError:
            return {}
        signatures: Dict[str, str] = {}
        for date_str in self.list_dates():
            normalized = self._normalize_date(date_str)
            try:
                source_day = datetime.datetime.strptime(
                    normalized, "%Y/%m/%d"
                ).date()
            except ValueError:
                continue
            if source_day >= today:
                continue
            path = self._date_to_path(normalized)
            if os.path.exists(path):
                signatures[normalized] = self._file_signature(path)
        return signatures

    def _collect_dated_sources(self, today: datetime.date) -> List[tuple]:
        """列出今天之前的全部 daily 日期（date 对象, 'YYYY/MM/DD'）。"""
        dated_sources: List[tuple] = []
        for date_str in self.list_dates():
            normalized = self._normalize_date(date_str)
            try:
                source_day = datetime.datetime.strptime(
                    normalized, "%Y/%m/%d"
                ).date()
            except ValueError:
                continue
            if source_day < today:
                dated_sources.append((source_day, normalized))
        return dated_sources

    def _record_self_write(self, date_str: Optional[str]) -> None:
        """记录本管理器刚写入的日期文件签名，用于区分用户手动编辑。"""
        normalized = self._normalize_date(date_str or "")
        if not normalized:
            return
        signature = self._file_signature(self._date_to_path(normalized))
        if not signature:
            return
        self._self_written[normalized] = signature
        self._persist_self_write(normalized, signature)

    def _persist_self_write(self, date_str: str, signature: str) -> None:
        """把自写签名同步进当天批次状态，保证进程重启后仍能识别。"""
        with self._review_state_lock:
            state = _facade.safe_json_load(self._review_batch_state_path, default={})
            if not isinstance(state, dict) or state.get("review_date") != (
                self._normalize_date(self._get_today_str())
            ):
                return
            written = state.get("self_written_signatures")
            if not isinstance(written, dict):
                written = {}
            if written.get(date_str) == signature:
                return
            written[date_str] = signature
            state["self_written_signatures"] = written
            try:
                _facade.safe_json_dump(state, self._review_batch_state_path)
            except OSError as exc:
                logger.warning(f"持久化 daily 自写签名失败: {exc}")

    def _sync_source_signatures(self, state: Dict[str, Any]) -> bool:
        """核对历史 daily 文件签名，返回是否存在「外部（手动）编辑」。

        只在签名确实变化时才回写状态：系统自身写入（复习标记/移除）引起
        的变化只更新快照并返回 False，不触发补录。
        """
        current = self._collect_source_signatures()
        old = state.get("source_signatures")
        old_map = old if isinstance(old, dict) else {}
        if old_map == current:
            return False

        merged: Dict[str, str] = {
            key: value
            for key, value in old_map.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        written = state.get("self_written_signatures")
        if isinstance(written, dict):
            merged.update(
                {
                    key: value
                    for key, value in written.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
            )
        merged.update(self._self_written)
        if merged == current:
            # 差异全部来自本管理器的写入：刷新快照即可，不重算批次
            self._update_review_batch_fields({"source_signatures": current})
            return False
        return True

    def _update_review_batch_fields(self, fields: Dict[str, Any]) -> None:
        """只更新当天批次状态的附加字段，不动已锁定的 entries。"""
        with self._review_state_lock:
            state = _facade.safe_json_load(self._review_batch_state_path, default={})
            if (
                not isinstance(state, dict)
                or state.get("review_date")
                != self._normalize_date(self._get_today_str())
            ):
                return
            state.update(fields)
            try:
                _facade.safe_json_dump(state, self._review_batch_state_path)
            except OSError as exc:
                logger.warning(f"更新 daily 批次状态字段失败: {exc}")

    @staticmethod
    def _merge_new_entries(
        persisted: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """把新增候选补进已锁定批次：recent_retry 靠前，历史补漏追加队尾。"""
        seen = {str(item.get("word") or "").strip().lower() for item in persisted}
        added_retry: List[Dict[str, Any]] = []
        added_backlog: List[Dict[str, Any]] = []
        for item in candidates:
            key = str(item.get("word") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            if item.get("pending_reason") == "recent_retry":
                added_retry.append(item)
            else:
                added_backlog.append(item)
        if not added_retry and not added_backlog:
            return persisted

        merged = list(persisted)
        if added_retry:
            last_index = -1
            for index, item in enumerate(merged):
                if item.get("pending_reason") == "recent_retry":
                    last_index = index
            merged[last_index + 1 : last_index + 1] = added_retry
        merged.extend(added_backlog)
        return merged

    def _write_review_batch_state(
        self,
        entries: List[Dict[str, Any]],
        safe_batch_size: int,
        today_str: str,
    ) -> None:
        """原子写入当天批次状态（含源文件签名快照与自写签名）。"""
        with self._review_state_lock:
            state = _facade.safe_json_load(self._review_batch_state_path, default={})
            written: Dict[str, str] = {}
            if isinstance(state, dict):
                old_written = state.get("self_written_signatures")
                if isinstance(old_written, dict):
                    written.update(
                        {
                            key: value
                            for key, value in old_written.items()
                            if isinstance(key, str) and isinstance(value, str)
                        }
                    )
            written.update(self._self_written)
            try:
                _facade.safe_json_dump(
                    {
                        "version": 5,
                        "review_date": today_str,
                        "batch_size": safe_batch_size,
                        "entries": entries,
                        "selected_at": _facade.get_current_time_str("%Y-%m-%d %H:%M:%S"),
                        "source_signatures": self._collect_source_signatures(),
                        "self_written_signatures": written,
                    },
                    self._review_batch_state_path,
                )
            except OSError as exc:
                logger.warning(f"持久化 daily 复习批次失败: {exc}")
