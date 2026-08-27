# -*- coding: utf-8 -*-
"""历史获取与清洗（簇 A）。

职责：从 memory_manager + ChatHistoryStore 拉取历史，清洗为可喂给 LLM 的消息列表。
依赖 WeightedMemoryManager / chat_history_store，以及 history_compression 做压缩。
"""

import asyncio
import re
from typing import Any, Dict, List

from config.debug_config import is_debug_enabled
from core.utils.debug_markers import is_debug_context_message
from core.utils.logger import get_logger
from core.utils.time_utils import format_timestamp

from .history_compression import (
    apply_long_message_compression,
    apply_study_session_compression,
)

logger = get_logger("ChatAgent")


def sanitize_history_messages(
    history: List[Dict[str, Any]],
    add_timestamp_prefix: bool = True,
    persona_filename: str = "",
) -> List[Dict[str, Any]]:
    """清理历史消息并可选地添加时间戳前缀。

    Args:
        history: 原始历史消息列表
        add_timestamp_prefix: 是否为每条消息添加时间戳前缀（默认True）
        persona_filename: 角色配置文件名（保留参数，用于未来扩展）

    Returns:
        清理后的历史消息列表
    """
    if not history:
        return []
    sanitized: List[Dict[str, Any]] = []
    placeholder_set = {"我在。刚刚处理了一下上下文，现在可以继续了。"}
    for msg in history:
        content = str(msg.get("content") or "").strip()
        has_reasoning = bool(msg.get("reasoning_content"))
        has_tool_calls = bool(msg.get("tool_calls"))
        if not content and not has_reasoning and not has_tool_calls:
            continue
        content = re.sub(
            r"^(?:\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*)+",
            "",
            content,
        ).strip()
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

        # 为消息添加时间戳前缀
        # 格式保持 [MM-DD HH:MM]，QQ 端 strip_ai_timestamp 依赖此格式做去重
        if add_timestamp_prefix and cleaned:
            ts = msg.get("timestamp", 0)
            if ts:
                try:
                    ts_float = float(ts)
                    if ts_float > 0:
                        time_prefix = f"[{format_timestamp(ts_float, '%m-%d %H:%M')}] "
                        cleaned = time_prefix + cleaned
                except (ValueError, TypeError):
                    pass

        # 平台标记：在消息末尾追加来源标注，让 LLM 区分 QQ / Obsidian 历史
        # 不改时间戳格式，避免破坏 QQ 端的 strip_ai_timestamp 去重逻辑
        _pf = str(msg.get("platform") or "").strip().lower()
        if _pf and _pf != "qq":
            # 存量历史无 platform 默认是 qq，不标注；只标注非 qq 来源
            _pf_label = {"obsidian": "Obsidian"}.get(_pf, _pf.capitalize())
            cleaned = f"{cleaned}（来自{_pf_label}）"

        # 为主动关怀消息添加标记，让主 LLM 知道这是 AI 主动发起的消息
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

        # 双角色剧本消息：按说话者归类，让 LLM 区分这是角色间私聊（不影响实际 QQ 显示）
        # 仅在喂给 LLM 的历史里加标记，memory 和 QQ 消息保持纯台词
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


def _check_recent_learning_context(
    memory_manager: Any, scope: str, is_sensitive_mode: bool
) -> bool:
    """检查最近的历史消息中是否包含learning类别，判断用户是否在学习对话上下文中

    解决问题：bot发题目保存为category=learning，用户回复答案时消息未被识别为学习模式，
    导致learning类别消息被排除，bot看不到自己发的题目。

    策略：查看最近10条消息，如果其中有learning类别的assistant消息（bot出的题），
    说明用户很可能在回答学习问题，应保留learning上下文。
    """
    try:
        # 隐私隔离开关：关闭时 sensitive 记忆也能进上下文
        try:
            from config.integrated_config import get_settings
            privacy_isolation = bool(getattr(getattr(get_settings(), "chat", None), "privacy_isolation", False))
        except Exception:
            privacy_isolation = False
        recent_raw = memory_manager.get_history(
            scope=scope,
            raw=True,
            exclude_categories=["thinking", "profile", "persona_prompt", "context_injection"],
            exclude_sensitive=not is_sensitive_mode and privacy_isolation,
            limit=10,
        )
        if not recent_raw:
            return False
        for m in recent_raw:
            cat = m.get("category")
            role = m.get("role", m.get("source", ""))
            if cat == "learning" and role == "assistant":
                logger.info("Detected recent learning assistant message in history, including learning context")
                return True
        return False
    except Exception as e:
        if is_debug_enabled("context_budget"):
            logger.info(f"_check_recent_learning_context check failed: {e}")
        return False


