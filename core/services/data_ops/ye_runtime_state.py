"""叶 Persona 2.0 运行态写回门面。"""
# ruff: noqa: F401

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping, Optional

from core.services.data_ops.ye_runtime.document import (
    QUESTION_MARKERS as _QUESTION_MARKERS,
    _clean_text,
    _default_document,
    _empty_scalar,
    _is_question,
    _normalize_document,
)
from core.services.data_ops.ye_runtime.expiry import (
    _cn_number,
    _is_expired,
    _parse_expiry,
    _prune_expired,
    _strip_tail,
)
from core.services.data_ops.ye_runtime.merge import (
    SCENE_STATE_FIELDS,
    _add_candidate,
    _apply_changes,
    _best_candidate,
    _item_identity,
    _limit,
    _merge_candidates,
    _upsert_list,
)
from core.services.data_ops.ye_runtime.rule_extractor import (
    ACTIVITY_VERBS as _ACTIVITY_VERBS,
    _extract_assistant_scene,
    _extract_confirmed_question,
    _extract_private_mode,
    _extract_relationship_rules,
    _extract_rule_changes,
    _extract_user_corrections,
    _find_activity,
    _find_location,
)
from core.services.data_ops.ye_runtime.uie import (
    _extract_uie_changes,
    _merge_uie_spans,
    _select_uie_fields,
    _uie_item_value,
)
from core.utils.async_locks import LazyAsyncLock
from core.utils.atomic_io import safe_json_dump, safe_json_load
from core.utils.common import get_project_root
from core.utils.data.scope_registry import (
    resolve_data_scope_from_conversation_id,
    resolve_persona_slug_scope,
)
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("YeRuntimeState")
_PROJECT_ROOT = Path(get_project_root())
_CONFIG_PATH = _PROJECT_ROOT / "config" / "ye_runtime_state_extraction.json"
_DEFAULT_STATE_PATH = (
    _PROJECT_ROOT / "companion_data" / "ye_data" / "runtime" / "current_state.json"
)
_STATE_LOCK = LazyAsyncLock()


@lru_cache(maxsize=1)
def _load_default_config() -> dict[str, Any]:
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("叶 runtime state 配置读取失败，已停用自动写回: %s", exc)
        return {}


def clear_ye_runtime_state_config_cache() -> None:
    _load_default_config.cache_clear()


def _resolve_state_path(config: Mapping[str, Any]) -> Path:
    configured = str(config.get("runtime_state_path") or "").strip()
    if not configured:
        return _DEFAULT_STATE_PATH
    path = Path(configured)
    return path if path.is_absolute() else _PROJECT_ROOT / path


def get_ye_runtime_state_path() -> Path:
    return _resolve_state_path(_load_default_config())


def _is_ye_turn(
    conversation_id: str,
    persona_filename: Optional[str],
    config: Mapping[str, Any],
) -> bool:
    expected_scope = str(config.get("scope") or "ye").strip().lower()
    if persona_filename:
        return resolve_persona_slug_scope(persona_filename) == expected_scope
    return (
        resolve_data_scope_from_conversation_id(conversation_id, default="aveline")
        == expected_scope
    )


def character_state_tool_enabled(persona_filename: str) -> bool:
    config = _load_default_config()
    return bool(
        persona_filename
        and config.get("enabled", False)
        and config.get("scene_write_mode") == "tool"
        and _is_ye_turn("", persona_filename, config)
    )


