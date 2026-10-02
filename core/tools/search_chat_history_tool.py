"""SearchChatHistoryTool — 让 LLM 能主动查询原始聊天记录。

与 search_memory（搜索记忆摘要）不同，此工具直接查询 ChatHistoryStore 中的
原始聊天记录，支持按关键词、日期、角色过滤，让 Agent 能真正"翻看"历史对话。

Design principles:
- 结果包含原始对话内容，而非摘要
- 支持按关键词搜索、按日期范围过滤
- 自动限定在当前用户和当前会话的范围内
- 支持搜索与Ling/Aveline的私聊记录（跨角色）
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
from core.services.chat_history_store import _tokenize_query
from core.tools.base import BaseTool
from core.utils.conversation_labels import _sanitize_segment
from core.utils.data.chat_channel import get_current_platform, source_suffix
from core.utils.logger import get_logger
from core.utils.privacy import should_exclude_sensitive

logger = get_logger("SearchChatHistoryTool")


class SearchChatHistoryInput(BaseModel):
    query: str = Field(description="搜索关键词")
    conversation_id: Optional[str] = Field(
        default=None,
        description="会话ID；不填则当前会话所属角色",
    )
    peer_role: Optional[str] = Field(
        default=None,
        description="'ling'(Ling)、'aveline'(Aveline)；不填则当前会话",
    )
    limit: int = Field(
        default=20,
        description="返回条数上限 1-50",
        ge=1,
        le=50,
    )
    roles: Optional[List[str]] = Field(
        default=None,
        description="按角色过滤，如 ['user','assistant']",
    )
    before_date: Optional[str] = Field(
        default=None,
        description="只返回此日期前，YYYY-MM-DD",
    )
    after_date: Optional[str] = Field(
        default=None,
        description="只返回此日期后，YYYY-MM-DD",
    )
    source: Optional[str] = Field(
        default=None,
        description="按平台过滤：qq / obsidian；不填不限",
    )


_PEER_ROLE_NAMES = {
    "ling": "Ling",
    "aveline": "Aveline",
}

# peer_role → 匹配 conversation_id / 文件名的关键词集合
_PEER_MATCH_KEYWORDS: dict[str, list[str]] = {
    "ling": ["ling", "core_ling", "Ling"],
    "aveline": ["aveline", "core_aveline", "七濑", "Aveline"],
}


class SearchChatHistoryTool(BaseTool):
    name = "search_chat_history"
    description = (
        "搜索原始聊天记录，返回真实对话原文而非摘要。"
        "用户提到之前聊过、说过什么时优先用它，不要用 web_search 搜互联网；"
        "记录里确实找不到才考虑联网。只在需要查历史时调用，不要每轮都调。"
        "默认覆盖当前角色全部历史会话；没命中只代表本次没找到，不要据此说记录已删除。"
        "peer_role：回顾你与另一角色的互聊，不要用它窥探主人与该角色的私聊。"
        "source：按平台过滤，qq / obsidian。"
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
                return f"无效的 peer_role 值 '{peer_role}'，可选值：ling（Ling）、aveline（Aveline）。"
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
        query_tokens = _tokenize_query(query)
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
                                payload,
                                query_tokens,
                                normalized_roles,
                                before_ts,
                                after_ts,
                                source,
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
                # 旧记录可能没有 ID；同一事件经当前会话和归档扫描各读一次时仍需去重。
                deduped["legacy:" + json.dumps(item, sort_keys=True, ensure_ascii=False)] = item
        result = sorted(
            deduped.values(), key=lambda e: float(e.get("timestamp") or 0.0)
        )
        if limit > 0 and len(result) > limit:
            result = result[-limit:]
        return result

    # ------------------------------------------------------------------
    # 普通搜索：合并当前会话与同角色归档，再筛选、去重和截断
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
        """搜索当前角色的完整归档，兼容旧会话存储和关键词匹配。

        当前会话命中不能阻断旧会话召回：用户重提关键词时，当前记录往往
        只有这次提问，真正的往事在 QQ、旧客户端或旧会话标识下。
        """
        from core.services.chat_history_store import get_chat_history_store

        indexed = self._search_in_store_indexed(
            conversation_id=conversation_id,
            query=query,
            limit=limit,
            roles=roles,
            before_ts=before_ts,
            after_ts=after_ts,
            source=source,
            scope=scope,
        )
        if indexed is not None:
            return indexed

        store = get_chat_history_store()
        events = store.list_conversation_events(
            conversation_id,
            # 必须先合并、过滤，再截断，避免最新的无效候选占满名额。
            limit=0,
            before=before_ts,
            query=query,
            roles=roles,
        )
        events.extend(
            self._search_in_scope_dir(
                conversation_id=conversation_id,
                query=query,
                limit=0,
                roles=roles,
                before_ts=before_ts,
                after_ts=after_ts,
                source=source,
            )
        )

        if after_ts is not None:
            events = [
                e
                for e in events
                if float(e.get("timestamp") or 0.0) >= after_ts
            ]

        events = [
            e
            for e in events
            if str(e.get("event_type") or "") != "chat_thought"
        ]

        # 按来源平台过滤（基于 metadata.platform）
        if source and source != "all":
            events = [e for e in events if self._match_source(e, source)]

        if should_exclude_sensitive(scope=scope):
            events = [
                e
                for e in events
                if "sensitive"
                not in str(e.get("metadata", {}).get("topics", [])).lower()
            ]

        return self._dedup_and_trim(events, limit)

    # ------------------------------------------------------------------
    # 索引版普通搜索：当前会话 + 同角色文件合并成一次 SQL 查询
    # ------------------------------------------------------------------
    @staticmethod
    def _usable_index(root: Path):
        """返回已补齐到与 JSONL 一致的 SQLite 索引；不可用时返回 None。"""
        try:
            from core.services.chat_history_index import get_history_index

            index = get_history_index(root)
            index.ensure_sync()
            return index if index.is_usable() else None
        except Exception as e:
            if is_debug_enabled("search_history"):
                logger.info(f"chat_history 索引不可用，回退文件扫描: {root} ({e})")
            return None

    def _search_in_store_indexed(
        self,
        *,
        conversation_id: str,
        query: str,
        limit: int,
        roles: Optional[List[str]],
        before_ts: Optional[float],
        after_ts: Optional[float],
        source: str,
        scope: str,
    ) -> Optional[List[dict]]:
        """索引版实现：当前会话文件 + 同角色其它文件，一次查询出全部候选。

        与 ``_search_in_scope_dir`` 的 ``same_role_file`` 语义逐条对齐：
        文件名 stem 身份已知时必须等于当前角色；身份不明（解析为空）放行。
        返回 None 表示索引不可用，由调用方回退现有文件扫描路径。
        """
        from core.utils.data_paths import get_chat_history_dir_for_conversation
        from core.utils.data.scope_registry import matched_persona_scope

        try:
            scope_dir = get_chat_history_dir_for_conversation(conversation_id)
        except Exception as e:
            if is_debug_enabled("search_history"):
                logger.info(f"获取 scope 目录失败: {e}")
            return None
        if not scope_dir or not scope_dir.exists():
            return None

        index = self._usable_index(scope_dir)
        if index is None:
            return None

        current_stem = _sanitize_segment(conversation_id)
        current_role = matched_persona_scope(conversation_id)
        try:
            stems = index.distinct_file_stems()
        except Exception as e:
            if is_debug_enabled("search_history"):
                logger.info(f"读取索引文件清单失败: {e}")
            return None

        allowed_stems = []
        for stem in stems:
            if stem == current_stem:
                continue
            # 历史目录可能混有旧版本误放的其他角色文件；已知身份不能只信目录。
            file_role = matched_persona_scope(stem)
            if not current_role or not file_role or file_role == current_role:
                allowed_stems.append(stem)
        allowed_stems.append(current_stem)

        query_tokens = _tokenize_query(query)
        try:
            events = index.query(
                file_stems=allowed_stems,
                roles=roles,
                exclude_event_types=["chat_thought"],
                platform=source if source and source != "all" else None,
                before=before_ts,
                after=after_ts,
                query_tokens=query_tokens or None,
                limit=0,
            )
        except Exception as e:
            if is_debug_enabled("search_history"):
                logger.info(f"索引查询失败，回退文件扫描: {e}")
            return None

        if should_exclude_sensitive(scope=scope):
            events = [
                e
                for e in events
                if "sensitive"
                not in str((e.get("metadata") or {}).get("topics", [])).lower()
            ]

        return self._dedup_and_trim(events, limit)

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
        """扫描同一 scope 的其它历史会话，避免重复读取当前 conversation。

        解决场景：Ling有 core_ling 和 ling_love 两个会话，
        用户在 QQ 上问"搜小红书"时，conversation_id 是 core_ling，
        但"小红书"的内容在 ling_love 文件里。当前会话已经由 ChatHistoryStore
        单独读取，因此这里明确跳过同名 JSONL，只扩展到同 scope 的其它会话。
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

        logger.info(f"搜索同角色全部历史会话: {scope_dir}")
        from core.utils.data.scope_registry import matched_persona_scope

        current_role = matched_persona_scope(conversation_id)
        current_filename = f"{_sanitize_segment(conversation_id)}.jsonl"

        def same_role_file(path: Path) -> bool:
            if path.name == current_filename:
                return False
            # 历史目录可能混有旧版本误放的其他角色文件；已知身份不能只信目录。
            file_role = matched_persona_scope(path.stem)
            return not current_role or not file_role or file_role == current_role

        return self._scan_events(
            search_roots=[scope_dir],
            query=query,
            limit=limit,
            roles=roles,
            before_ts=before_ts,
            after_ts=after_ts,
            scope="",
            source=source,
            file_filter=same_role_file,
        )

    def _peer_search_indexed(
        self,
        *,
        search_roots: List[Path],
        match_keywords: List[str],
        query: str,
        limit: int,
        roles: Optional[List[str]],
        before_ts: Optional[float],
        after_ts: Optional[float],
        source: str,
    ) -> Optional[List[dict]]:
        """索引版 peer 搜索：各 scope 库分别查询后合并去重。

        与 ``_scan_events(file_filter=...)`` 的匹配语义对齐——现有 file_filter 用
        **完整绝对路径**做关键词包含判断，所以某个 root 自身路径命中关键词时，
        该 root 下所有文件都算命中，否则按相对路径匹配。
        返回 None 表示索引不可用，由调用方回退文件扫描。
        """
        keywords = [
            str(kw).strip().lower() for kw in (match_keywords or []) if str(kw).strip()
        ]
        if not keywords:
            return None

        query_tokens = _tokenize_query(query)
        common = {
            "roles": roles,
            "exclude_event_types": ["chat_thought"],
            "platform": source if source and source != "all" else None,
            "before": before_ts,
            "after": after_ts,
            "query_tokens": query_tokens or None,
            "limit": 0,
        }

        events: List[dict] = []
        usable = False
        for root in search_roots:
            index = self._usable_index(root)
            if index is None:
                continue
            usable = True
            root_matches = any(kw in str(root).lower() for kw in keywords)
            try:
                if root_matches:
                    rows = index.query(**common)
                else:
                    rows = index.query(relative_path_like_any=keywords, **common)
            except Exception as e:
                if is_debug_enabled("search_history"):
                    logger.info(f"peer 索引查询失败，回退文件扫描: {e}")
                return None
            events.extend(rows)

        if not usable:
            return None
        return self._dedup_and_trim(events, limit)

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
                self._peer_search_indexed,
                search_roots=search_roots,
                match_keywords=match_keywords,
                query=query,
                limit=limit,
                roles=roles,
                before_ts=before_ts,
                after_ts=after_ts,
                source=source,
            )
        except Exception as e:
            logger.warning(f"搜索与{peer_name}的聊天记录失败: {e}")
            results = None

        if results is None:
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
                fallback_body = (
                    fallback.split("\n", 1)[-1] if "\n" in fallback else fallback
                )
                return (
                    f"聊天记录中未找到与{peer_name}相关的\"{query}\"，"
                    f"但在记忆摘要中找到相关信息：\n" + fallback_body
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
        """格式化搜索结果

        与当前渠道不同的记录追加「（来自QQ）」这类后缀：模型可能是在 App 里
        翻到 QQ 上的旧对话，不标就分不清这条是不是「刚刚在这里说的」。
        """
        current = get_current_platform()
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
            formatted.append(
                f"- {role_text}{time_label}: {content}{source_suffix(event, current)}"
            )

        if not formatted:
            return "未找到相关聊天记录。"
        header = f"找到 {len(formatted)} 条相关聊天记录：\n"
        return header + "\n".join(formatted)

    def _format_peer_results(self, events: List[dict], peer_name: str) -> str:
        """格式化与另一个角色的聊天记录搜索结果"""
        current = get_current_platform()
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
            formatted.append(
                f"- {role_text}{time_label}: {content}{source_suffix(event, current)}"
            )

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
                    exclude_categories=[
                        "thinking",
                        "profile",
                        "context_injection",
                        "persona_prompt",
                    ],
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