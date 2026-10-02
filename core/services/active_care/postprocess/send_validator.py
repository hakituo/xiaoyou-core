"""主动消息发送层硬 Gate（defense-in-depth）

2026-09-04 改造：即使决策层已经有了工具出口（send/defer），发送前仍保留
最后一层确定性校验，防止三类内容漏进用户消息链路：

    1. reject_internal_meta   — prompt 内部控制标记 / 决策过程表述泄漏
                                 （[GOODNIGHT_GUARD] / "先不发了" / "按优先级" 等）
    2. reject_prompt_leak     — 整段 prompt / 推理过程泄漏（复用 LeakDetector）
    3. reject_excessive_length— 超长兜底（> poke_max_chars 的普通 poke 压缩一次，
                                 仍超长就 DROP，不进发送链路）

这层不做"语义纠错"，只做"该拦的坚决拦"。拦截后的压缩/丢弃由 pipeline 步骤负责。
"""

import re
from dataclasses import dataclass
from typing import Optional

from core.utils.logger import get_module_logger
from core.services.active_care.postprocess.leak_detector import LeakDetector

logger = get_module_logger("ACTIVE_CARE_SEND_VALIDATOR", "active_care_messages.log")

# 长消息兜底上限（普通 poke 类型硬上限；超出先压缩一次，仍超就 DROP）
DEFAULT_POKE_MAX_CHARS = 40
# 任何任务类型都不得突破的绝对上限。固定提醒可豁免短消息上限，
# 但不能允许数千字推理过程借“完整传达”之名穿透发送门。
ABSOLUTE_MESSAGE_MAX_CHARS = 1200

# 控制标记 / 内部字段名：正常用户消息里不应出现
_INTERNAL_META_MARKERS = (
    # 内部控制区块
    "[GOODNIGHT_GUARD]",
    "[CONTINUATION_RULE]",
    "[ANTI_SELF_QA]",
    "[ACTIVE_CARE_PROACTIVE_TRIGGER]",
    "[ACTIVE_CARE_CONTEXT_CONTINUATION]",
    "[LAST_ASSISTANT_MESSAGE]",
    "[LAST_USER_MESSAGE]",
    "[TOOL_CALL]",
    # 决策协议字段 / 内部类型名
    "send_active_care",
    "defer_active_care",
    "defer_reason",
    "reason_code",
    "retry_after_seconds",
    "retry_after_minutes",
    "should_send",
    "next_check_seconds",
    "specific_instruction",
    "curious_question",
    "share_thought",
    "planned_topic",
    # 决策过程表述（模型把"不发的理由"当消息发出来）
    "先不发了",
    "先不发",
    "不发了",
    "等他回复",
    "等他回",
    "稍后再看",
    "稍后再说",
    "这轮不适合发",
    "这轮不发",
    "这轮跳过",
    "系统判定",
    "按优先级",
    "冲突检测",
    "我就不打扰",
    "不打扰你",
    "我决定不打扰",
)

# "长铺垫转场词"：prompt 层明令禁止的无意义转场。短 poke 若含这些词又带提问，
# 几乎必然是『报备自己在做什么 → 突然想到 → 追问』的铺垫结构（案例 4），硬拦。
# 只匹配"行首或标点之后"的位置，避免误伤"话说得有点多"这类普通表达。
_PADDED_TRANSITION_RE = re.compile(
    r"(^|[，,。！？!?：:\s])"
    r"(?:话说|对了|刚好|突然想到|刚看到|我刚看到|我刚发现|突然想起来|刚好看到)"
)

# 疑问句特征（用于确认是否在"带铺垫地问用户"）
_INTERROGATIVE_MARKERS = ("？", "?", "吗", "么", "没？", "呢？")


# 短 poke 类型：自由聊天 / 轻量陪伴，需应用"一句话短消息"长度与风格约束。
SHORT_POKE_INTENTS = frozenset({
    "proactive_chat",
    "curious_question",
    "share_thought",
    "emotional_support",
    "gossip_share",
    "weather_complaint",
    "share_peer_chat",
    "planned_topic",
    "checking",
})


# 压缩/长度校验豁免的任务类型：固定任务内容（通知转述/提醒/数字健康等）
# 以"完整准确传达关键信息"为优先，不为凑短丢信息，只做元信息/泄漏硬拦。
POKE_LENGTH_EXEMPT_TYPES = frozenset({
    "reminder",
    "notification_assistant",
    "usage_limit_exceeded",
    "focus_nudge",
    "morning_report",
    "wake_up_greeting",
    "sleep_again_proactive",
    "activity_return_proactive",
    "goodnight_proactive",
    "good_morning_proactive",
    "insomnia",
    "bio_complaint",
    "user_health_reminder",
})


# 睡眠语境下的唤醒类硬禁短语（Prompt v2：sleep-safe 是 P1 硬约束）
_SLEEP_WAKE_PHRASES = (
    "醒了没", "起床了没", "还在睡吧", "该起了", "该起床了",
    "怎么还不睡", "又熬夜", "你怎么还没醒", "快起来",
)


@dataclass
class ValidationResult:
    """校验结果。allowed=False 表示不得进入发送链路。"""

    allowed: bool
    reason: str = ""
    text: str = ""

    @classmethod
    def ok(cls, text: str) -> "ValidationResult":
        return cls(allowed=True, text=text)

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        return cls(allowed=False, reason=reason)


