"""融合裁决的配置、常量、结果容器与通用清洗函数。

从 ``memory.core.analysis_ops`` 拆出（原 1125 行单文件按职责拆成薄壳门面 + 7 个子模块）。
本模块只放被其他子模块共享的「类型 + 常量 + 纯函数」，不含任何记忆读写逻辑。

拆分是纯搬家：未改逻辑、命名与断言，对外路径与符号名仍由门面
``memory.core.analysis_ops`` 转发。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class FusionConfig:
    """融合裁决配置，替代硬编码字典"""
    s_rule: float = 0.40
    s_ai: float = 0.20
    s_consistency: float = 0.30
    s_stability: float = 0.10

    consistency_topic: float = 0.55
    consistency_category: float = 0.20
    consistency_discourse: float = 0.25

    trigger_rule_signal: float = 0.40
    trigger_ai_signal: float = 0.35
    trigger_state_consistency: float = 0.15
    trigger_consistency: float = 0.10

    rule_topic_strength: float = 0.6
    rule_category_strength: float = 0.4

    trigger_allow_threshold: float = 0.72


DEFAULT_FUSION_CONFIG = FusionConfig()

BLOCKED_DISCOURSE_LABELS = frozenset({
    "RETROSPECTIVE_SELF_REPORT",
    "FUTURE_PLAN",
    "HYPOTHETICAL",
    "REPORTED_SPEECH",
    "INSTRUCTION",
    "QUESTION",
})

RISK_CATEGORIES = frozenset({"preference", "sensitive", "state"})
RISK_MEMORY_TYPES = frozenset({"preference", "sensitive", "state", "profile"})

DISCOURSE_WEIGHT_PENALTIES = {
    "INSTRUCTION": -0.4,
    "QUESTION": -0.4,
    "REPORTED_SPEECH": -0.4,
    "HYPOTHETICAL": -0.25,
    "FUTURE_PLAN": -0.25,
    "RETROSPECTIVE_SELF_REPORT": -0.1,
}


@dataclass
class FusionResult:
    """融合裁决结果，替代 _write_fusion_metadata 的 20+ 参数"""
    action: str = "reject"
    final_confidence: float = 0.0
    s_rule: float = 0.0
    s_ai: float = 0.0
    s_consistency: float = 0.0
    s_stability: float = 0.0
    trigger_final_confidence: float = 0.0
    trigger_decision: str = "deny"
    rule_discourse_label: str = "GENERIC_CHAT"
    rule_state_event: str = "NONE"
    ai_discourse_label: str = "GENERIC_CHAT"
    ai_state_event: str = "NONE"
    override_threshold: float = 0.75
    supplement_threshold: float = 0.5
    effective_override_threshold: float = 0.75
    effective_supplement_threshold: float = 0.5
    risk_level: str = "normal"
    allow_override: bool = False
    original_category: str = "uncategorized"
    original_topics: List[str] = field(default_factory=list)
    ai_category: str = "uncategorized"
    ai_topics: List[str] = field(default_factory=list)
    memory_type: str = "dialogue"
    now_ts: float = 0.0


def _ensure_analysis_meta(metadata: Dict[str, Any]) -> Dict[str, Any]:
    analysis_meta = metadata.get("analysis_meta")
    if not isinstance(analysis_meta, dict):
        analysis_meta = {}
        metadata["analysis_meta"] = analysis_meta
    return analysis_meta


def _safe_float(value: Any, default: float = 0.0, min_val: float = 0.0, max_val: float = 1.0) -> float:
    try:
        return max(min_val, min(max_val, float(value)))
    except Exception:
        return default


def _clean_topics(topics: Any, limit: int = 8) -> List[str]:
    result = []
    for t in (topics or []):
        ts = str(t).strip()
        if ts and ts not in result:
            result.append(ts)
    return result[:limit]


def _clean_category(category: Any) -> str:
    return str(category or "uncategorized").strip() or "uncategorized"
