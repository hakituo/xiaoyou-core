"""
Active Care 决策模型的工具调用支持

为决策模型提供工具调用能力，使用主工具系统的统一实现。
工具定义来自 core/tools/ 目录下的 BaseTool 实现。

工具调用循环设计：
- 如果模型支持 function calling → 执行工具并返回结果
- 如果模型不支持（如 V3.2）→ 直接返回文本响应，走原有 JSON 解析流程
- 最多 1 轮工具调用（决策不需要多轮）

运行方式：
    由 decision.py 的 ActiveCareDecision 内部调用
"""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from core.llm import get_llm_module
from core.tools.registry import ToolRegistry, register_all_tools
from core.services.active_care.decision.action_protocol import (
    TERMINAL_TOOL_NAMES,
    ActiveCareDecisionAction,
    parse_terminal_tool_call,
)

logger = get_logger("ACTIVE_CARE_TOOLS")

# 全局工具注册表单例（延迟初始化）
_tool_registry: Optional[ToolRegistry] = None


def _get_tool_registry() -> ToolRegistry:
    """获取或初始化全局工具注册表"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        register_all_tools(_tool_registry)
    return _tool_registry

# ============================================================
# 工具 Schema 定义（OpenAI function calling 格式）
# ============================================================

# 终止型工具（send / defer）：命中即结束决策，由 action_protocol 直接解析，
# 不进 ToolRegistry 执行。定义见 decision/action_protocol.py。
#
# Prompt v2：send 不再带 text 参数——决策只表态"值得发"，最终文本由生成层产出。
DECISION_TERMINAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_active_care",
            "description": (
                "现在值得主动联系用户时调用。"
                "只表示当前存在明确、具体、且有依据的联系价值；"
                "不要在参数里写最终消息文本。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason_code": {
                        "type": "string",
                        "description": "简短内部原因代码，如 planned_reminder_due / recent_open_topic，只进日志",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "defer_active_care",
            "description": (
                "现在不值得主动联系用户时调用。"
                "大多数检查轮次都应该调用这个——不发送是正常结果，"
                "不要为了完成检查而强行寻找话题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "为什么不发。只进日志，永远不会发给用户",
                    },
                    "retry_after_seconds": {
                        "type": "integer",
                        "description": "多少秒后重新判断，必须 >= 60",
                        "default": 1800,
                    },
                },
                "required": ["reason", "retry_after_seconds"],
            },
        },
    },
]

DECISION_CONTEXT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "搜索用户的过往记忆和聊天记录。"
                "当你需要找话题、回忆用户之前的偏好或经历时调用。"
                "返回最相关的记忆摘要。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如'兴趣爱好'、'最近聊的话题'、'喜欢的食物'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认3",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bionic_state",
            "description": (
                "查看用户的仿生体状态：饥饿度、口渴度、心情、能量等。"
                "可以据此判断是否需要提醒用户吃饭喝水休息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

# 传给模型的完整工具集：上下文工具 + 终止型出口工具。
# 终止型工具放在最后，让模型先看"可以查什么"，再看"最终怎么表态"。
DECISION_TOOLS = DECISION_CONTEXT_TOOLS + DECISION_TERMINAL_TOOLS


# ============================================================
# 工具执行器（使用主工具系统的统一实现）
# ============================================================

async def execute_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    user_id: str,
    memory_manager: Any = None,
) -> str:
    """执行单个工具调用，返回工具执行结果字符串
    
    使用主工具系统的 ToolRegistry，统一工具实现。
    """
    registry = _get_tool_registry()
    # 终止型出口工具不是可执行工具：走到这里说明调用方漏了拦截，
    # 直接报错而不是去注册表里找（那里本来就没有实现）。
    if str(tool_name or "").strip() in TERMINAL_TOOL_NAMES:
        return json.dumps(
            {"error": f"{tool_name} 是决策出口工具，不应被执行"}, ensure_ascii=False
        )
    tool = registry.get_tool(tool_name)
    
    if tool is None:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)
    
    # 设置运行时上下文
    tool.set_runtime_context({
        "user_id": user_id,
        "scope": "sfw",
    })
    
    try:
        result = await tool.run(**arguments)
        return result
    except Exception as e:
        logger.warning(f"工具 {tool_name} 执行失败: {e}")
        return json.dumps({"error": f"工具执行失败: {e}"}, ensure_ascii=False)


# ============================================================
# 带工具调用的 LLM 调用
# ============================================================

async def chat_with_tools(
    messages: List[Dict[str, str]],
    *,
    model_path: Optional[str] = None,
    temperature: float = 0.45,
    max_new_tokens: int = 600,
    user_id: str = "",
    memory_manager: Any = None,
    max_tool_rounds: int = 1,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    带工具调用的 LLM 对话（旧兼容入口）

    只挂上下文工具（search_memory / get_bionic_state），不含 send/defer 终止型出口。
    终止型出口请用 `chat_with_decision_tools`。

    Returns:
        (text_response, updated_messages)
        - text_response: 最终文本响应（可能是 JSON 字符串）
        - updated_messages: 包含工具调用/结果的完整消息列表
    """
    llm = get_llm_module()
    working_messages = list(messages)

    for round_idx in range(max_tool_rounds + 1):
        try:
            raw = await asyncio.wait_for(
                llm.chat(
                    working_messages,
                    temperature=temperature,
                    max_new_tokens=max_new_tokens,
                    model_path=model_path,
                    tools=DECISION_CONTEXT_TOOLS,
                    tool_choice="auto",
                ),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"决策模型 LLM 调用超时 (round={round_idx})")
            # 回退：不带 tools 重新调用
            if round_idx == 0:
                return await _fallback_no_tools(messages, model_path, temperature, max_new_tokens)
            return "", working_messages

        # 解析响应
        if not isinstance(raw, dict):
            return str(raw or ""), working_messages

        tool_calls = raw.get("tool_calls")
        text_content = str(raw.get("response") or raw.get("text") or "")

        # 没有工具调用 → 返回文本
        if not tool_calls:
            return text_content, working_messages

        # 有工具调用 → 构建 assistant 消息 + 执行工具
        logger.info(
            "决策模型返回 %d 个上下文工具调用 (round=%d)",
            len(tool_calls), round_idx,
        )

        # 构建带 tool_calls 的 assistant 消息
        assistant_msg = {
            "role": "assistant",
            "content": text_content or "",
            "tool_calls": tool_calls,
        }
        working_messages.append(assistant_msg)

        # 执行每个工具调用
        for tc in tool_calls:
            tc_id = tc.get("id", f"call_{round_idx}")
            func_info = tc.get("function", {})
            func_name = func_info.get("name", "")
            func_args_str = func_info.get("arguments", "{}")

            try:
                func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
            except (json.JSONDecodeError, TypeError):
                func_args = {}

            result = await execute_tool_call(
                func_name, func_args,
                user_id=user_id,
                memory_manager=memory_manager,
            )

            # 添加工具结果消息
            working_messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })

    # 工具循环结束后，做一次最终调用让模型基于工具结果生成决策
    try:
        raw = await asyncio.wait_for(
            llm.chat(
                working_messages,
                temperature=temperature,
                max_new_tokens=max_new_tokens,
                model_path=model_path,
                tools=DECISION_CONTEXT_TOOLS,
                tool_choice="auto",
            ),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        logger.warning("决策模型最终调用超时")
        return "", working_messages

    if isinstance(raw, dict):
        return str(raw.get("response") or raw.get("text") or ""), working_messages
    return str(raw or ""), working_messages


@dataclass
class DecisionToolResult:
    """带终止型出口的决策调用结果。

    Attributes:
        raw_text: 模型最终返回的文本（可能仍是 JSON，供 JSON fallback 解析）。
        action: 命中终止型工具时的归一化出口；未命中为 None。
        messages: 含工具调用/结果的完整消息列表（调试用）。
    """

    raw_text: str = ""
    action: Optional["ActiveCareDecisionAction"] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)


