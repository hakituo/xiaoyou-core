"""ChatAgent 非流式 handler：会话历史与生成参数准备。

从 ``core/agents/chat_agent_components/handler.py`` 拆出，本模块负责：
- ``_prepare_conversation_messages``：准备本轮工具列表与对话历史（含失败回退）
- ``_inject_affect_instruction``：把角色影响指令插到 system 消息之后
- ``_resolve_server_side_search``：判定当前模型是否使用服务端 web_search
- ``_resolve_repetition_penalty``：本地/敏感模型提高重复惩罚
"""
from __future__ import annotations

from typing import Any, List, Tuple

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


async def _prepare_conversation_messages(
    agent: Any,
    user_id: str,
    message: str,
    system_prompt_override: Any,
    tool_persona_filename: str,
) -> Tuple[List[str], List[dict]]:
    """准备本轮 active_tools 与对话历史，返回 ``(active_tools, messages)``。"""
    active_tools: List[str] = []
    try:
        # 只在需要保存历史时才构建带 message_id 的历史
        # 这样即使不保存，也能生成回复，但不会污染 Weighted Memory
        # _build_conversation_history 主要是为了获取上下文给 LLM
        # 真正的保存是在最后的 _save_conversation_history

        from core.agents.chat_agent_components.context_persona import prepare_active_tools

        active_tools = await prepare_active_tools(agent, message, None, persona_filename=tool_persona_filename, user_id=user_id)
        messages = await agent._build_conversation_history(
            user_id,
            message,
            system_prompt=system_prompt_override,
            active_tools=active_tools,
            persona_filename=tool_persona_filename,
        )
    except Exception as e:
        # Fallback
        logger.warning(f"Build history failed, trying fallback: {e}")
        messages = [{"role": "user", "content": message}]
    return active_tools, messages


def _inject_affect_instruction(messages: List[dict], affect_instruction: str) -> None:
    """把角色影响指令插入到已有 system 消息之后（原地修改 messages）。"""
    if affect_instruction and messages:
        insert_at = 0
        if (
            isinstance(messages[0], dict)
            and messages[0].get("role") == "system"
            and messages[0].get("content")
        ):
            insert_at = 1
        messages.insert(insert_at, {"role": "system", "content": affect_instruction})


def _resolve_server_side_search(agent: Any) -> bool:
    """判断当前LLM是否使用服务端web_search。"""
    use_server_side_search = False
    try:
        from config.model_config import should_use_server_side_web_search, is_web_search_enabled
        if is_web_search_enabled() and hasattr(agent, "llm_module"):
            current_model = agent.llm_module.get_current_model_name()
            current_provider = ""
            if current_model and current_model.startswith("cloud:"):
                parts = current_model.split(":", 2)
                if len(parts) >= 2:
                    current_provider = parts[1]
            model_name = current_model.split(":")[-1] if ":" in current_model else current_model
            use_server_side_search = should_use_server_side_web_search(current_provider, model_name)
    except Exception:
        pass
    return use_server_side_search


def _resolve_repetition_penalty(agent: Any, is_sensitive_mode: bool) -> float:
    """Dynamic Repetition Penalty for Local/Sensitive Models.

    Llama 3.2 Stheno and other small RP models often need higher penalty to avoid loops.
    """
    repetition_penalty = agent.config.repetition_penalty if hasattr(agent.config, "repetition_penalty") else 1.08
    if is_sensitive_mode:
        repetition_penalty = max(repetition_penalty, 1.15)
    return repetition_penalty
