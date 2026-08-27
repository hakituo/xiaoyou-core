"""nightly 后熬夜补丁事件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class NightPatchDecision:
    """nightly 后补丁决策。"""

    should_adjust_plan: bool = False
    should_backfill_diary: bool = False
    should_ignore: bool = True
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_adjust_plan": self.should_adjust_plan,
            "should_backfill_diary": self.should_backfill_diary,
            "should_ignore": self.should_ignore,
            "reason": self.reason,
        }


def build_night_patch_decision(
    *,
    schedule_adjust_tendency: float,
    diary_backfill_tendency: float,
    patch_pending: bool,
) -> NightPatchDecision:
    """根据配置构建轻量补丁决策。"""
    if not patch_pending:
        return NightPatchDecision()
    adjust = float(schedule_adjust_tendency or 0.0) >= 0.5
    diary = float(diary_backfill_tendency or 0.0) >= 0.35
    return NightPatchDecision(
        should_adjust_plan=adjust,
        should_backfill_diary=diary,
        should_ignore=not adjust and not diary,
        reason="nightly 后又熬夜，生成轻量补丁建议",
    )
