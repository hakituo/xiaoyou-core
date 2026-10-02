"""ChatAgent 非流式 handler：native tools 准备与工具发现扩展。

从 ``core/agents/chat_agent_components/handler.py`` 拆出，本模块负责：
- ``ToolRuntime``：一次请求内的工具运行态（跨多轮 LLM 调用保持）
- ``_expand_discovered_tool_schemas``：解析 search_tools 结果并扩展下一轮 schema
- ``_prepare_native_tools``：按人设 / 模式 / 敏感模式过滤并构建首轮 schema
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


@dataclass
class ToolRuntime:
    """一次请求内的工具运行态（跨多轮 LLM 调用保持）。"""

    persona_filename: str = ""
    is_sensitive_mode: bool = False
    available_tool_names: List[str] = field(default_factory=list)
    native_tool_names: List[str] = field(default_factory=list)
    used_tool_names: List[str] = field(default_factory=list)
    openai_tools: Any = None


def _expand_discovered_tool_schemas(
    agent: Any,
    tool_name: str,
    tool_result: Any,
    available_tool_names: list[str],
    native_tool_names: list[str],
):
    """解析 search_tools 结果，并只为权限内候选构建下一轮 schema。"""
    if tool_name != "search_tools":
        return native_tool_names, None
    try:
        discovery_payload = json.loads(str(tool_result))
    except (TypeError, ValueError):
        return native_tool_names, None

    allowed_names = set(available_tool_names)
    discovered_names = [
        str(item.get("name", "")).strip()
        for item in discovery_payload.get("tools", [])
        if isinstance(item, dict)
        and str(item.get("name", "")).strip() in allowed_names
    ]
    if not discovered_names:
        return native_tool_names, None

    expanded_names = list(dict.fromkeys(native_tool_names + discovered_names))
    expanded_schemas = agent.tool_registry.get_openai_tools(
        include_names=expanded_names
    )
    logger.info(
        "[Native Tools] 非流式工具发现后扩展 schema: %s",
        ", ".join(discovered_names),
    )
    return expanded_names, expanded_schemas


def _prepare_native_tools(
    agent: Any,
    active_tools: List[str],
    tools: ToolRuntime,
    tool_mode: str,
    use_server_side_search: bool,
) -> None:
    """准备 native tools（与 streaming.py 对齐，让云模型也能 function calling）。

    结果写回 ``tools``：``available_tool_names`` / ``native_tool_names`` / ``openai_tools``。
    """
    if not (hasattr(agent, "tool_registry") and agent.tool_registry):
        return

    from core.tools.tool_visibility import filter_tool_names

    # 复用本轮构建Prompt时的人设快照，不重新读取全局选择。

    available_tool_names = filter_tool_names(
        agent.tool_registry.get_active_tools(),
        tool_registry=agent.tool_registry,
        persona_filename=tools.persona_filename,
        mode=tool_mode,
        is_sensitive_mode=tools.is_sensitive_mode,
    )
    native_tool_names = list(active_tools)
    native_tool_names = filter_tool_names(
        native_tool_names,
        tool_registry=agent.tool_registry,
        persona_filename=tools.persona_filename,
        mode=tool_mode,
        is_sensitive_mode=tools.is_sensitive_mode,
    )
    if use_server_side_search:
        available_tool_names = [
            name for name in available_tool_names if name != "web_search"
        ]
        native_tool_names = [
            name for name in native_tool_names if name != "web_search"
        ]
    openai_tools = agent.tool_registry.get_openai_tools(
        include_names=native_tool_names
    )
    if openai_tools:
        schema_chars = len(
            json.dumps(
                openai_tools,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        logger.info(
            "[Native Tools] 非流式路径注册 %d 个工具, schema_chars=%d",
            len(openai_tools),
            schema_chars,
        )

    tools.available_tool_names = available_tool_names
    tools.native_tool_names = native_tool_names
    tools.openai_tools = openai_tools
