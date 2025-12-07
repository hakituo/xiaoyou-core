from typing import Any, Dict, Optional
from .error_response import ErrorCode

ERROR_KEY = "error"
ERROR_CODE_KEY = "error_code"
DETAILS_KEY = "details"
REQUEST_ID_KEY = "request_id"

def success_response(data: Optional[Dict[str, Any]] = None, message: str = "OK") -> Dict[str, Any]:
    return {"status": "success", "message": message, "data": data or {}}

def error_response(error_code: ErrorCode, message: Optional[str] = None, request_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"status": "error", ERROR_KEY: message or "Error", ERROR_CODE_KEY: error_code.value, DETAILS_KEY: details or {}, REQUEST_ID_KEY: request_id}

