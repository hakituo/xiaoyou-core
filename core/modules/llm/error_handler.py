"""
LLM模块错误处理和诊断工具
"""


def is_oom_error(msg: str) -> bool:
    """检查是否为内存不足错误"""
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "out of memory",
            "cuda error",
            "ggml-cuda",
            "cublas",
            "vram",
            "memory allocation",
            "failed to allocate",
            "not enough memory",
        ]
    )


def is_cuda_backend_error(msg: str) -> bool:
    """检查是否为CUDA后端错误"""
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


def is_invalid_vector_subscript_error(msg: str) -> bool:
    """检查是否为无效的vector subscript错误（通常表示模型文件损坏）"""
    lowered = (msg or "").lower()
    return "invalid vector subscript" in lowered


def is_index_out_of_bounds_error(msg: str) -> bool:
    """检查是否为索引越界错误"""
    lowered = (msg or "").lower()
    return "index" in lowered and "out of bounds" in lowered


def is_context_window_error(msg: str) -> bool:
    """检查是否为上下文窗口超限错误"""
    lowered = (msg or "").lower()
    return "exceed context window" in lowered


def is_model_load_error(msg: str) -> bool:
    """检查是否为模型加载错误"""
    lowered = (msg or "").lower()
    return "failed to load model from file" in lowered


def expand_gpu_layer_candidates(raw_value: int) -> list[int]:
    """
    扩展GPU层数候选列表，用于自动降级策略

    Args:
        raw_value: 原始GPU层数配置

    Returns:
        候选GPU层数列表
    """
    try:
        v = int(raw_value)
    except Exception:
        v = 0

    if v == 0:
        return [0]

    if v < 0:
        # -1 表示使用所有层，失败后尝试逐步减少
        return [v, 48, 32, 24, 16, 8, 0]

    return [v, max(v // 2, 1), max(v // 4, 1), 0]


def get_error_message(error_type: str, details: str = "") -> str:
    """
    获取标准化的错误消息

    Args:
        error_type: 错误类型
        details: 详细错误信息

    Returns:
        格式化的错误消息
    """
    messages = {
        "model_not_found": f"模型路径不存在: {details}",
        "invalid_gguf_header": f"GGUF模型文件头异常，可能文件不完整或已损坏: {details}",
        "gguf_read_error": f"读取GGUF模型文件失败: {details}",
        "llama_cpp_not_installed": (
            "检测到 GGUF 模型但未安装 llama-cpp-python。"
            "Windows 建议使用 Python 3.10-3.12；"
            "CPU 版：pip install llama-cpp-python；"
            "CUDA 版建议安装预编译轮子："
            "pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu128"
        ),
        "invalid_vector_subscript": (
            f"GGUF模型加载失败，底层llama.cpp报告 invalid vector subscript，"
            f"通常表示模型文件损坏或与当前llama-cpp版本不兼容: {details}"
        ),
        "memory_pressure": (
            f"系统内存占用过高({details})，已阻止加载本地模型，请释放内存后重试。"
        ),
        "load_timeout": f"本地模型加载超时（{details}），请检查模型文件或减少并发请求。",
        "load_failed": f"加载文本模型失败: {details}",
        "gguf_load_failed": f"GGUF模型加载失败: {details}",
        "cuda_backend_error": f"GGUF推理触发CUDA后端错误: {details}",
        "first_token_timeout": (
            f"GPU推理在 {details} 秒内没有响应，已自动切换到CPU模式。"
            "请重新发送消息以使用CPU推理。"
        ),
        "thread_lock_timeout": (
            "本地模型推理被占用或已卡死（可能是上一次推理未结束/后端异常）。"
            "建议重启后端；若频繁发生，可尝试将 n_gpu_layers 设为 0 以禁用 CUDA 后端。"
        ),
        "stream_init_failed": "GPU推理stream初始化失败，请检查模型加载状态",
        "context_window_exceeded": f"请求长度超过上下文窗口限制 ({details})，请缩短输入或增加 n_ctx 配置。",
        "transformers_not_installed": "未安装 transformers 库",
        "torch_not_installed": "未安装 torch，无法加载 transformers 文本模型",
        "cloud_model_in_local": f"Local module cannot load cloud model: {details}",
        "scheduler_failed": f"C++ Scheduler 推理失败: {details}",
    }
    return messages.get(error_type, f"未知错误: {details}")
