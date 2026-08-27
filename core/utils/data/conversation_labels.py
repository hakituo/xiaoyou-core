import re
from typing import Dict, List


def _sanitize_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "default"
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._")
    return text[:80] or "default"


def _resolve_scope_from_active_persona() -> str:
    try:
        from core.character.managers.persona_manager import get_persona_manager
        current_filename = get_persona_manager().get_current_filename()
        if current_filename:
            fn_lower = str(current_filename).strip().lower()
            if "ling" in fn_lower or "core_ling" in fn_lower:
                return "ling"
            if "aveline" in fn_lower or "core_aveline" in fn_lower:
                return "aveline"
    except Exception:
        pass
    return "aveline"


def is_external_or_internal_conversation_id(conversation_id: str) -> bool:
    cid = str(conversation_id or "").strip()
    if not cid:
        return True

    lowered = cid.lower()
    if lowered in {"null", "none"}:
        return True
    # 注意：Telegram adapter 用 `tg_{chat_id}` 格式（见 clients/bots/telegram/adapter.py:108），
    # 必须把 `tg_` 也识别为外部会话，否则 is_primary_user_conversation_id 会把
    # `tg_6867233990` 之类误判为主用户会话，导致 active_care 往已禁用的 Telegram cid 写主动消息。
    if lowered.startswith(("group_", "private_", "peer_", "tg_", "telegram_group_", "telegram_private_")):
        return True
    if lowered.endswith("_local"):
        return True
    if any(token in lowered for token in ("__circle__", "__bg__", "__persona__")):
        return True
    return False


def is_primary_user_conversation_id(conversation_id: str) -> bool:
    cid = str(conversation_id or "").strip()
    if not cid:
        return False
    lowered = str(cid).lower()
    if lowered in {"default", "default_user"}:
        return True
    # Master QQ ID's private conversation is also primary user
    try:
        from clients.bots.qq.settings import MASTER_QQ_ID
        master_id = str(MASTER_QQ_ID or "").strip()
        if master_id and lowered == f"private_{master_id}":
            return True
    except Exception:
        pass
    return not is_external_or_internal_conversation_id(cid)


def get_conversation_label_info(conversation_id: str) -> Dict[str, object]:
    cid = str(conversation_id or "").strip()
    lowered = cid.lower()

    persona_slug = "default"
    persona_name = "默认会话"
    lane_name = "主线对话"
    storage_scope = "aveline"

    # 判断是否是群聊：只有当 session_id 部分以 "group_" 开头时才是群聊
    # session_id 是 conversation_id 的第一部分（在 __persona__ 或 __circle__ 之前）
    # 例如：group_12345_67890__persona__xxx 是群聊
    # 例如：default_user__persona__aveline_qq_group 不是群聊（虽然包含 _group_）
    session_id_part = lowered.split("__")[0] if "__" in lowered else lowered
    is_group_chat = session_id_part.startswith("group_")
    is_peer_chat = session_id_part.startswith("peer_")

    if "__circle__" in lowered:
        circle_token = lowered.split("__circle__", 1)[1].split("__", 1)[0].strip("_")
        if circle_token == "ling":
            lane_name = "后台对话-Ling"
            storage_scope = "ling"
            persona_slug = "wang_ling"
            persona_name = "Ling"
        elif circle_token == "aveline":
            lane_name = "后台对话-七濑 澪"
            storage_scope = "aveline"
            persona_slug = "qilai_wei"
            persona_name = "七濑 澪"
        else:
            lane_name = f"后台对话-{circle_token or 'default'}"
    elif "__persona__" in lowered:
        persona_token = lowered.split("__persona__", 1)[1].split("__", 1)[0].strip("_")
        if persona_token.endswith("core_ling") or persona_token == "core_ling":
            persona_slug = "wang_ling"
            persona_name = "Ling"
            storage_scope = "ling"
        elif persona_token.endswith("core_aveline") or persona_token == "core_aveline":
            persona_slug = "qilai_wei"
            persona_name = "七濑 澪"
            storage_scope = "aveline"
        elif "aveline_qq" in persona_token:
            persona_slug = "qq_aveline"
            persona_name = "七濑 澪"
            if is_group_chat:
                lane_name = "QQ群聊"
            elif is_peer_chat:
                lane_name = "peer_chat"
            else:
                lane_name = "QQ对话"
            storage_scope = "dual_role" if is_peer_chat else "aveline"
        elif "ling_qq" in persona_token:
            persona_slug = "qq_ling"
            persona_name = "Ling"
            if is_group_chat:
                lane_name = "QQ群聊"
            elif is_peer_chat:
                lane_name = "peer_chat"
            else:
                lane_name = "QQ对话"
            storage_scope = "dual_role" if is_peer_chat else "ling"

    if lowered == "default_user":
        persona_slug = "user_workspace"
        persona_name = "用户工作区"
        lane_name = "工作区记忆"
        storage_scope = "user"
    elif lowered.endswith("_local"):
        lane_name = "本地对话"
    elif lowered in {"default", "default_user"}:
        persona_slug = "default"
        persona_name = "默认会话"
        lane_name = "主线对话"
        storage_scope = "user"

    safe_persona = _sanitize_segment(persona_name)
    safe_lane = _sanitize_segment(lane_name)
    mirror_segments: List[str] = [safe_persona]
    mirror_filename = f"{safe_lane}.jsonl"

    return {
        "conversation_id": cid or "default",
        "persona_name": persona_name,
        "persona_slug": persona_slug,
        "lane_name": lane_name,
        "safe_persona": safe_persona,
        "safe_lane": safe_lane,
        "mirror_segments": mirror_segments,
        "chat_segments": [safe_lane],
        "mirror_filename": mirror_filename,
        "readable_title": f"{persona_name} / {lane_name}",
        "storage_scope": storage_scope,
    }
