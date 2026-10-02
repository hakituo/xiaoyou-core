"""消息层判定：这条消息本身算不算学习行为（与候选是否有效分开）。

从 ``signal_detector.py`` 拆出。``_decide_message`` 出判定，
``_reject_signal`` 负责把三层产物与拒因留证（脏数据可复盘）。
"""
from __future__ import annotations

from typing import List, Optional

from core.services.study.signal_patterns import (
    _CHEM_FORMULA_RE,
    _FILLER_ONLY,
    _FORMULA_RE,
    _KNOWLEDGE_QUERY_RE,
    _META_QUESTION_RE,
    _META_TOPIC_MARKERS,
    _PERSONA_MARKERS,
    _SECOND_PERSON_META,
    _WEAK_FILLER_WORDS,
)
from core.services.study.signal_promotion import ACCEPT_SUBJECT_CONFIDENCE
from core.services.study.signal_subject import _match_content_hint
from core.services.study.signal_types import (
    FilteredCandidate,
    LearningIntent,
    LearningSignal,
    MessageDecision,
    NormalizedCandidate,
    RawCandidate,
    RejectReason,
)


# ----------------------------------------------------------------------
# 消息层判定
# ----------------------------------------------------------------------


def _looks_like_meta_question(text: str) -> bool:
    """含疑问词，但问的是**角色/情绪/生活**而不是知识。

    矩阵 R-19「为什么你今天不开心」与 R-02「好好看你人设是什么样的」：
    字面含 ``为什么`` / ``什么样的``，但问的对象是「你」（角色）或情绪，
    不构成学习意图。判据只用**结构特征**：

      * 命中 ``_META_TOPIC_MARKERS``（你头发/你人设/你名字…），或
      * 命中 ``_META_QUESTION_RE``——**疑问词与第二人称相邻**。

    **不能只判「句中出现第二人称」**：``为什么国内对于资本家的刻板印象
    我不知道国外是不是`` 里有 ``我``，但它只是附属子句的主语，
    被问的对象是「国内…刻板印象」（矩阵 R-06/R-07 要求 teaching_request）。
    必须要求第二人称**紧跟在疑问词之后**，才是「在问对方」。
    """
    body = str(text or "")
    # ``_META_TOPIC_MARKERS`` 里的**外观类**词（你头发/你眼睛）不足以单独
    # 否定学习意图——矩阵 R-05「不过你头发为什么是紫色的」意图仍是
    # ``teaching_request``；只有**人设类**词（你人设/你的设定）才否定意图
    # （矩阵 R-02「好好看你人设是什么样的」→ ``none``）。
    if any(marker in body for marker in _PERSONA_MARKERS):
        return True
    if not _META_QUESTION_RE.search(body):
        return False
    # 句中有真正的学习内容（公式 / 课程标准概念）时不算 meta
    if _FORMULA_RE.search(body) or _CHEM_FORMULA_RE.search(body):
        return False
    if _match_content_hint(body, tier="concept"):
        return False
    return True


def _looks_like_knowledge_query(text: str) -> bool:
    """消息是否为**明确的知识查询句式**（不判断领域，只判断句式）。"""
    body = str(text or "")
    if any(marker in body for marker in _META_TOPIC_MARKERS):
        return False
    return bool(_KNOWLEDGE_QUERY_RE.search(body))


