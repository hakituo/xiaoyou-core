"""
错误响应模块

定义系统中使用的标准错误码和API错误类，确保错误处理的一致性。
"""

import asyncio
import random
from enum import Enum
from typing import Optional, Dict, Any


class ErrorCode(Enum):
    """
    错误码枚举类
    定义系统中所有可能的错误类型及其对应的错误码
    """

    # 系统错误
    INTERNAL_ERROR = "SYSTEM_INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"

    # 请求错误
    INVALID_REQUEST = "INVALID_REQUEST"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_PARAMETER = "INVALID_PARAMETER"

    # 认证授权错误
    UNAUTHORIZED = "UNAUTHORIZED"
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # 资源错误
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"

    # LLM相关错误
    LLM_INFERENCE_ERROR = "LLM_INFERENCE_ERROR"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_MODEL_NOT_FOUND = "LLM_MODEL_NOT_FOUND"
    LLM_API_ERROR = "LLM_API_ERROR"

    # 任务调度错误
    TASK_SCHEDULING_ERROR = "TASK_SCHEDULING_ERROR"
    TASK_CANCELLED = "TASK_CANCELLED"

    # 速率限制错误
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # 业务领域特定错误 (Business Specific Errors)
    # Daily Data
    DAILY_DATA_RECENT_FAILED = "DAILY_DATA_RECENT_FAILED"
    DAILY_DATA_LIST_FAILED = "DAILY_DATA_LIST_FAILED"
    DAILY_DATA_READ_FAILED = "DAILY_DATA_READ_FAILED"
    INVALID_PATH = "INVALID_PATH"

    # Vision & Image
    MISSING_IMAGE = "MISSING_IMAGE"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    VISION_FAILED = "VISION_FAILED"
    IMAGE_GENERATION_FAILED = "IMAGE_GENERATION_FAILED"

    # Media (TTS/STT/Voice)
    STT_FAILED = "STT_FAILED"
    STT_AUDIO_FORMAT_UNSUPPORTED = "STT_AUDIO_FORMAT_UNSUPPORTED"
    TTS_FAILED = "TTS_FAILED"
    TTS_TIMEOUT = "TTS_TIMEOUT"
    VOICES_ERROR = "VOICES_ERROR"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    EMPTY_TEXT = "EMPTY_TEXT"

    # Search & Misc
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    EMPTY_QUERY = "EMPTY_QUERY"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    MISSING_API_KEY = "MISSING_API_KEY"
    SEARCH_FAILED = "SEARCH_FAILED"

    # Chat & Message
    INVALID_MESSAGE_FORMAT = "INVALID_MESSAGE_FORMAT"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"


