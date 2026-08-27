"""
后处理管线 — Pipeline Step 实现（P2-1）

将原 postprocessor.py 中 200+ 行的 postprocess 长方法拆分为独立 step：
- 每个 step 只负责一个职责
- step 通过 PipelineState 共享数据
- step 可设置 state.aborted = True 中止管线
- 行为与原实现保持一致（包括所有 abort 路径和日志）

Step 列表（按执行顺序）：
1. ContentExtractionStep       — 提取 content / message_type / thought
2. ReasoningStripStep          — 剥离推理段
3. EmojiStripStep              — 剥离 emoji / 软萌符号 / 内心独白
4. EmptyAfterStripCheckStep    — 剥离后空内容检查
5. DebugContextCheckStep       — 调试上下文消息拦截
6. LanguageRewriteStep         — 英文重写 / fallback
7. SemanticDedupStep           — 整句语义去重（含二次改写）
8. PartialRepetitionStep       — 句子级部分包含检测（含二次改写）
9. SleepSanitizeStep           — 睡眠时间声明 / 场景邀请净化
10. LeakDetectionStep          — Prompt/推理泄露检测与回收
11. SleepEnforceStep           — 睡眠低打扰输出 / 冗余睡眠问题净化
12. FinalEmptyCheckStep        — 最终空内容检查
13. MessageTypeAdjustStep      — 睡眠会话消息类型降级
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from core.utils.logger import get_logger, get_module_logger
from core.services.active_care.postprocess.sleep_sanitizer import SleepSanitizer
from core.services.active_care.postprocess.deduplicator import Deduplicator
from core.services.active_care.postprocess.leak_detector import LeakDetector

if TYPE_CHECKING:
    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
        LanguageHandler,
        PostprocessContext,
    )

logger = get_logger("ACTIVE_CARE_PIPELINE")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")

# 短句关怀类 sys_prompt_type：天然容易与历史重复（"晚安""早安"等），
# 去重会误杀这类必要的一次性关怀，因此跳过整句去重和句子级部分包含检测，
# 仅保留后续的睡眠净化和泄露检测。
_DEDUP_BYPASS_SYS_PROMPT_TYPES = frozenset(
    {"goodnight_proactive", "good_morning_proactive", "sleep_again_proactive"}
)


# ── Pipeline State ────────────────────────────────────


@dataclass
class PipelineState:
    """Pipeline 中间状态，所有 step 共享"""

    # 待处理的文本（持续被各 step 修改）
    final_text: str = ""
    # 原始完整文本（用于 TTS，部分 step 会同步更新）
    full_raw_text: str = ""
    # 消息类型（text/voice 等）
    message_type: str = "text"
    # LLM thought 字段
    llm_thought: Optional[str] = None
    # 原始 response 对象（仅读取，不修改）
    response: Any = None

    # 中止标志
    aborted: bool = False
    abort_reason: str = ""

    # 中间状态（用于日志或后续 step 判断）
    previous_anchor: str = ""
    skip_dedup: bool = False
    dedup_scene: str = "general"


@dataclass
class PipelineDependencies:
    """Pipeline 依赖的处理器实例（由 ActiveCarePostprocessor 注入）"""

    language_handler: "LanguageHandler"
    deduplicator: Deduplicator
    sleep_sanitizer: SleepSanitizer
    leak_detector: LeakDetector
    postprocessor: "ActiveCarePostprocessor"  # 用于调用 _regenerate_non_repetitive_text
    agent: Any = None
    aveline_service: Any = None


# ── Pipeline Step 基类 ────────────────────────────────


class PipelineStep:
    """Pipeline 步骤基类"""

    name: str = "base"

    async def run(
        self,
        state: PipelineState,
        ctx: "PostprocessContext",
        deps: PipelineDependencies,
    ) -> None:
        """执行步骤，修改 state。如需中止，设置 state.aborted = True。"""
        raise NotImplementedError


# ── Step 实现 ─────────────────────────────────────────


class ContentExtractionStep(PipelineStep):
    """从 response 中提取初始 content / message_type / thought"""

    name = "content_extraction"

    async def run(self, state, ctx, deps) -> None:
        response = state.response
        final_text = (
            response.get("content", "")
            if isinstance(response, dict)
            else str(response)
        )
        full_raw_text = (
            response.get("full_content", final_text)
            if isinstance(response, dict)
            else str(response)
        )
        message_type = (
            response.get("message_type", "text")
            if isinstance(response, dict)
            else "text"
        )
        llm_thought = (
            response.get("thought") if isinstance(response, dict) else None
        )
        state.final_text = final_text
        state.full_raw_text = full_raw_text
        state.message_type = message_type
        state.llm_thought = llm_thought


class ReasoningStripStep(PipelineStep):
    """剥离推理段（<think>...</think>、TOOL_CALL 等）"""

    name = "reasoning_strip"

    async def run(self, state, ctx, deps) -> None:
        # 使用 postprocessor 的静态方法保持行为一致
        from core.services.active_care.postprocess.postprocessor import (
            ActiveCarePostprocessor,
        )

        state.final_text = ActiveCarePostprocessor.strip_reasoning_segments(
            state.final_text
        )
        state.full_raw_text = ActiveCarePostprocessor.strip_reasoning_segments(
            state.full_raw_text
        )


class EmojiStripStep(PipelineStep):
    """剥离 emoji / 软萌符号 / 内心独白"""

    name = "emoji_strip"

    async def run(self, state, ctx, deps) -> None:
        from core.services.active_care.postprocess.postprocessor import (
            ActiveCarePostprocessor,
        )

        final_text = state.final_text
        final_text = ActiveCarePostprocessor._strip_emoji_markers(final_text)
        final_text = ActiveCarePostprocessor._strip_all_emojis(final_text)
        final_text = ActiveCarePostprocessor._strip_cute_symbols_and_monologue(
            final_text
        )
        state.final_text = final_text


class EmptyAfterStripCheckStep(PipelineStep):
    """剥离推理后内容为空 → 中止"""

    name = "empty_after_strip_check"

    async def run(self, state, ctx, deps) -> None:
        if not str(state.final_text or "").strip():
            original_len = len(
                str(
                    state.response.get("content", "")
                    if isinstance(state.response, dict)
                    else ""
                )
            )
            msg_logger.warning(
                "Active Care: postprocess 剥离推理后内容为空，原始content长度=%d",
                original_len,
            )
            state.aborted = True
            state.abort_reason = "empty_after_strip"


class DebugContextCheckStep(PipelineStep):
    """拦截 LLM 错误消息（调试上下文消息）"""

    name = "debug_context_check"

    async def run(self, state, ctx, deps) -> None:
        from core.utils.debug_markers import is_debug_context_message

        if is_debug_context_message(state.final_text):
            msg_logger.error(
                f"Active Care: 拦截到 LLM 错误消息并放弃发送: {state.final_text}"
            )
            state.aborted = True
            state.abort_reason = "debug_context_message"


class LanguageRewriteStep(PipelineStep):
    """英文重写（若首选语言为 en 且文本以中文为主）"""

    name = "language_rewrite"

    async def run(self, state, ctx, deps) -> None:
        final_text = await deps.language_handler.rewrite_to_english_if_needed(
            agent=deps.agent,
            target_conversation_id=ctx.target_conversation_id,
            text=state.final_text,
            preferred_language=ctx.preferred_language,
        )
        state.final_text = final_text
        state.full_raw_text = final_text

        # 英文 fallback
        if (
            ctx.preferred_language == "en"
            and deps.language_handler.is_mostly_cjk(state.final_text)
        ):
            final_text = deps.language_handler.build_english_fallback(
                original_text=state.final_text,
                last_user_message=ctx.last_user_message,
            )
            state.final_text = final_text
            state.full_raw_text = final_text


class SemanticDedupStep(PipelineStep):
    """整句语义去重；命中则触发二次改写"""

    name = "semantic_dedup"

    async def run(self, state, ctx, deps) -> None:
        sys_prompt_type = ctx.sys_prompt_type if hasattr(ctx, "sys_prompt_type") else ""
        state.skip_dedup = sys_prompt_type in _DEDUP_BYPASS_SYS_PROMPT_TYPES
        if state.skip_dedup:
            msg_logger.info(
                "Active Care: sys_prompt_type=%s 跳过去重检测（短句关怀类）",
                sys_prompt_type,
            )
            return

        repeat_anchors = ctx.repeat_anchors or []
        previous_anchor = ""
        for anchor in repeat_anchors:
            if deps.deduplicator.is_semantically_repetitive(
                state.final_text, anchor, scene=state.dedup_scene
            ):
                previous_anchor = anchor
                break

        if not previous_anchor:
            return

        state.previous_anchor = previous_anchor
        msg_logger.info(
            "Active Care: 重复语义命中，触发模型二次改写。new='%s' prev='%s'",
            state.final_text[:80],
            previous_anchor[:80],
        )

        regenerated = await deps.postprocessor._regenerate_non_repetitive_text(
            aveline_service=deps.aveline_service,
            target_conversation_id=ctx.target_conversation_id,
            candidate_text=state.final_text,
            previous_proactive_message=previous_anchor,
            last_user_message=ctx.last_user_message,
            preferred_language=ctx.preferred_language,
            sys_prompt_type=sys_prompt_type,
        )

        if regenerated and (
            not any(
                deps.deduplicator.is_semantically_repetitive(
                    regenerated, anchor, scene=state.dedup_scene
                )
                for anchor in repeat_anchors
            )
        ):
            partial_after_regen = deps.deduplicator.analyze_partial_repetition(
                regenerated, repeat_anchors, scene=state.dedup_scene,
            )
            if not partial_after_regen["triggered"]:
                state.final_text = regenerated
                state.full_raw_text = regenerated
            else:
                msg_logger.info(
                    "Active Care: 二次改写通过整句去重，但仍命中句子级重复，跳过本轮发送。"
                )
                state.aborted = True
                state.abort_reason = "regen_passes_semantic_but_partial_hit"
        else:
            msg_logger.info("Active Care: 二次改写仍重复，跳过本轮发送。")
            state.aborted = True
            state.abort_reason = "regen_still_repetitive"

    @staticmethod
    def _final_dedup_check(
        state: PipelineState,
        ctx: "PostprocessContext",
        deps: PipelineDependencies,
    ) -> None:
        """发送前最终去重检查（供 FinalDedupCheckStep 使用）"""
        if state.skip_dedup:
            return
        repeat_anchors = ctx.repeat_anchors or []
        if any(
            deps.deduplicator.is_semantically_repetitive(
                state.final_text, anchor, scene=state.dedup_scene
            )
            for anchor in repeat_anchors
        ):
            msg_logger.info("Active Care: 发送前最终去重失败，跳过本轮发送。")
            state.aborted = True
            state.abort_reason = "final_dedup_failed"


class FinalDedupCheckStep(PipelineStep):
    """发送前最终去重检查（仅当未跳过去重时执行）"""

    name = "final_dedup_check"

    async def run(self, state, ctx, deps) -> None:
        if state.skip_dedup:
            return
        repeat_anchors = ctx.repeat_anchors or []
        if any(
            deps.deduplicator.is_semantically_repetitive(
                state.final_text, anchor, scene=state.dedup_scene
            )
            for anchor in repeat_anchors
        ):
            msg_logger.info("Active Care: 发送前最终去重失败，跳过本轮发送。")
            state.aborted = True
            state.abort_reason = "final_dedup_failed"


class PartialRepetitionStep(PipelineStep):
    """句子级部分包含检测；命中则触发二次改写"""

    name = "partial_repetition"

    async def run(self, state, ctx, deps) -> None:
        sys_prompt_type = (
            ctx.sys_prompt_type if hasattr(ctx, "sys_prompt_type") else ""
        )
        repeat_anchors = ctx.repeat_anchors or []

        if state.skip_dedup:
            partial_analysis: Dict[str, Any] = {"triggered": False}
        else:
            partial_analysis = deps.deduplicator.analyze_partial_repetition(
                state.final_text, repeat_anchors, scene=state.dedup_scene,
            )

        if not partial_analysis["triggered"]:
            return

        matched_preview = ""
        if partial_analysis["matches"]:
            first_match = partial_analysis["matches"][0]
            matched_preview = (
                f" sent='{str(first_match.get('sentence') or '')[:40]}'"
                f" anchor='{str(first_match.get('anchor') or '')[:40]}'"
                f" reason={first_match.get('reason') or 'unknown'}"
            )
        msg_logger.info(
            "Active Care: 句子级部分包含检测命中，重复句数=%s，阈值=%s。new='%s'%s",
            partial_analysis["repetitive_count"],
            partial_analysis["required_count"],
            state.final_text[:80],
            matched_preview,
        )

        rewrite_anchor = str(ctx.last_proactive_assistant_message or "").strip()
        if partial_analysis["matches"]:
            rewrite_anchor = str(
                partial_analysis["matches"][0].get("anchor") or ""
            ).strip()

        regenerated = await deps.postprocessor._regenerate_non_repetitive_text(
            aveline_service=deps.aveline_service,
            target_conversation_id=ctx.target_conversation_id,
            candidate_text=state.final_text,
            previous_proactive_message=rewrite_anchor,
            last_user_message=ctx.last_user_message,
            preferred_language=ctx.preferred_language,
            sys_prompt_type=sys_prompt_type,
        )

        if not regenerated:
            msg_logger.info(
                "Active Care: 句子级重复改写失败，跳过本轮发送。"
            )
            state.aborted = True
            state.abort_reason = "partial_regen_failed"
            return

        final_semantic_hit = any(
            deps.deduplicator.is_semantically_repetitive(
                regenerated, anchor, scene=state.dedup_scene
            )
            for anchor in repeat_anchors
        )
        final_partial_hit = deps.deduplicator.analyze_partial_repetition(
            regenerated, repeat_anchors, scene=state.dedup_scene,
        )["triggered"]

        if not final_semantic_hit and not final_partial_hit:
            state.final_text = regenerated
            state.full_raw_text = regenerated
        else:
            msg_logger.info(
                "Active Care: 句子级重复改写后仍命中去重，跳过本轮发送。"
            )
            state.aborted = True
            state.abort_reason = "partial_regen_still_hits"


class SleepSanitizeStep(PipelineStep):
    """睡眠时间声明 / 场景邀请净化"""

    name = "sleep_sanitize"

    async def run(self, state, ctx, deps) -> None:
        sys_prompt_type = (
            ctx.sys_prompt_type if hasattr(ctx, "sys_prompt_type") else ""
        )
        final_text = deps.sleep_sanitizer.sanitize_sleep_time_claims(
            state.final_text
        )
        final_text = deps.sleep_sanitizer.sanitize_sleep_scene_invitation(
            final_text, sys_prompt_type=sys_prompt_type
        )
        # 去除首尾引号
        final_text = str(final_text or "").strip().strip("""\u201c\u201d"'""")
        state.final_text = final_text
        state.full_raw_text = final_text


