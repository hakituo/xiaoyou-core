# -*- coding: utf-8 -*-
"""云端/本地上下文预算裁剪（簇 C）。

职责：按 token/字符预算裁剪历史。
- apply_cloud_history_budget：云端统一取连续最近窗口（起点按块前移以保住缓存前缀）
- apply_local_context_budget：按 n_ctx 预算切片+可选压缩
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from ._utils import safe_float, safe_int

logger = get_logger("ChatAgent")


def _looks_like_active_study_context(
    history: List[Dict[str, Any]],
    message: str,
    user_id: str = "",
) -> bool:
    """识别云端预算阶段是否需要保持连续的学习工作记忆。"""
    if user_id:
        try:
            from core.tools.study_mode_tool import is_study_mode_active

            if is_study_mode_active(user_id):
                return True
        except Exception:
            pass

    try:
        from core.services.study.mode_detector import is_study_mode

        if is_study_mode(str(message or "")):
            return True
    except Exception:
        pass

    # 短回答（如“B”“对”）本身没有学习关键词，依赖历史里的 learning 类别续上。
    for msg in history[-10:]:
        if str(msg.get("category") or "").strip().lower() == "learning":
            return True
    return False


def _history_chars(messages: List[Dict[str, Any]]) -> int:
    """统计消息列表的总字符数（与云端字符上限同口径）。"""
    return sum(len(str(m.get("content") or "")) for m in messages)


def _clip_from_tail(
    messages: List[Dict[str, Any]], max_chars: int
) -> List[Dict[str, Any]]:
    """从尾部往前保留消息，直到达到字符上限。

    这是兜底安全网：只在「单块消息本身就超出字符上限」时才会真正裁剪，
    正常路径已由按块推进的字符上限处理。
    """
    clipped: List[Dict[str, Any]] = []
    total_chars = 0
    for msg in reversed(messages):
        content_len = len(str(msg.get("content") or ""))
        if total_chars + content_len > max_chars:
            break
        clipped.insert(0, msg)
        total_chars += content_len
    return clipped


def _align_window_start_to_user(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把窗口起点对齐到最近的 user 消息。

    条数上限与字符上限都可能把窗口切在助手回复上，模型会看到自己的回复却没有
    前面的提问。丢掉开头这几条非 user 消息即可（最多一两条）；
    整段都没有 user 消息时原样返回，避免把历史清空。
    """
    for index, msg in enumerate(messages):
        if str(msg.get("role") or "") == "user":
            return messages[index:]
    return messages


