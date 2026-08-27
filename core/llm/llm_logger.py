"""
统一 LLM 日志模块

集中管理所有 LLM 相关的日志记录，包括：
- API 调用统计（消息数量、字符数、模型名）
- 完整 prompt 日志（受 log_full_prompt 配置控制）
- API 调用追踪（调用次数、来源、调用栈）
- Active Care prompt 摘要

所有 LLM 客户端（OpenAI兼容、SiliconFlow、本地等）统一调用此模块，
避免日志逻辑散落在各个客户端文件中。
"""

import json
import os
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from core.utils.time_utils import now_iso

logger = get_logger("llm_logger")

_project_root = Path(__file__).resolve().parent.parent.parent
_api_call_log = _project_root / "logs" / "api_calls_simple.log"

_api_call_count = 0
if _api_call_log.exists():
    try:
        lines = _api_call_log.read_text(encoding="utf-8").splitlines()
        if lines:
            last_line = json.loads(lines[-1])
            _api_call_count = last_line.get("count", 0)
    except Exception:
        pass


def get_api_call_count() -> int:
    return _api_call_count


def _is_log_full_prompt() -> bool:
    try:
        from config.debug_config import is_debug_enabled
        return is_debug_enabled("log_full_prompt")
    except Exception:
        return False


def _is_api_call_log_enabled() -> bool:
    """是否启用 api_calls_simple.log 调试日志（受 debug_config.api_call_log 控制）"""
    try:
        from config.debug_config import is_debug_enabled
        return is_debug_enabled("api_call_log")
    except Exception:
        return False


