"""
推理工具模块
提供消息处理、token估算、上下文裁剪等工具函数
"""


import math
import re
from typing import Any, Optional

from core.utils.logger import get_logger

logger = get_logger(__name__)

# 尝试加载C++加速分词器
try:
    import importlib.util
    _spec = importlib.util.find_spec("fast_tokenizer_py")
    if _spec is not None:
        import fast_tokenizer_py
        _fast_tokenizer = fast_tokenizer_py.FastTokenizer()
        _HAS_CPP_TOKENIZER = True
        logger.info("已加载 C++ 快速分词器 (fast_tokenizer_py)")
    else:
        _fast_tokenizer = None
        _HAS_CPP_TOKENIZER = False
except Exception:
    _fast_tokenizer = None
    _HAS_CPP_TOKENIZER = False

_CJK_PATTERN = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]"
)


def messages_to_text(messages: Any) -> str:
    """将消息列表转换为文本"""
    if isinstance(messages, list):
        parts = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role")
                content = m.get("content")
                if role is None and content is None:
                    parts.append(str(m))
                    continue
                if role is None:
                    parts.append(str(content))
                else:
                    # 使用ChatML格式
                    r_lower = str(role).lower()
                    if r_lower in ("user", "human"):
                        role = "user"
                    elif r_lower in ("assistant", "gpt", "bot", "ai"):
                        role = "assistant"
                    elif r_lower in ("system", "sys"):
                        role = "system"
                    parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
                continue
            parts.append(str(m))
        # 添加assistant生成提示
        parts.append("<|im_start|>assistant\n")
        return "\n".join([str(p) for p in parts if p is not None])
    if not isinstance(messages, str):
        return str(messages)
    return messages


def clamp_text(text: str, limit: int) -> str:
    """限制文本长度"""
    if not isinstance(text, str):
        text = str(text)
    if limit > 0 and len(text) > limit:
        return text[-limit:]
    return text


def clamp_messages(messages: Any, limit: int) -> Any:
    """限制消息列表的总字符数"""
    if not isinstance(messages, list) or limit <= 0:
        return messages

    normalized = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if not role or content is None:
            continue
        normalized.append({"role": str(role), "content": str(content)})

    if not normalized:
        return messages

    sys_msg = None
    rest = normalized
    if normalized and normalized[0].get("role") == "system":
        sys_msg = dict(normalized[0])
        rest = normalized[1:]

    if sys_msg:
        sys_limit = max(256, int(limit * 0.6))
        sys_msg["content"] = str(sys_msg.get("content", ""))[:sys_limit]

    used = len(sys_msg.get("content", "")) if sys_msg else 0
    budget = max(0, limit - used)

    kept = []
    for m in reversed(rest):
        c = m.get("content", "")
        if not c:
            continue
        if len(c) > budget and budget > 0:
            m = dict(m)
            m["content"] = clamp_text(c, budget)
            kept.append(m)
            budget = 0
            break
        if len(c) <= budget:
            kept.append(m)
            budget -= len(c)
        if budget <= 0:
            break

    kept.reverse()
    if sys_msg:
        return [sys_msg, *kept]
    return kept


def rough_estimate_tokens_from_text(text: str) -> int:
    """粗略估算文本的token数（优先使用C++加速，回退到正则检测）"""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return 0
    if not text:
        return 0

    # 优先使用C++加速分词器
    if _HAS_CPP_TOKENIZER and _fast_tokenizer is not None:
        try:
            return _fast_tokenizer.count_tokens(text)
        except Exception:
            pass

    # 回退到Python正则估算
    total = len(text)
    cjk = len(_CJK_PATTERN.findall(text))
    ratio = cjk / max(1, total)
    chars_per_token = 0.6 if ratio >= 0.5 else 2.0
    return max(0, int(total / chars_per_token))


def conservative_estimate_tokens_from_text(text: str) -> int:
    """为 C++ 上下文保护提供不依赖具体模型词表的保守 token 估算。"""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return 0
    if not text:
        return 0

    cjk = len(_CJK_PATTERN.findall(text))
    non_cjk = max(0, len(text) - cjk)
    unicode_safe_estimate = math.ceil(cjk * 2.0 + non_cjk / 3.0)
    return max(rough_estimate_tokens_from_text(text), unicode_safe_estimate)


