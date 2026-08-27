# -*- coding: utf-8 -*-
"""云端/本地上下文预算裁剪（簇 C）。

职责：按 token/字符预算裁剪历史。
- apply_cloud_history_budget：云端模式，按相关性+消息数+字符数三重裁剪
- apply_local_context_budget：本地模式，按 n_ctx 预算切片+可选压缩
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from ._utils import safe_float, safe_int, extract_match_tokens

logger = get_logger("ChatAgent")


def _select_relevant_history_for_cloud(
    history: List[Dict[str, Any]],
    query: str,
    keep_recent: int,
    top_k: int,
    candidate_window: int,
) -> List[Dict[str, Any]]:
    """按 query 关键词相关性从历史中选择消息，叠加 keep_recent 兜底。"""
    if not history:
        return []

    keep_recent = max(0, int(keep_recent))
    top_k = max(0, int(top_k))
    candidate_window = max(1, int(candidate_window))

    query_tokens = extract_match_tokens(query)
    tail_start = max(0, len(history) - keep_recent)
    recent_idx = set(range(tail_start, len(history)))
    candidates_start = max(0, tail_start - candidate_window)

    scored: List[tuple[float, int]] = []
    for i in range(candidates_start, tail_start):
        msg = history[i]
        content = str(msg.get("content") or "")
        if not content.strip():
            continue
        score = 0.0
        msg_tokens = extract_match_tokens(content)
        if query_tokens and msg_tokens:
            overlap = query_tokens.intersection(msg_tokens)
            if overlap:
                score += float(len(overlap)) * 1.8
        if query and query.strip() and query.strip() in content:
            score += 2.0
        role = str(msg.get("role") or "")
        if role == "user":
            score += 0.35
        score += float(i) * 1e-6
        if score > 0.0:
            scored.append((score, i))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked_idx = set(recent_idx)
    for _, idx in scored[:top_k]:
        picked_idx.add(idx)

    selected = [history[i] for i in sorted(picked_idx) if 0 <= i < len(history)]
    return selected


def apply_cloud_history_budget(
    history: List[Dict[str, Any]], message: str
) -> List[Dict[str, Any]]:
    """云端模式历史预算：相关性选择 + 消息数上限 + 字符数上限。"""
    if not history:
        return history
    cloud_max_history_messages = 18
    cloud_max_history_chars = 6000
    cloud_relevance_keep_recent = 8
    cloud_relevance_top_k = 12
    cloud_relevance_candidate_window = 80
    try:
        from config.integrated_config import get_settings

        s = get_settings()
        chat = getattr(s, "chat", None)
        budget = getattr(chat, "context_budget", None) if chat is not None else None
        if budget is not None:
            cloud_max_history_messages = safe_int(
                getattr(budget, "cloud_max_history_messages", cloud_max_history_messages),
                cloud_max_history_messages,
            )
            cloud_max_history_chars = safe_int(
                getattr(budget, "cloud_max_history_chars", cloud_max_history_chars),
                cloud_max_history_chars,
            )
            cloud_relevance_keep_recent = safe_int(
                getattr(budget, "cloud_relevance_keep_recent", cloud_relevance_keep_recent),
                cloud_relevance_keep_recent,
            )
            cloud_relevance_top_k = safe_int(
                getattr(budget, "cloud_relevance_top_k", cloud_relevance_top_k),
                cloud_relevance_top_k,
            )
            cloud_relevance_candidate_window = safe_int(
                getattr(budget, "cloud_relevance_candidate_window", cloud_relevance_candidate_window),
                cloud_relevance_candidate_window,
            )
    except Exception:
        pass

    logger.info(f"[Cloud History Budget] 原始历史记录: {len(history)} 条消息")
    original_chars = sum(len(str(m.get("content", ""))) for m in history)
    logger.info(f"[Cloud History Budget] 原始总字符数: {original_chars}")

    selected = _select_relevant_history_for_cloud(
        history=history,
        query=message or "",
        keep_recent=cloud_relevance_keep_recent,
        top_k=cloud_relevance_top_k,
        candidate_window=cloud_relevance_candidate_window,
    )
    if selected:
        history = selected

    if cloud_max_history_messages > 0 and len(history) > cloud_max_history_messages:
        history = history[-cloud_max_history_messages:]

    if cloud_max_history_chars > 0:
        clipped: List[Dict[str, Any]] = []
        total_chars = 0
        for msg in reversed(history):
            c = str(msg.get("content") or "")
            c_len = len(c)
            if total_chars + c_len > cloud_max_history_chars:
                break
            clipped.insert(0, msg)
            total_chars += c_len
        history = clipped

    final_chars = sum(len(str(m.get("content", ""))) for m in history)
    logger.info(
        "Cloud history selection applied: selected=%s messages, %s chars (max_messages=%s, max_chars=%s)",
        str(len(history)),
        str(final_chars),
        str(cloud_max_history_messages),
        str(cloud_max_history_chars),
    )
    return history


async def apply_local_context_budget(
    history: List[Dict[str, Any]],
    messages: List[Dict[str, str]],
    user_message: str,
    active_tools: List[str],
    compress_history_fn: Callable[[List[Dict[str, Any]], int, str, int, float], Awaitable[str]],
) -> Tuple[List[Dict[str, Any]], str]:
    """本地模式上下文预算：按 n_ctx 计算可用字符，切片历史+可选压缩更早对话。"""
    if history:
        total_history_chars = sum(len(msg.get("content", "")) for msg in history)
        if total_history_chars > 10000:
            logger.info(
                "Local history is large (%s chars). Will slice context without clearing memory.",
                str(total_history_chars),
            )

    try:
        from config.integrated_config import get_settings

        s = get_settings()
        n_ctx = safe_int(getattr(getattr(s, "model", None), "n_ctx", 0), 2048)
        chat = getattr(s, "chat", None)
        budget = getattr(chat, "context_budget", None) if chat is not None else None
        compress = getattr(chat, "context_compress", None) if chat is not None else None
    except Exception:
        n_ctx = 2048
        budget = None
        compress = None

    budget_enabled = True
    local_chars_per_token = 1.5
    buffer_chars = 200
    min_history_chars = 500
    image_history_cap = 800
    max_total_chars_cap = 24000
    max_user_message_chars_setting = 2400
    if budget is not None:
        budget_enabled = bool(getattr(budget, "enabled", budget_enabled))
        local_chars_per_token = safe_float(
            getattr(budget, "local_chars_per_token", local_chars_per_token),
            local_chars_per_token,
        )
        buffer_chars = safe_int(getattr(budget, "buffer_chars", buffer_chars), buffer_chars)
        min_history_chars = safe_int(
            getattr(budget, "min_history_chars", min_history_chars), min_history_chars
        )
        image_history_cap = safe_int(
            getattr(budget, "image_tool_history_cap_chars", image_history_cap),
            image_history_cap,
        )
        max_total_chars_cap = safe_int(
            getattr(budget, "max_total_chars_cap", max_total_chars_cap),
            max_total_chars_cap,
        )
        max_user_message_chars_setting = safe_int(
            getattr(budget, "max_user_message_chars", max_user_message_chars_setting),
            max_user_message_chars_setting,
        )
    if not budget_enabled:
        return history, user_message

    current_used_chars = sum(len(m.get("content", "")) for m in messages)
    max_total_chars = int(n_ctx * float(local_chars_per_token))
    max_total_chars = max(2000, max_total_chars - int(buffer_chars))
    if max_total_chars_cap:
        max_total_chars = min(int(max_total_chars), int(max_total_chars_cap))

    max_user_message_chars = min(
        int(max_user_message_chars_setting),
        max(500, int(max_total_chars * 0.8)),
    )
    if user_message and len(user_message) > max_user_message_chars:
        user_message = user_message[-max_user_message_chars:]

    current_used_chars += len(user_message or "")
    available_chars_for_history = max(
        int(min_history_chars), int(max_total_chars - current_used_chars)
    )
    if "generate_image" in active_tools:
        available_chars_for_history = min(
            int(available_chars_for_history), int(image_history_cap)
        )

    sliced_history: List[Dict[str, Any]] = []
    current_history_chars = 0
    for msg in reversed(history):
        content_len = len(msg.get("content", ""))
        if current_history_chars + content_len > available_chars_for_history:
            break
        sliced_history.insert(0, msg)
        current_history_chars += content_len

    compressed_msg: Optional[Dict[str, Any]] = None
    if len(sliced_history) < len(history):
        truncated_block = history[: len(history) - len(sliced_history)]
        compress_enabled = True
        compress_max_summary_chars = 900
        compress_min_truncate_chars = 800
        compress_model_path = ""
        compress_timeout_seconds = 0.8
        compress_max_tokens = 160
        compress_api_model = None
        if compress is not None:
            compress_enabled = bool(getattr(compress, "enabled", compress_enabled))
            compress_max_summary_chars = safe_int(
                getattr(compress, "max_summary_chars", compress_max_summary_chars),
                compress_max_summary_chars,
            )
            compress_min_truncate_chars = safe_int(
                getattr(compress, "min_truncate_chars_to_compress", compress_min_truncate_chars),
                compress_min_truncate_chars,
            )
            compress_model_path = str(getattr(compress, "model_path", "") or "").strip()
            compress_api_model = str(getattr(compress, "api_model", "") or "").strip() or None
            compress_timeout_seconds = safe_float(
                getattr(compress, "timeout_seconds", compress_timeout_seconds),
                compress_timeout_seconds,
            )
            compress_max_tokens = safe_int(
                getattr(compress, "max_tokens", compress_max_tokens),
                compress_max_tokens,
            )
        truncated_chars = sum(len(m.get("content", "") or "") for m in truncated_block)
        if compress_enabled and truncated_chars >= int(compress_min_truncate_chars):
            summary_budget = min(
                int(compress_max_summary_chars),
                max(240, int(available_chars_for_history * 0.45)),
            )
            try:
                compressed_text = await compress_history_fn(
                    truncated_block,
                    summary_budget,
                    compress_model_path,
                    compress_max_tokens,
                    compress_timeout_seconds,
                    api_model=compress_api_model,
                )
            except Exception:
                compressed_text = ""
            if compressed_text:
                content = (
                    "【更早对话压缩】\n"
                    + compressed_text.strip()
                    + "\n\n[提示] 以上是更早对话的压缩摘要，可能遗漏了部分细节。"
                    "如果用户提到之前聊过的内容而你不确定，"
                    "请使用 search_chat_history 工具搜索原始聊天记录，"
                    "或使用 search_memory 工具搜索记忆摘要。"
                )
                compressed_msg = {"role": "system", "content": content}
                available_chars_for_history = max(
                    int(min_history_chars),
                    int(available_chars_for_history - len(content)),
                )

        sliced_history = []
        current_history_chars = 0
        for msg in reversed(history):
            content_len = len(msg.get("content", ""))
            if current_history_chars + content_len > available_chars_for_history:
                break
            sliced_history.insert(0, msg)
            current_history_chars += content_len
        logger.info(
            "Local LLM Context Slicing: %s -> %s messages (%s chars). Total approx: %s / %s",
            str(len(history)),
            str(len(sliced_history)),
            str(current_history_chars),
            str(
                current_used_chars
                + current_history_chars
                + (len(compressed_msg.get("content")) if compressed_msg else 0)
            ),
            str(max_total_chars),
        )

    if compressed_msg is not None:
        return [compressed_msg] + sliced_history, user_message
    return sliced_history, user_message