class ActiveCareSendValidator:
    """发送前最后一层确定性校验。"""

    def __init__(self, max_poke_chars: int = DEFAULT_POKE_MAX_CHARS):
        self.max_poke_chars = int(max_poke_chars or DEFAULT_POKE_MAX_CHARS)

    # ==================== 单条检查 ====================

    @staticmethod
    def reject_internal_meta(text: str) -> Optional[str]:
        """拦截内部控制标记/内部字段名泄漏。返回拦截原因；通过返回 None。"""
        raw = str(text or "")
        if not raw:
            return None
        for marker in _INTERNAL_META_MARKERS:
            if marker in raw:
                return f"internal_meta_marker:{marker[:30]}"
        return None

    @staticmethod
    def reject_prompt_leak(text: str) -> Optional[str]:
        """拦截整段 prompt / 推理过程泄漏。返回拦截原因；通过返回 None。"""
        if LeakDetector.looks_like_prompt_or_reasoning_dump(text):
            return "prompt_or_reasoning_leak"
        return None

    def reject_excessive_length(self, text: str, sys_prompt_type: str = "") -> Optional[str]:
        """拦截超出长度兜底的普通 poke。返回拦截原因；通过返回 None。"""
        text_len = len(str(text or ""))
        if text_len > ABSOLUTE_MESSAGE_MAX_CHARS:
            return f"excessive_length_absolute:{text_len}>{ABSOLUTE_MESSAGE_MAX_CHARS}"
        if str(sys_prompt_type or "").strip() in POKE_LENGTH_EXEMPT_TYPES:
            return None
        if text_len > self.max_poke_chars:
            return f"excessive_length:{text_len}>{self.max_poke_chars}"
        return None

    @staticmethod
    def reject_padded_style(text: str, sys_prompt_type: str = "") -> Optional[str]:
        """拦截『报备自己在做什么 → 转场 → 追问』的铺垫结构。

        案例 4："浇花呢，刚看到阳台上的绿萝又抽新芽了。你英语复习开始了没？"
        ——命中"转场词（刚看到）+ 提问"，属于 prompt 层禁止的"为了弱化查岗感
        先写两句生活铺垫"结构。命中后交给压缩（把核心意思压成一句话），
        而不是直接丢弃（内容本身可以挽救）。
        """
        raw = str(text or "")
        if not raw:
            return None
        if str(sys_prompt_type or "").strip() in POKE_LENGTH_EXEMPT_TYPES:
            return None
        # 只拦截"同时含转场词 + 提问意图"的文本
        if not _PADDED_TRANSITION_RE.search(raw):
            return None
        if not any(m in raw for m in _INTERROGATIVE_MARKERS):
            return None
        return "padded_poke_style"

    @staticmethod
    def reject_sleep_wake_phrases(text: str, sleep_session_active: bool = False) -> Optional[str]:
        """睡眠语境的唤醒类硬禁短语（P1 硬约束的确定性兜底）。"""
        if not sleep_session_active:
            return None
        raw = str(text or "")
        for phrase in _SLEEP_WAKE_PHRASES:
            if phrase in raw:
                return f"sleep_wake_phrase:{phrase[:20]}"
        return None

    # ==================== 汇总 ====================

    def validate(
        self, text: str, sys_prompt_type: str = "", sleep_session_active: bool = False
    ) -> ValidationResult:
        """对发送前文本做完整校验。

        Args:
            sys_prompt_type: 任务类型（用于长度/风格豁免判断）。
            sleep_session_active: 睡眠会话是否活跃（P1 硬校验开关）。

        Returns:
            ValidationResult：allowed=False 携带原因；allowed=True 携带原文本。
        """
        cleaned = str(text or "").strip()
        if not cleaned:
            return ValidationResult.reject("empty_content")

        meta_hit = self.reject_internal_meta(cleaned)
        if meta_hit:
            logger.warning(
                "Active Care: 发送门拦截内部控制标记泄漏 (%s): %s",
                meta_hit, cleaned[:80],
            )
            return ValidationResult.reject(meta_hit)

        leak_hit = self.reject_prompt_leak(cleaned)
        if leak_hit:
            logger.warning(
                "Active Care: 发送门拦截 prompt/推理泄漏 (%s): %s",
                leak_hit, cleaned[:80],
            )
            return ValidationResult.reject(leak_hit)

        sleep_hit = self.reject_sleep_wake_phrases(cleaned, sleep_session_active)
        if sleep_hit:
            logger.warning(
                "Active Care: 发送门拦截睡眠唤醒短语 (%s): %s",
                sleep_hit, cleaned[:80],
            )
            return ValidationResult.reject(sleep_hit)

        length_hit = self.reject_excessive_length(cleaned, sys_prompt_type)
        if length_hit:
            return ValidationResult.reject(length_hit)

        padded_hit = self.reject_padded_style(cleaned, sys_prompt_type)
        if padded_hit:
            return ValidationResult.reject(padded_hit)

        return ValidationResult.ok(cleaned)


__all__ = [
    "ActiveCareSendValidator",
    "ValidationResult",
    "POKE_LENGTH_EXEMPT_TYPES",
    "DEFAULT_POKE_MAX_CHARS",
]