def estimate_prompt_tokens(llm: Any, messages: Any) -> Optional[int]:
    """估算提示的token数"""
    if not isinstance(messages, list):
        try:
            text = str(messages)
        except Exception:
            return None
        payload = text
    else:
        parts = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            content = m.get("content")
            if role is None or content is None:
                continue
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        payload = "\n".join(parts)

    try:
        b = payload.encode("utf-8", errors="ignore")
    except Exception:
        return None

    try:
        toks = llm.tokenize(b)
        return int(len(toks))
    except TypeError:
        try:
            toks = llm.tokenize(b, add_bos=True)
            return int(len(toks))
        except Exception:
            return None
    except Exception:
        return None


def fallback_estimate_messages_tokens(messages: Any) -> Optional[int]:
    """回退的消息token估算"""
    if not isinstance(messages, list):
        try:
            return int(rough_estimate_tokens_from_text(str(messages)))
        except Exception:
            return None
    parts = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role is None or content is None:
            continue
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    try:
        # 增加30%的安全余量
        val = rough_estimate_tokens_from_text("\n".join(parts))
        return int(val * 1.3)
    except Exception:
        return None


def shrink_message_content_to_token_budget(
    llm: Any,
    role: str,
    content: str,
    token_budget: int,
    keep_tail: bool,
) -> str:
    """将消息内容缩减到指定token预算"""
    try:
        s = str(content or "")
    except Exception:
        s = ""
    if token_budget <= 0 or not s:
        return ""

    # 优先使用C++加速截断（仅在keep_tail=True时可用）
    if _HAS_CPP_TOKENIZER and _fast_tokenizer is not None and keep_tail:
        try:
            return _fast_tokenizer.truncate_from_back(s, token_budget)
        except Exception:
            pass

    # 回退到二分查找
    def make(mid: int) -> str:
        if mid <= 0:
            return ""
        return s[-mid:] if keep_tail else s[:mid]

    lo = 0
    hi = len(s)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = make(mid)
        pt = estimate_prompt_tokens(llm, [{"role": role, "content": candidate}])
        if pt is None:
            pt = fallback_estimate_messages_tokens(
                [{"role": role, "content": candidate}]
            )
        if isinstance(pt, int) and pt <= token_budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def trim_messages_for_ctx(llm: Any, messages: Any, ctx: int, reserve: int) -> Any:
    """根据上下文窗口裁剪消息"""
    if not isinstance(messages, list) or ctx <= 0:
        return messages

    normalized = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if not role or content is None:
            continue
        normalized.append({"role": str(role), "content": str(content)})
    if not normalized:
        return messages

    sys_msg = None
    rest = normalized
    if normalized and normalized[0].get("role") == "system":
        sys_msg = dict(normalized[0])
        rest = normalized[1:]

    allowed = max(1, int(ctx) - int(reserve))
    if sys_msg is not None:
        sys_tokens = estimate_prompt_tokens(llm, [sys_msg])
        if sys_tokens is None:
            sys_tokens = fallback_estimate_messages_tokens([sys_msg])
        if isinstance(sys_tokens, int) and sys_tokens >= allowed:
            budget = max(1, allowed - 1)
            sys_msg["content"] = shrink_message_content_to_token_budget(
                llm,
                "system",
                sys_msg.get("content", ""),
                budget,
                keep_tail=False,
            )

    kept = []
    last_good = [sys_msg] if sys_msg else []
    for m in reversed(rest):
        candidate_kept = [m, *kept]
        candidate = candidate_kept
        if sys_msg:
            candidate = [sys_msg, *candidate]

        pt = estimate_prompt_tokens(llm, candidate)
        if pt is None:
            pt = fallback_estimate_messages_tokens(candidate)

        if isinstance(pt, int) and pt <= allowed:
            kept = candidate_kept
            last_good = candidate
            continue

        if not kept:
            base = [sys_msg] if sys_msg else []
            base_tokens = estimate_prompt_tokens(llm, base)
            if base_tokens is None:
                base_tokens = fallback_estimate_messages_tokens(base)
            if not isinstance(base_tokens, int) or base_tokens < 0:
                base_tokens = 0

            remaining = max(1, allowed - base_tokens)
            truncated = shrink_message_content_to_token_budget(
                llm,
                str(m.get("role") or "user"),
                m.get("content", ""),
                remaining,
                keep_tail=True,
            )
            if truncated:
                trimmed = {"role": str(m.get("role") or "user"), "content": truncated}
                last_good = [*base, trimmed] if base else [trimmed]
            break

        break

    return last_good
