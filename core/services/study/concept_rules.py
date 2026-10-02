"""知识点状态机与掌握规则（纯函数层）。

把「状态枚举、阈值、掌握度增量、状态推导、复习排期」这些**无副作用**的规则
从 ``concept_state.py`` 抽出来单独成模块，好处：

- ``concept_state.py`` 只负责数据模型与持久化，不再夹着一堆业务规则；
- 规则可以被单测直接调用，不需要构造管理器；
- 调参（阈值 / 增量 / 排期）只改这一个文件。

``ConceptStatus`` 放在这里而不是模型文件里，是为了避免
``concept_state <-> concept_rules`` 的循环导入；``concept_state`` 会重新导出它，
所以 ``from core.services.study.concept_state import ConceptStatus`` 依然可用。
"""
from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import List

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("ConceptRules")


class ConceptStatus(str, Enum):
    """知识点状态。"""

    UNKNOWN = "unknown"      # 见过但还没教过，或从未出现
    LEARNING = "learning"    # 正在学，尚未通过检索验证
    WEAK = "weak"            # 出过错且掌握度偏低
    REVIEWING = "reviewing"  # 已能答对，进入间隔复习
    MASTERED = "mastered"    # 多次独立答对


# 掌握判定阈值
MASTERED_MASTERY_THRESHOLD = 0.8
MASTERED_STREAK_THRESHOLD = 3
WEAK_MASTERY_THRESHOLD = 0.6

# 掌握度单次调整幅度（独立答对 0.2 => 约 4 次独立答对 + streak>=3 进入掌握）
DELTA_INDEPENDENT_CORRECT = 0.2
DELTA_INDEPENDENT_PARTIAL = 0.08
DELTA_INDEPENDENT_WRONG = -0.12
DELTA_HINT_CORRECT = 0.05
DELTA_HINT_PARTIAL = 0.02
DELTA_HINT_WRONG = -0.06

DEFAULT_REVIEW_INTERVALS = (1, 3, 7, 14)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def clamp01(value: float) -> float:
    return clamp(value, 0.0, 1.0)


def review_intervals() -> List[int]:
    """读取配置里的间隔复习天数。"""
    try:
        from config.integrated_config import get_settings

        intervals = get_settings().study.get_review_intervals()
        return intervals or list(DEFAULT_REVIEW_INTERVALS)
    except Exception as e:  # noqa: BLE001
        logger.debug("读取复习间隔配置失败，使用默认值 %s：%s", DEFAULT_REVIEW_INTERVALS, e)
        return list(DEFAULT_REVIEW_INTERVALS)


def max_review_level() -> int:
    return max(0, len(review_intervals()) - 1)


def compute_mastery_delta(
    *, correctness: float, independent: bool, used_hint: bool
) -> float:
    """按规则计算掌握度增量。

    规则集中在后端，保证同一份评价永远得到同一个结果，也让测试可断言。
    非独立作答（看答案或用了提示）收益显著更低，答错仍有小惩罚。
    """
    if not independent:
        if correctness >= MASTERED_MASTERY_THRESHOLD:
            return DELTA_HINT_CORRECT
        if correctness >= 0.5:
            return DELTA_HINT_PARTIAL
        return DELTA_HINT_WRONG

    if correctness >= MASTERED_MASTERY_THRESHOLD:
        return DELTA_INDEPENDENT_CORRECT
    if correctness >= 0.5:
        return DELTA_INDEPENDENT_PARTIAL
    return DELTA_INDEPENDENT_WRONG


def recompute_status(state) -> None:
    """根据聚合指标重算状态（唯一推导入口，避免多处各写一套）。

    判定顺序有讲究：先看是否达到掌握，再看是否刚从掌握掉下来，
    最后才落到 learning，避免出现「mastery 高但刚答错仍显示已掌握」的假掌握。
    """
    if state.evidence_count == 0:
        state.status = ConceptStatus.UNKNOWN
        return

    if (
        state.mastery >= MASTERED_MASTERY_THRESHOLD
        and state.independent_success_streak >= MASTERED_STREAK_THRESHOLD
    ):
        state.status = ConceptStatus.MASTERED
        return

    if state.independent_failure_streak > 0 and state.mastery < WEAK_MASTERY_THRESHOLD:
        state.status = ConceptStatus.WEAK
        return

    if state.mastery >= WEAK_MASTERY_THRESHOLD and state.independent_success_streak > 0:
        state.status = ConceptStatus.REVIEWING
        return

    if state.independent_failure_streak > 0 and state.mastery < MASTERED_MASTERY_THRESHOLD:
        # 刚失败过且没到掌握线：即使掌握度尚可，也回落到薄弱，避免「假掌握」
        state.status = ConceptStatus.WEAK
        return

    state.status = ConceptStatus.LEARNING


def compute_next_review(state, today: str) -> str:
    """计算下次复习日期。已掌握的知识点仍保留长间隔复习（用于长期记忆维持）。

    ``today`` 仅用于调用方对齐日期口径，日期推进统一走 ``get_current_time()``。
    """
    intervals = review_intervals()
    if not intervals:
        return ""
    if state.status == ConceptStatus.MASTERED:
        days = intervals[-1]
    else:
        days = intervals[min(state.review_level, len(intervals) - 1)]
    target = get_current_time() + timedelta(days=days)
    return target.strftime("%Y-%m-%d")