async def _backfill_from_chat_history_store(
    history: List[Dict[str, Any]],
    memory_manager: Any,
    user_id: str,
    exclude_categories: List[str],
    persona_filename: str = "",
) -> List[Dict[str, Any]]:
    """从 ChatHistoryStore（JSONL文件）补充短期记忆中缺失的对话

    解决程序重启后短期记忆丢失最近的对话的问题（自动保存间隔300秒）。
    修剪逻辑已优化为按马尔科夫性质保留最近对话，此处只需补充重启丢失的部分。

    策略：从 ChatHistoryStore 获取最近对话事件，与短期记忆合并去重。
    """
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
            # 保留主动消息标记，确保 backfill 的主动关怀消息也能被主 LLM 正确识别
            if isinstance(metadata, dict) and metadata.get("is_proactive"):
                entry["is_proactive"] = True
            # 保留平台标记，让 LLM 区分历史来自 QQ / Obsidian
            if isinstance(metadata, dict):
                _pf = metadata.get("platform")
                if _pf:
                    entry["platform"] = str(_pf)
            backfill_items.append(entry)

        if not backfill_items:
            return history

        backfill_items.sort(key=lambda x: x.get("timestamp", 0))
        backfill_sanitized = sanitize_history_messages(
            backfill_items, add_timestamp_prefix=True, persona_filename=persona_filename
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

    依次执行：memory_manager 取历史 → sanitize 清洗 → ChatHistoryStore 回填 →
    长消息压缩 → 学习会话压缩。
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

        should_include_learning = is_study_mode
        if not should_include_learning:
            should_include_learning = _check_recent_learning_context(
                memory_manager, scope, is_sensitive_mode
            )

        exclude_categories = list(base_exclude)
        if not should_include_learning:
            exclude_categories.append("learning")

        def _get_history_sync():
            try:
                # 隐私隔离开关：关闭时 sensitive 记忆也能进上下文
                try:
                    from config.integrated_config import get_settings
                    privacy_isolation = bool(
                        getattr(getattr(get_settings(), "chat", None), "privacy_isolation", False)
                    )
                except Exception:
                    privacy_isolation = False
                return memory_manager.get_history(
                    scope=scope,
                    exclude_categories=exclude_categories,
                    exclude_sensitive=not is_sensitive_mode and privacy_isolation,
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
        history = sanitize_history_messages(history, persona_filename=persona_filename)

        history = await _backfill_from_chat_history_store(
            history,
            memory_manager,
            user_id,
            exclude_categories,
            persona_filename=persona_filename,
        )

        # 对非近期窗口的长 assistant 消息进行上下文压缩
        # （仅影响喂给 LLM 的历史，不修改 STM 原文，搜索不受影响）
        history = apply_long_message_compression(history)

        # 学习会话压缩：当用户退出学习模式后，压缩学习过程中的上下文
        # 检测学习→非学习的边界，将学习部分替换为摘要
        history = apply_study_session_compression(history)

        logger.info(
            f"Retrieved {len(history)} history items for {user_id} "
            f"(Scope: {scope}, include_learning={should_include_learning})"
        )
    except Exception as e:
        logger.warning(f"get_history 执行失败: {e}")
    return history
