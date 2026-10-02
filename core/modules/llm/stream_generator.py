"""LLM模块流式生成器
负责流式聊天生成逻辑

拆分说明（薄壳门面 + 按职责拆 mixin 子模块）
--------------------------------------------
原 1116 行单文件按职责拆成下列子模块，``StreamGenerator`` 由 mixin 组合而成，
**对外路径、类名与方法名不变**（``from core.modules.llm.stream_generator import
StreamGenerator`` 照旧可用）：

| 子模块 | 职责 |
|---|---|
| ``stream_generator_params.py``    | 提示词/超时估算、上下文窗口重试、n_ctx 长度夹取 |
| ``stream_generator_runtime.py``   | ``generate`` 主入口、GPU 资源准备与旧模型回退 |
| ``stream_generator_scheduler.py`` | 委派给 C++ 调度器生成 |
| ``stream_generator_worker.py``    | 生产者线程 ``_do_generate``、队列消费与超时恢复 |
| ``stream_generator_gguf.py``      | GGUF 流式生成与 CUDA 失败后的 CPU 重试 |
| ``stream_generator_stream.py``    | chunk 迭代与 Transformers 流式生成 |

本文件保留：模块级 patch 点、``STOP_TOKENS`` 与 ``__init__``。

⚠️ 本门面同时是模块级 patch 点：测试会 patch / 读取本模块的 ``time`` /
``TextIteratorStreamer`` / ``get_torch`` / ``get_resource_lock`` / ``asyncio`` /
``re``（``monkeypatch.setattr(sg, "get_torch", ...)`` 这类**按名重绑定**只有改到
门面才生效），子模块因此在**调用期**从本模块取名，不能顶层 from-import 固化。

拆分是**纯搬家**：未改逻辑、命名与断言，唯一差异是 import 与 mixin 样板行。
"""

import asyncio  # noqa: F401  # 兼容：测试按旧路径 patch sg.asyncio.create_task
import re  # noqa: F401  # 兼容：测试按旧路径 patch sg.re.search
import time  # noqa: F401  # 兼容：测试按旧路径 patch sg.time

try:
    from transformers import TextIteratorStreamer  # noqa: F401  # 兼容：测试 patch 该名字
except ImportError:
    TextIteratorStreamer = None

from core.modules.llm.stream_generator_gguf import StreamGeneratorGgufMixin
from core.modules.llm.stream_generator_params import StreamGeneratorParamsMixin
from core.modules.llm.stream_generator_runtime import StreamGeneratorRuntimeMixin
from core.modules.llm.stream_generator_scheduler import StreamGeneratorSchedulerMixin
from core.modules.llm.stream_generator_stream import StreamGeneratorStreamMixin
from core.modules.llm.stream_generator_worker import StreamGeneratorWorkerMixin
from core.utils.logger import get_logger
from core.utils.resource_lock import get_resource_lock  # noqa: F401  # 兼容：测试 patch 该名字
from .utils import get_torch  # noqa: F401  # 兼容：测试 patch 该名字

# 兼容再导出：原单文件模块顶层可见的工具函数与异常判定（供按旧路径引用）
from contextlib import AsyncExitStack as AsyncExitStack
from core.services.scheduler.inference.inference_utils import (
    clamp_messages as clamp_messages,
    clamp_text as clamp_text,
    rough_estimate_tokens_from_text as rough_estimate_tokens_from_text,
)
from .error_handler import (
    get_error_message as get_error_message,
    is_context_window_error as is_context_window_error,
    is_cuda_backend_error as is_cuda_backend_error,
)
from .inference_utils import (
    build_llama_cpp_chat_kwargs as build_llama_cpp_chat_kwargs,
    strip_unexpected_llama_cpp_kwargs as strip_unexpected_llama_cpp_kwargs,
)
from .utils import (
    is_local_runtime_ready as is_local_runtime_ready,
    normalize_local_path as normalize_local_path,
)

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGenerator(
    StreamGeneratorRuntimeMixin,
    StreamGeneratorParamsMixin,
    StreamGeneratorSchedulerMixin,
    StreamGeneratorWorkerMixin,
    StreamGeneratorGgufMixin,
    StreamGeneratorStreamMixin,
):
    """流式生成器，负责处理流式聊天请求

    具体职责由 mixin 提供（见模块头部表格），本类只保留停止 token 与构造。
    """

    # 定义停止token
    STOP_TOKENS = [
        "User:",
        "user:",
        "\nUser",
        "<|user|>",
        "<|end|>",
        "<|endoftext|>",
        "\n\n\n",
    ]

    def __init__(self, module):
        """
        初始化流式生成器

        Args:
            module: 所属的LLMModule实例
        """
        self.module = module
