from __future__ import annotations


DEBUG_ERROR_PREFIX = "[DEBUG_ERROR]"
DEBUG_INTERNAL_PREFIX = "[DEBUG_INTERNAL]"


def ensure_debug_error_prefix(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return DEBUG_ERROR_PREFIX
    if raw.startswith(DEBUG_ERROR_PREFIX):
        return raw
    return f"{DEBUG_ERROR_PREFIX} {raw}"


def ensure_debug_internal_prefix(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return DEBUG_INTERNAL_PREFIX
    if raw.startswith(DEBUG_INTERNAL_PREFIX):
        return raw
    return f"{DEBUG_INTERNAL_PREFIX} {raw}"


def is_debug_context_message(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if raw.startswith((DEBUG_ERROR_PREFIX, DEBUG_INTERNAL_PREFIX)):
        return True
    if DEBUG_ERROR_PREFIX in raw or DEBUG_INTERNAL_PREFIX in raw:
        return True
    if lowered.startswith("system error:"):
        return True
    if lowered.startswith("error:") and any(
        marker in raw
        for marker in (
            "[REQUEST_FAILED]",
            "[NETWORK_INTERRUPTED]",
            "[SSL_ERROR]",
            "[SYSTEM_INTERNAL_ERROR]",
            "Cannot connect to host",
            "拒绝访问。",
        )
    ):
        return True
    return False
