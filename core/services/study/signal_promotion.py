"""层 4 promotion_gate：候选有没有资格进入 ConceptState。

从 ``signal_detector.py`` 拆出。**独立于 filter**——filter 通过 ≠ 可建档。
"""
from __future__ import annotations

from typing import List, Optional

from core.services.study.signal_types import (
    FilteredCandidate,
    LearningIntent,
    MessageDecision,
)


# ----------------------------------------------------------------------
# 层 4：promotion_gate —— 候选有没有资格进入 ConceptState
# ----------------------------------------------------------------------

CREATE_CONCEPT_INTENTS = frozenset(
    {
        LearningIntent.TEACHING_REQUEST,
        LearningIntent.PURE_QUERY,
        LearningIntent.CONFUSION,
        LearningIntent.ANSWER_ATTEMPT,
    }
)

# 只有这些来源才允许**从 message 直接晋升** ConceptState。
# passive 观察路径（question_asked / mastery_claim / answer_attempt）
# 一律不创建 —— 这是本模块修复的核心越权点。
#
# **注意**：``registry`` / ``keyword`` / ``formula`` 都**不在**这里。
# 矩阵 R-15/R-16 明确要求「registry 识别出 biology/physics、filter 通过、
# 消息 accept，但 create_concept=False」——用户只是提问，不代表该建知识点。
PROMOTION_SOURCES = frozenset({"explicit_tool"})

# 学科证据的最低置信度：低于它连 ``accept`` 都拿不到（只能 candidate_only）。
#
# **0.9 而不是 0.7**：矩阵 R-15/R-16（已确认学科 → accept）与
# R-07/R-08/R-09（未确认学科 → candidate_only）的分界就在这。
# 校准原则与 ``SubjectRegistry.match_text`` 一致：
# **长 alias（>= 3 字符）→ 高置信；短 alias / 关键字兜底 → 低置信**。
ACCEPT_SUBJECT_CONFIDENCE = 0.9

# **未确认**的学科来源：只是「撞到学科名 / 撞到符号 / 撞到领域专名」，
# 不是「认出了学科概念」。
#
# 分界依据（矩阵 §3 / §6 / §7）：
#   registry      —— 维护者显式声明的 canonical，已确认
#   content_hint  —— 内容术语命中：
#                     * 概念档（光合作用/胡克定律）0.9 → 已确认
#                     * 话题档（柬埔寨国王/财产局）0.75 → **未确认**（矩阵 R-08/R-09）
#   content_hint  —— 内容术语命中，**再看置信度**：
#                     * 概念档（光合作用/胡克定律）0.9 → 已确认
#                     * 话题档（柬埔寨国王/财产局）0.75 → 未确认（矩阵 R-08/R-09）
#   keyword       —— 通用学科名表（``SUBJECT_KEYWORDS``），只是提到了学科名，一律未确认
#
# （``formula`` 不在列表里：矩阵 R-16 明确它是**强领域证据**，给 0.9。）
UNCONFIRMED_SUBJECT_SOURCES = frozenset({"keyword"})
# 需要**结合置信度**再判的来源（同为 content_hint，两档语义完全不同）
_CONFIDENCE_SENSITIVE_SOURCES = frozenset({"content_hint"})


def _is_subject_unconfirmed(
    subject_source: Optional[str], subject_confidence: float
) -> bool:
    """学科证据是否**未确认**（不足以让消息升格为 ``accept``）。

    判定顺序即优先级：

    1. **已知强来源**（``registry`` / ``explicit_tool``）→ 已确认，直接 False；
    2. ``content_hint`` 同时覆盖概念档（0.9）与话题档（0.75），
       必须**结合置信度**判定；
    3. 其余来源（``keyword`` 等）→ 未确认。

    最后一条兜底用**置信度**而不是"不在名单里就算未确认"——
    否则任何新增来源都会默认被降级，而新增来源更可能是我们还没想清楚的，
    应当让置信度说话。
    """
    if subject_source in ("registry", "explicit_tool"):
        return False
    if subject_source in _CONFIDENCE_SENSITIVE_SOURCES:
        # ``content_hint``：概念档 0.9 已确认、话题档 0.75 未确认
        return subject_confidence < ACCEPT_SUBJECT_CONFIDENCE
    if subject_source in UNCONFIRMED_SUBJECT_SOURCES:
        return True
    return subject_confidence < ACCEPT_SUBJECT_CONFIDENCE


def decide_promotion(
    admitted: List[FilteredCandidate],
    *,
    subject: Optional[str],
    subject_source: Optional[str],
    subject_confidence: float,
    intent: LearningIntent,
    message_decision: MessageDecision,
) -> bool:
    """独立判定「候选有没有资格进入 ConceptState」。

    **不在 filter 内**：filter 通过 ≠ 可建档（矩阵 R-15/R-16/R-17）。

    只有**显式工具调用**（``study_record_teaching``）才允许建档——
    用户提问、自述没听懂、疑似作答都不算「该建一个知识点」的证据。
    """
    if not admitted:
        return False
    if message_decision is not MessageDecision.ACCEPT:
        return False
    if intent not in CREATE_CONCEPT_INTENTS:
        return False
    if not subject or subject == "general":
        return False
    if subject_source not in PROMOTION_SOURCES:
        return False
    return subject_confidence >= ACCEPT_SUBJECT_CONFIDENCE
