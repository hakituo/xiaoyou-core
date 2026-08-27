"""人物档案候选批次的蒸馏信号门控。"""

from __future__ import annotations

import re
from contextlib import nullcontext
from typing import Any, Dict, List

_PROFILE_SIGNAL_WINDOW_SECONDS = 600


class PeopleProfileSignalGate:
    """汇总蒸馏元数据，并以零 API 规则筛选原始聊天批次。"""

    @staticmethod
    def collect(
        memory_managers: Dict[str, Any],
        last_processed_ts: float,
    ) -> Dict[str, Any]:
        """汇总所有记忆 scope 中已落盘的蒸馏人物线索。"""
        people: List[Dict[str, Any]] = []
        role_updates: List[Dict[str, Any]] = []
        analyzed_count = 0
        seen: set[tuple[str, str, float]] = set()
        for scope_id, manager in memory_managers.items():
            lock = getattr(manager, "lock", None)
            with lock if lock is not None else nullcontext():
                memories = list(
                    getattr(manager, "weighted_memories", {}).values()
                )
            for memory in memories:
                timestamp = float(memory.get("timestamp", 0) or 0)
                if timestamp <= last_processed_ts:
                    continue
                metadata = memory.get("distillation_metadata")
                if not isinstance(metadata, dict) or not metadata.get(
                    "profile_signal_analyzed"
                ):
                    continue
                dedupe_key = (
                    str(scope_id),
                    str(memory.get("id") or ""),
                    timestamp,
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                analyzed_count += 1
                people_mentions = list(metadata.get("people_mentions") or [])
                if people_mentions:
                    people.append(
                        {"timestamp": timestamp, "hints": people_mentions}
                    )
                role_candidates = list(
                    metadata.get("role_update_candidates") or []
                )
                if role_candidates:
                    role_updates.append(
                        {"timestamp": timestamp, "hints": role_candidates}
                    )
        return {
            "people": people,
            "role_updates": role_updates,
            "analyzed_count": analyzed_count,
        }

    @classmethod
    def select_batches(
        cls,
        batches: List[List[Dict[str, Any]]],
        distillation_signals: List[Dict[str, Any]],
        *,
        signal_type: str,
    ) -> List[List[Dict[str, Any]]]:
        """结合蒸馏时间/文本线索和本地规则筛选候选批次。"""
        selected: List[List[Dict[str, Any]]] = []
        for batch in batches:
            if cls._matches_distillation_signal(batch, distillation_signals):
                selected.append(batch)
                continue
            if any(
                cls._matches_local_signal(message, signal_type)
                for message in batch
            ):
                selected.append(batch)
        return selected

    @staticmethod
    def _matches_distillation_signal(
        batch: List[Dict[str, Any]],
        signals: List[Dict[str, Any]],
    ) -> bool:
        """判断批次是否命中蒸馏时间窗或明确文本提示。"""
        timestamps = [
            float(message.get("timestamp", 0) or 0)
            for message in batch
            if float(message.get("timestamp", 0) or 0) > 0
        ]
        batch_start = min(timestamps) if timestamps else 0.0
        batch_end = max(timestamps) if timestamps else 0.0
        content = "\n".join(str(item.get("content") or "") for item in batch)
        for signal in signals:
            signal_ts = float(signal.get("timestamp", 0) or 0)
            hints = [str(item).strip() for item in signal.get("hints") or []]
            time_hit = bool(
                batch_start
                and signal_ts
                and batch_start - _PROFILE_SIGNAL_WINDOW_SECONDS
                <= signal_ts
                <= batch_end + _PROFILE_SIGNAL_WINDOW_SECONDS
            )
            text_hit = any(
                hint
                and hint != "local_candidate"
                and hint.lower() in content.lower()
                for hint in hints
            )
            if time_hit or text_hit:
                return True
        return False

    @classmethod
    def _matches_local_signal(
        cls,
        message: Dict[str, Any],
        signal_type: str,
    ) -> bool:
        local = cls.detect_local_signals(message)
        return bool(local.get(signal_type))

    @staticmethod
    def detect_local_signals(message: Dict[str, Any]) -> Dict[str, bool]:
        """原始聊天未进入加权记忆时的零 API 保底检测。"""
        content = str(message.get("content") or "").strip()
        role = str(message.get("role") or "").strip().lower()
        people = bool(
            re.search(
                r"(?:我的|他的|她的|家里的|班上的)?"
                r"(?:妈妈|爸爸|父亲|母亲|哥哥|弟弟|姐姐|妹妹|"
                r"老师|同学|朋友|同事|亲戚|室友|班主任|教授|"
                r"医生|师傅|老板|邻居|叔叔|阿姨|爷爷|奶奶|"
                r"外公|外婆|男朋友|女朋友)"
                r"|(?:叫|名叫|姓)\s*[\u4e00-\u9fff]{1,4}",
                content,
            )
        )
        role_updates = bool(
            role in {"assistant", "aveline", "ling"}
            and re.search(
                r"(?:我|本人).{0,6}(?:喜欢|讨厌|不喜欢|习惯|"
                r"偏好|以后都|从不|总是|害怕|擅长|想要)",
                content,
            )
        )
        return {"people": people, "role_updates": role_updates}
