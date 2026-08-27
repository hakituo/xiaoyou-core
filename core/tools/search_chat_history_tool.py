"""SearchChatHistoryTool — 让 LLM 能主动查询原始聊天记录。

与 search_memory（搜索记忆摘要）不同，此工具直接查询 ChatHistoryStore 中的
原始聊天记录，支持按关键词、日期、角色过滤，让 Agent 能真正"翻看"历史对话。

Design principles:
- 结果包含原始对话内容，而非摘要
- 支持按关键词搜索、按日期范围过滤
- 自动限定在当前用户和当前会话的范围内
- 支持搜索与Ling/七濑 澪的私聊记录（跨角色）
- 结果格式化为易读的对话形式
- 统一走 ChatHistoryStore 搜索，peer 搜索扫描所有 chat_history 目录
- 搜索结果找不到时自动回退到记忆摘要搜索
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from config.debug_config import is_debug_enabled
from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("SearchChatHistoryTool")


class SearchChatHistoryInput(BaseModel):
    query: str = Field(
        description="搜索关键词，用于在聊天记录中检索包含该关键词的对话"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="指定会话ID查询。不填则搜索当前会话的记录。",
    )
    peer_role: Optional[str] = Field(
        default=None,
        description="搜索与另一个角色的私聊记录。可选值：'ling'（Ling）、'aveline'（七濑 澪）。不填则搜索当前会话。",
    )
    limit: int = Field(
        default=20,
        description="返回结果数量上限（1-50），默认20",
        ge=1,
        le=50,
    )
    roles: Optional[List[str]] = Field(
        default=None,
        description="按角色过滤，如 ['user', 'assistant']。不填则不限角色。",
    )
    before_date: Optional[str] = Field(
        default=None,
        description="只返回此日期之前的记录，格式 'YYYY-MM-DD'。不填则不限。",
    )
    after_date: Optional[str] = Field(
        default=None,
        description="只返回此日期之后的记录，格式 'YYYY-MM-DD'。不填则不限。",
    )
    source: Optional[str] = Field(
        default=None,
        description=(
            "按来源平台过滤历史记录。可选值：'qq'（仅QQ历史）、'obsidian'（仅Obsidian历史）、"
            "'all'（全部平台，默认）。"
            "当用户明确问'QQ上聊过'、'QQ里说过'时用'qq'；"
            "问'Obsidian上聊过'、'笔记里聊过'时用'obsidian'。"
            "不填则返回所有平台的历史。"
        ),
    )


_PEER_ROLE_NAMES = {
    "ling": "Ling",
    "aveline": "七濑 澪",
}

# peer_role → 匹配 conversation_id / 文件名的关键词集合
_PEER_MATCH_KEYWORDS: dict[str, list[str]] = {
    "ling": ["ling", "core_ling", "Ling"],
    "aveline": ["aveline", "core_aveline", "七濑", "澪"],
}


class SearchChatHistoryTool(BaseTool):
    name = "search_chat_history"
    description = (
        "搜索原始聊天记录。当你需要查看之前聊了什么、对方说过什么话时调用。"
        "这会返回真实的对话内容，不是摘要。"
        "【重要】当用户提到'之前说过'、'上次聊过'、'跟你说过'等涉及过去对话的内容时，"
        "必须优先使用此工具搜索聊天记录，而不是用web_search搜索互联网。"
        "【双角色搜索】当你想回顾'你与该角色之间的互聊(peer chat)记录'——即对方在你们互聊时告诉你的内容——时使用 peer_role 参数。"
        "注意：peer_role 搜索的是你与该角色之间的【互聊记录】，不要用来窥探主人与该角色的私聊内容；"
        "若你想了解主人与另一角色的私事，应通过你与该角色的 peer chat 获知，而非直接翻看他们的私聊。"
        "【来源过滤】当用户明确问'QQ上聊过'、'Obsidian上聊过'时，"
        "使用 source 参数按平台过滤（'qq' 或 'obsidian'），避免混入其他平台的历史。"
        "只有当聊天记录中确实找不到相关信息时，才考虑使用web_search。"
        "不要在每次对话中都调用，只在确实需要查看历史对话时使用。"
    )
    short_description = "搜索原始聊天记录（涉及过去对话时优先使用，而非web_search）"
    args_schema = SearchChatHistoryInput
    category = "memory"
    enabled_by_default = True

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    async def _run(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        peer_role: Optional[str] = None,
        limit: int = 20,
        roles: Optional[List[str]] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        source: Optional[str] = None,
    ) -> str:
        agent = self._get_ctx("agent")
        user_id = self._get_ctx("user_id")
        scope = self._get_ctx("scope", "sfw")

        if not agent:
            return "Error: 缺少上下文（agent），无法搜索聊天记录。"

        # 规范化 source：qq / obsidian / all
        source = (source or "all").strip().lower()
        if source not in ("qq", "obsidian", "all"):
            source = "all"

        before_ts, after_ts = self._parse_date_range(before_date, after_date)

        # ---- peer 搜索（跨角色）----
        if peer_role:
            peer_role = peer_role.strip().lower()
            if peer_role not in _PEER_ROLE_NAMES:
                return f"无效的 peer_role 值 '{peer_role}'，可选值：ling（Ling）、aveline（七濑 澪）。"
            return await self._do_peer_search(
                agent=agent,
                user_id=user_id or "",
                query=query,
                peer_role=peer_role,
                limit=limit,
                roles=roles,
                before_ts=before_ts,
                after_ts=after_ts,
                scope=scope,
                source=source,
            )

        # ---- 普通搜索（当前会话）----
        if not conversation_id:
            conversation_id = user_id or ""
        if not conversation_id:
            return "Error: 缺少会话ID，无法搜索聊天记录。"

        try:
            results = await asyncio.to_thread(
                self._search_in_store,
                conversation_id=conversation_id,
                query=query,
                limit=limit,
                roles=roles,
                before_ts=before_ts,
                after_ts=after_ts,
                scope=scope,
                source=source,
            )
        except Exception as e:
            logger.warning(f"search_chat_history 执行失败: {e}")
            return f"搜索聊天记录时出错: {e}"

        if not results:
            fallback = await self._fallback_search_memory(agent, user_id, query, scope)
            if fallback:
                return fallback
            return "未找到相关聊天记录。建议尝试用不同的关键词搜索，或使用 search_memory 搜索记忆摘要。"

        return self._format_results(results)

    # ------------------------------------------------------------------
    # 统一底层：在指定目录集合中扫描 .jsonl 文件
    # ------------------------------------------------------------------
    def _scan_events(
        self,
        search_roots: List[Path],
        query: str,
        limit: int,
        roles: Optional[List[str]],
        before_ts: Optional[float],
        after_ts: Optional[float],
        scope: str,
        file_filter=None,
        source: str = "all",
    ) -> List[dict]:
        """在多个 chat_history 根目录中扫描并搜索事件。

        Args:
            search_roots: 要扫描的 chat_history 目录列表
            file_filter: 可选 callable(Path) -> bool，用于过滤文件
            source: 来源平台过滤（qq/obsidian/all），基于 metadata.platform
        """
        normalized_query = str(query or "").strip().lower()
        query_tokens = [t for t in normalized_query.split() if t]
        if not query_tokens and normalized_query:
            query_tokens = [normalized_query]
        normalized_roles = {
            str(r).strip().lower() for r in (roles or []) if str(r).strip()
        }

        all_events: List[dict] = []
        for base_dir in search_roots:
            if not base_dir or not base_dir.exists():
                continue
            for file_path in sorted(base_dir.rglob("*.jsonl")):
                if file_filter and not file_filter(file_path):
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            raw = line.strip()
                            if not raw:
                                continue
                            try:
                                payload = json.loads(raw)
                            except Exception:
                                continue
                            if not self._event_matches(
                                payload, query_tokens, normalized_roles,
                                before_ts, after_ts, source,
                            ):
                                continue
                            all_events.append(payload)
                except Exception:
                    continue

        return self._dedup_and_trim(all_events, limit)

    @staticmethod
    def _match_source(event: dict, source: str) -> bool:
        """按来源平台过滤事件。

        source='qq': 包含 platform='qq' 和无 platform 的老数据（老数据默认归 QQ）
        source='obsidian': 仅 platform='obsidian'
        source='all' 或其他: 不过滤
        """
        if not source or source == "all":
            return True
        pf = ""
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            pf = str(metadata.get("platform") or "").strip().lower()
        if source == "qq":
            # 存量历史无 platform 字段，默认归为 QQ（Obsidian 是新接入的）
            return pf in ("", "qq")
        if source == "obsidian":
            return pf == "obsidian"
        return True

    @staticmethod
    def _event_matches(
        payload: dict,
        query_tokens: List[str],
        normalized_roles: set,
        before_ts: Optional[float],
        after_ts: Optional[float],
        source: str = "all",
    ) -> bool:
        """判断单条事件是否满足搜索条件。"""
        # 跳过内心独白
        if str(payload.get("event_type") or "") == "chat_thought":
            return False
        # 来源平台过滤
        if not SearchChatHistoryTool._match_source(payload, source):
            return False
        # 角色过滤
        role = str(payload.get("role") or "system").strip().lower()
        if normalized_roles and role not in normalized_roles:
            return False
        # 时间范围
        try:
            ts = float(payload.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if before_ts is not None and ts >= before_ts:
            return False
        if after_ts is not None and ts < after_ts:
            return False
        # 关键词匹配
        if query_tokens:
            content_lower = str(payload.get("content") or "").lower()
            if not any(token in content_lower for token in query_tokens):
                return False
        return True

    @staticmethod
    def _dedup_and_trim(events: List[dict], limit: int) -> List[dict]:
        """按 event_id 去重，按时间排序，截断到 limit。"""
        deduped: dict[str, dict] = {}
        for item in sorted(events, key=lambda e: float(e.get("timestamp") or 0.0)):
            eid = str(item.get("event_id") or "").strip()
            if eid:
                deduped[eid] = item
            else:
                deduped[f"{item.get('timestamp')}_{len(deduped)}"] = item
        result = list(deduped.values())
        if limit > 0 and len(result) > limit:
            result = result[-limit:]
        return result

    # ------------------------------------------------------------------
    # 普通搜索：通过 ChatHistoryStore（兼容旧行为）+ 同 scope 回退
    # ------------------------------------------------------------------
    def _search_in_store(
        self,
        conversation_id: str,
        query: str,
        limit: int,
        roles: Optional[List[str]],
        before_ts: Optional[float],
        after_ts: Optional[float],
        scope: str,
        source: str = "all",
    ) -> List[dict]:
        """通过 ChatHistoryStore 搜索当前会话（精确匹配优先）。

        如果精确匹配无结果，自动扩展到同一 scope 下的所有聊天文件，
        解决同一角色不同 conversation_id（如 QQ 对话 vs 主线对话）
        之间搜不到记录的问题。
        """
        from core.services.chat_history_store import get_chat_history_store

        store = get_chat_history_store()
        fetch_limit = limit * 3 if after_ts else limit

        events = store.list_conversation_events(
            conversation_id,
            limit=fetch_limit,
            before=before_ts,
            query=query,
            roles=roles,
        )

        if after_ts is not None:
            events = [
                e for e in events
                if float(e.get("timestamp") or 0.0) >= after_ts
            ]

        events = [
            e for e in events
            if str(e.get("event_type") or "") != "chat_thought"
        ]

        # 按来源平台过滤（基于 metadata.platform）
        if source and source != "all":
            events = [e for e in events if self._match_source(e, source)]

        if scope == "sfw":
            try:
                from config.integrated_config import get_settings
                privacy_isolation = bool(
                    getattr(getattr(get_settings(), "chat", None), "privacy_isolation", False)
                )
            except Exception:
                privacy_isolation = False
            if privacy_isolation:
                events = [
                    e for e in events
                    if "sensitive" not in str(e.get("metadata", {}).get("topics", [])).lower()
                ]

        if len(events) > limit:
            events = events[-limit:]

        # ---- 同 scope 回退：精确匹配无结果时扫描同目录下所有文件 ----
        if not events:
            events = self._search_in_scope_dir(
                conversation_id=conversation_id,
                query=query,
                limit=limit,
                roles=roles,
                before_ts=before_ts,
                after_ts=after_ts,
                source=source,
            )

        return events

    def _search_in_scope_dir(
        self,
        conversation_id: str,
        query: str,
        limit: int,
        roles: Optional[List[str]],
        before_ts: Optional[float],
        after_ts: Optional[float],
        source: str = "all",
    ) -> List[dict]:
        """扫描同一 scope 的 chat_history 目录下所有 .jsonl 文件。

        解决场景：Ling有 ling_qq_master 和 ling_love 两个会话，
        用户在 QQ 上问"搜小红书"时，conversation_id 是 ling_qq_master，
        但"小红书"的内容在 ling_love 文件里。此方法自动扩展到同 scope
        的所有文件。
        """
        try:
            from core.utils.data_paths import get_chat_history_dir_for_conversation
            scope_dir = get_chat_history_dir_for_conversation(conversation_id)
        except Exception as e:
            if is_debug_enabled("search_history"):
                logger.info(f"获取 scope 目录失败: {e}")
            return []

        if not scope_dir or not scope_dir.exists():
            return []

        logger.info(
            f"精确搜索无结果，扩展到同 scope 目录: {scope_dir}"
        )
        return self._scan_events(
            search_roots=[scope_dir],
            query=query,
            limit=limit,
            roles=roles,
            before_ts=before_ts,
            after_ts=after_ts,
            scope="",
            source=source,
        )

    # ------------------------------------------------------------------
    # Peer 搜索：跨角色，扫描所有 chat_history 目录
    # ------------------------------------------------------------------
    async def _do_peer_search(
        self,
        agent: Any,
        user_id: str,
        query: str,
        peer_role: str,
        limit: int,
        roles: Optional[List[str]],
        before_ts: Optional[float],
        after_ts: Optional[float],
        scope: str,
        source: str = "all",
    ) -> str:
        """跨角色搜索：扫描所有 chat_history 目录，匹配与 peer_role 相关的文件。"""
        peer_name = _PEER_ROLE_NAMES.get(peer_role, peer_role)
        match_keywords = _PEER_MATCH_KEYWORDS.get(peer_role, [])

        def file_filter(fp: Path) -> bool:
            """宽松匹配：文件名或路径中包含 peer_role 相关关键词即可。"""
            fp_text = str(fp).lower()
            return any(kw.lower() in fp_text for kw in match_keywords)

        try:
            from core.utils.data_paths import get_all_chat_history_dirs
            search_roots = get_all_chat_history_dirs()
        except Exception as e:
            logger.warning(f"获取 chat_history 目录失败: {e}")
            return f"搜索与{peer_name}的聊天记录时出错: {e}"

        try:
            results = await asyncio.to_thread(
                self._scan_events,
                search_roots=search_roots,
                query=query,
                limit=limit,
                roles=roles,
                before_ts=before_ts,
                after_ts=after_ts,
                scope=scope,
                file_filter=file_filter,
                source=source,
            )
        except Exception as e:
            logger.warning(f"搜索与{peer_name}的聊天记录失败: {e}")
            return f"搜索与{peer_name}的聊天记录时出错: {e}"

        if not results:
            # 回退到记忆摘要搜索
            fallback = await self._fallback_search_memory(agent, user_id, query, scope)
            if fallback:
                fallback_body = fallback.split("\n", 1)[-1] if "\n" in fallback else fallback
                return (
                    f"聊天记录中未找到与{peer_name}相关的\"{query}\"，"
                    f"但在记忆摘要中找到相关信息：\n"
                    + fallback_body
                )
            return f"未找到与{peer_name}的相关聊天记录。建议尝试用不同的关键词搜索。"

        return self._format_peer_results(results, peer_name)

    # ------------------------------------------------------------------
    # 日期解析
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_date_range(
        before_date: Optional[str],
        after_date: Optional[str],
    ) -> tuple[Optional[float], Optional[float]]:
        before_ts: Optional[float] = None
        after_ts: Optional[float] = None
        try:
            if before_date:
                from datetime import datetime
                dt = datetime.strptime(before_date.strip(), "%Y-%m-%d")
                before_ts = dt.replace(hour=23, minute=59, second=59).timestamp()
            if after_date:
                from datetime import datetime
                dt = datetime.strptime(after_date.strip(), "%Y-%m-%d")
                after_ts = dt.replace(hour=0, minute=0, second=0).timestamp()
        except ValueError:
            pass
        return before_ts, after_ts

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------
    def _format_results(self, events: List[dict]) -> str:
        """格式化搜索结果"""
        formatted: List[str] = []
        for event in events:
            role = str(event.get("role") or "system").strip()
            content = str(event.get("content") or "")
            if not content:
                continue
            role_map = {"user": "用户", "assistant": "我", "system": "系统"}
            role_text = role_map.get(role, role)
            time_label = ""
            created_at = event.get("created_at")
            if created_at:
                time_label = f" [{created_at}]"
            if len(content) > 300:
                content = content[:300] + "..."
            formatted.append(f"- {role_text}{time_label}: {content}")

        if not formatted:
            return "未找到相关聊天记录。"
        header = f"找到 {len(formatted)} 条相关聊天记录：\n"
        return header + "\n".join(formatted)

    def _format_peer_results(self, events: List[dict], peer_name: str) -> str:
        """格式化与另一个角色的聊天记录搜索结果"""
        formatted: List[str] = []
        for event in events:
            role = str(event.get("role") or "system").strip()
            content = str(event.get("content") or "")
            if not content:
                continue
            role_map = {"user": peer_name, "assistant": "我", "system": "系统"}
            role_text = role_map.get(role, role)
            time_label = ""
            created_at = event.get("created_at")
            if created_at:
                time_label = f" [{created_at}]"
            if len(content) > 300:
                content = content[:300] + "..."
            formatted.append(f"- {role_text}{time_label}: {content}")

        if not formatted:
            return f"未找到与{peer_name}的相关聊天记录。"
        header = f"找到 {len(formatted)} 条与{peer_name}的聊天记录：\n"
        return header + "\n".join(formatted)

    # ------------------------------------------------------------------
    # 记忆摘要回退
    # ------------------------------------------------------------------
    async def _fallback_search_memory(
        self,
        agent: Any,
        user_id: str,
        query: str,
        scope: str,
    ) -> Optional[str]:
        """当聊天记录搜不到时，回退到搜索记忆摘要。"""
        try:
            mm = agent._get_memory_manager(user_id)
            if not mm or not hasattr(mm, "hybrid_search"):
                return None

            def _search():
                return mm.hybrid_search(
                    query,
                    limit=3,
                    min_similarity=0.45,
                    scope=scope,
                    exclude_categories=["thinking", "profile", "context_injection", "persona_prompt"],
                )

            results = await asyncio.to_thread(_search)
            if not results:
                return None

            parts = []
            for mem in results:
                content = mem.get("summary") or mem.get("content", "")
                if not content or len(content) < 5:
                    continue
                ts = mem.get("timestamp")
                time_label = ""
                if ts:
                    try:
                        from core.utils.time_utils import format_timestamp
                        time_label = f" [{format_timestamp(float(ts), '%m-%d %H:%M')}]"
                    except Exception:
                        pass
                if len(content) > 300:
                    content = content[:300] + "..."
                parts.append(f"- 记忆{time_label}: {content}")

            if not parts:
                return None

            return (
                f"聊天记录中未找到\"{query}\"，但在记忆摘要中找到 {len(parts)} 条相关信息：\n"
                + "\n".join(parts)
                + "\n\n（这些是记忆摘要，可能包含不同时间点的信息。如需查看原始对话，请尝试用不同的关键词搜索聊天记录。）"
            )
        except Exception as e:
            if is_debug_enabled("search_history"):
                logger.info(f"回退搜索记忆摘要失败: {e}")
            return None
