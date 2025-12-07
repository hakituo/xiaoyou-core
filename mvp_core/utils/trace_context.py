import uuid
import contextvars
from typing import Optional

# 定义 ContextVar 来存储当前的 trace_id
# 默认值为 "system" 或者 None
_trace_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)

class TraceContext:
    """
    链路追踪上下文管理器
    用于在异步调用链中传递 Trace ID
    """
    
    @staticmethod
    def set_trace_id(trace_id: str) -> contextvars.Token:
        """设置当前的 Trace ID"""
        return _trace_id_ctx.set(trace_id)
    
    @staticmethod
    def get_trace_id() -> str:
        """获取当前的 Trace ID，如果没有则生成一个新的或返回默认值"""
        tid = _trace_id_ctx.get()
        if tid is None:
            return "system" # 默认标记为系统内部调用
        return tid
    
    @staticmethod
    def generate_trace_id() -> str:
        """生成一个新的 UUID 作为 Trace ID"""
        return str(uuid.uuid4())
    
    @staticmethod
    def reset_trace_id(token: contextvars.Token):
        """重置 Trace ID 到之前的状态"""
        _trace_id_ctx.reset(token)

    @staticmethod
    def current() -> Optional[str]:
        """获取原始的 ContextVar 值"""
        return _trace_id_ctx.get()