class LeakDetectionStep(PipelineStep):
    """Prompt / 推理泄露检测与回收"""

    name = "leak_detection"

    async def run(self, state, ctx, deps) -> None:
        if not deps.leak_detector.looks_like_prompt_or_reasoning_dump(
            state.final_text
        ):
            return

        msg_logger.warning(
            "Active Care: LeakDetector 检测到可能的 prompt/reasoning 泄露，尝试提取安全消息"
        )
        cleaned = deps.leak_detector.extract_safe_message_from_dump(
            state.final_text
        )
        if cleaned:
            state.final_text = cleaned
            state.full_raw_text = cleaned
        else:
            fallback = deps.deduplicator.build_non_repetitive_fallback(
                last_user_message=ctx.last_user_message,
                previous_proactive_message=ctx.last_proactive_assistant_message,
                preferred_language=ctx.preferred_language,
            )
            state.final_text = fallback
            state.full_raw_text = fallback


class SleepEnforceStep(PipelineStep):
    """睡眠低打扰输出 / 冗余睡眠问题净化"""

    name = "sleep_enforce"

    async def run(self, state, ctx, deps) -> None:
        sys_prompt_type = (
            ctx.sys_prompt_type if hasattr(ctx, "sys_prompt_type") else ""
        )
        final_text = deps.sleep_sanitizer.enforce_sleep_low_disturb_output(
            state.final_text,
            sleep_session_active=ctx.sleep_session_active,
            sleep_confirmed_by_silence=ctx.sleep_confirmed_by_silence,
            sys_prompt_type=sys_prompt_type,
        )
        final_text = deps.sleep_sanitizer.sanitize_redundant_sleep_question(
            final_text,
            known_sleep_time=ctx.known_sleep_time,
            last_user_message=ctx.last_user_message,
        )
        state.final_text = final_text
        state.full_raw_text = final_text