def _any_persona_candidate(
    filtered: List[FilteredCandidate], *, text: str = ""
) -> bool:
    """这条消息是否**本质上在聊角色/人设/语气**，而不是在问知识。

    用于区分「真提问但候选不合格」（R-12「乳晕那个是什么」，留 candidate_only）
    与「问的是角色或纯语气」R-01/R-02/R-10/R-18/R-19（必须 reject）。

    两类判据（任一成立即算角色/语气话题）：

    1. **候选层**：被拒理由落在「这段内容本身不是话题」的集合里。
       只有 ``weak_source`` / ``no_subject_evidence`` 这两种
       「内容是话题、只是证据不够」的理由才允许 downgrade 成 candidate_only。
    2. **消息层（``text``）**：``_PERSONA_MARKERS`` / ``_SECOND_PERSON_META``
       命中。**必须有这一条**：R-01 的 ``Aveline的含金量`` 在 normalize 时
       ``truncate_clause`` 把 ``，以前的所有东西都能找出来`` 截掉了，
       人设词「Aveline」也随之消失——只看候选就再也看不出它在聊角色。

    **没有任何候选时**（R-19「为什么你今天不开心」）：
    连候选都没抽出来，谈不上「有话题但证据不够」，直接判为角色/语气话题。
    """
    if text:
        lowered = str(text).lower()
        if any(marker in lowered for marker in _PERSONA_MARKERS):
            return True
        if any(marker in lowered for marker in _SECOND_PERSON_META):
            return True
    if not filtered:
        return True
    topicish = {
        RejectReason.WEAK_SOURCE.value,
        RejectReason.NO_SUBJECT_EVIDENCE.value,
    }
    reasons = [item.reason for item in filtered if not item.admit]
    if not reasons:
        return False
    # **语气/填充词不算话题**：R-10「猜猜看」的拒因是 ``weak_source``，
    # 单看理由会误判成「有话题只是证据不够」（→ candidate_only），
    # 但它是**语气词**，矩阵要求 reject（R-10 reason：语气词）。
    # R-12「乳晕」同样是 ``weak_source``，但它是**内容名词**，就该留 candidate_only。
    # 二者的分界是**词本身是否承载语义**，不是拒因字符串。
    for item in filtered:
        if item.admit:
            continue
        if item.candidate in _WEAK_FILLER_WORDS or item.candidate in _FILLER_ONLY:
            return True
    return any(reason not in topicish for reason in reasons)


def _reject_signal(
    raws: List[RawCandidate],
    normalized: List[NormalizedCandidate],
    filtered: List[FilteredCandidate],
    evidence: List[str],
    *,
    intent: LearningIntent = LearningIntent.NONE,
) -> LearningSignal:
    """构造「消息层判定为 reject」的信号，**保留三层产物与拒因**。

    ``extract / normalize / filter`` 的结果必须留证：即使消息最终被拒，
    也要能回答「detector 看到了什么、为什么没通过」——
    否则脏数据出现后无法事后复盘（这正是本次修复的动因）。

    ``intent`` 照实记录（矩阵要求）：**「识别到什么意图」与「要不要落库」
    是两个问题**。消息被拒不代表没识别出意图，抹掉它会让复盘失真。
    """
    return LearningSignal(
        intent=intent,
        is_learning=False,
        subject=None,
        concepts=[],
        confidence=0.0,
        evidence=list(evidence),
        raw_candidates=raws,
        normalized_candidates=normalized,
        filtered_candidates=filtered,
        message_decision=MessageDecision.REJECT,
        create_concept=False,
        allow_latest_binding=False,
        eligible_as_latest=False,
    )


