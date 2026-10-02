"""跨请求工具延续（carryover）。

解决的问题：连续对话里第二轮往往无法命中关键词路由，模型只能先调 ``search_tools``
再回来调目标工具，多花一轮。例如：

    U1: 明天天气怎么样？        -> get_weather
    U2: 那后天呢？              -> 路由命中不了，需要 discovery

carryover 让上一请求**真正执行过的**按需工具，在下一请求直接带上 schema。

设计约束：
- TTL 以 **request（用户消息）** 为单位，不是 LLM turn。一个请求内部的
  ``LLM -> tool -> LLM -> tool`` 循环属于同一 request，不消耗额度。
- 按 ``(conversation_id, persona_scope, mode)`` 隔离，避免跨会话、跨角色、
  跨模式串味。
- **carryover 不是授权**。这里只产出候选名字，最终仍要过 RoleToolPolicy 与
  tool_visibility；被禁用的工具不会因此复活。
- 只保留最近实际使用的少数工具，顺带控制 ``get_openai_tools`` 的
  组合缓存条目数（缓存键是工具名集合）。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Iterable, Optional, Tuple

DEFAULT_MAX_TOOLS = 2
DEFAULT_MAX_ENTRIES = 200

# 发现器本身不参与延续：它每轮都在常驻里，延续它只会浪费一个名额。
NEVER_CARRY = frozenset({"search_tools"})

CarryoverKey = Tuple[str, str, str]


@dataclass
class _CarryoverEntry:
    tool_names: list[str] = field(default_factory=list)
    remaining_turns: int = 0


class ToolCarryoverManager:
    """进程内的跨请求工具延续表。"""

    def __init__(
        self,
        max_tools: int = DEFAULT_MAX_TOOLS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._max_tools = max(1, int(max_tools))
        self._max_entries = max(1, int(max_entries))
        self._entries: "OrderedDict[CarryoverKey, _CarryoverEntry]" = OrderedDict()
        self._lock = RLock()
        # 轻量观测：只在内存里计数，供诊断接口读取线上真实命中率
        self._stats = {"recorded_requests": 0, "hit_requests": 0, "hit_tools": 0}

    @staticmethod
    def build_key(
        conversation_id: Optional[str],
        persona_scope: Optional[str],
        mode: Optional[str],
    ) -> CarryoverKey:
        """同一会话、同一角色、同一模式才共享延续。"""
        return (
            str(conversation_id or "").strip(),
            str(persona_scope or "").strip(),
            str(mode or "chat").strip() or "chat",
        )

    def get(self, key: CarryoverKey) -> list[str]:
        """取出延续工具并消耗一个 request 额度；无记录时返回空列表。"""
        if not key or not key[0]:
            # 没有 conversation_id 就不做延续，避免跨会话共用同一份状态
            return []
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return []
            names = list(entry.tool_names)
            self._stats["hit_requests"] += 1
            self._stats["hit_tools"] += len(names)
            entry.remaining_turns -= 1
            if entry.remaining_turns <= 0:
                self._entries.pop(key, None)
            else:
                self._entries.move_to_end(key)
            return names

    def record(
        self,
        key: CarryoverKey,
        tool_names: Iterable[str],
        *,
        exclude: Optional[Iterable[str]] = None,
    ) -> None:
        """记录本请求实际使用过的工具，供下一请求延续。

        ``exclude`` 用来剔除常驻工具（下一轮本来就有，不必占名额）。
        空结果会清掉旧记录：上一轮用过、这一轮完全没再用，不应继续延续。
        """
        if not key or not key[0]:
            return
        skip = set(NEVER_CARRY)
        if exclude:
            skip.update(str(name) for name in exclude)
        names: list[str] = []
        for raw in tool_names:
            name = str(raw).strip()
            if not name or name in skip or name in names:
                continue
            names.append(name)
            if len(names) >= self._max_tools:
                break
        with self._lock:
            if not names:
                self._entries.pop(key, None)
                return
            # 只统计「真的有工具可延续」的请求，空记录不计入分母
            self._stats["recorded_requests"] += 1
            self._entries[key] = _CarryoverEntry(names, 1)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def peek(self, key: CarryoverKey) -> list[str]:
        """只看不消耗，供测试与诊断使用。"""
        with self._lock:
            entry = self._entries.get(key)
            return list(entry.tool_names) if entry else []

    def clear(self, key: Optional[CarryoverKey] = None) -> None:
        """清除指定 key 或整张表。"""
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)

    def stats(self) -> dict:
        """只读计数快照：命中率 = hit_requests / recorded_requests。

        注意分母是「真正执行过工具的请求数」，不是全部请求——纯闲聊请求
        不该被算进来稀释命中率（Carryover Opportunity Hit Rate 口径）。
        """
        with self._lock:
            return dict(self._stats)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def record_request_tools(
    conversation_id: Optional[str],
    persona_filename: Optional[str],
    mode: Optional[str],
    used_tool_names: Optional[Iterable[str]],
    resident_tool_names: Optional[Iterable[str]] = None,
) -> None:
    """请求结束时统一记录本请求实际用过的工具。

    ``resident_tool_names`` 用于剔除常驻工具：它们下一请求本来就在，占名额没意义。
    本请求没用过任何工具时不写——上一请求的额度在读取时已经消耗掉了。
    """
    if not conversation_id or not used_tool_names:
        return
    try:
        from core.utils.data.scope_registry import resolve_persona_slug_scope

        key = ToolCarryoverManager.build_key(
            conversation_id, resolve_persona_slug_scope(persona_filename), mode
        )
        get_tool_carryover_manager().record(
            key, used_tool_names, exclude=resident_tool_names
        )
    except Exception:  # noqa: BLE001 - 延续状态失败不能影响对话主流程
        logger = _get_logger()
        if logger is not None:
            logger.debug("写入工具延续状态失败，忽略")


def _get_logger():
    try:
        from core.utils.logger import get_logger

        return get_logger("TOOL_CARRYOVER")
    except Exception:  # noqa: BLE001
        return None


_manager: Optional[ToolCarryoverManager] = None


def get_tool_carryover_manager() -> ToolCarryoverManager:
    """全局单例；测试里用 ``clear()`` 复位而不是重建。"""
    global _manager
    if _manager is None:
        _manager = ToolCarryoverManager()
    return _manager


__all__ = [
    "CarryoverKey",
    "ToolCarryoverManager",
    "get_tool_carryover_manager",
    "record_request_tools",
]