async def update_character_scene_state(
    *,
    conversation_id: str,
    persona_filename: Optional[str],
    updates: Mapping[str, Optional[str]],
    evidence: str,
) -> dict[str, Any]:
    """只提交当前角色已明确发生的现场变化。"""
    config = _load_default_config()
    if not config.get("enabled", False) or config.get("scene_write_mode") != "tool":
        return {"ok": False, "error": "角色现场状态工具未启用"}
    if not _is_ye_turn(conversation_id, persona_filename, config):
        return {"ok": False, "error": "当前角色未配置现场状态存储"}
    if not updates or set(updates) - set(SCENE_STATE_FIELDS):
        raise ValueError("只能更新非空的现场状态字段集合")
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 300:
        raise ValueError("必须提供不超过300字的状态变化依据")
    for value in updates.values():
        if value is not None and (
            not isinstance(value, str) or not value.strip() or len(value) > 240
        ):
            raise ValueError("字段应为1至240字的文字；清空时显式传null")

    target = _resolve_state_path(config)
    timestamp = get_current_time().isoformat(timespec="seconds")
    async with _STATE_LOCK:
        try:
            raw = await asyncio.to_thread(target.read_text, encoding="utf-8")
        except FileNotFoundError:
            document = _default_document()
        else:
            document = json.loads(raw)
            if not isinstance(document, dict) or not isinstance(document.get("state"), dict):
                raise ValueError("已有角色状态格式异常，未写入")
            document = _normalize_document(document)
        state = document["state"]
        changed = []
        for field, value in updates.items():
            value = value.strip() if isinstance(value, str) else None
            previous = state.get(field)
            previous = previous.get("value") if isinstance(previous, dict) else previous
            if previous == value:
                continue
            state[field] = {
                "value": value,
                "source": "llm_tool",
                "updated_at": timestamp,
                "confidence": None,
            }
            changed.append(field)
        if changed:
            document["updated_at"] = timestamp
            document["runtime_meta"]["last_tool_update"] = {
                "conversation_id": conversation_id,
                "fields": changed,
                "evidence": evidence.strip(),
                "updated_at": timestamp,
            }
            await asyncio.to_thread(safe_json_dump, document, target, "utf-8", True)
        return {
            "ok": True,
            "updated": bool(changed),
            "fields": changed,
            "state": {field: state[field] for field in updates},
        }


async def update_ye_runtime_state_after_turn(
    *,
    conversation_id: str,
    user_text: str,
    assistant_text: str,
    persona_filename: Optional[str] = None,
    message_id: Optional[str] = None,
    state_path: Optional[Path] = None,
    config: Optional[Mapping[str, Any]] = None,
    uie_extractor: Any = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """提取一轮叶对话中的明确状态变化并原子写回。"""
    effective_config = dict(config) if isinstance(config, Mapping) else _load_default_config()
    if not effective_config.get("enabled", False):
        return {"updated": False, "skipped": "disabled", "fields": []}
    if not _is_ye_turn(conversation_id, persona_filename, effective_config):
        return {"updated": False, "skipped": "not_ye", "fields": []}
    user_text = _clean_text(user_text)
    assistant_text = _clean_text(assistant_text)
    if not user_text and not assistant_text:
        return {"updated": False, "skipped": "empty", "fields": []}

    effective_now = now or get_current_time()
    timestamp = effective_now.isoformat(timespec="seconds")
    changes = _extract_rule_changes(
        user_text=user_text,
        assistant_text=assistant_text,
        config=effective_config,
        now=effective_now,
    )
    uie_fields = _select_uie_fields(assistant_text, effective_config)
    uie_values: dict[str, Any] = {}
    if uie_fields:
        uie_changes = await _extract_uie_changes(
            assistant_text,
            uie_fields,
            effective_config,
            uie_extractor=uie_extractor,
        )
        uie_values = {
            field: candidate["value"]
            for field, candidates in uie_changes.items()
            if (candidate := _best_candidate(uie_changes, field)) is not None
        }
        _merge_candidates(changes, uie_changes)

    target = Path(state_path or _resolve_state_path(effective_config))
    async with _STATE_LOCK:
        document = await asyncio.to_thread(safe_json_load, target, "utf-8", None)
        document = _normalize_document(document) if isinstance(document, dict) else _default_document()
        runtime_meta = document.setdefault("runtime_meta", {})
        processed = runtime_meta.setdefault("processed_message_ids", [])
        normalized_message_id = str(message_id or "").strip()
        if normalized_message_id and normalized_message_id in processed:
            return {"updated": False, "skipped": "duplicate", "fields": []}

        state = document["state"]
        changed_fields = _apply_changes(
            state, changes, timestamp, effective_now, effective_config
        )
        changed_fields.update(_prune_expired(state, effective_now))
        if normalized_message_id:
            processed.append(normalized_message_id)
            max_ids = _limit(effective_config, "processed_message_ids", 100)
            runtime_meta["processed_message_ids"] = processed[-max_ids:]
            runtime_meta["last_message_id"] = normalized_message_id
        if not changed_fields and not normalized_message_id:
            return {"updated": False, "skipped": "no_change", "fields": []}
        document["updated_at"] = timestamp
        runtime_meta["last_processed_at"] = timestamp
        await asyncio.to_thread(safe_json_dump, document, target, "utf-8", True)

    return {
        "updated": bool(changed_fields),
        "skipped": None,
        "fields": sorted(changed_fields),
        "state_path": str(target),
        "uie_fields": sorted(uie_fields),
        "uie_values": uie_values,
    }


__all__ = [
    "clear_ye_runtime_state_config_cache",
    "update_ye_runtime_state_after_turn",
]
