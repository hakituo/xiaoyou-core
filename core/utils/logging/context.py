"""日志请求上下文（request_id / 用户上下文）存储与读取。

与具体 Handler / Formatter 解耦，供 JSONFormatter 等组件读取当前请求的
request_id，便于跨模块日志串联。
"""
import threading


# 请求上下文存储，用于跟踪 request_id
_request_context_local = threading.local()


def set_request_id(request_id: str) -> None:
    """设置当前线程/协程的 request_id。"""
    _request_context_local.request_id = request_id


def get_request_id() -> "str | None":
    """获取当前请求的 request_id。"""
    return getattr(_request_context_local, "request_id", None)
