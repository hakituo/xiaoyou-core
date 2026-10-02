#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prefetch Query Embedding for RAG

Fire-and-forget：不阻塞流式响应启动，异步预取查询嵌入向量。
"""

import asyncio

from core.utils.async_tasks import spawn_bg_task
from core.utils.logger import get_logger

logger = get_logger(__name__)


def schedule_prefetch_embedding(content_preview: str, conversation_id: str):
    """后台预取查询嵌入向量（不阻塞主流程）。"""

    async def _prefetch_embedding_task():
        try:
            from core.core_engine.service_singletons import get_aveline_service

            svc = get_aveline_service()
            if svc and hasattr(svc, "chat_agent"):
                cid = str(conversation_id or "").strip() or "default"
                mm = await svc.chat_agent.get_memory_manager_async(cid)
                if hasattr(mm, "embedding_generator") and getattr(
                    mm.embedding_generator, "_model_loaded", True
                ):

                    def _prefetch_embedding():
                        try:
                            from memory.core.retrieval_ops import (
                                get_cached_query_embedding,
                            )

                            get_cached_query_embedding(
                                mm, content_preview, mm.embedding_generator
                            )
                            logger.info(
                                f"Prefetched embedding for query: {content_preview[:20]}..."
                            )
                        except Exception as e:
                            logger.debug(f"Prefetch embedding failed: {e}")

                    await asyncio.to_thread(_prefetch_embedding)
        except Exception as e:
            logger.debug(f"Failed to prefetch embedding: {e}")

    spawn_bg_task(_prefetch_embedding_task(), name="prefetch_embedding")
