from dataclasses import dataclass
from enum import Enum


class TriggerOutcome(str, Enum):
    """主动关怀触发结果类型。"""

    DELIVERED = "delivered"
    OVERLAP_BLOCKED = "overlap_blocked"
    GENERATION_FAILED = "generation_failed"
    DISPATCH_FAILED = "dispatch_failed"
    EXECUTION_EXCEPTION = "execution_exception"


@dataclass(frozen=True)
class TriggerMessageResult:
    """一次 trigger_message 调用的显式结果。"""

    delivered: bool
    outcome: TriggerOutcome
    detail: str = ""

    @property
    def is_interval_blocked(self) -> bool:
        return self.outcome is TriggerOutcome.OVERLAP_BLOCKED

    @property
    def legacy_skip_reason(self) -> str:
        if self.outcome is TriggerOutcome.OVERLAP_BLOCKED:
            return "overlap_guard"
        if self.outcome is TriggerOutcome.GENERATION_FAILED:
            return "generation_failed"
        if self.outcome is TriggerOutcome.DISPATCH_FAILED:
            return "dispatch_failed"
        if self.outcome is TriggerOutcome.EXECUTION_EXCEPTION:
            return "exception"
        return ""
