"""
错误处理工具模块
提供错误检测和友好错误消息转换
"""


def is_oom_error(msg: str) -> bool:
    """检测是否为内存不足错误"""
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "out of memory",
            "cuda error",
            "ggml-cuda",
            "cublas",
            "hip error",
            "vram",
            "memory allocation",
            "failed to allocate",
            "not enough memory",
        ]
    )


def is_cuda_backend_error(msg: str) -> bool:
    """检测是否为CUDA后端错误"""
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "ggml-cuda",
            "cuda error",
            "cublas",
            "hip error",
            "illegal memory access",
            "device-side assert",
            "driver",
        ]
    )


def friendly_llm_error(msg: str) -> str:
    """将技术错误消息转换为用户友好的消息"""
    lowered = (msg or "").lower()

    if (
        "failed to load model from file" in lowered
        or "load model from file" in lowered
        or ("gguf" in lowered and "load" in lowered)
    ):
        return (
            "本地模型加载失败了。请确认GGUF文件完整可用，并尽量释放一些系统内存后再试。"
        )

    if (
        "exceed context window" in lowered
        or "context window of" in lowered
        or "maximum context length" in lowered
    ):
        return (
            "这次对话的内容有点长了，刚刚没有成功生成回复，"
            "你可以换一种说法或分几次发给我。"
        )

    if "out of memory" in lowered or "cuda error" in lowered or "oom" in lowered:
        return "刚刚处理内容时资源有点紧张，你可以稍后再试一次，或者简化一下问题。"

    return "我刚刚有点没反应过来，现在已经恢复了，你可以继续提问。"
