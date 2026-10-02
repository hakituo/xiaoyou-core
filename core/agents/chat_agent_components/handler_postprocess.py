"""ChatAgent 非流式 handler：回复后处理与收尾。

从 ``core/agents/chat_agent_components/handler.py`` 拆出，本模块负责：
- ``_postprocess_response``：情感/时间戳/工具协议标签清理、图片与语音标签提取、风格强化
- ``_process_emotion``：情绪管理器处理并取回有效情绪与响应策略
- ``_persist_turn``：保存历史、生成会话标题、通知自我改进系统
- ``_extract_hardware_data``：从响应策略里取硬件控制数据
- ``_record_tool_carryover``：把本请求用过的工具交接给下一请求
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from core.llm.openai_compat.dsml_parser import strip_tool_mark_residue
from core.utils.data.chat_channel import strip_model_channel_marks
from core.utils.logger import get_logger
from core.utils.text_processor import (
    enforce_dialogue_style,
    extract_and_strip_emotion,
    strip_parentheses_tags,
)

logger = get_logger("ChatAgent")


@dataclass
class PostprocessResult:
    """回复后处理结果。"""

    final_content: str = ""
    full_content: str = ""
    emotion_label: str = ""
    image_prompt: Optional[str] = None
    voice_id: Optional[str] = None
    message_type: str = "text"
    ui_content: str = ""


def _postprocess_response(
    response_content: str,
    collected_image_prompts: List[str],
    is_sensitive_mode: bool,
) -> PostprocessResult:
    """清理模型回复并提取图片 / 语音标签。"""
    result = PostprocessResult()

    final_content, emotion_label = extract_and_strip_emotion(response_content)
    # 剥离AI模仿上下文时间戳格式自行生成的时间戳（如 [23:10]、[05-22 01:45] 或 [2025-05-22 01:45]）
    # 全局匹配，不仅匹配行首，也匹配回复中间出现的时间戳
    _ai_ts_pattern = re.compile(r"\[(?:\d{2,4}(?:-\d{2}){1,2}\s+)?\d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*")
    final_content = _ai_ts_pattern.sub("", final_content)
    # 剥离模型复述出来的渠道标注（「（来自QQ）」「来自App」）——这是系统给跨渠道
    # 历史消息加的后缀，不该出现在回复正文里（与流式链 postprocess 保持一致）
    final_content = strip_model_channel_marks(final_content)
    # 剥离残留的工具调用标记（DSML 及其漂移形态、拆散的裸标签残片）——
    # 解析阶段漏掉的形态在这里兜底，避免原始 token 发给用户（与流式链同一实现）
    final_content = strip_tool_mark_residue(final_content)

    # 剥离 MiniMax-M2.5 等模型输出的 [TOOL_CALL]...[/TOOL_CALL] 格式
    if "[TOOL_CALL]" in final_content and "[/TOOL_CALL]" in final_content:
        _tc_pattern = re.compile(r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", re.DOTALL)
        _extracted = []
        for _m in _tc_pattern.finditer(final_content):
            _text_match = re.search(r'--text\s+["\u201c](.+?)["\u201d]', _m.group(1), re.DOTALL)
            if _text_match:
                _extracted.append(_text_match.group(1).strip())
        _cleaned = _tc_pattern.sub("", final_content).strip()
        if _extracted:
            final_content = " ".join(_extracted)
        elif _cleaned:
            final_content = _cleaned
    # 保存包含情感标签的完整内容用于 TTS
    full_content = final_content

    image_prompt = None
    voice_id = None

    img_match = re.search(r"\[GEN_IMG:\s*(.*?)\]", final_content)
    if img_match:
        image_prompt = img_match.group(1)
        final_content = final_content.replace(img_match.group(0), "")
        full_content = full_content.replace(img_match.group(0), "")

    if not image_prompt and collected_image_prompts:
        image_prompt = collected_image_prompts[-1]

    # 语音检测逻辑：支持 [VOICE] 标签，同时兼容全角括号 ［VOICE］
    voice_match = re.search(r"[\[［]VOICE(?:[：:]\s*(.*?))?[\]］]", final_content, re.IGNORECASE)
    message_type = "text"
    if voice_match:
        voice_id = voice_match.group(1) or None
        final_content = final_content.replace(voice_match.group(0), "")
        full_content = full_content.replace(voice_match.group(0), "")
        message_type = "voice"

    # 如果没有显式标签，但情绪比较强烈且字数较少，也可以自动转语音（对齐自主决策逻辑）
    if message_type == "text" and emotion_label and emotion_label != "neutral":
        if len(final_content) < 50: # 短句更容易触发语音
            # 这里可以根据配置决定是否开启自动语音，目前保持保守，仅在有标签时触发，
            # 或者后续增加一个 probability 判断
            pass

    final_content = final_content.strip()
    full_content = full_content.strip()

    final_content = enforce_dialogue_style(
        final_content,
        max_chars=None,
        at_start=True,
        skip_breathing=(not is_sensitive_mode),
        replace_emoji_with_kaomoji=True,
    )
    # 对 full_content 同样应用风格强化，但保留情感标签
    full_content = enforce_dialogue_style(
        full_content,
        max_chars=None,
        at_start=True,
        skip_breathing=(not is_sensitive_mode),
        replace_emoji_with_kaomoji=True,
    )

    # 在发送给前端的内容中移除情感标签 (情绪词)
    # 同时也确保移除了 <think> 标签（如果之前没有处理干净，例如在 full_content 中）
    # 注意：full_content 应该只包含最终的对话内容（可能带 [EMO]），不应包含 <think>

    # Remove <think> from full_content just in case
    full_content = re.sub(r"<think>.*?</think>", "", full_content, flags=re.DOTALL).strip()
    final_content = re.sub(r"<think>.*?</think>", "", final_content, flags=re.DOTALL).strip()

    ui_content = strip_parentheses_tags(final_content)

    result.final_content = final_content
    result.full_content = full_content
    result.emotion_label = emotion_label
    result.image_prompt = image_prompt
    result.voice_id = voice_id
    result.message_type = message_type
    result.ui_content = ui_content
    return result


def _process_emotion(
    agent: Any, user_id: str, full_content: str, emotion_label: str
) -> Tuple[str, Any, Any]:
    """用情绪管理器处理文本，返回 ``(emotion_label, effective_state, strategy)``。"""
    effective = None
    emo_start = time.time()
    try:
        # 使用智能情绪检测器（关键词 + BERT），不再依赖 LLM 标签
        agent.emotion_manager.process_text(user_id, full_content)
        effective = agent.emotion_manager.get_effective_state(user_id)
        if effective and effective.primary_emotion:
            emotion_label = effective.primary_emotion.value

        strategy = agent.emotion_manager.get_response_strategy(user_id)
    except Exception as e:
        logger.warning(f"情绪管理器处理失败: {e}")
        strategy = None
    logger.info(f"Emotion processing took: {time.time() - emo_start:.4f}s")
    return emotion_label, effective, strategy


async def _persist_turn(
    agent: Any,
    user_id: str,
    message: str,
    full_content: str,
    final_content: str,
    message_id: str,
    thought_content: Optional[str],
    save_history: bool,
    skip_memory_storage: bool,
    used_placeholder_response: bool,
) -> None:
    """保存本轮历史，并触发会话标题与自我改进系统的后置钩子。"""
    try:
        if save_history and not skip_memory_storage and (not used_placeholder_response):
            save_start = time.time()
            await agent._save_conversation_history(
                user_id, message, full_content, message_id, thought=thought_content
            )
            logger.info(f"Save history took: {time.time() - save_start:.4f}s")
        elif used_placeholder_response:
            logger.info(
                f"Skipped saving history for message {message_id} (placeholder response)"
            )
        elif skip_memory_storage:
            logger.info(f"Skipped saving history for message {message_id} (skip_memory_storage=True)")
    except Exception as e:
        logger.warning(f"Failed to save conversation history: {e}")

    asyncio.create_task(
        agent._maybe_generate_session_title(user_id, message, full_content)
    )

    # 调用自我改进系统记录对话轮次
    if save_history and not skip_memory_storage and (not used_placeholder_response):
        try:
            from core.services.self_improvement.service import get_self_improvement_service
            # 根据 user_id 推断 scope
            from core.utils.data_paths import resolve_data_scope_from_conversation_id
            scope = resolve_data_scope_from_conversation_id(user_id, default="user")
            si = get_self_improvement_service(scope=scope)
            # 异步调用 on_turn_end，不阻塞主流程
            asyncio.create_task(si.on_turn_end(
                user_text=message,
                assistant_text=final_content,
            ))
        except Exception as e:
            logger.debug(f"自我改进系统调用失败（不影响主流程）: {e}")


def _extract_hardware_data(strategy: Any) -> Any:
    """从响应策略里提取硬件控制数据（标准化 HardwareIntent 优先，回退旧字段）。"""
    hardware_data = None
    if strategy and strategy.metadata:
        # Check for standardized HardwareIntent
        if "hardware_intent" in strategy.metadata:
            hw_intent = strategy.metadata["hardware_intent"]
            if hasattr(hw_intent, "to_dict"):
                hardware_data = hw_intent.to_dict()

        # Fallback to legacy metadata if standardized one is missing but legacy keys exist
        if not hardware_data and ("vibration_pattern" in strategy.metadata or "light_color" in strategy.metadata):
            # We might want to construct a temporary HardwareIntent or just pass it through
            # For now, let's just pass the metadata as is if it contains hardware keys,
            # but ideally we should normalize it.
            # Since we updated EmotionResponder to ALWAYS produce HardwareIntent, this fallback is mostly for safety.
            hardware_data = strategy.metadata
    return hardware_data


def _record_tool_carryover(
    user_id: str,
    persona_filename: Callable[[], str],
    tool_mode: Callable[[], str],
    used_tool_names: List[str],
    active_tools: List[str],
) -> None:
    """本请求实际用过的工具交给下一请求延续；失败不影响回复。

    传入门面里的**取值函数**而非取值结果：原实现把取值写在 try 内，异常早于变量赋值
    （``resolve_persona_filename`` / ``_is_study_mode`` 抛错）时由 except 静默兜住，
    这里保持同一语义，同时不必在门面重复包一层兜底。
    """
    try:
        from core.tools.tool_carryover import record_request_tools

        record_request_tools(
            user_id, persona_filename(), tool_mode(),
            used_tool_names, active_tools,
        )
    except Exception:  # noqa: BLE001 - 延续状态失败不能影响回复
        pass