class APIError(Exception):
    """
    API错误类
    用于表示API调用过程中发生的错误
    """

    def __init__(
        self,
        error_code: ErrorCode,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        初始化API错误

        Args:
            error_code: 错误码枚举值
            message: 错误消息，如果不提供则使用默认消息
            details: 错误详情，包含额外的错误信息
            original_error: 原始异常对象
        """
        self.error_code = error_code
        self.message = message or self._get_default_message(error_code)
        self.details = details or {}
        self.original_error = original_error

        # 调用父类初始化
        super().__init__(self.message)

    def _get_default_message(self, error_code: ErrorCode) -> str:
        """
        获取错误码对应的默认错误消息

        Args:
            error_code: 错误码枚举值

        Returns:
            str: 默认错误消息
        """
        default_messages = {
            ErrorCode.INTERNAL_ERROR: "系统内部错误",
            ErrorCode.SERVICE_UNAVAILABLE: "服务暂时不可用",
            ErrorCode.TIMEOUT_ERROR: "请求超时",
            ErrorCode.INVALID_REQUEST: "无效的请求",
            ErrorCode.MISSING_PARAMETER: "缺少必要参数",
            ErrorCode.INVALID_PARAMETER: "参数值无效",
            ErrorCode.UNAUTHORIZED: "未授权访问",
            ErrorCode.PERMISSION_DENIED: "权限不足",
            ErrorCode.RESOURCE_NOT_FOUND: "资源不存在",
            ErrorCode.RESOURCE_CONFLICT: "资源冲突",
            ErrorCode.LLM_INFERENCE_ERROR: "语言模型推理失败",
            ErrorCode.LLM_RATE_LIMITED: "语言模型调用频率超限",
            ErrorCode.LLM_MODEL_NOT_FOUND: "指定的模型不存在",
            ErrorCode.LLM_API_ERROR: "语言模型API错误",
            ErrorCode.TASK_SCHEDULING_ERROR: "任务调度失败",
            ErrorCode.TASK_CANCELLED: "任务被取消",
            ErrorCode.RATE_LIMIT_EXCEEDED: "请求频率超限",
        }

        return default_messages.get(error_code, "未知错误")

    def to_dict(self) -> Dict[str, Any]:
        """
        将错误对象转换为字典格式

        Returns:
            Dict[str, Any]: 错误信息字典
        """
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "details": self.details,
        }


def create_error_response(
    error_code: ErrorCode,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    创建标准化的错误响应字典

    Args:
        error_code: 错误码枚举值
        message: 自定义错误消息
        details: 错误详情

    Returns:
        Dict[str, Any]: 格式化的错误响应
    """
    return APIError(error_code, message, details).to_dict()


def map_exception_to_error_code(exc: Exception) -> ErrorCode:
    if isinstance(exc, APIError):
        return exc.error_code
    if isinstance(exc, asyncio.TimeoutError):
        return ErrorCode.TIMEOUT_ERROR
    if isinstance(exc, PermissionError):
        return ErrorCode.PERMISSION_DENIED
    if isinstance(exc, FileNotFoundError):
        return ErrorCode.RESOURCE_NOT_FOUND
    if isinstance(exc, (KeyError,)):
        return ErrorCode.MISSING_PARAMETER
    if isinstance(exc, (ValueError, TypeError)):
        return ErrorCode.INVALID_PARAMETER
    if isinstance(exc, ConnectionError):
        return ErrorCode.SERVICE_UNAVAILABLE
    return ErrorCode.INTERNAL_ERROR


def get_friendly_error_message(exc: Exception) -> str:
    """
    将技术异常转换为用户友好的中文提示 (自然口语版)
    """
    try:
        raw = str(exc or "").strip()
    except Exception:
        raw = ""

    lowered = raw.lower()

    # --- 1. 显存/内存炸了 (OOM) ---
    if (
        "cuda" in lowered and ("out of memory" in lowered or "oom" in lowered)
    ) or "cuda oom" in lowered:
        options = [
            "哎呀，显存好像爆了，我得缓缓...",
            "脑容量有点不够用了，能不能少发点或者等会儿再试？",
            "GPU 冒烟了... 咱们歇会儿吧？",
        ]
        return random.choice(options)

    if "out of memory" in lowered or "memoryerror" in lowered or "内存不足" in raw:
        options = [
            "内存吃紧，我有点晕...",
            "东西太多记不住啦，清理一下再来？",
            "系统内存告急，这题太难了...",
        ]
        return random.choice(options)

    # --- 2. 超时 (Timeout) ---
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in lowered or "超时" in raw:
        options = [
            "我想了太久没想出来，要不你再问一遍？",
            "刚才走神了，没跟上你的节奏，再说一次？",
            "信号好像不太好，这句没发出去...",
            "卡住了卡住了，刚刚那是啥？",
        ]
        return random.choice(options)

    # --- 3. 连接问题 (Connection) ---
    if (
        "connection refused" in lowered
        or "connect" in lowered
        and "refused" in lowered
        or "connection closed" in lowered
        or "connection reset" in lowered
    ):
        options = [
            "我和大脑断连了... 后端服务好像没开？",
            "连不上中枢了，是不是网线被拔了？",
            "呼叫失败，服务端没反应诶。",
        ]
        return random.choice(options)

    # --- 4. 调度器未就绪 (Not Ready) ---
    if (
        "c++ gpu worker" in lowered
        or "gpu worker" in lowered
        or "未就绪" in raw
        or "not ready" in lowered
    ):
        options = [
            "我还起床气呢，引擎没热好，稍微等下...",
            "正在加载大脑模块，马上就好！",
            "调度器还没醒，再给我几秒钟...",
        ]
        return random.choice(options)

    # --- 5. 任务取消 (Cancelled) ---
    if (
        isinstance(exc, asyncio.CancelledError)
        or "cancelled" in lowered
        or "task_cancelled" in lowered
    ):
        options = ["好嘞，不说了。", "收到，闭嘴。", "OK，打住。", "行，那听你的。"]
        return random.choice(options)

    # --- 6. 文件/资源缺失 ---
    if isinstance(exc, FileNotFoundError):
        return "好像缺了点什么零件（文件丢失），跑不起来啦。"

    # --- 7. APIError 直接透传 (如果已有 Message) ---
    if isinstance(exc, APIError):
        # 即使是 APIError，也可以稍微润色一下，但为了准确性暂时保留
        return exc.message

    # --- 8. 通用兜底 (Generic Fallback) ---
    # 避免输出太长的技术报错
    fallback_options = [
        "哎呀，出错了...",
        "我不小心绊了一跤（报错了）。",
        "刚才那下没反应过来，出Bug了。",
        "系统开了个小差，报错了。",
    ]
    base_msg = random.choice(fallback_options)

    # 如果有简短的错误信息，附带在后面，方便调试但不过于硬核
    if len(raw) < 30 and "error" not in lowered and "exception" not in lowered and raw:
        return f"{base_msg} ({raw})"

    return base_msg
