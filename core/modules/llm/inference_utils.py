"""
LLM模块推理工具函数
"""

from typing import Optional, List


def build_llama_cpp_chat_kwargs(
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repetition_penalty: float,
    top_k: Optional[int] = None,
    min_p: Optional[float] = None,
    stop: Optional[List[str]] = None,
    stream: bool = False,
) -> dict:
    """构建 llama_cpp chat completion 的参数"""
    kwargs: dict = {
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "top_p": float(top_p) if top_p is not None else None,
        "repeat_penalty": float(repetition_penalty),
    }
    if stream:
        kwargs["stream"] = True
    if min_p is not None:
        try:
            kwargs["min_p"] = float(min_p)
        except Exception:
            pass
    if top_k is not None:
        try:
            kwargs["top_k"] = int(top_k)
        except Exception:
            pass
    if stop is not None:
        kwargs["stop"] = stop

    return {k: v for k, v in kwargs.items() if v is not None}


def strip_unexpected_llama_cpp_kwargs(kwargs: dict, error_str: str) -> dict:
    """移除 llama_cpp 不支持的参数"""
    lowered = (error_str or "").lower()
    filtered = dict(kwargs)
    for key in ("min_p", "top_k"):
        if key in filtered and f"{key}" in lowered and "unexpected keyword" in lowered:
            filtered.pop(key, None)
    return filtered


def apply_default_template(messages: list, tokenizer=None) -> str:
    """
    应用默认的聊天模板（ChatML 风格）用于 C++ scheduler。
    防止模型看到原始的 "User: ..." 行并产生幻觉。
    """
    try:
        # 如果已加载 tokenizer，尝试使用它
        if tokenizer is not None:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
    except Exception:
        pass

    # 回退到 ChatML（许多 GGUF 模型的标准格式，如 Qwen, Hermes, Yi 等）
    parts = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "")).lower()
        content = str(m.get("content", ""))

        # 映射角色到标准 ChatML 角色
        if role in ("human", "user"):
            role = "user"
        elif role in ("gpt", "assistant", "bot", "ai"):
            role = "assistant"
        elif role in ("system", "sys"):
            role = "system"

        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")

    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)
