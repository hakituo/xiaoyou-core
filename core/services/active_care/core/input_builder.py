"""Active Care LLM 输入构建器

负责根据上下文构建模型用户输入（沉默区间策略、自问自答防护、晚安守卫等）。
从 executor.py 拆分而来，方法签名与原 _xxx 方法保持一致。
"""
from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class ModelInputBuilder:
    """模型用户输入构建器

    所有方法均无副作用，仅依赖传入参数。
    """

    def build_model_user_input_for_active_care(
        self,
        *,
        user_input_mock: str,
        last_user_message: str,
        last_assistant_message: str,
        last_proactive_assistant_message: str,
        elapsed_seconds: float,
        preferred_language: str,
        sleep_session_active: bool = False,
        is_first_probe: bool = False,
        last_assistant_after_user: bool = False,
    ) -> str:
        """构建模型用户输入

        沉默区间策略：
        - < 1800s: 延续模式，顺接最近对话
        - >= 1800s: 主动触发模式，开启新话题

        自问自答防护：
        - 如果上一条助手消息是主动消息且用户尚未回复，不使用延续模式
        - 改为基于用户最后消息跟进或发起新话题

        主程序回复防护：
        - 如果最后一条助手消息是主程序（chat agent）的回复，且该回复晚于用户最后一条消息
          （last_assistant_after_user=True，说明主程序已经回复过用户那条消息），
          则把主程序的回复作为延续锚点，让 active care 顺着主程序的话继续往下说，
          而不是重新回应用户那条"已被主程序回复过"的消息。
        - 若主程序回复早于用户最后一条消息（用户消息尚未被回复），则仍用用户消息做跟进。
        """
        model_user_input = str(user_input_mock or "").strip()
        is_long_silence = elapsed_seconds >= 1800

        # 判断最后一条助手消息是否是主程序的回复（不是 active care 的主动消息）
        is_last_from_main_chat = bool(
            last_assistant_message
            and (
                not last_proactive_assistant_message
                or last_proactive_assistant_message != last_assistant_message
            )
        )

        # 自问自答防护：如果最后一条助手消息是主动消息且用户未回复，
        # 不使用它作为延续锚点，避免 AI 自己回答自己的主动消息
        if last_proactive_assistant_message and not last_user_message:
            # 只有主动消息、没有任何用户消息 → 视为长时间沉默
            continuation_anchor = ""
        elif last_proactive_assistant_message and last_proactive_assistant_message == last_assistant_message:
            # 最后一条助手消息就是主动消息，优先用用户消息做跟进而非延续自己的话
            # 只有当用户消息比较新（< 1800s）时才用用户消息做跟进
            if last_user_message and not is_long_silence:
                continuation_anchor = ""
            else:
                # 用户消息也很旧或不存在，开启新话题
                continuation_anchor = ""
        elif is_last_from_main_chat and last_assistant_after_user:
            # 主程序已经回复过用户最后一条消息（主程序回复时间 > 用户最后消息时间），
            # 用户那条消息已被回应，active care 不应再"回复主程序已回过的消息"。
            # 把主程序的回复作为延续锚点，顺着它继续往下说，保持对话连贯。
            continuation_anchor = str(last_assistant_message or "").strip()
        elif is_last_from_main_chat:
            # 主程序回复早于用户最后一条消息（用户消息尚未被主程序回复），
            # 用用户消息做跟进，不把过时的主程序回复当锚点。
            continuation_anchor = ""
        else:
            continuation_anchor = str(
                last_assistant_message or ""
            ).strip()

        assistant_gn_detected = self.detect_assistant_goodnight_in_anchor(
            continuation_anchor
        )

        if assistant_gn_detected and not is_long_silence:
            return self.build_goodnight_continuation_input(
                continuation_anchor, user_input_mock, preferred_language
            )

        if continuation_anchor and not is_long_silence:
            return self.build_continuation_input(
                continuation_anchor, user_input_mock, preferred_language,
            )
        if last_user_message and not is_long_silence:
            return self.build_follow_up_input(
                last_user_message, user_input_mock, preferred_language,
            )
        if is_long_silence:
            return self.build_proactive_trigger_input(
                preferred_language, sleep_session_active=sleep_session_active,
                is_first_probe=is_first_probe,
            )
        return model_user_input

    def detect_assistant_goodnight_in_anchor(self, anchor: str) -> bool:
        """检测延续锚点（最后助手消息）是否包含晚安意图"""
        if not anchor:
            return False
        try:
            from core.services.active_care.detection.intent_detector import IntentDetector
            detector = IntentDetector()
            return detector.contains_goodnight_intent(anchor)
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("检测晚安意图失败", exc_info=True)
            return False

    def build_goodnight_continuation_input(
        self,
        continuation_anchor: str,
        user_input_mock: str,
        preferred_language: str,
    ) -> str:
        """构建晚安后的延续输入，强约束不矛盾"""
        clipped = continuation_anchor[:300] + "..." if len(continuation_anchor) > 300 else continuation_anchor
        if preferred_language == "en":
            return (
                "[ACTIVE_CARE_CONTEXT_CONTINUATION]\n"
                f"Last assistant message: {clipped}\n"
                "[GOODNIGHT_GUARD]: You just said goodnight to the user. "
                "The user should be going to sleep now.\n"
                "Do NOT say anything that implies the user should wake up, get up, or is already awake.\n"
                "Keep the tone quiet, gentle, and consistent with having just said goodnight.\n"
                "If you cannot naturally continue the goodnight context, output nothing."
            )
        return (
            f"{user_input_mock}\n"
            f"[LAST_ASSISTANT_MESSAGE]: {clipped}\n"
            "[CONTINUATION_RULE]: 优先顺着你上一句往下推进，不要重新回答用户更早那句。\n"
            "[GOODNIGHT_GUARD]: 你刚才说了晚安，用户应该正在睡觉。"
            "绝对不要说任何暗示用户应该起床、已经醒来、或催促起床的话。"
            "保持安静、温柔、与晚安一致的语气。"
            "如果无法自然延续晚安语境，请输出空内容。"
        )

    def build_continuation_input(
        self,
        continuation_anchor: str,
        user_input_mock: str,
        preferred_language: str,
    ) -> str:
        """构建延续输入"""
        clipped = continuation_anchor[:300] + "..." if len(continuation_anchor) > 300 else continuation_anchor
        if preferred_language == "en":
            return (
                "[ACTIVE_CARE_CONTEXT_CONTINUATION]\n"
                f"Last assistant message: {clipped}\n"
                "Continue from your own previous line in English.\n"
                "Do NOT re-answer the user's older message.\n"
                "IMPORTANT: If your last message was a proactive question or greeting "
                "(not a reply to user), do NOT answer it yourself. Start a NEW topic instead."
            )
        return (
            f"{user_input_mock}\n"
            f"[LAST_ASSISTANT_MESSAGE]: {clipped}\n"
            "[CONTINUATION_RULE]: 优先顺着你上一句往下推进，不要重新回答用户更早那句。\n"
            "[ANTI_SELF_QA]: 如果你上一句是主动发起的问候或提问（不是回复用户），"
            "不要自己回答自己的问题，应开启新话题或等待用户回复。"
        )

    def build_follow_up_input(
        self,
        last_user_message: str,
        user_input_mock: str,
        preferred_language: str,
    ) -> str:
        """构建跟进输入"""
        clipped = last_user_message[:300] + "..." if len(last_user_message) > 300 else last_user_message
        if preferred_language == "en":
            return (
                "[ACTIVE_CARE_CONTEXT_CONTINUATION]\n"
                f"Last user message: {clipped}\n"
                "Reply as a direct follow-up to this topic in English.\n"
                "IMPORTANT: Do NOT repeat or rephrase the main program's previous reply. "
                "Continue the conversation naturally from where it left off."
            )
        return (
            f"{user_input_mock}\n[LAST_USER_MESSAGE]: {clipped}\n"
            "[重要] 不要重复主程序已经回复过的内容！继续对话，从上次聊到的地方自然接话。"
        )

    def build_proactive_trigger_input(self, preferred_language: str, *, sleep_session_active: bool = False, is_first_probe: bool = False) -> str:
        """构建主动触发输入

        Args:
            preferred_language: 首选语言
            sleep_session_active: 睡眠会话是否活跃
            is_first_probe: 是否是晚安后的首次探针（确认用户是否真的睡了）
        """
        if preferred_language == "en":
            base = (
                "[ACTIVE_CARE_PROACTIVE_TRIGGER]\n"
                "This is a PROACTIVE message, NOT a reply to user's last message.\n"
                "Start a NEW topic based on current time, user profile, or daily schedule.\n"
                "Do NOT repeat the user's last message, but respect any facts they already shared."
            )
            if sleep_session_active:
                base += (
                    "\n[GOODNIGHT_GUARD]: Sleep session is active (you recently said goodnight). "
                    "Do NOT say anything that implies the user should wake up or get up. "
                    "Keep the tone quiet and sleep-friendly."
                )
                if is_first_probe:
                    from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
                        GOODNIGHT_PROBE_INSTRUCTION,
                        GOODNIGHT_PROBE_EXAMPLES,
                    )
                    base += GOODNIGHT_PROBE_INSTRUCTION + GOODNIGHT_PROBE_EXAMPLES
            return base
        base = (
            "[ACTIVE_CARE_PROACTIVE_TRIGGER]\n"
            "这是主动发起的问候，不是回复用户的消息。\n"
            "请基于当前时间、用户画像或日程安排开启新话题。\n"
            "不要复读用户最后一条消息，但用户已告知的事实必须尊重。"
        )
        if sleep_session_active:
            base += (
                "\n[GOODNIGHT_GUARD]: 睡眠会话活跃（你最近说了晚安）。"
                "绝对不要说任何暗示用户应该起床或已经醒来的话。"
                "保持安静、适合睡眠的语气。"
            )
            if is_first_probe:
                from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
                    GOODNIGHT_PROBE_INSTRUCTION,
                    GOODNIGHT_PROBE_EXAMPLES,
                )
                base += GOODNIGHT_PROBE_INSTRUCTION + GOODNIGHT_PROBE_EXAMPLES
        return base

    def resolve_known_sleep_time(self) -> str:
        """解析已知睡眠时间"""
        try:
            from core.services.daily.manager import get_daily_manager
            summary = get_daily_manager().get_today_summary()
            from core.services.active_care.prompt.prompt_builder import extract_known_sleep_time_fact
            return extract_known_sleep_time_fact(summary)
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("解析已知睡眠时间失败", exc_info=True)
            return ""