class FinalEmptyCheckStep(PipelineStep):
    """最终空内容检查（所有净化完成后）"""

    name = "final_empty_check"

    async def run(self, state, ctx, deps) -> None:
        if not str(state.final_text or "").strip():
            msg_logger.warning(
                "Active Care: postprocess produced empty content after stripping reasoning. Aborting send."
            )
            state.aborted = True
            state.abort_reason = "final_empty"


class MessageTypeAdjustStep(PipelineStep):
    """睡眠会话确认静默时，将 voice 降级为 text"""

    name = "message_type_adjust"

    async def run(self, state, ctx, deps) -> None:
        # 如果所有内容都是推理（例如MiniMax-M2.5仅返回
        # reasoning_content而没有实际消息），中止此次发送。
        if not str(state.final_text or "").strip():
            msg_logger.warning(
                "Active Care: postprocess produced empty content after stripping reasoning. Aborting send."
            )
            state.aborted = True
            state.abort_reason = "final_empty_after_all_steps"
            return

        # 确定应以语音还是文本发送
        # 如果message_type已确定为其他类型（如来自LLM），则尊重它
        # 否则，如果在睡眠会话中且通过静默确认，强制为'text'
        if (
            ctx.sleep_session_active
            and ctx.sleep_confirmed_by_silence
            and state.message_type == "voice"
        ):
            state.message_type = "text"


