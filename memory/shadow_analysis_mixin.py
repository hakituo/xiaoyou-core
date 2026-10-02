"""AI 影子分析 Mixin
负责 AI 影子分析的全部操作
"""
from typing import Any, Dict, List

from memory.core.analysis_ops import (
    count_pending_analysis as count_pending_analysis_impl,
    get_pending_analysis_items as get_pending_analysis_items_impl,
    attach_ai_shadow_result as attach_ai_shadow_result_impl,
    count_ai_shadow_results as count_ai_shadow_results_impl,
    apply_ai_shadow_adjudication as apply_ai_shadow_adjudication_impl,
    process_pending_analysis as process_pending_analysis_impl,
)


class ShadowAnalysisMixin:
    """AI 影子分析操作 Mixin"""

    def count_pending_analysis(self) -> int:
        return count_pending_analysis_impl(self)

    def get_pending_analysis_items(self, limit: int = 16) -> List[Dict[str, Any]]:
        return get_pending_analysis_items_impl(self, limit=limit)

    def attach_ai_shadow_result(
        self,
        memory_id: str,
        *,
        ai_topics: List[str],
        ai_category: str,
        ai_confidence: float,
        ai_weight_delta: float = 0.0,
        ai_reason: str = "",
        source: str = "llm",
        status: str = "ok",
        latency_ms: float = 0.0,
    ) -> bool:
        return attach_ai_shadow_result_impl(
            self,
            memory_id,
            ai_topics=ai_topics,
            ai_category=ai_category,
            ai_confidence=ai_confidence,
            ai_weight_delta=ai_weight_delta,
            ai_reason=ai_reason,
            source=source,
            status=status,
            latency_ms=latency_ms,
        )

    def count_ai_shadow_results(self) -> int:
        return count_ai_shadow_results_impl(self)

    def apply_ai_shadow_adjudication(
        self,
        *,
        limit: int = 16,
        override_min_confidence: float = 0.75,
        supplement_min_confidence: float = 0.5,
        allow_override: bool = False,
    ) -> Dict[str, Any]:
        return apply_ai_shadow_adjudication_impl(
            self,
            limit=limit,
            override_min_confidence=override_min_confidence,
            supplement_min_confidence=supplement_min_confidence,
            allow_override=allow_override,
        )

    def process_pending_analysis(self, limit: int = 32) -> Dict[str, Any]:
        return process_pending_analysis_impl(self, limit=limit)
