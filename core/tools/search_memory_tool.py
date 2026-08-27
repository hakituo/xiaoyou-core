"""SearchMemoryTool — lets the LLM actively search user memories on demand.

Instead of passively injecting memories via RAG (which only triggers on
keyword cues like "记得"/"上次"), the LLM can now call this tool whenever
it feels it needs more context about the user's past.

Design principles:
- Results are concise (summary only, no raw embedding / metadata)
- Sensitive-category memories are excluded by default
- Scope filtering is inherited from the current conversation scope
- The tool uses hybrid_search (keyword + vector) for best recall
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("SearchMemoryTool")


class SearchMemoryInput(BaseModel):
    query: str = Field(
        description="搜索关键词或自然语言描述，用于检索相关记忆和聊天记录"
    )
    limit: int = Field(
        default=5,
        description="返回结果数量上限（1-10），默认5",
        ge=1,
        le=10,
    )
    category: Optional[str] = Field(
        default=None,
        description="按记忆分类过滤，如 preference/event/daily 等。不填则不限分类。",
    )
    include_chat_history: bool = Field(
        default=True,
        description="是否同时搜索聊天记录（默认开启）",
    )
    days_back: Optional[int] = Field(
        default=None,
        description="只搜索最近N天内的聊天记录。不填则搜索全部历史。",
        ge=1,
    )


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = (
        "搜索用户的过往记忆。当你需要回忆用户之前说过的话、偏好、经历等时调用。"
        "不要在每次对话中都调用，只在确实需要回忆过去信息时使用。"
    )
    short_description = "搜索用户过往记忆（需要回忆时调用）"
    args_schema = SearchMemoryInput
    category = "memory"
    enabled_by_default = True

    async def _run(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None,
        include_chat_history: bool = True,
        days_back: Optional[int] = None,
    ) -> str:
        agent = self._get_ctx("agent")
        user_id = self._get_ctx("user_id")
        scope = self._get_ctx("scope", "sfw")

        if not user_id:
            return "Error: 缺少 user_id，无法搜索。"
        
        # agent 可以为 None（只搜索聊天记录），但记录警告
        if not agent:
            logger.debug("agent 上下文为空，将只搜索聊天记录")

        # 搜索长期记忆
        memory_results = []
        try:
            if hasattr(agent, "get_memory_manager_async"):
                memory_manager = await agent.get_memory_manager_async(user_id)
            else:
                memory_manager = agent._get_memory_manager(user_id)
        except Exception:
            memory_manager = None

        if memory_manager and hasattr(memory_manager, "hybrid_search"):
            exclude_categories = ["thinking", "profile", "context_injection", "persona_prompt"]
            if scope == "sfw":
                try:
                    from config.integrated_config import get_settings
                    privacy_isolation = bool(getattr(getattr(get_settings(), "chat", None), "privacy_isolation", False))
                except Exception:
                    privacy_isolation = False
                if privacy_isolation:
                    exclude_categories.append("sensitive")

            try:
                memory_results = await asyncio.to_thread(
                    memory_manager.hybrid_search,
                    query=query,
                    limit=limit,
                    min_similarity=0.45,
                    emotion=None,
                    scope=scope,
                    exclude_categories=exclude_categories,
                    associative_top_k=3,
                    conflict_filter=True,
                )
            except Exception as e:
                logger.warning(f"搜索长期记忆失败: {e}")

        # 搜索聊天记录（只搜索用户消息，排除系统思考）
        chat_results = []
        if include_chat_history:
            try:
                from core.services.chat_history_store import get_chat_history_store
                from core.utils.time_utils import get_current_time
                
                store = get_chat_history_store()
                
                # 只搜索 user 角色的消息
                chat_items = await asyncio.to_thread(
                    store.list_conversation_events,
                    conversation_id=user_id,
                    limit=limit * 3,
                    query=query,
                    roles=["user"],
                )
                
                # 按时间过滤
                if days_back is not None:
                    from datetime import timedelta
                    cutoff_ts = (get_current_time() - timedelta(days=days_back)).timestamp()
                    chat_items = [item for item in chat_items if item.get("timestamp", 0) >= cutoff_ts]
                
                for item in chat_items:
                    content = item.get("content", "")
                    if len(content) < 3:
                        continue
                    chat_results.append({
                        "content": content,
                        "role": "user",
                        "timestamp": item.get("timestamp", 0),
                        "source": "chat_history",
                        "category": "chat",
                    })
                    if len(chat_results) >= limit:
                        break
                        
            except Exception as e:
                logger.warning(f"搜索聊天记录失败: {e}")

        # 合并结果，去重
        all_results = []
        seen_content = set()

        # 优先添加长期记忆（已通过 hybrid_search 召回 weighted_memories）
        for mem in memory_results:
            content = mem.get("summary") or mem.get("content", "")
            if content and content not in seen_content:
                seen_content.add(content)
                all_results.append(mem)

        # 添加聊天记录
        for item in chat_results:
            content = item.get("content", "")
            if content and content not in seen_content and len(content) > 5:
                seen_content.add(content)
                all_results.append(item)

        if not all_results:
            return "未找到相关记忆或聊天记录。"

        # Format results concisely for LLM consumption
        formatted: List[str] = []
        for mem in all_results[:limit]:
            content = mem.get("summary") or mem.get("content", "")
            if not content or len(content) < 3:
                continue
            ts = mem.get("timestamp")
            time_label = ""
            if ts:
                try:
                    from core.utils.time_utils import format_timestamp
                    time_label = f" [{format_timestamp(float(ts), '%m-%d %H:%M')}]"
                except Exception:
                    time_label = ""
            source = mem.get("source", "")
            source_label = ""
            if source == "chat_history":
                source_label = "[聊天] "
            elif source:
                source_label = f"[{source}] "
            cat = mem.get("category", "")
            cat_label = f"({cat}) " if cat and cat != "chat" else ""
            formatted.append(f"- {source_label}{cat_label}{time_label} {content}")

        if not formatted:
            return "未找到相关记忆或聊天记录。"

        memory_count = len([m for m in all_results[:limit] if m.get("source") != "chat_history"])
        chat_count = len([m for m in all_results[:limit] if m.get("source") == "chat_history"])
        header = f"找到 {len(formatted)} 条结果（记忆:{memory_count} 聊天:{chat_count}）：\n"
        return header + "\n".join(formatted)
