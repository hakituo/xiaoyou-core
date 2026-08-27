"""
流式聊天实现 (编排层)
各阶段实现已解耦到 streaming_pipeline 子包：
- 预处理 → preparation.py
- 动态上下文与消息构建 → dynamic_context.py
- 模型解析与工具准备 → model_resolution.py
- 流式标签解析状态机 → tag_stream_parser.py
- 回复后处理清洗 → postprocess.py
- 空回复兜底重试 → empty_retry.py
本模块只负责按阶段编排并向调用方 yield 事件
"""
import asyncio
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

# 保留导出：单测通过 streaming 模块命名空间 patch 这些类的方法
from .stream_utils import (
    extract_image_request_prompt,
    StreamContextBuilder,  # noqa: F401  (单测兼容导出)
    ParallelProcessor,  # noqa: F401  (单测兼容导出)
)
from .streaming_pipeline import (
    StreamTagSession,
    build_stream_messages,
    detect_server_side_search,
    postprocess_response,
    prepare_native_tools,
    prepare_stream_request,
    resolve_model_by_persona,
    resolve_model_path,
    retry_visible_response,
)

logger = get_logger("ChatAgent")

# 兼容旧导出（tests/unit/test_image_trigger_tightening.py 等仍在引用）
async def _extract_image_request_prompt(message: str) -> Optional[str]:
    return await extract_image_request_prompt(message)


# 兼容旧导出：人设-模型映射解析已迁移至 streaming_pipeline.model_resolution
_resolve_model_by_persona = resolve_model_by_persona


