import hmac
from typing import Any, Dict, Optional
from .error_response import ErrorCode

ERROR_KEY = "error"
ERROR_CODE_KEY = "error_code"
DETAILS_KEY = "details"
REQUEST_ID_KEY = "request_id"


def validate_internal_token(x_internal_token: Optional[str]) -> bool:
    from config.integrated_config import get_settings
    settings = get_settings()
    required = str(getattr(settings.security, "web_access_token", "") or "").strip()
    if not required:
        return True
    provided = str(x_internal_token or "").strip()
    # 使用常量时间比较，防止时序侧信道攻击泄露 token
    try:
        return hmac.compare_digest(provided, required)
    except TypeError:
        return False


def success_response(
    data: Optional[Dict[str, Any]] = None, message: str = "OK"
) -> Dict[str, Any]:
    return {"status": "success", "message": message, "data": data or {}}


def error_response(
    error_code: ErrorCode,
    message: Optional[str] = None,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    msg = message or "Error"
    return {
        "status": "error",
        "message": msg,
        "detail": msg,
        ERROR_KEY: msg,
        ERROR_CODE_KEY: error_code.value,
        DETAILS_KEY: details or {},
        REQUEST_ID_KEY: request_id,
    }
