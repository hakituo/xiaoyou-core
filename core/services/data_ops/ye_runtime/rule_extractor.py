"""叶运行态的规则式事实提取。"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping

from core.services.data_ops.ye_runtime.document import _clean_text, _is_question
from core.services.data_ops.ye_runtime.expiry import _parse_expiry, _strip_tail
from core.services.data_ops.ye_runtime.merge import _add_candidate

ACTIVITY_VERBS = (
    "做实验",
    "做切片",
    "看论文",
    "写论文",
    "写报告",
    "写作业",
    "上课",
    "学习",
    "复习",
    "吃饭",
    "喝水",
    "走路",
    "回宿舍",
    "回家",
    "坐地铁",
    "等车",
    "睡觉",
    "洗澡",
    "收拾",
    "休息",
    "刷视频",
    "开会",
    "聊天",
    "工作",
    "跑步",
)


def _extract_rule_changes(
    *,
    user_text: str,
    assistant_text: str,
    config: Mapping[str, Any],
    now: datetime,
) -> dict[str, list[dict[str, Any]]]:
    changes: dict[str, list[dict[str, Any]]] = {}
    location_terms = tuple(
        str(item).strip() for item in config.get("location_terms", []) if str(item).strip()
    )
    physical_terms = tuple(
        str(item).strip() for item in config.get("physical_terms", []) if str(item).strip()
    )
    if config.get("scene_write_mode", "automatic") != "tool":
        _extract_assistant_scene(changes, assistant_text, location_terms, physical_terms)
        _extract_user_corrections(changes, user_text, location_terms)
        _extract_confirmed_question(changes, user_text, assistant_text, location_terms)
    _extract_relationship_rules(changes, user_text, assistant_text, now)
    _extract_private_mode(changes, user_text, config)
    return changes


def _extract_assistant_scene(
    changes: dict[str, list[dict[str, Any]]],
    text: str,
    location_terms: tuple[str, ...],
    physical_terms: tuple[str, ...],
) -> None:
    if not text:
        return
    location = _find_location(text, location_terms, subject_pattern=r"(?:我)?(?:现在|刚刚|刚才)?")
    if location:
        _add_candidate(changes, "location", location, "assistant_rule", 0.90)
    activity = _find_activity(text, location_terms)
    if activity:
        _add_candidate(changes, "activity", activity, "assistant_rule", 0.88)
    clothing_match = re.search(r"(?:我)?(?:今天|现在)?穿(?:着|的是|了)?\s*([^，。！？?]{1,36})", text)
    if clothing_match:
        value = _strip_tail(clothing_match.group(1), ("呢", "呀", "啊"))
        _add_candidate(changes, "clothing", value, "assistant_rule", 0.94)
    people_match = re.search(
        r"(?:和|跟)([^，。！？?]{1,16}?)(?:一起|在(?:我)?(?:旁边|身边))|"
        r"([^，。！？?]{1,16}?)(?:也)?在(?:我)?(?:旁边|身边)",
        text,
    )
    if people_match:
        _add_candidate(
            changes,
            "people_present",
            people_match.group(1) or people_match.group(2),
            "assistant_rule",
            0.91,
        )
    found_physical = [term for term in physical_terms if term in text]
    if found_physical:
        _add_candidate(
            changes,
            "physical_state",
            "、".join(dict.fromkeys(found_physical)),
            "assistant_rule",
            0.90,
        )
    possession_match = re.search(
        r"(?:我)?(?:现在)?(?:拿着|带着|收着|手里有)\s*([^，。！？?]{1,24})", text
    )
    if possession_match:
        _add_candidate(
            changes,
            "current_possessions",
            _strip_tail(possession_match.group(1), ("呢", "呀", "啊")),
            "assistant_rule",
            0.90,
        )


def _extract_user_corrections(
    changes: dict[str, list[dict[str, Any]]],
    text: str,
    location_terms: tuple[str, ...],
) -> None:
    from ..scene_facts import extract_explicit_scene_facts

    facts = extract_explicit_scene_facts(
        text, names=("Ye", "Ye"), location_terms=location_terms
    )
    for field, value in facts.items():
        _add_candidate(changes, field, value, "user_explicit", 0.99)


def _extract_confirmed_question(
    changes: dict[str, list[dict[str, Any]]],
    user_text: str,
    assistant_text: str,
    location_terms: tuple[str, ...],
) -> None:
    if not user_text or not assistant_text:
        return
    if not re.match(r"^(?:嗯|对|是|在|到了|没错|对的)(?:[，。！呀啊呢 ]|$)", assistant_text):
        return
    location = _find_location(
        user_text,
        location_terms,
        subject_pattern=r"(?:你|Ye|Ye)(?:现在|刚刚|刚才)?",
    )
    if location:
        _add_candidate(changes, "location", location, "assistant_confirmation", 0.96)


def _find_location(text: str, terms: tuple[str, ...], *, subject_pattern: str) -> str:
    if not text or not terms:
        return ""
    alternatives = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    pattern = rf"{subject_pattern}(?:在|到(?:了)?|回到|去了?)\s*([^，。！？?]*?(?:{alternatives}))"
    match = re.search(pattern, text)
    return _clean_text(match.group(1)) if match else ""


def _find_activity(text: str, location_terms: tuple[str, ...]) -> str:
    for activity in ACTIVITY_VERBS:
        if activity in text:
            return activity
    if location_terms:
        alternatives = "|".join(
            re.escape(term) for term in sorted(location_terms, key=len, reverse=True)
        )
        match = re.search(
            rf"(?:我)?(?:现在)?(?:正在|在)(?:[^，。！？?]*?(?:{alternatives}))?\s*"
            r"(做[^，。！？?]{1,20}|看[^，。！？?]{1,20}|写[^，。！？?]{1,20})",
            text,
        )
        if match:
            return _strip_tail(match.group(1), ("呢", "呀", "啊"))
    return ""


def _extract_relationship_rules(
    changes: dict[str, list[dict[str, Any]]],
    user_text: str,
    assistant_text: str,
    now: datetime,
) -> None:
    if not user_text:
        return
    return_match = re.search(r"(?:把)?\s*([^，。！？?]{1,12}?)(?:还给我|还我)", user_text)
    if return_match:
        _add_candidate(
            changes,
            "active_rules_remove",
            _strip_tail(return_match.group(1), ("把",)),
            "user_explicit",
            1.0,
        )
    borrow_match = re.search(
        r"([^，。！？?\s]{1,12}?)(?:先)?借(?:给)?你(?:用)?(?:到|至)([^，。！？?]{1,12})",
        user_text,
    )
    if borrow_match:
        target = borrow_match.group(1).strip()
        time_text = borrow_match.group(2).strip()
        expires_at = _parse_expiry(time_text, now)
        _add_candidate(
            changes,
            "active_rules_add",
            {"type": "borrow", "target": target, "holder": "ye", "expires_at": expires_at, "expires_label": time_text},
            "user_explicit",
            1.0,
        )
        _add_candidate(
            changes,
            "time_constraints_add",
            {"label": time_text, "related_type": "borrow", "target": target, "expires_at": expires_at},
            "user_explicit",
            1.0,
        )
    instruction_match = re.search(
        r"((?:你|Ye)(?:先|等会|待会|今天|明天)?[^，。！？?]{0,36}(?:要|记得|必须|不许|不能)[^，。！？?]{1,36})",
        user_text,
    )
    if instruction_match:
        instruction = instruction_match.group(1).strip()
        _add_candidate(
            changes,
            "active_rules_add",
            {"type": "instruction", "text": instruction, "expires_at": None},
            "user_explicit",
            0.96,
        )
    pending_match = re.search(
        r"(?:你|Ye)(?:先|等会|待会|今天|明天)?\s*"
        r"(去[^，。！？?]{1,30}|做[^，。！？?]{1,30}|写[^，。！？?]{1,30}|看[^，。！？?]{1,30})",
        user_text,
    )
    if pending_match and not _is_question(user_text):
        _add_candidate(
            changes,
            "pending_actions_add",
            {"action": pending_match.group(1).strip(), "status": "pending"},
            "user_explicit",
            0.93,
        )
    if re.search(r"(?:做完|写完|看完|完成|已经弄好|已经好了)", assistant_text):
        _add_candidate(changes, "pending_actions_complete", "latest", "assistant_rule", 0.90)


def _extract_private_mode(
    changes: dict[str, list[dict[str, Any]]], text: str, config: Mapping[str, Any]
) -> None:
    private_config = config.get("private_mode")
    if not isinstance(private_config, Mapping):
        return
    enter = tuple(str(item) for item in private_config.get("enter_markers", []) if str(item))
    exit_markers = tuple(
        str(item) for item in private_config.get("exit_markers", []) if str(item)
    )
    if any(marker in text for marker in exit_markers):
        _add_candidate(changes, "ongoing_interaction", "ordinary", "user_explicit", 1.0)
    elif any(marker in text for marker in enter):
        _add_candidate(changes, "ongoing_interaction", "private", "user_explicit", 1.0)