async def stream_chat_impl(
    agent: Any,
    user_id: str,
    message: Any,
    message_id: Optional[str] = None,
    save_history: bool = True,
    model_hint: Optional[str] = None,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    user_name: Optional[str] = None,
    persona_filename: Optional[str] = None,
    service_dynamic_context: Optional[str] = None,
    api_key: Optional[str] = None,
    platform: Optional[str] = None,
    history_override: Optional[List[Dict[str, str]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    流式聊天实现 (编排层)

    按阶段调用 streaming_pipeline 各模块，并向调用方透传事件
    """
    cid = str(user_id or "").strip() or "default"

    if not message_id:
        message_id = f"msg_{cid}_{datetime.now().timestamp()}"

    yield {
        "type": "thought_chain",
        "data": {
            "stage": "initialization",
            "status": "start",
            "description": "Processing request...",
        },
        "done": False,
    }

    # 初始化agent
    if not agent.is_initialized:
        logger.info(f"StreamChat: Initializing agent ({cid})...")
        t_init = time.time()
        await agent.initialize()
        logger.info(f"StreamChat: Initialized in {time.time() - t_init:.4f}s")

    # ========== 阶段1：预处理（事件检测、并行任务、情绪注入） ==========
    prep = await prepare_stream_request(
        agent, user_id, message, model_hint, system_prompt, max_tokens
    )
    for evt in prep.pre_events:
        yield evt

    # ========== 阶段2：动态上下文收集与消息构建 ==========
    logger.info("StreamChat: Building conversation history...")
    yield {
        "type": "thought_chain",
        "data": {
            "stage": "context_building",
            "status": "processing",
            "description": "Constructing memory context..."
        },
        "done": False
    }

    messages, ctx_events = await build_stream_messages(
        agent=agent,
        user_id=user_id,
        message=message,
        model_hint=model_hint,
        system_prompt=system_prompt,
        user_name=user_name,
        persona_filename=persona_filename,
        service_dynamic_context=service_dynamic_context,
        prep=prep,
        history_override=history_override,
    )
    for evt in ctx_events:
        yield evt

    # 检测图片请求
    forced_image_prompt = await extract_image_request_prompt(message)
    if forced_image_prompt:
        yield {"type": "image_trigger", "data": forced_image_prompt, "done": False}

    # ========== 阶段3：模型路径解析与工具准备 ==========
    is_cloud, model_path = resolve_model_path(model_hint)

    # 开始流式生成
    logger.info("Starting LLM streaming...")
    yield {
        "type": "thought_chain",
        "data": {
            "stage": "inference",
            "status": "start",
            "description": "Generating response..."
        },
        "done": False
    }

    # 判断当前LLM是否使用服务端web_search
    use_server_side_search = detect_server_side_search(agent)

    # 准备原生 function calling 工具（DeepSeek v4 等）
    from core.tools.tool_visibility import filter_tool_names

    available_tool_names = []
    if hasattr(agent, "tool_registry") and agent.tool_registry:
        available_tool_names = filter_tool_names(
            agent.tool_registry.get_active_tools(),
            tool_registry=agent.tool_registry,
            persona_filename=persona_filename,
            mode=prep.mode,
            is_sensitive_mode=prep.is_sensitive_mode,
        )
    if use_server_side_search:
        available_tool_names = [
            name for name in available_tool_names if name != "web_search"
        ]
    openai_tools = prepare_native_tools(
        agent,
        persona_filename,
        prep.is_sensitive_mode,
        use_server_side_search,
        active_tool_names=prep.active_tools,
    )

    # ========== 阶段4：多轮流式生成与标签解析 ==========
    session = StreamTagSession(
        agent=agent,
        user_id=user_id,
        is_sensitive_mode=prep.is_sensitive_mode,
        messages=messages,
        model_path=model_path,
        allowed_tool_names=available_tool_names,
    )
    if forced_image_prompt:
        session.collected_image_prompts.append(forced_image_prompt)

    current_turn = 0
    max_turns = 3

    while current_turn < max_turns:
        session.begin_turn()

        llm_kwargs = {
            "temperature": temperature or 0.7,
            "max_tokens": prep.max_tokens,
            "model_path": model_path,
            "conversation_id": user_id,
            "tools": openai_tools,
            "tool_choice": "auto" if openai_tools else None,
        }
        if use_server_side_search:
            llm_kwargs["web_search_enabled"] = True
        if api_key:
            llm_kwargs["api_key"] = api_key

        try:
            async for chunk in agent.llm_module.stream_chat(
                messages=messages,
                **llm_kwargs,
            ):
                if is_debug_enabled("streaming"):
                    chunk_raw = str(chunk)[:200]
                    logger.info(f"[STREAM][TT] LLM chunk in: {chunk_raw}")
                # process_chunk 内部才会把可见文本写入 rt_emits，
                # 必须先处理 chunk，再 drain 立即逐块发送（真流式核心）
                if await session.process_chunk(chunk):
                    # 工具调用轮次：先把工具调用前已产生的文本逐块发出，
                    # 再由外层发送 response_reset 让前端清空
                    sent = 0
                    for tok in session._drain_rt_emits():
                        sent += 1
                        yield tok
                    if is_debug_enabled("streaming"):
                        logger.info(f"[STREAM][TT] tool turn, drained {sent} tokens then break")
                    break
                sent = 0
                for tok in session._drain_rt_emits():
                    sent += 1
                    yield tok
                if is_debug_enabled("streaming"):
                    logger.info(f"[STREAM][TT] drained {sent} tokens after chunk")
        except Exception as e:
            logger.error(f"LLM streaming error: {e}")
            yield {
                "type": "error",
                "error": str(e),
                "done": True
            }
            return

        # 本轮流式读取结束后，把缓冲的实时 token 发送出去（工具调用前的可见文本）
        for tok in session._drain_rt_emits():
            yield tok

        if session.tool_executed_this_turn:
            if session.discovered_tool_names:
                expanded_tool_names = list(dict.fromkeys(
                    prep.active_tools + session.discovered_tool_names
                ))
                openai_tools = prepare_native_tools(
                    agent,
                    persona_filename,
                    prep.is_sensitive_mode,
                    use_server_side_search,
                    active_tool_names=expanded_tool_names,
                )
                logger.info(
                    "[Native Tools] 工具发现后扩展 schema: %s",
                    ", ".join(session.discovered_tool_names),
                )
            # 中间轮次（有工具调用）：
            # 1) 先发送 response_reset，通知前端清空当前正在生成的临时内容
            #    （工具调用前的半句已实时发给前端，此时需要被清空）
            # 2) 再 discard_turn，丢弃中间轮次的事件缓冲并回退 current_response_content，
            #    这样最终轮次不会把中间轮次的文本重复输出
            yield {"type": "response_reset"}
            session.discard_turn()
            if is_debug_enabled("streaming"):
                logger.info(f"[STREAM] Turn {current_turn} had tool calls, sent response_reset and discarding intermediate content")
            current_turn += 1
            continue

        # 最终轮次（无工具调用）：输出剩余缓存的事件（思考链、图片触发等非文本事件）
        for evt in session.turn_event_buffer:
            yield evt
        break

    # ========== 阶段5：收尾与后处理清洗 ==========
    session.flush_tail()

    extracted_topics: List[str] = list(session.extracted_topics)
    current_response_content = postprocess_response(
        session.current_response_content, extracted_topics
    )
    thought_content = session.thought_content
    llm_emo_tag = session.llm_emo_tag

    # ========== 阶段6：空回复兜底重试 ==========
    if (not current_response_content) and thought_content:
        # 模型只输出了思考内容，没有可见回复，重试一次
        retry_text, thought_content = await retry_visible_response(
            agent=agent,
            messages=messages,
            temperature=temperature,
            max_tokens=prep.max_tokens,
            model_path=model_path,
            user_id=user_id,
            is_sensitive_mode=prep.is_sensitive_mode,
            thought_content=thought_content,
        )
        if retry_text:
            current_response_content = retry_text
            for ch in retry_text:
                yield {
                    "type": "token",
                    "content": ch,
                    "done": False,
                }

    # ========== 阶段7：历史保存与完成信号 ==========
    # 后台保存对话历史：调度动作必须放在 yield done 的 try/finally 里。
    # 原因：消费端在收到 done 后会 break（stream_orchestrator 收到 done 后 break、
    # WS 适配器收到 response_done 后 break），break 后 async 生成器引用被丢弃，
    # asyncio 的 asyncgen finalizer 会调度 aclose()，GeneratorExit 抛在 yield done 处，
    # yield 之后裸写的代码永远不会执行 → 落库静默丢失。
    # try/finally 保证无论消费者完整消费还是 break/aclose，保存任务都一定被调度。
    if save_history and (current_response_content or thought_content):
        try:
            final_thought = thought_content if thought_content else None

            # OOC Emoji 过滤：保存到历史前剥离人设之外的emoji
            history_content = current_response_content
            try:
                from clients.bots.qq.utils import strip_ooc_emoji

                history_content = strip_ooc_emoji(current_response_content, persona_filename)
            except Exception:
                pass

            # 保存参数先暂存，待 response_done 之后才真正调度写入数据库
            _pending_save = dict(
                user_id=user_id,
                user_msg=message,
                assistant_msg=history_content,
                message_id=message_id,
                model_hint=model_hint,
                extracted_topics=extracted_topics,
                thought=final_thought,
                persona_filename=persona_filename,
                platform=platform,
            )
        except Exception as e:
            logger.warning(f"Failed to prepare history save: {e}")
            _pending_save = None
    else:
        _pending_save = None

    # 发送完成信号（response_done）：至此完整结果已确定。
    # finally 在两种路径下都会执行：
    # - 正常路径：消费者完整消费，yield 正常返回后执行；
    # - break/aclose 路径：GeneratorExit 抛在 yield 处，执行 finally 后继续向上传播。
    try:
        yield {
            "done": True,
            "content": current_response_content,
            "emotion": llm_emo_tag,
            "thought": (thought_content or None),
        }
    finally:
        # response_done 之后才把完整结果写入数据库（create_task 异步执行，不影响流式完成；
        # 调度放在 finally 内，生成器被关闭也不会丢失保存任务）
        if _pending_save:
            try:
                asyncio.create_task(agent._save_conversation_history(**_pending_save))
            except Exception as e:
                logger.warning(f"Failed to schedule history save: {e}")
