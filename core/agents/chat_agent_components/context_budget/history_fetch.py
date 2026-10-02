# -*- coding: utf-8 -*-
"""历史获取与清洗（簇 A）。

职责：从 memory_manager + ChatHistoryStore 拉取历史，清洗为可喂给 LLM 的消息列表。
依赖 WeightedMemoryManager / chat_history_store，以及 history_compression 做压缩。
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.data.chat_channel import (
    get_current_platform,
    normalize_platform,
    source_suffix,
    strip_source_suffix,
)
from core.utils.debug_markers import is_debug_context_message
from core.utils.logger import get_logger
from core.utils.privacy import should_exclude_sensitive
from core.utils.time_utils import from_timestamp, get_current_time

from .history_compression import (
    apply_long_message_compression,
    apply_study_session_compression,
)

logger = get_logger("ChatAgent")

# 历史消息里已存在的时间戳前缀（旧数字格式 + 新相对格式）。
# sanitize 前先剥掉，防止同一条消息被二次打前缀时叠加。
_STRIP_EXISTING_TS_PREFIX_RE = re.compile(
    r"^(?:\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*"
    r"|\[(?:今天|昨天|\d+天前) \d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*)+"
)


def _format_relative_time_label(ts: float) -> str:
    """把时间戳格式化为相对时间标签：今天 HH:MM / 昨天 HH:MM / X天前 HH:MM。

    主对话 user 消息前缀已注入绝对「当前时间：YYYY-MM-DD HH:MM」，模型知道今天
    是几号，历史消息用相对词对模型更直观（省去换算），信息量不丢失。
    """
    try:
        msg_dt = from_timestamp(float(ts))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    now = get_current_time()
    day_diff = (now.date() - msg_dt.date()).days
    hm = msg_dt.strftime("%H:%M")
    if day_diff <= 0:
        return f"今天 {hm}"
    if day_diff == 1:
        return f"昨天 {hm}"
    return f"{day_diff}天前 {hm}"


def sanitize_history_messages(
    history: List[Dict[str, Any]],
    add_timestamp_prefix: bool = True,
    persona_filename: str = "",
    current_platform: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """清理历史消息并可选地添加时间戳前缀。

    ``current_platform`` 是「本轮请求发起的渠道」，为 None 时读
    ``chat_channel`` 的 ContextVar。与当前渠道不同的历史消息会追加来源后缀，
    让模型分得清同一会话里混着的多端记录。
    """
    if not history:
        return []
    current = (
        get_current_platform()
        if current_platform is None
        else normalize_platform(current_platform)
    )
    sanitized: List[Dict[str, Any]] = []
    placeholder_set = {"我在。刚刚处理了一下上下文，现在可以继续了。"}
    for msg in history:
        content = str(msg.get("content") or "").strip()
        has_reasoning = bool(msg.get("reasoning_content"))
        has_tool_calls = bool(msg.get("tool_calls"))
        if not content and not has_reasoning and not has_tool_calls:
            continue
        content = _STRIP_EXISTING_TS_PREFIX_RE.sub("", content).strip()
        cleaned = re.sub(
            r"<think.*?</think\s*>", "", content, flags=re.DOTALL | re.IGNORECASE
        ).strip()
        open_idx = cleaned.lower().find("<think")
        if open_idx >= 0:
            cleaned = cleaned[:open_idx].strip()
        cleaned = re.sub(r"</think\s*>", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = cleaned.replace("/think>", "").strip()
        if not cleaned or cleaned in placeholder_set:
            if not has_reasoning and not has_tool_calls:
                continue
            cleaned = ""
        if cleaned and is_debug_context_message(cleaned):
            continue

        copied = dict(msg)

        # 为消息添加相对时间戳前缀：今天 HH:MM / 昨天 HH:MM / X天前 HH:MM。
        # 主 user 消息前缀已注入绝对「当前时间」，历史消息用相对词对模型更直观；
        # 保留方括号，客户端 strip_ai_timestamp 可精确剥掉模型模仿输出的同格式时间戳。
        if add_timestamp_prefix and cleaned:
            ts = msg.get("timestamp", 0)
            if ts:
                label = _format_relative_time_label(ts)
                if label:
                    cleaned = f"[{label}] " + cleaned

        # 渠道标记：与当前渠道不同的历史消息追加来源后缀（QQ 上说的记录在 App 里
        # 显示为「（来自QQ）」），让模型区分同一会话里混着的多端记录。
        # 与当前渠道一致时不标 —— App 上看 App 历史保持零噪音；prompt 里的
        # 「当前渠道：X」负责告诉模型「没标的就是本渠道」。
        suffix = source_suffix(msg, current)
        if suffix:
            cleaned = strip_source_suffix(cleaned) + suffix

        # 为主动关怀消息添加标记，让主 LLM 知道这是 AI 主动发起的消息。
        metadata = msg.get("metadata") or {}
        is_proactive = bool(
            msg.get("is_proactive")
            or (isinstance(metadata, dict) and metadata.get("is_proactive"))
            or (
                isinstance(metadata, dict)
                and str(metadata.get("type") or "").strip().lower() == "proactive"
            )
            or str(msg.get("type") or "").strip().lower() == "proactive"
            or str(msg.get("event_type") or "").strip().lower() == "proactive_message"
        )
        if is_proactive:
            copied["is_proactive"] = True
        if is_proactive and cleaned:
            cleaned = "[主动消息] " + cleaned

        # 双角色剧本消息：按说话者归类，让 LLM 区分这是角色间私聊。
        is_peer_script_msg = bool(
            (isinstance(metadata, dict) and metadata.get("is_peer_script"))
            or str(msg.get("category") or "").strip().lower() == "peer_chat"
        )
        if is_peer_script_msg and cleaned:
            speaker = ""
            if isinstance(metadata, dict):
                speaker = str(metadata.get("peer_speaker") or "").strip()
            if speaker:
                cleaned = f"[与{speaker}的私聊] " + cleaned
            else:
                cleaned = "[角色间私聊] " + cleaned

        if has_tool_calls and not cleaned:
            copied["content"] = None
        else:
            copied["content"] = cleaned
        sanitized.append(copied)
    return sanitized


def _get_recent_learning_context_state(
    memory_manager: Any, scope: str, is_sensitive_mode: bool
) -> Tuple[bool, float]:
    """返回最近是否仍有学习上下文，以及最近 learning assistant 的时间戳。"""
    try:
        recent_raw = memory_manager.get_history(
            scope=scope,
            raw=True,
            exclude_categories=["thinking", "profile", "persona_prompt", "context_injection"],
            exclude_sensitive=should_exclude_sensitive(is_sensitive_mode=is_sensitive_mode),
            limit=10,
        )
        if not recent_raw:
            return False, 0.0

        latest_ts = 0.0
        detected = False
        for msg in recent_raw:
            category = str(msg.get("category") or "").strip().lower()
            role = str(msg.get("role", msg.get("source", "")) or "").strip().lower()
            if category != "learning" or role != "assistant":
                continue
            detected = True
            try:
                latest_ts = max(latest_ts, float(msg.get("timestamp", 0) or 0))
            except (TypeError, ValueError):
                pass

        if detected:
            logger.info(
                "Detected recent learning assistant message in history, including learning context"
            )
        return detected, latest_ts
    except Exception as e:
        if is_debug_enabled("context_budget"):
            logger.info(f"_get_recent_learning_context_state check failed: {e}")
        return False, 0.0


def _check_recent_learning_context(
    memory_manager: Any, scope: str, is_sensitive_mode: bool
) -> bool:
    """兼容旧调用：检查最近是否仍有 learning 类别的 assistant 消息。"""
    detected, _ = _get_recent_learning_context_state(
        memory_manager, scope, is_sensitive_mode
    )
    return detected


def _get_explicit_study_session_state(
    user_id: str,
) -> Tuple[Optional[bool], float, float]:
    """读取 enter/exit_study_mode 维护的显式会话状态。

    Returns:
        (active, entered_at, exited_at)。没有显式会话时 active 为 None。
    """
    try:
        from core.tools.study_mode_tool import get_study_session

        session = get_study_session(user_id)
        if not isinstance(session, dict):
            return None, 0.0, 0.0
        active = bool(session.get("active"))
        try:
            entered_at = float(session.get("entered_at", 0) or 0)
        except (TypeError, ValueError):
            entered_at = 0.0
        try:
            exited_at = float(session.get("exited_at", 0) or 0)
        except (TypeError, ValueError):
            exited_at = 0.0
        return active, entered_at, exited_at
    except Exception as e:
        if is_debug_enabled("context_budget"):
            logger.info(f"读取显式学习会话状态失败: {e}")
        return None, 0.0, 0.0


async def _backfill_from_chat_history_store(
    history: List[Dict[str, Any]],
    memory_manager: Any,
    user_id: str,
    exclude_categories: List[str],
    persona_filename: str = "",
) -> List[Dict[str, Any]]:
    """从 ChatHistoryStore（JSONL文件）补充短期记忆中缺失的对话。"""
    try:
        from core.services.chat_history_store import get_chat_history_store

        store = get_chat_history_store()
        conversation_id = str(user_id or "").strip() or "default"

        def _fetch_events():
            return store.list_conversation_events(
                conversation_id,
                limit=120,
                roles=["user", "assistant"],
            )

        events = await asyncio.to_thread(_fetch_events)
        if not events:
            return history

        existing_ts_set = set()
        for msg in history:
            ts = msg.get("timestamp", 0)
            if ts:
                try:
                    existing_ts_set.add(int(float(ts)))
                except (ValueError, TypeError):
                    pass

        backfill_items: List[Dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_ts = float(event.get("timestamp", 0) or 0)
            if event_ts <= 0:
                continue
            if int(event_ts) in existing_ts_set:
                continue

            role = str(event.get("role") or "").strip().lower()
            if role not in ("user", "assistant"):
                continue

            content = str(event.get("content") or "").strip()
            if not content:
                continue

            event_type = str(event.get("event_type") or "").strip().lower()
            if event_type == "chat_thought":
                continue

            metadata = event.get("metadata") or {}
            if isinstance(metadata, dict) and metadata.get("hidden"):
                continue

            entry: Dict[str, Any] = {
                "role": role,
                "content": content,
                "timestamp": event_ts,
            }
            if isinstance(metadata, dict) and metadata.get("is_proactive"):
                entry["is_proactive"] = True
            # 渠道判据要原样带出来，否则下游只能靠 platform 判定：pairs 导入器只写
            # imported、QQ bot 早期记录只靠 readable_title 车道名，都会漏。
            if isinstance(metadata, dict):
                for hint in ("platform", "imported", "source_kind"):
                    if metadata.get(hint):
                        entry[hint] = metadata[hint]
            readable_title = str(event.get("readable_title") or "")
            if readable_title:
                entry["readable_title"] = readable_title
            backfill_items.append(entry)

        if not backfill_items:
            return history

        backfill_items.sort(key=lambda x: x.get("timestamp", 0))
        backfill_sanitized = sanitize_history_messages(
            backfill_items,
            add_timestamp_prefix=True,
            persona_filename=persona_filename,
        )

        combined = list(history) + backfill_sanitized
        combined.sort(key=lambda x: float(x.get("timestamp", 0) or 0))

        logger.info(
            "短期记忆回填：从 ChatHistoryStore 补充了 %d 条消息（短期记忆原有 %d 条）",
            len(backfill_sanitized),
            len(history),
        )
        return combined
    except Exception as e:
        logger.warning(f"短期记忆回填失败: {e}")
        return history


async def fetch_history_for_scope(
    memory_manager: Any,
    user_id: str,
    scope: str,
    is_sensitive_mode: bool = False,
    is_study_mode: bool = False,
    persona_filename: str = "",
) -> List[Dict[str, Any]]:
    """按 scope 获取历史消息（编排入口）。

    学习模式与普通聊天采用不同的压缩策略：学习进行中保护连续工作记忆；显式退出
    后才把该学习会话收束成摘要。短回答未命中学习关键词时，仍通过最近 learning
    assistant 的时间戳判断是否是同一教学链的延续。
    """
    history: List[Dict[str, Any]] = []
    if not hasattr(memory_manager, "get_history"):
        return history

    try:
        base_exclude = [
            "thinking",
            "profile",
            "persona_prompt",
            "context_injection",
            "peer_chat",
        ]

        recent_learning = False
        recent_learning_ts = 0.0
        if not is_study_mode:
            recent_learning, recent_learning_ts = _get_recent_learning_context_state(
                memory_manager,
                scope,
                is_sensitive_mode,
            )

        explicit_active, entered_at, exited_at = _get_explicit_study_session_state(
            user_id
        )

        should_include_learning = bool(is_study_mode or recent_learning)
        if explicit_active is True:
            should_include_learning = True

        # 显式退出后，只有出现比 exited_at 更新的 learning assistant 才算重新进入
        # 学习链；这样“退出学习模式”的下一轮会立刻触发会话摘要。
        if explicit_active is False and exited_at > 0:
            # 已有明确退出事件时，退出本身优先于“最近 learning”兜底；只有退出之后
            # 又出现新的 learning assistant，才视为重新进入一条学习链。时间戳缺失时
            # 不擅自推翻显式退出状态。
            recent_learning_after_exit = bool(
                recent_learning and recent_learning_ts > exited_at
            )
        else:
            recent_learning_after_exit = recent_learning
        study_context_active = bool(
            is_study_mode
            or explicit_active is True
            or recent_learning_after_exit
        )

        exclude_categories = list(base_exclude)
        if not should_include_learning:
            exclude_categories.append("learning")

        def _get_history_sync():
            try:
                return memory_manager.get_history(
                    scope=scope,
                    exclude_categories=exclude_categories,
                    exclude_sensitive=should_exclude_sensitive(
                        is_sensitive_mode=is_sensitive_mode
                    ),
                )
            except TypeError:
                try:
                    return memory_manager.get_history(scope=scope)
                except TypeError:
                    try:
                        return memory_manager.get_history(scope)
                    except TypeError:
                        return memory_manager.get_history()

        history = await asyncio.to_thread(_get_history_sync)
        history = list(history or [])
        history = sanitize_history_messages(
            history,
            persona_filename=persona_filename,
        )

        history = await _backfill_from_chat_history_store(
            history,
            memory_manager,
            user_id,
            exclude_categories,
            persona_filename=persona_filename,
        )

        # 学习进行中保留更大的连续原文窗口，避免旧长回复先被压成首句。
        history = apply_long_message_compression(
            history,
            study_context_active=study_context_active,
        )

        # 只有当前学习链已经结束才压缩整段会话。
        if not study_context_active:
            force_exit_compression = bool(
                explicit_active is False and entered_at > 0 and exited_at > 0
            )
            history = apply_study_session_compression(
                history,
                force=force_exit_compression,
                session_start_ts=entered_at if force_exit_compression else None,
                session_end_ts=exited_at if force_exit_compression else None,
            )

        logger.info(
            "Retrieved %d history items for %s (Scope: %s, include_learning=%s, "
            "study_context_active=%s)",
            len(history),
            user_id,
            scope,
            should_include_learning,
            study_context_active,
        )
    except Exception as e:
        logger.warning(f"get_history 执行失败: {e}")
    return history
