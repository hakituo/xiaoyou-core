"""学习结果评价（EvaluationResult）与结构化校验。

分工
----
LLM 负责**判断**用户答得怎么样（返回结构化 JSON）；后端负责**校验 + 落状态**。
LLM 不能直接改任何状态文件，也不能决定掌握度增量——``mastery_delta`` 只是
LLM 的自我描述，最终写入由 ``ConceptStateManager`` 的规则计算。

校验失败的载荷一律视为「不可信」，返回 ``None``，由调用方放弃本次状态更新，
避免把解析错误误判成「用户答错」而惩罚学习者。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from core.services.study.learning_event import LearningEventType
from core.utils.logger import get_logger

logger = get_logger("StudyEvaluation")

# 允许的教学动作（与 TeachingOrchestrator 的动作表保持一致）
ALLOWED_ACTIONS = (
    "explain",
    "ask_question",
    "give_hint",
    "simplify",
    "provide_example",
    "retrieval_test",
    "spaced_review",
    "prerequisite_review",
    "advance_next_concept",
)

# 判定为「答对」/「答错」的分界线
CORRECT_THRESHOLD = 0.8
INCORRECT_THRESHOLD = 0.5


class EvaluationResult(BaseModel):
    """一次答题评价的结构化结果。"""

    correctness: float = Field(default=0.0, ge=0.0, le=1.0, description="答对程度 0-1")
    independent: bool = True
    used_hint: bool = False
    misconception: Optional[str] = None
    confidence_delta: float = 0.0
    mastery_delta: float = 0.0
    recommended_action: str = "ask_question"

    @property
    def verdict(self) -> str:
        """三档结论：correct / partial / incorrect。"""
        if self.correctness >= CORRECT_THRESHOLD:
            return "correct"
        if self.correctness >= INCORRECT_THRESHOLD:
            return "partial"
        return "incorrect"

    @property
    def event_type(self) -> LearningEventType:
        """映射到学习事件类型。"""
        return {
            "correct": LearningEventType.ANSWER_CORRECT,
            "partial": LearningEventType.ANSWER_PARTIAL,
            "incorrect": LearningEventType.ANSWER_INCORRECT,
        }[self.verdict]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "y", "1", "是", "对"}:
            return True
        if v in {"false", "no", "n", "0", "否", "不是"}:
            return False
    return default


def normalize_correctness(raw: Any) -> float:
    """把 LLM 可能给出的 0-1 / 0-100 / 0-5 分制统一到 0-1。"""
    value = _to_float(raw, 0.0)
    if value > 1.0:
        if value <= 5.0:
            value = value / 5.0
        elif value <= 100.0:
            value = value / 100.0
    return max(0.0, min(1.0, value))


def parse_evaluation_payload(
    payload: Any,
) -> Tuple[Optional[EvaluationResult], List[str]]:
    """解析并校验 LLM 返回的评价载荷。

    Args:
        payload: dict，或 JSON 字符串，或已经是 EvaluationResult

    Returns:
        (结果, 警告列表)。载荷不可信时结果为 None。
    """
    warnings: List[str] = []

    if isinstance(payload, EvaluationResult):
        return payload, warnings

    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None, ["评价载荷为空"]
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None, ["评价载荷不是合法 JSON"]

    if not isinstance(payload, dict):
        return None, ["评价载荷必须是 JSON 对象"]

    # correctness 支持多种键名
    raw_correctness = payload.get("correctness")
    if raw_correctness is None and "correct" in payload:
        raw_correctness = 1.0 if _to_bool(payload.get("correct")) else 0.0
        warnings.append("缺少 correctness，已用 correct 布尔值折算")
    if raw_correctness is None:
        return None, ["评价载荷缺少 correctness"]

    correctness = normalize_correctness(raw_correctness)

    used_hint = _to_bool(payload.get("used_hint", False))
    independent = _to_bool(payload.get("independent", True))
    if used_hint and independent:
        # 用了提示却声称独立作答：以后端一致性为准，强制非独立
        independent = False
        warnings.append("used_hint=true 与 independent=true 冲突，已按非独立处理")

    action = str(payload.get("recommended_action") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        if action:
            warnings.append(f"未知的 recommended_action: {action}，已改用默认动作")
        action = _default_action(correctness)

    misconception = payload.get("misconception")
    if misconception is not None:
        misconception = str(misconception).strip()[:200] or None

    result = EvaluationResult(
        correctness=correctness,
        independent=independent,
        used_hint=used_hint,
        misconception=misconception,
        confidence_delta=max(-0.3, min(0.3, _to_float(payload.get("confidence_delta"), 0.0))),
        mastery_delta=max(-0.3, min(0.3, _to_float(payload.get("mastery_delta"), 0.0))),
        recommended_action=action,
    )
    return result, warnings


def _default_action(correctness: float) -> str:
    """按答题结果给出保守的默认下一步动作。"""
    if correctness >= CORRECT_THRESHOLD:
        return "advance_next_concept"
    if correctness >= INCORRECT_THRESHOLD:
        return "give_hint"
    return "explain"


class EvaluationService:
    """评价结果校验与归一化。"""

    ALLOWED_ACTIONS = ALLOWED_ACTIONS

    @staticmethod
    def parse(payload: Any) -> Tuple[Optional[EvaluationResult], List[str]]:
        return parse_evaluation_payload(payload)

    @staticmethod
    def to_dict(result: EvaluationResult) -> Dict[str, Any]:
        data = result.model_dump(mode="json")
        data["verdict"] = result.verdict
        data["event_type"] = result.event_type.value
        return data


def get_evaluation_service() -> EvaluationService:
    return EvaluationService()
