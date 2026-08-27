"""
动态上下文收集与消息列表构建
从 streaming.py 解耦：情感影响指令、每日总结、明日总基调、今日计划、
Active Care 计划提醒等动态上下文的收集，以及对话历史消息列表的构建
"""
import inspect
import time
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger

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

    # 1. 情感影响指令
    if affect_instruction:
        dynamic_context_parts.append(f"【情感影响指令】\n{affect_instruction}")

    # 2. 每日总结
    if prep.is_cloud and not prep.is_sensitive_mode:
        try:
            daily_summary = await agent._check_daily_routine(user_id)
            if daily_summary:
                dynamic_context_parts.append(f"【每日总结】\n{daily_summary}")
                logger.info(f"Injected daily summary for {user_id}")
                events.append({
                    "type": "thought_chain",
                    "data": {
                        "stage": "context_enrichment",
                        "status": "success",
                        "description": "Checking daily schedule..."
                    },
                    "done": False
                })
        except Exception as e:
            logger.warning(f"Failed to check daily routine: {e}")

    t_after_daily = time.time()

    # 3. 明日总基调
    try:
        from core.services.journal.service import get_journal_service
        tomorrow_tone = await get_journal_service().get_tomorrow_tone()
        if tomorrow_tone:
            tone_injection = (
                f"【今日总基调（来自昨日日记总结）】\n{tomorrow_tone}\n"
                "这部分只用于语气、话题方向和互动节奏，不是日期或节日的事实来源。"
                "其中若出现‘今天/明天’或具体节日，不得直接复述，必须以权威日历事实锚点为准。"
            )
            dynamic_context_parts.append(tone_injection)
            logger.info(f"Injected tomorrow_tone for {user_id}")
    except Exception as e:
        logger.warning(f"Failed to inject tomorrow_tone: {e}")

    t_after_journal = time.time()

    # 4. 今日学习生活计划
    try:
        from core.services.journal.service import get_journal_service
        journal_svc = get_journal_service()
        today_plan = await journal_svc.get_plan()  # 默认今日
        if today_plan and today_plan.items:
            plan_text = journal_svc.format_plan_for_injection(today_plan)
            if plan_text:
                plan_injection = (
                    f"【今日学习生活计划（TODO 清单）】\n{plan_text}\n"
                    "这份计划就像 TODO 清单，你需要主动追踪主人的执行进度：\n"
                    "- 当主人说做完了某项（如\"数学写完了\"\"刚背完单词\"），立即调用 mark_plan_item_status 工具把对应项标记为 completed；\n"
                    "- 当主人开始做某项时，可以标记为 in_progress；\n"
                    "- 当主人明确表示跳过某项时，标记为 skipped；\n"
                    "- 标记时需要传 item_id 和 status，date 留空默认今日；\n"
                    "- 不要每次都问要不要勾，主人提到做完了就直接勾，然后简短回应一下即可；\n"
                    "- 如果主人长时间偏离计划（如该学习时在玩），可以自然地提醒一下进度。"
                )
                dynamic_context_parts.append(plan_injection)
                logger.info(f"Injected today_plan for {user_id} ({len(today_plan.items)} items)")
    except Exception as e:
        logger.warning(f"Failed to inject today_plan: {e}")

    # 5. Active Care 计划提醒注入
    try:
        from core.services.active_care.shared.reminder_injection import get_reminder_injection_store
        injection_store = get_reminder_injection_store()
        pending_reminder = await injection_store.get_and_clear()
        if pending_reminder:
            reminder_parts = ["【计划提醒】"]
            merged_count = int(pending_reminder.get("merged_count") or 0)
            if merged_count > 1:
                reminder_parts.append(f"共有 {merged_count} 条提醒待自然带入本轮回复")
            if pending_reminder.get('task_title'):
                reminder_parts.append(f"任务：{pending_reminder['task_title']}")
            reminder_parts.append(f"提醒：{pending_reminder['reminder_text']}")
            if pending_reminder.get('recent_chat_summary'):
                reminder_parts.append(f"最近对话背景：{pending_reminder['recent_chat_summary']}")
            reminder_parts.append("请在回复中自然地提醒用户这个计划，不要直接说'系统提醒你'，而是融入对话中。")
            dynamic_context_parts.append("\n".join(reminder_parts))
            logger.info(f"Injected Active Care reminder for {user_id}: {pending_reminder.get('task_title', '')}")
    except Exception as e:
        logger.warning(f"Failed to inject Active Care reminder: {e}")

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

    messages = await build_fn(user_id, message, model_hint, **build_kwargs)

    t_after_build = time.time()

    # 处理系统事件
    if prep.is_system_event and messages and messages[-1]["role"] == "user":
        messages[-1]["role"] = "system"
        logger.info("Converted purchase event to system message")

    total_history_time = time.time() - t_history
    logger.info(
        f"StreamChat: History built in {total_history_time:.4f}s "
        f"(inspect={t_after_inspect - t_history:.4f}s, "
        f"affect={t_after_affect - t_after_inspect:.4f}s, "
        f"daily_routine={t_after_daily - t_after_affect:.4f}s, "
        f"journal_tone={t_after_journal - t_after_daily:.4f}s, "
        f"build_history={t_after_build - t_after_journal:.4f}s, "
        f"post_process={total_history_time - (t_after_build - t_history):.4f}s)"
    )

    return messages, events
