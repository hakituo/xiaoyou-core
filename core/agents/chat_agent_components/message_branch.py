"""客户端消息树分支元数据辅助函数。

Android 仍使用 ``history_override`` 决定本轮 LLM 看见的激活路径；本模块只承载
消息树 ID / parent / variant 关系，供 WeightedMemory 关系图使用。
分支元数据通过 ContextVar 随当前请求传播，不进入模型消息正文。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, Optional


_MAX_ID_LENGTH = 128
_MAX_VARIANT_INDEX = 10000
_request_branch_metadata: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "xiaoyou_request_branch_metadata", default=None
)


def _clean_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > _MAX_ID_LENGTH:
        return ""
    return text


def _clean_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(number, _MAX_VARIANT_INDEX))


def normalize_branch_metadata(raw: Any) -> Optional[Dict[str, Any]]:
    """校验并归一化一轮 user/assistant 的消息树关系。"""
    if not isinstance(raw, dict):
        return None

    user_message_id = _clean_id(raw.get("user_message_id"))
    assistant_message_id = _clean_id(raw.get("assistant_message_id"))
    if not user_message_id or not assistant_message_id:
        return None

    user_variant_index = _clean_non_negative_int(raw.get("user_variant_index"), 0)
    assistant_variant_index = _clean_non_negative_int(
        raw.get("assistant_variant_index"), 0
    )
    user_variant_count = max(
        user_variant_index + 1,
        _clean_non_negative_int(raw.get("user_variant_count"), 1),
        1,
    )
    assistant_variant_count = max(
        assistant_variant_index + 1,
        _clean_non_negative_int(raw.get("assistant_variant_count"), 1),
        1,
    )

    return {
        "user_message_id": user_message_id,
        "user_parent_id": _clean_id(raw.get("user_parent_id")) or None,
        "user_variant_index": user_variant_index,
        "user_variant_count": user_variant_count,
        "user_variant_of": _clean_id(raw.get("user_variant_of")) or None,
        "assistant_message_id": assistant_message_id,
        "assistant_parent_id": _clean_id(raw.get("assistant_parent_id")) or None,
        "assistant_variant_index": assistant_variant_index,
        "assistant_variant_count": assistant_variant_count,
        "assistant_variant_of": _clean_id(raw.get("assistant_variant_of")) or None,
        "branch_id": _clean_id(raw.get("branch_id")) or None,
    }


def set_request_branch_metadata(raw: Any) -> Token:
    """绑定当前请求的分支元数据；无效 payload 会显式绑定为 None。"""
    return _request_branch_metadata.set(normalize_branch_metadata(raw))


def reset_request_branch_metadata(token: Token) -> None:
    _request_branch_metadata.reset(token)


def get_request_branch_metadata() -> Optional[Dict[str, Any]]:
    value = _request_branch_metadata.get()
    return dict(value) if isinstance(value, dict) else None


def branch_metadata_for_role(
    branch_metadata: Optional[Dict[str, Any]], role: str
) -> Dict[str, Any]:
    """投影为一条 WeightedMemory 记录可直接合并的关系字段。"""
    normalized = normalize_branch_metadata(branch_metadata)
    role_key = str(role or "").strip().lower()
    if normalized is None or role_key not in {"user", "assistant"}:
        return {}

    prefix = "user" if role_key == "user" else "assistant"
    client_message_id = _clean_id(normalized.get(f"{prefix}_message_id"))
    if not client_message_id:
        return {}

    result: Dict[str, Any] = {
        "client_message_id": client_message_id,
        "variant_index": int(normalized.get(f"{prefix}_variant_index") or 0),
        "variant_count": int(normalized.get(f"{prefix}_variant_count") or 1),
    }
    parent_id = _clean_id(normalized.get(f"{prefix}_parent_id"))
    variant_of = _clean_id(normalized.get(f"{prefix}_variant_of"))
    branch_id = _clean_id(normalized.get("branch_id"))
    if parent_id:
        result["parent_id"] = parent_id
    if variant_of:
        result["variant_of"] = variant_of
    if branch_id:
        result["branch_id"] = branch_id
    return result