def _message_ts(message: Dict[str, Any]) -> float:
    """取消息时间戳；缺失或非法返回 0。"""
    try:
        return float(message.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0.0


def _resolve_window_start(
    history: List[Dict[str, Any]],
    contiguous_window: int,
    quantize: int,
    quantum_seconds: int,
) -> int:
    """计算云端历史的窗口起点索引。

    **不能用 len(history) 当锚点**：上游历史是「最近 N 条」的滑动列表
    （`list_conversation_events` 带 limit，实测被截在约 100 条），列表一滑动，
    同一个下标就指向不同消息，前缀每轮都对不上，历史块永远命中不了 prompt cache。

    改用时间锚点：把「按条数算出的候选起点」的时刻向下取整到 quantum_seconds
    边界，再往前回退到第一条不早于该边界的消息。只要边界没跨过去，起点就始终
    是同一条消息，历史块才能作为稳定前缀命中缓存。

    回退距离以 quantize 条为上限，保证窗口有界；时间戳缺失时退回条数量化。
    """
    total = len(history)
    candidate = max(0, total - contiguous_window)
    if candidate <= 0 or quantize <= 1:
        return candidate

    anchor_ts = _message_ts(history[candidate])
    if anchor_ts <= 0 or quantum_seconds <= 0:
        return ((candidate + quantize - 1) // quantize) * quantize

    boundary = (int(anchor_ts) // quantum_seconds) * quantum_seconds
    start = candidate
    lower_bound = max(0, candidate - quantize)
    while start > lower_bound and _message_ts(history[start - 1]) >= boundary:
        start -= 1
    return start


def apply_cloud_history_budget(
    history: List[Dict[str, Any]],
    message: str,
    *,
    user_id: str = "",
) -> List[Dict[str, Any]]:
    """云端模式历史预算。

    统一使用「连续最近窗口」：普通聊天取最近 N 条，学习上下文取更小的连续
    工作窗口（题目、推导、用户短回答保持成串）并放宽字符上限。

    历史不再按关键词抽样。抽样会把用户消息单独抽出来、丢掉对应的助手回复，
    模型看到的是「用户连问多句、中间没有任何回应」；而远端召回已由加权记忆、
    core memory 注入和 search_chat_history 工具承担，不需要在这里再抽样一次。

    窗口起点用**时间锚点**（``cloud_history_quantum_seconds``）而不是条数下标：
    上游历史是「最近 N 条」的滑动列表（实测被截在约 100 条），用 len(history)
    算出的起点会冻死、窗口照样每轮滑 1 条，前缀永远对不上；时间锚点则让起点
    在边界跨过之前始终指向同一条消息，历史块才有机会进缓存。
    回退距离以 ``cloud_history_quantize_messages`` 条为上限，窗口因此最多比
    ``cloud_max_history_messages`` 多出这么多条。

    学习窗口同样走时间锚点：此前「精确最近 20 条」逐轮滑动，每个学习请求
    都把历史前缀整个打穿（实测早自习一串 8 个 study 请求全部各自 miss）。
    锚定后同一锚点块内的连续学习请求共享前缀；学习↔普通切换因窗口大小不同
    仍会各断一次前缀，属结构代价。
    """
    if not history:
        return history

    cloud_max_history_messages = 60
    cloud_max_history_chars = 12000
    cloud_history_quantize_messages = 20
    cloud_history_quantum_seconds = 300
    study_active_recent_window = 20
    study_active_cloud_max_history_chars = 18000
    try:
        from config.integrated_config import get_settings

        settings = get_settings()
        chat = getattr(settings, "chat", None)
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
            cloud_history_quantize_messages = safe_int(
                getattr(
                    budget,
                    "cloud_history_quantize_messages",
                    cloud_history_quantize_messages,
                ),
                cloud_history_quantize_messages,
            )
            cloud_history_quantum_seconds = safe_int(
                getattr(
                    budget,
                    "cloud_history_quantum_seconds",
                    cloud_history_quantum_seconds,
                ),
                cloud_history_quantum_seconds,
            )
            study_active_recent_window = safe_int(
                getattr(
                    budget,
                    "study_active_recent_window",
                    study_active_recent_window,
                ),
                study_active_recent_window,
            )
            study_active_cloud_max_history_chars = safe_int(
                getattr(
                    budget,
                    "study_active_cloud_max_history_chars",
                    study_active_cloud_max_history_chars,
                ),
                study_active_cloud_max_history_chars,
            )
    except Exception:
        pass

    study_context_active = _looks_like_active_study_context(
        history,
        message,
        user_id=user_id,
    )
    logger.info(f"[Cloud History Budget] 原始历史记录: {len(history)} 条消息")
    original_chars = sum(len(str(m.get("content", ""))) for m in history)
    logger.info(f"[Cloud History Budget] 原始总字符数: {original_chars}")

    # 连续最近窗口：学习上下文用更小的工作窗口 + 更宽的字符上限，
    # 普通聊天用 cloud_max_history_messages。
    if study_context_active:
        contiguous_window = max(1, study_active_recent_window)
        cloud_max_history_chars = max(
            cloud_max_history_chars,
            study_active_cloud_max_history_chars,
        )
    else:
        contiguous_window = cloud_max_history_messages
    # 学习窗口同样走时间锚点：旧实现「精确最近 20 条」逐轮滑动，每个学习请求
    # 都把历史前缀整个打穿（实测早自习一串 8 个 study 请求全部各自 miss）。
    # 锚定后同一锚点块内的连续学习请求共享前缀，跨块才回落一次，与普通聊天
    # 同一套锯齿经济学；学习↔普通切换因窗口大小不同仍会各断一次，属结构代价。
    # 工作记忆不受影响：呼吸只发生在窗口最老的一端，题目/推导/短回答链始终
    # 完整——逐轮滑动反而把最老消息一条条更快挤出去。
    # 块大小不超过窗口的一半，避免小窗口被压到接近空。
    quantize = max(
        1,
        min(cloud_history_quantize_messages, max(1, contiguous_window // 2)),
    )

    if cloud_max_history_messages > 0:
        contiguous_window = min(contiguous_window, cloud_max_history_messages)

    if contiguous_window > 0:
        total = len(history)
        # 窗口起点用时间锚点，而不是每轮往前滑 1 条：
        # prompt cache 按前缀匹配，起点每轮变 1 条会让整块历史都失效。
        # 详见 _resolve_window_start 的说明。
        window_start = _resolve_window_start(
            history,
            contiguous_window,
            quantize,
            cloud_history_quantum_seconds,
        )
        # 字符上限按块粒度推进，否则它会把锚点好的起点重新逐条滑动。
        if cloud_max_history_chars > 0 and quantize > 1:
            while (
                window_start + quantize <= total
                and _history_chars(history[window_start:]) > cloud_max_history_chars
            ):
                window_start += quantize
        history = history[window_start:]

    # 兜底：单块消息本身就超出字符上限时，退回逐条从尾部裁剪。
    if cloud_max_history_chars > 0:
        history = _clip_from_tail(history, cloud_max_history_chars)

    # 起点对齐到 user 消息，避免窗口以助手回复开头。
    history = _align_window_start_to_user(history)

    final_chars = sum(len(str(m.get("content", ""))) for m in history)
    logger.info(
        "Cloud history selection applied: selected=%s messages, %s chars "
        "(max_messages=%s, max_chars=%s, study_context_active=%s)",
        str(len(history)),
        str(final_chars),
        str(cloud_max_history_messages),
        str(cloud_max_history_chars),
        str(study_context_active),
    )
    return history


async def apply_local_context_budget(
    history: List[Dict[str, Any]],
    messages: List[Dict[str, str]],
    user_message: str,
    active_tools: List[str],
    compress_history_fn: Callable[
        [List[Dict[str, Any]], int, str, int, float], Awaitable[str]
    ],
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

        settings = get_settings()
        n_ctx = safe_int(getattr(getattr(settings, "model", None), "n_ctx", 0), 2048)
        chat = getattr(settings, "chat", None)
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
        buffer_chars = safe_int(
            getattr(budget, "buffer_chars", buffer_chars), buffer_chars
        )
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
                getattr(
                    compress,
                    "min_truncate_chars_to_compress",
                    compress_min_truncate_chars,
                ),
                compress_min_truncate_chars,
            )
            compress_model_path = str(
                getattr(compress, "model_path", "") or ""
            ).strip()
            compress_api_model = (
                str(getattr(compress, "api_model", "") or "").strip() or None
            )
            compress_timeout_seconds = safe_float(
                getattr(compress, "timeout_seconds", compress_timeout_seconds),
                compress_timeout_seconds,
            )
            compress_max_tokens = safe_int(
                getattr(compress, "max_tokens", compress_max_tokens),
                compress_max_tokens,
            )
        truncated_chars = sum(
            len(m.get("content", "") or "") for m in truncated_block
        )
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
