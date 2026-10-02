"""最近发展区（ZPD）判定与教学动作决策。

从 ``teaching_orchestrator.py`` 抽出的**纯决策层**：只吃 ConceptState 与意图，
产出「当前处于哪一层」和「下一步该做什么动作」，不碰持久化、不调 LLM。

放在单独模块的理由：教学策略是最常调参的部分，独立出来便于单测与调整，
也避免编排器重新膨胀成 God Class。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.services.study.concept_rules import ConceptStatus
from core.services.study.concept_state import ConceptState, ConceptStateManager
from core.services.study.signal_detector import LearningIntent

# ZPD 层级
ZPD_MASTERED = "mastered"
ZPD_PROXIMAL = "proximal"
ZPD_NOT_STARTED = "not_started"
ZPD_PREREQUISITE_GAP = "prerequisite_gap"
ZPD_SPAN_TOO_LARGE = "span_too_large"

# 教学动作
ACTION_EXPLAIN = "explain"
ACTION_ASK_QUESTION = "ask_question"
ACTION_GIVE_HINT = "give_hint"
ACTION_SIMPLIFY = "simplify"
ACTION_PROVIDE_EXAMPLE = "provide_example"
ACTION_RETRIEVAL_TEST = "retrieval_test"
ACTION_SPACED_REVIEW = "spaced_review"
ACTION_PREREQUISITE_REVIEW = "prerequisite_review"
ACTION_ADVANCE = "advance_next_concept"

# 需要教学动作的中文说明（注入 prompt 时用，避免模型只看到英文枚举）
ACTION_HINTS: Dict[str, str] = {
    ACTION_EXPLAIN: "先用最小必要篇幅讲清概念，不要一次铺开整章",
    ACTION_ASK_QUESTION: "讲完先提 1 个回忆型问题，让用户自己说出来",
    ACTION_GIVE_HINT: "只给一级提示，不要直接给答案",
    ACTION_SIMPLIFY: "换更小的步子重讲，先确认卡在哪一步",
    ACTION_PROVIDE_EXAMPLE: "给一个具体例子或反例帮助建立直觉",
    ACTION_RETRIEVAL_TEST: "先让用户独立回答，不要提前给提示",
    ACTION_SPACED_REVIEW: "按间隔复习安排，先测再补",
    ACTION_PREREQUISITE_REVIEW: "先补前置知识，不要硬讲当前概念",
    ACTION_ADVANCE: "可以推进到下一个相邻概念",
}


def judge_zpd(concept: ConceptState, concepts: ConceptStateManager) -> Dict[str, Any]:
    """判断某个知识点当前的最近发展区。"""
    if concept.status == ConceptStatus.MASTERED:
        return {
            "level": ZPD_MASTERED,
            "reason": "已多次独立答对，进入维持性复习",
            "missing_prerequisites": [],
        }

    missing = missing_prerequisites(concept, concepts)
    if missing:
        level = (
            ZPD_SPAN_TOO_LARGE
            if len(missing) >= 2 and concept.mastery < 0.3
            else ZPD_PREREQUISITE_GAP
        )
        return {
            "level": level,
            "reason": f"前置知识未掌握：{'、'.join(missing)}",
            "missing_prerequisites": missing,
        }

    if concept.status == ConceptStatus.UNKNOWN:
        return {
            "level": ZPD_NOT_STARTED,
            "reason": "尚未教过，可以从零讲起",
            "missing_prerequisites": [],
        }

    return {
        "level": ZPD_PROXIMAL,
        "reason": f"当前状态 {concept.status.value}，掌握度 {concept.mastery:.2f}",
        "missing_prerequisites": [],
    }


def missing_prerequisites(
    concept: ConceptState, concepts: ConceptStateManager
) -> List[str]:
    """返回尚未掌握的前置知识名称。"""
    if not concept.prerequisites:
        return []
    mastered = set(concepts.get_mastered_names(concept.subject))
    missing: List[str] = []
    for prereq in concept.prerequisites:
        if prereq in mastered:
            continue
        # 前置知识可能记录在别的科目下，跨科目再查一次
        state = concepts.get_by_name(concept.subject, prereq)
        if state is None:
            state = concepts.get_by_name("general", prereq)
        if state is not None and state.status == ConceptStatus.MASTERED:
            continue
        missing.append(prereq)
    return missing


def decide_action(
    intent: LearningIntent,
    zpd: Dict[str, Any],
    concept: Optional[ConceptState],
    *,
    due_count: int = 0,
) -> Dict[str, Any]:
    """按情境 + ZPD 决定下一步教学动作（desirable difficulty 原则）。"""
    level = zpd.get("level")

    if intent == LearningIntent.CONFUSION:
        # 用户明确表示没理解：降低认知负担，不要继续加难度
        action = ACTION_SIMPLIFY if concept and concept.taught_count else ACTION_EXPLAIN
        return action_payload(action, "用户自述没理解，先降低难度")

    if intent == LearningIntent.MASTERY_CLAIM:
        # 自称掌握不可信，必须用检索验证
        return action_payload(ACTION_RETRIEVAL_TEST, "自称掌握需要检索验证")

    if intent == LearningIntent.ANSWER_ATTEMPT:
        return action_payload(ACTION_ASK_QUESTION, "等待后端评价用户作答")

    if level == ZPD_MASTERED:
        return action_payload(ACTION_RETRIEVAL_TEST, "已掌握，做维持性检索")

    if level in (ZPD_PREREQUISITE_GAP, ZPD_SPAN_TOO_LARGE):
        missing = "、".join(zpd.get("missing_prerequisites") or [])
        return action_payload(ACTION_PREREQUISITE_REVIEW, f"跨度偏大，先补前置：{missing}")

    if level == ZPD_NOT_STARTED:
        action = (
            ACTION_PROVIDE_EXAMPLE
            if concept and concept.evidence_count
            else ACTION_EXPLAIN
        )
        return action_payload(action, "新概念，先建立直觉")

    # proximal：学新知识时先讲，检验长期记忆时先测
    if due_count > 0 and intent == LearningIntent.PURE_QUERY:
        return action_payload(ACTION_SPACED_REVIEW, f"有 {due_count} 个知识点到期")
    if concept is not None and concept.taught_count > 0 and not concept.verified_by_retrieval:
        return action_payload(ACTION_ASK_QUESTION, "已讲过但没验证过，先做回忆")
    return action_payload(ACTION_EXPLAIN, "正在掌握中，继续小步推进")


def action_payload(action: str, rationale: str) -> Dict[str, Any]:
    """统一的教学动作返回结构。"""
    return {
        "action": action,
        "rationale": rationale,
        "guidance": ACTION_HINTS.get(action, ""),
    }
