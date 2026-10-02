"""
动态上下文收集与消息列表构建
从 streaming.py 解耦：情感影响指令、每日总结、明日总基调、今日计划、
Active Care 计划提醒等动态上下文的收集，以及对话历史消息列表的构建
"""
import inspect
import time
from typing import Any, Dict, List, Optional, Tuple

from core.image.chat_image_input import (
    load_uploaded_image_data_url,
    split_chat_image_message,
)
from core.utils.logger import get_logger

from .agenda_injections import pick_agenda_injection
from .preparation import StreamPreparation

logger = get_logger("ChatAgent")


async def build_stream_messages(
    agent: Any,
    user_id: str,
    message: Any,
    model_hint: Optional[str],
    system_prompt: Optional[str],
    user_name: Optional[str],
    persona_filename: Optional[str],
    service_dynamic_context: Optional[str],
    prep: StreamPreparation,
    history_override: Optional[List[Dict[str, str]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """收集动态上下文并构建消息列表

    返回 (messages, events)：
    - messages: 传给 LLM 的消息列表
    - events: 构建过程中产生的、需要透传给前端的事件
    """
    events: List[Dict[str, Any]] = []

    # Android 图片消息把上传路径放在 `[图片: ...]` 附件标记里。
    # Prompt / 历史构建只看真实 caption；附件在消息构建完成后再升级成标准 image_url。
    message_for_context, image_ref = split_chat_image_message(message)

    t_history = time.time()
    build_fn = agent._build_conversation_history
    use_system_prompt = False
    try:
        sig = inspect.signature(build_fn)
        use_system_prompt = "system_prompt" in sig.parameters
    except (TypeError, ValueError):
        sig = None
        use_system_prompt = False

    t_after_inspect = time.time()

    # 构建情感影响指令
    affect_instruction = ""
    try:
        affect_instruction = agent.emotion_manager.build_dialogue_affect_instruction(
            user_id=user_id,
            life_level=prep.life_level,
            mood_score=prep.mood_score,
            shyness_score=prep.shyness_score,
            immune_damage=prep.immune_damage,
            is_sick=prep.is_sick,
            intimacy_level=prep.intimacy_level,
            soft_reply_char_limit=prep.soft_reply_char_limit,
            max_tokens=prep.max_tokens,
        )
    except Exception:
        affect_instruction = ""

    t_after_affect = time.time()

    # 【缓存优化关键】收集所有动态上下文，统一通过 extra_dynamic_context 传递
    # 这样 assembler 可以把动态内容放到 user 消息前缀中，而不是污染 system 消息
    dynamic_context_parts = []

    # 1. 语气类：情感影响指令。管的是语气而不是「要主人去做某件事」，
    #    所以不参与下面的议程竞争，保持每轮常驻。
    if affect_instruction:
        dynamic_context_parts.append(f"【情感影响指令】\n{affect_instruction}")

    # 2. 议程类：按优先级取**第一条命中的**，其余不消费、留到下一轮。
    #    原先这里是 5 段 if 顺序 append，谁都不让谁，于是同一轮回复里可能同时
    #    出现催吃饭、催背单词、盯计划进度（实测 2026-10-01 那轮：用户只说
    #    「买了个显示器」，回复里同时塞了催饭和「176 个词今天压着呢」）。
    #    优先级阶梯与各条的 peek/commit 语义见 agenda_injections.py。
    agenda_name, agenda_text, agenda_commit = await pick_agenda_injection(
        agent=agent, user_id=user_id, prep=prep, events=events
    )
    t_after_agenda = time.time()
    if agenda_text:
        dynamic_context_parts.append(agenda_text)
        logger.info(f"Injected agenda injection '{agenda_name}' for {user_id}")
        if agenda_commit is not None:
            # 只有被选中才消费（清提醒队列 / 落盘学习任务）
            await agenda_commit()
    else:
        logger.info(f"No agenda injection this turn for {user_id}")

    extra_dynamic_context = "\n\n".join(dynamic_context_parts) if dynamic_context_parts else None

    if service_dynamic_context and str(service_dynamic_context or "").strip():
        svc_ctx = str(service_dynamic_context).strip()
        extra_dynamic_context = f"{extra_dynamic_context}\n\n{svc_ctx}" if extra_dynamic_context else svc_ctx

    # 构建消息列表（按 build_fn 签名决定可传哪些参数，兼容旧签名）
    build_kwargs = {}
    if use_system_prompt:
        build_kwargs["system_prompt"] = system_prompt
    if sig is not None:
        if "user_name" in sig.parameters:
            build_kwargs["user_name"] = user_name
        if "persona_filename" in sig.parameters:
            build_kwargs["persona_filename"] = persona_filename
        if "extra_dynamic_context" in sig.parameters:
            build_kwargs["extra_dynamic_context"] = extra_dynamic_context
        if "history_override" in sig.parameters:
            build_kwargs["history_override"] = history_override
        if "active_tools" in sig.parameters:
            build_kwargs["active_tools"] = prep.active_tools

    # history_override 表示客户端选中的“当前分支”，空列表也有明确语义：
    # 从空历史重新生成第一轮回复。绝不能因为兼容 wrapper 的签名较旧而静默丢弃。
    # 当前 ChatAgent._build_conversation_history wrapper 就属于这种情况：底层 canonical
    # build_conversation_history 已支持 history_override，但 wrapper 尚未暴露参数。
    # 若 wrapper 不支持，则直接调用 canonical 实现，保证重新生成/编辑后的分支历史真正覆盖
    # 服务端线性历史；wrapper 后续补齐参数后会自动回到正常转发路径。
    supports_history_override = sig is not None and "history_override" in sig.parameters
    if history_override is not None and not supports_history_override:
        logger.warning(
            "build_stream_messages: _build_conversation_history does not expose "
            "history_override; using canonical context builder to preserve client branch"
        )
        from core.agents.chat_agent_components.context import (
            build_conversation_history as build_conversation_history_impl,
        )

        messages = await build_conversation_history_impl(
            agent,
            user_id,
            message_for_context,
            model_hint,
            system_prompt_override=system_prompt,
            user_name=user_name,
            persona_filename=persona_filename,
            extra_dynamic_context=extra_dynamic_context,
            history_override=history_override,
            active_tools_override=prep.active_tools,
        )
    else:
        messages = await build_fn(
            user_id, message_for_context, model_hint, **build_kwargs
        )

    t_after_build = time.time()

    # 处理系统事件
    if prep.is_system_event and messages and messages[-1]["role"] == "user":
        messages[-1]["role"] = "system"
        logger.info("Converted purchase event to system message")

    # 当前用户图片只在 LLM 入参层升级成标准多模态消息。
    # 多模态主模型会被 vision_router 原样直通；纯文本主模型才会触发 VL 描述中转。
    if image_ref and messages and messages[-1].get("role") == "user":
        try:
            image_data_url = await load_uploaded_image_data_url(image_ref)
            current_content = messages[-1].get("content")
            if image_data_url and isinstance(current_content, str):
                messages[-1]["content"] = [
                    {"type": "text", "text": current_content},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ]
                logger.info("Android 聊天图片已注入多模态消息: %s", image_ref)
            elif image_data_url:
                logger.warning("聊天图片附件未注入：当前 user content 不是文本")
        except Exception as e:
            # 图片附件异常只降级为普通文本消息，不能让整轮聊天直接失败。
            logger.warning("聊天图片附件注入失败，降级为文本消息: %s", e)

    total_history_time = time.time() - t_history
    logger.info(
        f"StreamChat: History built in {total_history_time:.4f}s "
        f"(inspect={t_after_inspect - t_history:.4f}s, "
        f"affect={t_after_affect - t_after_inspect:.4f}s, "
        f"agenda={t_after_agenda - t_after_affect:.4f}s, "
        f"build_history={t_after_build - t_after_agenda:.4f}s, "
        f"post_process={total_history_time - (t_after_build - t_history):.4f}s)"
    )

    return messages, events
