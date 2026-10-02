"""QQ 会话 ID 与跨平台 conversation_id 工具。"""

from __future__ import annotations

import hashlib
import re


def parse_session_user_id(session_id: str) -> str:
    """从 session_id 中解析出 qq_user_id。

    支持的格式：
    - private_<qq_id>
    - peer_<qq_id>
    - group_<group_id>_<qq_id>
    """
    parts = str(session_id or "").split("_")
    if parts and parts[0] in ("private", "peer") and len(parts) >= 2:
        return str(parts[1])
    if parts and parts[0] == "group" and len(parts) >= 3:
        return str(parts[2])
    return ""


def build_persona_conversation_id(session_id: str, persona_filename: str) -> str:
    """构建跨平台共享的 conversation_id

    所有平台（QQ/Telegram/websocket/Android）使用同一 persona 时返回相同的 cid：
    `shared__persona__{slug}`，让聊天历史和记忆跨平台互通。

    session_id 参数保留为兼容签名，但实际不再用作前缀（用 "shared"）。
    """
    try:
        from core.utils.data_paths import build_shared_persona_conversation_id
    except Exception:
        # 兜底：data_paths 不可用时回退到原实现（用 shared 当 base）
        base = "shared"
        raw = str(persona_filename or "").strip()
        if not raw:
            return base
        normalized = raw.replace("\\", "/").strip("/")
        stem = normalized.rsplit("/", 1)[-1]
        if "." in stem:
            stem = stem.rsplit(".", 1)[0]
        safe = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", stem).strip("_").lower()
        if not safe:
            digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
            safe = f"persona_{digest}"
        return f"{base}__persona__{safe}"
    return build_shared_persona_conversation_id(persona_filename)