def _decide_message(
    *,
    intent: LearningIntent,
    subject: Optional[str],
    subject_source: Optional[str],
    subject_confidence: float,
    admitted: List[FilteredCandidate],
    filtered: Optional[List[FilteredCandidate]] = None,
    text: str,
    open_domain: bool = False,
) -> MessageDecision:
    """消息层判定：这条消息本身算不算学习行为（与候选是否有效**分开**）。"""
    filtered = filtered if filtered is not None else list(admitted)
    if intent is LearningIntent.CONFUSION or intent is LearningIntent.ANSWER_ATTEMPT:
        # 先排除「问的是角色/人设」：「我没明白你的人设是什么」也命中困惑句式，
        # 但它谈的是角色，不是知识——必须 reject，不能留成诊断事件。
        # 否则 is_learning=True 会让它继续走到 observe_message / prompt /
        # 学习模式判定，等于把角色闲聊当成学习行为喂进去。
        #
        # 加 ``_looks_like_knowledge_query`` 守卫：``_any_persona_candidate``
        # 在「一个候选都没有」时无条件返回 True（那是为「为什么你今天不开心」
        # 设的规则），但「我还是没听懂」同样没候选，却是**真困惑**。
        # 区分点是句式：困惑/作答声明本身不含知识疑问，不该被当成人设话题；
        # 只有「在问某个东西是什么」时才需要警惕它其实在问角色。
        if (
            not admitted
            and _looks_like_knowledge_query(text)
            and _any_persona_candidate(filtered, text=text)
        ):
            return MessageDecision.REJECT
        # 无绑定上下文的信号只留诊断事件，不得改权威状态。
        #
        # 注意：这里仍然 is_learning=True（见下方 return）。diagnostic_only 的
        # 含义是「**不改状态**」，不是「不是学习行为」——「我还是没听懂」这类
        # 正是靠它回落最近知识点、留下待绑定的痕迹。真正的降权靠 authority：
        # 这些事件一律写 observed，进不了 prompt / ZPD / 日记。
        if not admitted and not subject:
            return MessageDecision.DIAGNOSTIC_ONLY
        return MessageDecision.CANDIDATE_ONLY

    if intent is LearningIntent.MASTERY_CLAIM:
        # 自称掌握永远不改权威状态
        return MessageDecision.CANDIDATE_ONLY

    # TEACHING_REQUEST / PURE_QUERY
    if not admitted and not subject:
        # 明确的疑问句式（矩阵 R-12「乳晕那个是什么」）：候选虽被 filter 拒，
        # 但**消息本身是提问**——留 candidate_only 供诊断，不静默丢弃。
        # 只有当句式也不成立（纯闲聊 / 角色纠正 / 半截话）才 reject。
        #
        # 必须同时排除「元话题 + 被拒候选全是非学习语境」：
        # R-01/R-02/R-05 也含「为什么/什么样的」，但它们问的是角色，必须 reject。
        if _looks_like_knowledge_query(text) and not _any_persona_candidate(
            filtered, text=text
        ):
            return MessageDecision.CANDIDATE_ONLY
        # 半截话、纯闲聊、角色纠正
        return MessageDecision.REJECT

    # **passive 观察路径几乎不给 accept。**
    #
    # 矩阵 R-07/R-08/R-09 的核心结论：即使学科识别正确（registry 0.75）、
    # 候选也准入，用户**只是问了一句**，不构成「这条消息可以改权威状态」的证据。
    #
    # accept 的门槛是**高置信学科证据 + 候选准入**：
    #   R-15（registry 0.9 + 光合作用 admit）→ accept
    #   R-16（registry 0.9 + F=-kx admit）→ accept
    #   R-07/R-08/R-09（registry 0.75）→ candidate_only
    #
    # **注意 ``admitted`` 也必须在门槛里**：单看学科置信度会让
    # 「学科够强但候选全被 filter 拒」（R-07）拿到 accept——
    # 而 accept 是「消息可进闭环」的许可，没有候选就没有闭环对象。
    #
    # **accept ≠ 可建档**：建档由 promotion_gate 独立判断，且只认显式工具调用。
    if admitted and subject and subject_confidence >= ACCEPT_SUBJECT_CONFIDENCE:
        return MessageDecision.ACCEPT
    # 领域未知但句式明确（矩阵 R-17）：候选留下，权威状态不动
    if open_domain:
        return MessageDecision.CANDIDATE_ONLY
    # 认不出学科但抽出了候选（矩阵 R-06/R-12）、或学科够强但候选无效（R-07）：
    # 消息有效、权威状态不动
    if admitted or subject:
        return MessageDecision.CANDIDATE_ONLY
    return MessageDecision.REJECT
