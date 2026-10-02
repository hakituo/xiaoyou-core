"""
流式聊天管线子包
从 streaming.py 解耦出的各阶段实现：
- preparation: 请求预处理（事件检测、并行任务、情绪注入）
- dynamic_context: 动态上下文收集与消息列表构建
- model_resolution: 模型路径解析、服务端搜索判断、原生工具准备
- tag_stream_parser: 流式标签解析状态机（跨轮次会话）
- postprocess: 回复内容后处理清洗
- empty_retry: 空回复兜底重试
"""
from .dynamic_context import build_stream_messages
from .empty_retry import retry_visible_response
from .model_resolution import (
    detect_server_side_search,
    prepare_native_tools,
    resolve_model_by_persona,
    resolve_model_path,
)
from .postprocess import postprocess_response
from .preparation import StreamPreparation, prepare_stream_request
from .tag_stream_parser import StreamTagSession

__all__ = [
    "StreamPreparation",
    "prepare_stream_request",
    "build_stream_messages",
    "resolve_model_by_persona",
    "resolve_model_path",
    "detect_server_side_search",
    "prepare_native_tools",
    "StreamTagSession",
    "postprocess_response",
    "retry_visible_response",
]
