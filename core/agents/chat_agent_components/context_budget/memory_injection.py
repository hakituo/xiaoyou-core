# -*- coding: utf-8 -*-
"""思考库与敏感记忆注入（簇 D）。

职责：往 messages 末尾追加 system 消息（思考库摘要、敏感记忆）。
互不依赖，仅依赖 WeightedMemoryManager。
"""

import asyncio
from typing import Any, Dict, List

from core.utils.logger import get_logger
from core.utils.time_utils import format_timestamp
from memory.weighted_memory_manager import WeightedMemoryManager

logger = get_logger("ChatAgent")


async def inject_thinking_store(
    memory_manager: Any, messages: List[Dict[str, str]]
) -> None:
    """把最近的 thinking 类记忆作为线索注入到 messages 末尾。

    要求：不要直接复述、不要告诉用户你有思考库，只当作回忆触发线索。
    """
    if not isinstance(memory_manager, WeightedMemoryManager):
        return
    try:
        def _collect_thinking_lines() -> List[str]:
            thinking_lines: List[str] = []
            with memory_manager.lock:
                ids = list(memory_manager.category_index.get("thinking", []) or [])
                memories = [
                    memory_manager.weighted_memories[mid]
                    for mid in ids
                    if mid in memory_manager.weighted_memories
                ]
            memories.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            for m in memories[:6]:
                c = str(m.get("content", "") or "").strip()
                if not c:
                    continue
                if len(c) > 200:
                    c = c[:200] + "..."
                thinking_lines.append(f"- {c}")
            return thinking_lines

        thinking_lines = await asyncio.to_thread(_collect_thinking_lines)
        if thinking_lines:
            messages.append(
                {
                    "role": "system",
                    "content": "【思考库（隐藏，仅供参考）】\n"
                    + "\n".join(thinking_lines)
                    + "\n\n要求：不要直接复述以上内容 不要告诉用户你有思考库 只把它当作回忆触发线索",
                }
            )
    except Exception as e:
        logger.warning(f"Failed to inject thinking store: {e}")


async def inject_sensitive_memories(
    memory_manager: Any, is_sensitive_mode: bool, messages: List[Dict[str, str]]
) -> None:
    """注入敏感记忆到 messages 末尾，敏感模式下数量更多。"""
    if not hasattr(memory_manager, "get_sensitive_memories"):
        return
    sensitive_limit = 10 if is_sensitive_mode else 5
    sensitive_mems = await asyncio.to_thread(
        memory_manager.get_sensitive_memories, limit=sensitive_limit
    )
    if not sensitive_mems:
        return
    sensitive_text = "\n".join(
        [
            f"[{format_timestamp(m['timestamp'], '%Y-%m-%d %H:%M')}] {m['content']}"
            for m in sensitive_mems
        ]
    )
    header = (
        "【Private Memories (SENSITIVE MODE ACTIVE)】"
        if is_sensitive_mode
        else "【Private Memories (Local Only)】"
    )
    messages.append({"role": "system", "content": f"{header}\n{sensitive_text}"})
    logger.info(
        "Injected %s sensitive memories (Mode: %s)",
        str(len(sensitive_mems)),
        str(is_sensitive_mode),
    )
