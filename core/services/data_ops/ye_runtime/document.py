"""叶运行态文档结构与文本规范化。"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

QUESTION_MARKERS = ("?", "？", "吗", "么", "哪", "什么", "谁", "多少", "几点")


def _empty_scalar() -> dict[str, Any]:
    return {"value": None, "source": None, "updated_at": None, "confidence": None}


def _default_document() -> dict[str, Any]:
    return {
        "character": "ye",
        "schema_version": "2.0",
        "updated_at": None,
        "state": {
            "location": _empty_scalar(),
            "activity": _empty_scalar(),
            "clothing": _empty_scalar(),
            "people_present": _empty_scalar(),
            "physical_state": {},
            "current_possessions": {},
            "active_rules": [],
            "ongoing_interaction": {
                "mode": "ordinary",
                "label": None,
                "started_at": None,
                "state": None,
            },
            "pending_actions": [],
            "time_constraints": [],
            "explicit_facts": [],
        },
        "update_semantics": [
            "字段由最近聊天、实际运行时数据或明确工具结果更新。",
            "每次更新记录来源和时间。",
            "新事实与旧事实冲突时，以更近且更明确的来源更新字段。",
            "没有来源的字段保持 null 或空集合。",
            "位置与动作等连续状态按时间和上下文自然延续。",
        ],
        "prompt_projection": {
            "mode": "always_non_null_only",
            "render": "只把当前有值的状态字段注入模型，避免大量空字段占上下文。",
        },
        "runtime_meta": {"processed_message_ids": []},
    }


def _normalize_document(document: Mapping[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(dict(document))
    baseline = _default_document()
    normalized.setdefault("character", "ye")
    normalized.setdefault("schema_version", "2.0")
    normalized.setdefault("updated_at", None)
    state = normalized.setdefault("state", {})
    if not isinstance(state, dict):
        state = {}
        normalized["state"] = state
    for key, value in baseline["state"].items():
        state.setdefault(key, deepcopy(value))
    metadata = normalized.setdefault("runtime_meta", {})
    if not isinstance(metadata, dict):
        normalized["runtime_meta"] = {"processed_message_ids": []}
    else:
        metadata.setdefault("processed_message_ids", [])
    return normalized


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_question(text: str) -> bool:
    tail = text[-24:] if text else ""
    return any(marker in tail for marker in QUESTION_MARKERS)
