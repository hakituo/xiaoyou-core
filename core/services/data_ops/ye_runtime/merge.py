"""叶运行态候选仲裁与状态合并。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping, Optional

SCENE_STATE_FIELDS = (
    "location",
    "activity",
    "clothing",
    "people_present",
    "physical_state",
    "current_possessions",
)


def _add_candidate(
    changes: dict[str, list[dict[str, Any]]],
    field: str,
    value: Any,
    source: str,
    confidence: float,
) -> None:
    if value in (None, "", [], {}):
        return
    changes.setdefault(field, []).append(
        {"value": value, "source": source, "confidence": round(float(confidence), 4)}
    )


def _merge_candidates(
    target: dict[str, list[dict[str, Any]]],
    incoming: Mapping[str, list[dict[str, Any]]],
) -> None:
    for field, candidates in incoming.items():
        target.setdefault(field, []).extend(candidates)


def _best_candidate(
    changes: Mapping[str, list[dict[str, Any]]], field: str
) -> Optional[dict[str, Any]]:
    candidates = changes.get(field, [])
    if not candidates:
        return None
    source_priority = {
        "user_explicit": 4,
        "assistant_confirmation": 3,
        "assistant_rule": 2,
        "assistant_uie": 1,
    }
    return max(
        candidates,
        key=lambda item: (
            source_priority.get(str(item.get("source") or ""), 0),
            float(item.get("confidence") or 0.0),
        ),
    )


def _apply_changes(
    state: dict[str, Any],
    changes: Mapping[str, list[dict[str, Any]]],
    timestamp: str,
    now: datetime,
    config: Mapping[str, Any],
) -> set[str]:
    del now
    changed: set[str] = set()
    for field in SCENE_STATE_FIELDS:
        candidate = _best_candidate(changes, field)
        if candidate is None:
            continue
        state[field] = {
            "value": candidate["value"],
            "source": candidate["source"],
            "updated_at": timestamp,
            "confidence": candidate["confidence"],
        }
        changed.add(field)

    remove_candidate = _best_candidate(changes, "active_rules_remove")
    if remove_candidate is not None:
        target = str(remove_candidate["value"])
        existing = state.get("active_rules") if isinstance(state.get("active_rules"), list) else []
        filtered = [item for item in existing if target not in _item_identity(item)]
        if len(filtered) != len(existing):
            state["active_rules"] = filtered
            changed.add("active_rules")

    for field, change_field, identity_keys in (
        ("active_rules", "active_rules_add", ("type", "target", "text")),
        ("pending_actions", "pending_actions_add", ("action",)),
        ("time_constraints", "time_constraints_add", ("related_type", "target", "label")),
        ("explicit_facts", "explicit_facts_add", ("fact",)),
    ):
        for candidate in changes.get(change_field, []):
            item = deepcopy(candidate["value"])
            if not isinstance(item, dict):
                continue
            item.update(
                {
                    "source": candidate["source"],
                    "updated_at": timestamp,
                    "confidence": candidate["confidence"],
                }
            )
            existing = state.get(field) if isinstance(state.get(field), list) else []
            limit = _limit(config, field, 20)
            state[field] = _upsert_list(existing, item, identity_keys)[-limit:]
            changed.add(field)

    complete_candidate = _best_candidate(changes, "pending_actions_complete")
    if complete_candidate is not None:
        existing = state.get("pending_actions") if isinstance(state.get("pending_actions"), list) else []
        for item in reversed(existing):
            if isinstance(item, dict) and item.get("status") == "pending":
                item["status"] = "completed"
                item["completed_at"] = timestamp
                item["completion_source"] = complete_candidate["source"]
                changed.add("pending_actions")
                break

    interaction = _best_candidate(changes, "ongoing_interaction")
    if interaction is not None:
        mode = str(interaction["value"])
        if mode == "private":
            state["ongoing_interaction"] = {
                "mode": "private",
                "label": "private_relationship",
                "started_at": timestamp,
                "state": "active",
                "source": interaction["source"],
            }
        else:
            state["ongoing_interaction"] = {
                "mode": "ordinary",
                "label": None,
                "started_at": None,
                "state": None,
                "source": interaction["source"],
                "updated_at": timestamp,
            }
        changed.add("ongoing_interaction")
    return changed


def _upsert_list(
    existing: list[Any], item: dict[str, Any], identity_keys: tuple[str, ...]
) -> list[Any]:
    identity = tuple(str(item.get(key) or "") for key in identity_keys)
    result = [entry for entry in existing if isinstance(entry, dict)]
    for index, entry in enumerate(result):
        entry_identity = tuple(str(entry.get(key) or "") for key in identity_keys)
        if entry_identity == identity:
            result[index] = item
            return result
    result.append(item)
    return result


def _item_identity(item: Any) -> str:
    if not isinstance(item, Mapping):
        return str(item)
    return " ".join(str(item.get(key) or "") for key in ("target", "text", "type"))


def _limit(config: Mapping[str, Any], key: str, fallback: int) -> int:
    limits = config.get("limits")
    if not isinstance(limits, Mapping):
        return fallback
    try:
        return max(1, int(limits.get(key, fallback)))
    except (TypeError, ValueError):
        return fallback
