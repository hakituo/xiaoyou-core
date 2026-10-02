"""ChatAgent 非流式 handler：工具调用执行（原生 tool_calls 与文本协议）。

从 ``core/agents/chat_agent_components/handler.py`` 拆出：
- ``_execute_native_tool_calls``：云模型原生 ``tool_calls``
- ``_execute_legacy_tool_call``：``[TOOL_USE: {...}]`` 文本协议

⚠️ 模块级 patch 语义：测试会按名替换门面模块的 ``execute_tool_call``，因此该名字
必须在**调用期**从门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, List, Optional

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.agents.chat_agent_components import handler as _facade
from core.agents.chat_agent_components.handler_tools import (
    ToolRuntime,
    _expand_discovered_tool_schemas,
)
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


async def _execute_native_tool_calls(
    agent: Any,
    messages: List[dict],
    native_tool_calls: List[dict],
    tools: ToolRuntime,
    user_id: str,
    message: str,
    turn: int,
    thought_content: Optional[str],
    current_study_data: Any,
) -> Any:
    """执行原生 tool_calls 并把助手/工具消息追加进 ``messages``。"""
    for tc in native_tool_calls:
        tc_id = tc.get("id", f"tc_{turn}")
        fn_info = tc.get("function", {})
        tool_name = fn_info.get("name", "")
        tool_args_str = fn_info.get("arguments", "{}")
        tool = agent.tool_registry.get_tool(tool_name) if hasattr(agent, "tool_registry") else None
        if tool:
            logger.info(f"[Native Tool] 非流式执行: {tool_name}")

            try:
                tool_args = json.loads(tool_args_str) if tool_args_str else {}
                tool_result = await _facade.execute_tool_call(agent=agent, tool_name=tool_name, arguments=tool_args, user_id=user_id, allowed_tool_names=tools.available_tool_names, persona_filename=tools.persona_filename, is_sensitive_mode=tools.is_sensitive_mode, used_tool_names=tools.used_tool_names, last_user_text=message)
            except Exception as e:
                tool_result = f"Error: {str(e)}"
                logger.error(f"[Native Tool] 非流式执行失败: {e}")

            tools.native_tool_names, expanded_schemas = (
                _expand_discovered_tool_schemas(
                    agent,
                    tool_name,
                    tool_result,
                    tools.available_tool_names,
                    tools.native_tool_names,
                )
            )
            if expanded_schemas is not None:
                tools.openai_tools = expanded_schemas

            # 检查 study_data_highlight
            if isinstance(tool_result, str) and '"type": "study_data_highlight"' in tool_result:
                try:
                    parsed_result = json.loads(tool_result)
                    if parsed_result.get("type") == "study_data_highlight":
                        current_study_data = parsed_result.get("data")
                        tool_result = f"[已在前端展示文件: {current_study_data.get('filePath')}]"
                except Exception:
                    pass

            assistant_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_args_str,
                    }
                }]
            }
            if thought_content:
                assistant_msg["reasoning_content"] = thought_content
            messages.append(assistant_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": str(tool_result),
            })
        else:
            logger.warning(f"[Native Tool] 未知工具: {tool_name}")
    return current_study_data


async def _execute_legacy_tool_call(
    agent: Any,
    messages: List[dict],
    response_content: str,
    tool_match: Any,
    tools: ToolRuntime,
    user_id: str,
    message: str,
    current_study_data: Any,
    collected_image_prompts: List[str],
) -> Any:
    """执行 ``[TOOL_USE: {...}]``；``messages`` / ``collected_image_prompts`` 就地修改。

    调用方在返回后统一 ``current_turn += 1; continue``（与原实现三条 continue 分支等价）。
    """
    json_str = tool_match.group(1)
    try:
        tool_call = json.loads(json_str)
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("arguments", {})

        tool = agent.tool_registry.get_tool(tool_name)
        if tool:
            logger.info(
                f"Executing tool {tool_name} with args {tool_args}"
            )
            # Inject runtime context so tools can access agent/user_id/scope

            tool_start = time.time()
            tool_result = await _facade.execute_tool_call(agent=agent, tool_name=tool_name, arguments=tool_args, user_id=user_id, allowed_tool_names=tools.available_tool_names, persona_filename=tools.persona_filename, is_sensitive_mode=tools.is_sensitive_mode, used_tool_names=tools.used_tool_names, last_user_text=message)
            logger.info(
                f"Tool execution took: {time.time() - tool_start:.4f}s"
            )

            tools.native_tool_names, expanded_schemas = (
                _expand_discovered_tool_schemas(
                    agent,
                    tool_name,
                    tool_result,
                    tools.available_tool_names,
                    tools.native_tool_names,
                )
            )
            if expanded_schemas is not None:
                tools.openai_tools = expanded_schemas

            # 检查是否是 study_data_highlight 类型的输出
            if isinstance(tool_result, str) and '"type": "study_data_highlight"' in tool_result:
                try:
                    parsed_result = json.loads(tool_result)
                    if parsed_result.get("type") == "study_data_highlight":
                        current_study_data = parsed_result.get("data")
                        # 简化给 LLM 的输出，避免 token 浪费，因为前端已经展示了
                        tool_result = f"[已在前端展示文件: {current_study_data.get('filePath')}]"
                except Exception as e:
                    logger.warning(f"Failed to parse study_data_highlight: {e}")

            if tool_name == "generate_image":
                img_match_tool = re.search(
                    r"\[GEN_IMG:\s*(.*?)\]", str(tool_result)
                )
                if img_match_tool:
                    collected_image_prompts.append(
                        img_match_tool.group(1)
                    )

            messages.append(
                {"role": "assistant", "content": response_content}
            )
            messages.append(
                {
                    "role": "system",
                    "content": f"工具“{tool_name}”输出：\n{tool_result}\n\n请基于该信息继续对话。",
                }
            )

            return current_study_data

        messages.append(
            {
                "role": "system",
                "content": f"Error: Tool '{tool_name}' not found.",
            }
        )
        return current_study_data
    except Exception as e:
        messages.append(
            {
                "role": "system",
                "content": f"Error parsing tool call: {e}",
            }
        )
        return current_study_data
