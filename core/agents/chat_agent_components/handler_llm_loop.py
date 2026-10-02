"""ChatAgent 非流式 handler：多轮 LLM 生成循环。

从 ``core/agents/chat_agent_components/handler.py`` 拆出，本模块负责：
- ``_split_think_blocks``：剥离 ``<think>`` 块并合并进 thought（含未闭合标签）
- ``_run_llm_turns``：多轮生成循环（原生 tool_calls / 文本协议工具 / 截断续写 / 占位兜底）

工具执行细节在 ``handler_tool_calls.py``，本模块只做编排。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.agents.chat_agent_components.handler_tool_calls import (
    _execute_legacy_tool_call,
    _execute_native_tool_calls,
)
from core.agents.chat_agent_components.handler_tools import ToolRuntime
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


@dataclass
class LlmTurnResult:
    """多轮生成结束后的结果状态。"""

    response_content: str = ""
    thought_content: Optional[str] = None
    used_placeholder_response: bool = False
    current_study_data: Any = None
    collected_image_prompts: List[str] = field(default_factory=list)


def _split_think_blocks(
    response_content: str, thought_content: Optional[str]
) -> Tuple[str, Optional[str]]:
    """剥离 ``<think>`` 块并合并进 thought_content。"""
    response_content = re.sub(
        r"(?i)(?<!<)/think>", "</think>", response_content
    )
    think_blocks = re.findall(
        r"<think>(.*?)</think>", response_content, flags=re.DOTALL | re.IGNORECASE
    )
    if think_blocks:
        merged_think = "\n".join(
            [str(item or "").strip() for item in think_blocks if str(item or "").strip()]
        ).strip()
        if merged_think:
            if thought_content:
                thought_content = f"{thought_content}\n{merged_think}"
            else:
                thought_content = merged_think
        response_content = re.sub(
            r"<think>.*?</think>", "", response_content, flags=re.DOTALL | re.IGNORECASE
        ).strip()

    unclosed_idx = response_content.lower().find("<think>")
    if unclosed_idx >= 0:
        dangling_think = response_content[unclosed_idx + len("<think>") :].strip()
        if dangling_think:
            if thought_content:
                thought_content = f"{thought_content}\n{dangling_think}"
            else:
                thought_content = dangling_think
        response_content = response_content[:unclosed_idx].strip()

    return response_content, thought_content


async def _run_llm_turns(
    agent: Any,
    messages: List[dict],
    tools: ToolRuntime,
    *,
    user_id: str,
    message: str,
    max_tokens: Optional[int],
    repetition_penalty: float,
    use_server_side_search: bool,
    max_turns: int = 3,
) -> LlmTurnResult:
    """多轮生成：每轮解析回复、处理工具调用与截断续写。"""
    result = LlmTurnResult()
    current_turn = 0
    forced_no_think_retry = False

    while current_turn < max_turns:
        llm_start = time.time()
        logger.info(f"Starting LLM generation (turn {current_turn}) with rep_penalty={repetition_penalty}")
        llm_chat_kwargs = {
            "temperature": agent.config.temperature,
            "max_tokens": max_tokens,
            "repetition_penalty": repetition_penalty,
        }
        if use_server_side_search:
            llm_chat_kwargs["web_search_enabled"] = True
        if tools.openai_tools:
            llm_chat_kwargs["tools"] = tools.openai_tools
            llm_chat_kwargs["tool_choice"] = "auto"
        response_payload = await agent.llm_module.chat(
            messages,
            **llm_chat_kwargs,
        )
        logger.info(
            f"LLM generation took: {time.time() - llm_start:.4f}s"
        )

        response_content = ""
        finish_reason = None

        if isinstance(response_payload, Dict):
            response_content = response_payload.get("response", "")
            finish_reason = response_payload.get("finish_reason")
            if response_payload.get("status") == "error":
                logger.error(f"LLM Error: {response_payload.get('error')}")

            # Handle DeepSeek R1 reasoning_content
            if response_payload.get("reasoning_content"):
                result.thought_content = response_payload.get("reasoning_content")
        else:
            response_content = str(response_payload)

        response_content, result.thought_content = _split_think_blocks(
            response_content, result.thought_content
        )

        if (not response_content.strip()) and result.thought_content and (not forced_no_think_retry):
            forced_no_think_retry = True
            # 不再注入提到think标签的system消息（反而会让模型注意到标签并模仿输出）
            current_turn += 1
            continue

        if (not response_content.strip()) and result.thought_content and forced_no_think_retry:
            response_content = "我在。刚刚处理了一下上下文，现在可以继续了。"
            result.used_placeholder_response = True

        # 处理 function calling 模式返回的 tool_calls（云模型原生工具调用）
        native_tool_calls = None
        if isinstance(response_payload, Dict):
            native_tool_calls = response_payload.get("tool_calls")
        if native_tool_calls and (not response_content.strip() or finish_reason == "tool_calls"):
            result.current_study_data = await _execute_native_tool_calls(
                agent,
                messages,
                native_tool_calls,
                tools,
                user_id,
                message,
                current_turn,
                result.thought_content,
                result.current_study_data,
            )
            current_turn += 1
            continue

        tool_match = re.search(
            r"\[TOOL_USE:\s*({.*?})\]", response_content, re.DOTALL
        )

        if tool_match:
            result.current_study_data = await _execute_legacy_tool_call(
                agent,
                messages,
                response_content,
                tool_match,
                tools,
                user_id,
                message,
                result.current_study_data,
                result.collected_image_prompts,
            )
            current_turn += 1
            continue

        if finish_reason == "length" and response_content.strip() and current_turn < max_turns - 1:
            logger.warning(
                f"LLM output truncated (finish_reason=length), attempting continuation. "
                f"Current length: {len(response_content)} chars"
            )
            messages.append({"role": "assistant", "content": response_content})
            messages.append({
                "role": "system",
                "content": "你的回复被截断了，请自然地继续说完，不要重复已说的内容。",
            })
            current_turn += 1
            continue

        break

    result.response_content = response_content
    return result