def _parse_tool_arguments(raw_args: Any) -> Dict[str, Any]:
    """把工具参数解析成 dict，失败返回空 dict。"""
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def chat_with_decision_tools(
    messages: List[Dict[str, str]],
    *,
    model_path: Optional[str] = None,
    temperature: float = 0.45,
    max_new_tokens: int = 600,
    user_id: str = "",
    memory_manager: Any = None,
    max_tool_rounds: int = 1,
) -> DecisionToolResult:
    """带终止型出口的决策调用

    与 `chat_with_tools` 的差别：模型调用 send_active_care / defer_active_care 时，
    不执行任何工具，直接把它当成决策出口返回，结束整个决策循环。

    Returns:
        DecisionToolResult：action 非 None 表示模型已明确表态（发/不发）。
    """
    working_messages = list(messages)

    for round_idx in range(max_tool_rounds + 1):
        try:
            raw = await asyncio.wait_for(
                llm_chat_with_tools(
                    working_messages,
                    temperature=temperature,
                    max_new_tokens=max_new_tokens,
                    model_path=model_path,
                ),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"决策模型 LLM 调用超时 (round={round_idx})")
            if round_idx == 0:
                fallback_text, fallback_messages = await _fallback_no_tools(
                    messages, model_path, temperature, max_new_tokens
                )
                return DecisionToolResult(
                    raw_text=fallback_text, messages=fallback_messages
                )
            return DecisionToolResult(raw_text="", messages=working_messages)

        if not isinstance(raw, dict):
            return DecisionToolResult(raw_text=str(raw or ""), messages=working_messages)

        tool_calls = raw.get("tool_calls")
        text_content = str(raw.get("response") or raw.get("text") or "")

        if not tool_calls:
            return DecisionToolResult(raw_text=text_content, messages=working_messages)

        # 终止型出口优先：模型已经表态发/不发，立即结束，不再执行上下文工具
        for tc in tool_calls:
            func_info = tc.get("function", {}) if isinstance(tc, dict) else {}
            func_name = str(func_info.get("name", "") or "").strip()
            if func_name not in TERMINAL_TOOL_NAMES:
                continue
            arguments = _parse_tool_arguments(func_info.get("arguments", "{}"))
            action = parse_terminal_tool_call(func_name, arguments)
            if action is not None:
                logger.info(
                    "决策模型命中终止型出口: %s (retry_after=%ss)",
                    action.action, action.retry_after_seconds,
                )
                return DecisionToolResult(
                    raw_text=text_content, action=action, messages=working_messages
                )

        logger.info("决策模型返回 %d 个上下文工具调用 (round=%d)", len(tool_calls), round_idx)

        assistant_msg = {
            "role": "assistant",
            "content": text_content or "",
            "tool_calls": tool_calls,
        }
        working_messages.append(assistant_msg)

        for tc in tool_calls:
            tc_id = tc.get("id", f"call_{round_idx}")
            func_info = tc.get("function", {})
            func_name = func_info.get("name", "")
            result = await execute_tool_call(
                func_name,
                _parse_tool_arguments(func_info.get("arguments", "{}")),
                user_id=user_id,
                memory_manager=memory_manager,
            )
            working_messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })

    # 工具循环结束，做一次最终调用让模型基于工具结果表态
    try:
        raw = await asyncio.wait_for(
            llm_chat_with_tools(
                working_messages,
                temperature=temperature,
                max_new_tokens=max_new_tokens,
                model_path=model_path,
            ),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        logger.warning("决策模型最终调用超时")
        return DecisionToolResult(raw_text="", messages=working_messages)

    if not isinstance(raw, dict):
        return DecisionToolResult(raw_text=str(raw or ""), messages=working_messages)

    final_text = str(raw.get("response") or raw.get("text") or "")
    for tc in raw.get("tool_calls") or []:
        func_info = tc.get("function", {}) if isinstance(tc, dict) else {}
        func_name = str(func_info.get("name", "") or "").strip()
        if func_name not in TERMINAL_TOOL_NAMES:
            continue
        action = parse_terminal_tool_call(
            func_name, _parse_tool_arguments(func_info.get("arguments", "{}"))
        )
        if action is not None:
            logger.info(
                "决策模型命中终止型出口(最终轮): %s (retry_after=%ss)",
                action.action, action.retry_after_seconds,
            )
            return DecisionToolResult(
                raw_text=final_text, action=action, messages=working_messages
            )

    return DecisionToolResult(raw_text=final_text, messages=working_messages)


async def llm_chat_with_tools(
    messages: List[Dict[str, Any]],
    *,
    temperature: float,
    max_new_tokens: int,
    model_path: Optional[str],
) -> Any:
    """统一的带工具 LLM 调用封装（tools 参数集中在此，便于替换与 mock）。"""
    llm = get_llm_module()
    return await llm.chat(
        messages,
        temperature=temperature,
        max_new_tokens=max_new_tokens,
        model_path=model_path,
        tools=DECISION_TOOLS,
        tool_choice="auto",
    )


async def _fallback_no_tools(
    messages: List[Dict[str, str]],
    model_path: Optional[str],
    temperature: float,
    max_new_tokens: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    """工具调用失败时的回退：不带 tools 直接调用"""
    logger.info("回退到不带工具的调用模式")
    llm = get_llm_module()
    try:
        raw = await asyncio.wait_for(
            llm.chat(
                messages,
                temperature=temperature,
                max_new_tokens=max_new_tokens,
                model_path=model_path,
            ),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        return "", messages

    if isinstance(raw, dict):
        return str(raw.get("response") or raw.get("text") or ""), messages
    return str(raw or ""), messages
