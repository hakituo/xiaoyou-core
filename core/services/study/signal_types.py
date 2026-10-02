"""学习信号的枚举与数据模型（四层产物的类型契约）。

从 ``signal_detector.py`` 拆出，只放类型：``LearningIntent`` / ``MessageDecision`` /
``RejectReason`` 三个枚举，以及 ``RawCandidate`` / ``NormalizedCandidate`` /
``FilteredCandidate`` / ``LearningSignal`` 四个 pydantic 模型。

本模块**不依赖任何词表或正则**，是全拆分的最底层。
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class LearningIntent(str, Enum):
    NONE = "none"
    PURE_QUERY = "pure_query"
    TEACHING_REQUEST = "teaching_request"
    CONFUSION = "confusion"
    ANSWER_ATTEMPT = "answer_attempt"
    MASTERY_CLAIM = "mastery_claim"


class MessageDecision(str, Enum):
    """消息层判定（与候选层判定**分开**，见矩阵 §2）。

    ``accept``           消息是知识查询，可进闭环
    ``candidate_only``   可能是知识问题，**不得改权威状态**
    ``diagnostic_only``  无绑定上下文的信号，只留诊断事件
    ``reject``           纯闲聊/角色/语气/生活描述，**连 candidate event 都不留**
    """

    ACCEPT = "accept"
    CANDIDATE_ONLY = "candidate_only"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    REJECT = "reject"


class RejectReason(str, Enum):
    """filter 的拒绝理由枚举（枚举即边界声明）。"""

    WEAK_SOURCE = "weak_source"                      # 来源片段本身没有承载知识
    NO_SUBJECT_EVIDENCE = "no_subject_evidence"      # 认不出学科，无学习语境
    NON_LEARNING_CONTEXT = "non_learning_context"    # 上下文非学习（口语断句/生活描述）
    REFERENTIAL_PHRASE = "referential_phrase"        # 强指代短语，脱离上下文无意义
    NO_STABLE_ENTITY = "no_stable_entity"            # 语气词/无稳定实体


class RawCandidate(BaseModel):
    """extract 层输出：**看到了什么**（原样保留正则命中片段）。"""

    id: str
    name: str
    source: str  # quoted / explicit_topic / formula / chemistry_formula / registry
    strength: str = "weak"  # weak / medium / strong
    # 片段在消息里的**起始偏移**。normalize 需要它来判断「转折标记是否在句首」
    # （矩阵 R-05 vs R-07 的分界），这是**结构性位置信息**，不是语义判断。
    # -1 表示未知（外部直接构造 RawCandidate 时），此时按「非句首」处理。
    start: int = -1


class NormalizedCandidate(BaseModel):
    """normalize 层输出：**它实际说的是哪一段**。"""

    name: str
    derived_from: str  # 指回 RawCandidate.id
    raw_name: str = ""  # normalize **之前**的片段（留证，filter 判指代要用）
    transforms: List[str] = Field(default_factory=list)
    source: str = ""
    raw_strength: str = "weak"  # detector 最初有多离谱（必须留证）
    normalized_strength: str = "weak"


class FilteredCandidate(BaseModel):
    """filter 层输出：只说收还是不收，**永不改 name**。"""

    candidate: str
    admit: bool
    reason: Optional[str] = None


class LearningSignal(BaseModel):
    """一条消息的准入判定结果。

    ``is_learning`` 表示「**这条消息算不算学习行为**」：它是 ``observe_message``
    的写入口开关，也决定 prompt 注入与学习模式判定。它与 ``message_decision``
    的关系是：

    - ``accept`` / ``candidate_only`` → True（消息是学习行为）
    - ``diagnostic_only`` → True（**是**学习行为，但不得改权威状态）
    - ``reject`` → False（纯闲聊 / 角色 / 语气 / 半截话）

    ``diagnostic_only`` 之所以仍算学习行为：它承载「我还是没听懂」这类
    无候选无科目的真困惑——要靠它回落最近知识点并留下痕迹。**它的降权靠
    ``authority=observed``，不靠 ``is_learning``**：写进去的只是遥测，
    不会进 prompt / ZPD / 日记。真正「不是学习行为」的是 ``reject``。
    """

    intent: LearningIntent = LearningIntent.NONE
    is_learning: bool = False
    subject: Optional[str] = None
    subject_source: Optional[str] = None   # registry / keyword / formula / None
    subject_confidence: float = 0.0
    concepts: List[str] = Field(default_factory=list)  # admitted 候选的 name（兼容旧调用）
    confidence: float = 0.0
    evidence: List[str] = Field(default_factory=list)

    # ---- 四层链路（规范要求可逐段断言的字段）----
    raw_candidates: List[RawCandidate] = Field(default_factory=list)
    normalized_candidates: List[NormalizedCandidate] = Field(default_factory=list)
    filtered_candidates: List[FilteredCandidate] = Field(default_factory=list)
    message_decision: MessageDecision = MessageDecision.REJECT
    # promotion_gate：候选有没有资格进入 ConceptState（**独立于 filter**）
    create_concept: bool = False
    allow_latest_binding: bool = False
    eligible_as_latest: bool = False

    # 供调用方回溯：trace 不是独立决策层，是贯穿整链的回指
    #   raw_id -> normalized.derived_from -> LearningEvent.candidate_trace
    #   -> ConceptState promotion provenance
    @property
    def admitted_names(self) -> List[str]:
        return [c.candidate for c in self.filtered_candidates if c.admit]

    @property
    def rejected_names(self) -> List[str]:
        return [c.candidate for c in self.filtered_candidates if not c.admit]

    def candidate_trace(self, name: str) -> Dict[str, object]:
        """按 admitted 结果名反查它的 raw 来源与 normalize 过程。"""
        normalized = next(
            (n for n in self.normalized_candidates if n.name == name), None
        )
        if normalized is None:
            return {}
        raw = next(
            (r for r in self.raw_candidates if r.id == normalized.derived_from), None
        )
        return {
            "raw_id": normalized.derived_from,
            "raw_name": raw.name if raw else "",
            "normalized_name": normalized.name,
            "transforms": list(normalized.transforms),
            "raw_strength": normalized.raw_strength,
            "normalized_strength": normalized.normalized_strength,
            "source": normalized.source,
        }
