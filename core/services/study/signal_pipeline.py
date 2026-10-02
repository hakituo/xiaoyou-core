"""四层流水线与对外唯一入口 ``detect_learning_signal``。

从 ``signal_detector.py`` 拆出。本模块只做**编排**：extract -> normalize -> filter
-> 消息层判定 -> promotion_gate，不新增判断口径。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.services.study.signal_extract import extract_raw_candidates
from core.services.study.signal_filter import filter_candidate
from core.services.study.signal_message import (
    _any_persona_candidate,
    _decide_message,
    _looks_like_knowledge_query,
    _looks_like_meta_question,
    _reject_signal,
)
from core.services.study.signal_normalize import normalize_candidate
from core.services.study.signal_patterns import (
    _ANSWER_MARKERS,
    _CONFUSION_PHRASES,
    _MASTERY_CLAIM_PHRASES,
    _MAX_CONCEPTS,
    _TEACHING_PHRASES,
)
from core.services.study.signal_promotion import (
    _is_subject_unconfirmed,
    decide_promotion,
)
from core.services.study.signal_subject import detect_subject_with_source
from core.services.study.signal_types import (
    FilteredCandidate,
    LearningIntent,
    LearningSignal,
    MessageDecision,
    NormalizedCandidate,
    RawCandidate,
)


def build_raw_candidates(
    message: str,
) -> Tuple[List[RawCandidate], List[NormalizedCandidate], List[FilteredCandidate]]:
    """跑完 extract -> normalize -> filter 三段，返回三段产物（供逐步断言）。"""
    raws = extract_raw_candidates(message)
    normalized = [normalize_candidate(raw) for raw in raws]
    subject, _source, _conf = detect_subject_with_source(message)
    # 认不出学科时，仍承认「明确的知识查询句式」——这正是 R-17 的场景。
    # **它只放宽 filter，不放宽 promotion**：建档仍由 promotion_gate 独立拒绝。
    open_domain = subject is None and _looks_like_knowledge_query(message)
    filtered = [
        filter_candidate(item, subject=subject, open_domain=open_domain, raw_text=message)
        for item in normalized
    ]
    return raws, normalized, filtered


def extract_concepts(message: str) -> List[str]:
    """兼容旧调用：返回 **admitted** 候选名。"""
    _raws, _normalized, filtered = build_raw_candidates(message)
    return [item.candidate for item in filtered if item.admit][:_MAX_CONCEPTS]


def detect_learning_signal(message: str) -> LearningSignal:
    """单条消息的学习信号判定（四层模型的对外唯一入口）。"""
    text = str(message or "")
    lowered = text.lower()
    evidence: List[str] = []
    intent = LearningIntent.NONE

    if any(p in lowered for p in _CONFUSION_PHRASES):
        intent = LearningIntent.CONFUSION
        evidence.append("confusion_phrase")
    elif any(p in lowered for p in _MASTERY_CLAIM_PHRASES):
        intent = LearningIntent.MASTERY_CLAIM
        evidence.append("mastery_claim_phrase")
    elif any(p in lowered for p in _ANSWER_MARKERS):
        intent = LearningIntent.ANSWER_ATTEMPT
        evidence.append("answer_marker")
    elif any(p in lowered for p in _TEACHING_PHRASES):
        # ``为什么`` / ``什么样的`` 出现在**第二人称或人设话题**里时不算学习意图：
        # 矩阵 R-19「为什么你今天不开心」问的是生活/情绪，不是知识——
        # 若照字面判成 ``teaching_request``，就会凭空造出一条学习消息
        # （而它本该是 ``none`` / reject）。矩阵 R-02/R-05 同理。
        #
        # 判据复用 ``_META_TOPIC_MARKERS`` + 第二人称开头：都是**结构性词面特征**，
        # 不引入新一层语义判断。
        if _looks_like_meta_question(text):
            intent = LearningIntent.NONE
            evidence.append("meta_question")
        else:
            intent = LearningIntent.TEACHING_REQUEST
            evidence.append("teaching_phrase")

    subject, subject_source, subject_confidence = detect_subject_with_source(text)
    raws, normalized, filtered = build_raw_candidates(text)
    admitted = [item for item in filtered if item.admit]

    # 认不出学科但抽得出候选：**不再伪造高置信**。
    # ``general`` 只作**路由标签**（用户架构评审的明确要求），
    # 置信度固定 0.3，且只能走到 ``candidate_only``——不得改权威状态。
    #
    # **只对「明确的知识查询句式」生效**：R-12「乳晕那个是什么」虽然抽出了
    # 候选，但它同时命中 intimate/口语语境，不应被 general 兜底洗白成
    # 可路由话题——所以这里用 ``_looks_like_knowledge_query`` 而不是裸的
    # ``admitted``。矩阵 R-12 要求 subject=None + candidate_only。
    open_domain = False
    if not subject and admitted and _looks_like_knowledge_query(text):
        open_domain = True
        subject = "general"
        subject_source = "open_domain_fallback"
        subject_confidence = 0.3
        evidence.append("open_domain_general")
    # 学科与候选**同时成立**，但学科只是「撞到学科名 / 撞到符号」（**未确认**）
    # 而消息是**明确的知识查询句式**时，按 open_domain 处理：
    # **放宽消息层判定，不放宽建档**。
    #
    # 依据是矩阵 §6「按学科词汇硬判太粗」与 §7「registry 是知识边界」：
    #   * ``耶稣这句话原文是什么语言？`` 只撞到 ``religion`` 的通用词，
    #     0.3 的置信度不该让消息升格；
    #   * 反过来，已经 **confirmed** 的学科（registry 命中 / 内容术语命中）
    #     不进这条分支——``柬埔寨国王``(confirmed history) 与
    #     ``光合作用``(confirmed biology) 就该拿到 ``accept``。
    #
    # 判定用 ``subject_source`` + 置信度而不是单看置信度数值：
    # **来源**决定「这条路本来就不可信」（keyword/formula），
    # **置信度**负责区分同名来源里的两档（content_hint 概念档 vs 话题档）。
    elif (
        subject
        and subject != "general"
        and admitted
        and _is_subject_unconfirmed(subject_source, subject_confidence)
        and _looks_like_knowledge_query(text)
    ):
        open_domain = True
        subject_source = "open_domain_fallback"
        subject_confidence = 0.3
        evidence.append("open_domain_downgrade")

    if not subject and not admitted and intent == LearningIntent.TEACHING_REQUEST:
        # 「为什么你今天不开心」这类：有 teaching phrase 但没有**可采纳**内容。
        # 但**明确的疑问句式 + 非角色话题**（矩阵 R-12）仍要留 candidate_only，
        # 不能因为候选被 filter 拒就把整条消息判死——那会丢掉诊断线索。
        #
        # ``text`` 必须传进去：R-01「Aveline的含金量」被 normalize 截断后
        # **人设词「Aveline」已不在候选里**，只看候选会误判成「非角色话题」。
        if _looks_like_knowledge_query(text) and not _any_persona_candidate(
            filtered, text=text
        ):
            return LearningSignal(
                intent=intent,
                is_learning=True,
                subject=None,
                confidence=0.4,
                evidence=list(evidence) + ["rejected_candidate_only"],
                raw_candidates=raws,
                normalized_candidates=normalized,
                filtered_candidates=filtered,
                message_decision=MessageDecision.CANDIDATE_ONLY,
                create_concept=False,
                allow_latest_binding=True,
                eligible_as_latest=False,
            )
        # **保留三层产物**——否则事后无法复盘「detector 到底看到了什么」，
        # 这正是当初脏数据无法追溯的原因之一。
        return _reject_signal(raws, normalized, filtered, evidence, intent=intent)

    if intent == LearningIntent.NONE:
        # 没有命中任何意图短语，但**确实围绕某个话题展开了**（抽到候选或认出学科）：
        # 记 ``pure_query``——矩阵 R-11「那奶头和胸是不是也……」的意图栏是
        # ``pure_query``（候选被拒也留意图，否则事后无法区分
        # 「没抽出东西」与「抽出了但被拒」）。
        #
        # **判据是 admitted / subject，不是 raws**：只要 filter 全部拒绝、
        # 也没认出学科，就不再假装这条消息有查询意图——
        # R-03「什么叫跑路啊喂」就属于这一类（矩阵意图栏为 ``none``）。
        if subject or admitted:
            intent = LearningIntent.PURE_QUERY
            evidence.append("subject_or_concept_only")
        else:
            return _reject_signal(raws, normalized, filtered, evidence, intent=intent)

    message_decision = _decide_message(
        intent=intent,
        subject=subject,
        subject_source=subject_source,
        subject_confidence=subject_confidence,
        admitted=admitted,
        filtered=filtered,
        text=text,
        open_domain=open_domain,
    )

    create_concept = decide_promotion(
        admitted,
        subject=subject,
        subject_source=subject_source,
        subject_confidence=subject_confidence,
        intent=intent,
        message_decision=message_decision,
    )

    if open_domain:
        # 「general」是路由标签不是学科证据：**整体置信度必须低**，
        # 避免重演 0.90 的假自信（矩阵 R-06/R-17 均要求 0.3）。
        confidence = 0.3
    elif subject:
        confidence = 0.4 + (0.3 if admitted else 0.0) + 0.2 * subject_confidence
    else:
        confidence = 0.3 + (0.2 if admitted else 0.0)
    if intent in (LearningIntent.CONFUSION, LearningIntent.ANSWER_ATTEMPT):
        confidence += 0.1
    if open_domain:
        confidence = min(confidence, 0.5)

    # 「消息有效」与「候选无效」可以并存（矩阵 R-07）：
    # candidate_only 时 admitted 仍可为空，事件照写、候选不落。
    #
    # eligible_as_latest（矩阵 §5 S-01/S-02 的核心区分）：
    #   「这条消息的候选够不够格当 latest_concept」——**只有真正进了候选层
    #   且学科可辨认**的才算。accept 时 admitted 非空即可；
    #   candidate_only 一律不算（否则 R-07 那种「有效但空」的消息会污染上下文）。
    eligible_as_latest = bool(admitted) and message_decision is MessageDecision.ACCEPT

    # is_learning 是写入口开关（observe_message）、prompt 注入依据（assembler）
    # 与学习模式判定依据（mode_detector）。它必须与 message_decision 一致，
    # 否则 reject 的消息会绕过 message_decision 的约束，从后门进 LLM。
    # 这是与 authority 同一类问题的第二个入口：降权必须两头都降。
    if message_decision is MessageDecision.REJECT:
        return _reject_signal(raws, normalized, filtered, evidence, intent=intent)

    return LearningSignal(
        intent=intent,
        is_learning=True,
        subject=subject,
        subject_source=subject_source,
        subject_confidence=subject_confidence,
        concepts=[item.candidate for item in admitted][:_MAX_CONCEPTS],
        confidence=round(min(1.0, confidence), 2),
        evidence=evidence,
        raw_candidates=raws,
        normalized_candidates=normalized,
        filtered_candidates=filtered,
        message_decision=message_decision,
        create_concept=create_concept,
        # allow_latest_binding：可不可以**回落到**最近的知识点
        # （作答/困惑不带知识点名时要靠它承接）
        allow_latest_binding=message_decision
        in (MessageDecision.ACCEPT, MessageDecision.CANDIDATE_ONLY),
        eligible_as_latest=eligible_as_latest,
    )


def intent_to_event_type(intent: LearningIntent) -> Optional[str]:
    mapping: Dict[LearningIntent, Optional[str]] = {
        LearningIntent.NONE: None,
        LearningIntent.PURE_QUERY: "question_asked",
        LearningIntent.TEACHING_REQUEST: "question_asked",
        LearningIntent.CONFUSION: "self_reported_confusion",
        LearningIntent.ANSWER_ATTEMPT: "answer_pending_evaluation",
        LearningIntent.MASTERY_CLAIM: "mastery_claim",
    }
    return mapping.get(intent)


def is_strong_evidence_intent(intent: LearningIntent) -> bool:
    """该意图是否构成**强证据**（可推进掌握度）。

    ``question_asked / mastery_claim / answer_pending_evaluation`` 是弱证据，
    只说明「用户接触过」，不构成掌握依据。
    """
    return intent in (LearningIntent.CONFUSION,)


# 旧名兼容：外部若曾引用 ``_clean_concept``，指向新的 normalize 语义
def _clean_concept(raw: str) -> str:
    """兼容包装：等价于对单个片段跑一遍 normalize。"""
    return normalize_candidate(
        RawCandidate(id="raw-0", name=str(raw or ""), source="explicit_topic")
    ).name