def log_llm_call_stats(
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    stream: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    记录 LLM 调用统计信息（统一入口）

    所有 LLM 客户端在发送请求前应调用此方法。

    Args:
        provider: 提供商标识（如 "openai_compat", "siliconflow", "local"）
        model: 模型名称
        messages: 消息列表
        stream: 是否流式
        extra: 额外信息（如 temperature, max_tokens 等）
    """
    num_messages = len(messages)
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    stream_tag = "stream" if stream else "sync"

    if _is_log_full_prompt():
        _log_full_messages(provider, model, messages, extra, num_messages, total_chars, stream_tag)
    else:
        logger.info(
            f"[LLM Call] provider={provider}, model={model}, "
            f"msgs={num_messages}, chars={total_chars}, mode={stream_tag}"
        )


def _log_full_messages(
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
    num_messages: int = 0,
    total_chars: int = 0,
    stream_tag: str = "stream",
) -> None:
    """
    记录完整的消息列表（仅在 log_full_prompt 开启时调用）
    """
    separator = "=" * 60
    logger.info(
        f"\n{separator}\n[Full Prompt] provider={provider}, model={model}, "
        f"msgs={num_messages}, chars={total_chars}, mode={stream_tag}\n{separator}"
    )
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
        # 只输出 system 消息（注入的 prompt），跳过历史和用户消息
        if role != "system":
            logger.info("[消息 %d] role=%s, len=%d (已省略)", i, role, len(content))
            continue
        logger.info("[消息 %d] role=%s, len=%d\n%s", i, role, len(content), content)
    if extra:
        logger.info("[额外参数] %s", json.dumps(extra, ensure_ascii=False, default=str))
    logger.info(separator)


def log_api_call(
    provider: str = "",
    model: str = "",
    prompt_preview: str = "",
    is_retry: bool = False,
) -> None:
    """
    记录一次 API 调用（持久化到 api_calls_simple.log + 日志输出）

    受 logging.api_call_log_enabled 配置控制：开关关闭时直接返回，
    不计数、不写文件、不打日志（生产环境默认关闭）。

    Args:
        provider: 提供商
        model: 模型名
        prompt_preview: prompt 预览
        is_retry: 是否重试
    """
    # 开关关闭：调试日志整体禁用，计数器不增长
    if not _is_api_call_log_enabled():
        return

    global _api_call_count

    pid = os.getpid()
    _api_call_count += 1

    call_stack: List[str] = []
    source = "unknown"
    try:
        stack = inspect.stack()
        for i, frame_info in enumerate(stack[2:], start=2):
            filename = Path(frame_info.filename).name
            func_name = frame_info.function
            lineno = frame_info.lineno

            skip_names = {"log_api_call", "llm_logger"}
            if any(s in filename.lower() for s in skip_names):
                continue

            call_stack.append(f"{filename}:{lineno}({func_name})")

            if source == "unknown":
                source = f"{filename}:{lineno}({func_name})"
    except Exception:
        pass

    log_data = {
        "count": _api_call_count,
        "pid": pid,
        "timestamp": now_iso(),
        "provider": provider,
        "source": source,
        "model": model,
        "is_retry": is_retry,
        "prompt_preview": prompt_preview[:100],
        "call_stack": call_stack[:10],
    }

    try:
        with _api_call_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
    except Exception:
        pass

    retry_tag = " [RETRY]" if is_retry else ""
    log_msg = f"[API Call #{_api_call_count}][PID:{pid}]{retry_tag} provider={provider} model={model}"
    log_msg += f"\n  Source: {source}"
    if call_stack:
        log_msg += "\n  Call Stack:"
        for i, cs in enumerate(call_stack[:5], 1):
            log_msg += f"\n    {i}. {cs}"

    logger.info(log_msg)


def log_active_care_prompt(
    intent: str,
    sections: Dict[str, Dict[str, Any]],
    model: str = "",
) -> None:
    """
    记录 Active Care prompt 摘要

    Args:
        intent: 触发意图
        sections: 各 section 的 {name: {chars: int, preview: str}}
        model: 使用的模型
    """
    total_chars = sum(s.get("chars", 0) for s in sections.values())
    non_empty = sum(1 for s in sections.values() if s.get("chars", 0) > 0)

    logger.info(
        f"[Active Care Prompt] intent={intent}, model={model}, "
        f"total_chars={total_chars}, sections={non_empty}"
    )

    if _is_log_full_prompt():
        for name, info in sections.items():
            chars = info.get("chars", 0)
            preview = info.get("preview", "")
            logger.info(f"  - {name}: chars={chars}, preview={preview[:80]}")


def log_stream_first_chunk(
    provider: str,
    model: str,
    first_content: str,
    ttft_ms: float,
) -> None:
    """
    记录流式首 chunk 信息

    Args:
        provider: 提供商
        model: 模型名
        first_content: 首 chunk 内容
        ttft_ms: 首 token 延迟（毫秒）
    """
    preview = first_content[:50] if first_content else "(empty)"
    logger.info(
        f"[STREAM] provider={provider}, model={model}, "
        f"TTFT={ttft_ms:.0f}ms, first={preview}"
    )


# ============================================================
# Prompt 缓存命中率统计（分级便于筛选复盘）
# ============================================================

_prompt_cache_stats_log = _project_root / "logs" / "prompt_cache_stats.log"

# 缓存命中率分级阈值（>= 阈值的归入该级，从上到下判断）
# S >= 90% 优秀 | A >= 70% 良好 | B >= 50% 一般 | C >= 20% 较低 | D < 20% 很低
CACHE_HIT_LEVELS = (
    (90, "S", "优秀"),
    (70, "A", "良好"),
    (50, "B", "一般"),
    (20, "C", "较低"),
)


def classify_cache_hit_rate(hit: int, miss: int) -> Tuple[Optional[float], str, str]:
    """计算 prompt 缓存命中率并分级

    Args:
        hit: 命中 token 数
        miss: 未命中 token 数

    Returns:
        (命中率 0~1, 等级码, 等级名) 元组；无缓存数据时命中率为 None、等级为 N/A
    """
    total = hit + miss
    if total <= 0:
        return None, "N/A", "无数据"
    rate = hit / total
    for threshold, code, name in CACHE_HIT_LEVELS:
        if rate >= threshold / 100:
            return rate, code, name
    return rate, "D", "很低"


def log_prompt_cache_usage(
    provider: str,
    model: str,
    usage: Optional[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
    key_id: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    """记录一次 LLM 请求的 prompt 缓存命中统计

    数据来源与 DeepSeek 开放平台控制台同源（usage.prompt_cache_hit_tokens /
    prompt_cache_miss_tokens），本地追加到 logs/prompt_cache_stats.log（JSONL），
    便于按命中率等级筛选复盘。

    Args:
        provider: 提供商标识
        model: 模型名
        usage: API 返回的 usage 字段
        extra: 额外标量字段（如请求模式 sync/stream）
    """
    if not isinstance(usage, dict):
        return

    try:
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    except (TypeError, ValueError):
        hit = 0
    try:
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    except (TypeError, ValueError):
        miss = 0

    # 部分 provider 用 prompt_tokens_details 结构兜底
    if hit == 0 and miss == 0:
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            try:
                hit = int(details.get("cached_tokens") or 0)
            except (TypeError, ValueError):
                hit = 0
            try:
                miss = int(details.get("uncached_tokens") or 0)
            except (TypeError, ValueError):
                miss = 0

    rate, level, level_name = classify_cache_hit_rate(hit, miss)
    total = hit + miss
    prompt_tokens = usage.get("prompt_tokens")

    record = {
        "timestamp": now_iso(),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "key_id": key_id,
        "source": source,
        "hit_tokens": hit,
        "miss_tokens": miss,
        "total_cache_tokens": total,
        "prompt_tokens": prompt_tokens if prompt_tokens is not None else total,
        "hit_rate": round(rate, 4) if rate is not None else None,
        "level": level,
        "level_name": level_name,
    }
    if extra:
        for k, v in extra.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                record[k] = v

    try:
        with _prompt_cache_stats_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if rate is not None:
        logger.info(
            "[PromptCache] key_id=%s source=%s provider=%s model=%s hit=%d miss=%d rate=%.1f%% level=%s(%s)",
            key_id, source, provider, model, hit, miss, rate * 100, level, level_name,
        )


def log_context_build(
    scope: str,
    is_cloud: bool,
    is_sensitive: bool,
    history_count: int,
    final_msg_count: int,
    final_total_chars: int,
    timings: Optional[Dict[str, float]] = None,
) -> None:
    """
    记录上下文构建统计

    Args:
        scope: 存储范围
        is_cloud: 是否云端
        is_sensitive: 是否敏感模式
        history_count: 历史消息数
        final_msg_count: 最终消息数
        final_total_chars: 最终总字符数
        timings: 各阶段耗时
    """
    mode_tag = "cloud" if is_cloud else "local"
    sensitive_tag = ", sensitive" if is_sensitive else ""
    logger.info(
        f"[Context Build] scope={scope}, mode={mode_tag}{sensitive_tag}, "
        f"history={history_count}, final_msgs={final_msg_count}, "
        f"final_chars={final_total_chars}"
    )
    if timings:
        timing_str = ", ".join([f"{k}: {v:.4f}s" for k, v in timings.items()])
        logger.info(f"[Context Build] timings: {timing_str}")
