"""
错误响应模块

定义系统中使用的标准错误码和API错误类，确保错误处理的一致性。
"""

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


class APIError(Exception):
    """
    API错误类
    用于表示API调用过程中发生的错误
    """
    
    def __init__(self,
                 error_code: ErrorCode,
                 message: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None,
                 original_error: Optional[Exception] = None):
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
            "details": self.details
        }


def create_error_response(error_code: ErrorCode, 
                         message: Optional[str] = None, 
                         details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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