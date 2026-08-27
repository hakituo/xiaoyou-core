"""
空回复兜底重试
从 streaming.py 解耦：模型只输出思考内容、没有可见回复时的非流式重试，
包括重试中出现 tool_calls 时的工具执行与二次调用
"""
import inspect
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


async def retry_visible_response(
    agent: Any,
    messages: List[Dict[str, Any]],
    temperature: Optional[float],
    max_tokens: Optional[int],
    model_path: Optional[str],
    user_id: str,
    is_sensitive_mode: bool,
    thought_content: str,
) -> Tuple[str, str]:
    """可见回复为空时兜底重试一次，返回 (retry_text, 更新后的思考内容)

    不再注入提到<think标签的system消息（反而会让模型注意到标签并模仿输出）
    """
    try:
        logger.warning("StreamChat: visible response empty, retrying once")
        retry_messages = list(messages)
        chat_fn = agent.llm_module.chat
        chat_sig = inspect.signature(chat_fn)
        # 检测是否有 **kwargs（VAR_KEYWORD），有则可接收任意关键字参数，
        # 无需逐个检查命名参数（HybridLLMModule.chat 等用 **kwargs 接收 model_path 等）
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in chat_sig.parameters.values()
        )
        retry_kwargs: Dict[str, Any] = {
            "messages": retry_messages,
            "temperature": temperature or 0.7,
        }
        if has_var_keyword:
            # chat 用 **kwargs 接收，无条件传递（保持与首次调用一致的模型路由）
            if max_tokens is not None:
                retry_kwargs["max_tokens"] = max_tokens
            if model_path:
                retry_kwargs["model_path"] = model_path
            retry_kwargs["conversation_id"] = user_id
        else:
            # 兼容旧式显式命名参数签名
            if "max_tokens" in chat_sig.parameters:
                retry_kwargs["max_tokens"] = max_tokens
            elif "max_new_tokens" in chat_sig.parameters:
                retry_kwargs["max_new_tokens"] = max_tokens
            if "model_path" in chat_sig.parameters and model_path:
                retry_kwargs["model_path"] = model_path
            if "conversation_id" in chat_sig.parameters:
                retry_kwargs["conversation_id"] = user_id

        retry_payload = await chat_fn(**retry_kwargs)
        retry_text = ""
        if isinstance(retry_payload, dict):
            retry_text = str(
                retry_payload.get("response")
                or retry_payload.get("content")
                or ""
            )
            retry_reasoning = str(retry_payload.get("reasoning_content") or "").strip()
            if retry_reasoning:
                thought_content = (
                    f"{thought_content}\n{retry_reasoning}" if thought_content else retry_reasoning
                )

            retry_tool_calls = retry_payload.get("tool_calls")
            if retry_tool_calls and not retry_text.strip():
                logger.warning(
                    "StreamChat: retry returned %d tool_calls "
                    "instead of text, executing and re-calling",
                    len(retry_tool_calls),
                )
                for tc in retry_tool_calls:
                    tc_id = tc.get(
                        "id", f"retry_tc_{len(retry_messages)}"
                    )
                    fn_info = tc.get("function", {})
                    tool_name = fn_info.get("name", "")
                    tool_args_str = fn_info.get("arguments", "{}")
                    has_reg = hasattr(agent, "tool_registry")
                    tool = (
                        agent.tool_registry.get_tool(tool_name)
                        if has_reg else None
                    )
                    if tool:
                        logger.info(
                            f"[Retry Tool] Executing: {tool_name}"
                        )
                        tool.set_runtime_context({
                            "agent": agent,
                            "user_id": user_id,
                            "scope": (
                                "sensitive"
                                if is_sensitive_mode
                                else "sfw"
                            ),
                        })
                        try:
                            tool_args = (
                                json.loads(tool_args_str)
                                if tool_args_str
                                else {}
                            )
                            tool_result = await tool.run(**tool_args)
                        except Exception as e:
                            tool_result = f"Error: {str(e)}"
                            logger.error(
                                f"[Retry Tool] Execution failed: {e}"
                            )

                        retry_assistant_msg = {
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
                        if retry_reasoning:
                            retry_assistant_msg["reasoning_content"] = retry_reasoning
                        retry_messages.append(retry_assistant_msg)
                        retry_messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": str(tool_result),
                        })
                    else:
                        logger.warning(
                            f"[Retry Tool] Unknown tool: "
                            f"{tool_name}, skipping"
                        )

                retry_messages.append({
                    "role": "system",
                    "content": (
                        "工具已执行完毕，结果如上。"
                        "现在请直接用自然语言文字回答用户，"
                        "不要再调用任何工具或函数。"
                    ),
                })

                try:
                    # retry_kwargs["messages"] 与 retry_messages 是同一列表，
                    # 上面追加的工具结果会一并带入二次调用
                    final_payload = await chat_fn(**retry_kwargs)
                    if isinstance(final_payload, dict):
                        retry_text = str(
                            final_payload.get("response")
                            or final_payload.get("content")
                            or ""
                        )
                        final_reasoning = str(
                            final_payload.get(
                                "reasoning_content"
                            ) or ""
                        ).strip()
                        if final_reasoning:
                            thought_content = (
                                f"{thought_content}\n"
                                f"{final_reasoning}"
                                if thought_content
                                else final_reasoning
                            )
                        if (
                            final_payload.get("tool_calls")
                            and not retry_text.strip()
                        ):
                            logger.warning(
                                "StreamChat: retry still returned "
                                "tool_calls after tool execution, "
                                "cleaning DSML tokens as fallback"
                            )
                    else:
                        retry_text = str(final_payload or "")
                except Exception as final_e:
                    logger.warning(
                        f"StreamChat: final retry after "
                        f"tool execution failed: {final_e}"
                    )
        else:
            retry_text = str(retry_payload or "")

        # 清理重试结果中的 think 标签残留
        retry_text = re.sub(r"(?i)(?<!<)/think>", "</think", retry_text)
        retry_text = re.sub(r"<think.*?</think\s*>", "", retry_text, flags=re.DOTALL | re.IGNORECASE)
        open_idx = retry_text.lower().find("<think")
        if open_idx >= 0:
            retry_text = retry_text[:open_idx]
        retry_text = re.sub(r"</think\s*>", "", retry_text, flags=re.IGNORECASE).replace("/think>", "").strip()
        return retry_text, thought_content
    except Exception as retry_e:
        logger.warning(f"StreamChat: no-think retry failed: {retry_e}")
        return "", thought_content