# ── Pipeline Runner ───────────────────────────────────


# 默认 step 顺序（与原 postprocess 长方法保持一致）
DEFAULT_STEPS: List[PipelineStep] = [
    ContentExtractionStep(),
    ReasoningStripStep(),
    EmojiStripStep(),
    EmptyAfterStripCheckStep(),
    DebugContextCheckStep(),
    LanguageRewriteStep(),
    SemanticDedupStep(),
    FinalDedupCheckStep(),
    PartialRepetitionStep(),
    SleepSanitizeStep(),
    LeakDetectionStep(),
    SleepEnforceStep(),
    FinalEmptyCheckStep(),
    MessageTypeAdjustStep(),
]


async def run_pipeline(
    *,
    response: Any,
    ctx: "PostprocessContext",
    deps: PipelineDependencies,
    steps: Optional[List[PipelineStep]] = None,
) -> Optional[Dict[str, Any]]:
    """运行后处理 pipeline

    Args:
        response: LLM 原始响应
        ctx: 后处理上下文
        deps: 依赖实例
        steps: 自定义 step 列表（默认使用 DEFAULT_STEPS）

    Returns:
        处理后的 dict（含 content/tts_text/message_type/llm_thought），
        或 None 表示中止发送
    """
    state = PipelineState(response=response)
    state.dedup_scene = (
        "reminder"
        if str(getattr(ctx, "sys_prompt_type", "") or "").strip().lower() == "reminder"
        else "general"
    )

    pipeline_steps = steps if steps is not None else DEFAULT_STEPS
    for step in pipeline_steps:
        if state.aborted:
            break
        try:
            await step.run(state, ctx, deps)
        except Exception as e:
            logger.exception(
                "Pipeline step '%s' 异常: %s", step.name, e
            )
            # 异常不中止整个管线，继续后续 step（保守策略）
            # 但记录错误以便排查

    if state.aborted:
        logger.debug(
            "Pipeline 中止: reason=%s, step=%s",
            state.abort_reason,
            pipeline_steps[-1].name if pipeline_steps else "unknown",
        )
        return None

    return {
        "content": state.final_text,
        "tts_text": state.full_raw_text,
        "message_type": state.message_type,
        "llm_thought": state.llm_thought,
    }
