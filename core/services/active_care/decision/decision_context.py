"""
主动关怀决策上下文数据类
封装决策流程中传递的参数，消除参数爆炸
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class DecisionFlowContext:
    """决策流程上下文，封装 _execute_final_decision 和 _run_decision_flow 之间的数据传递"""

    now: float = 0.0
    now_dt: Optional[datetime] = None
    last_interaction: float = 0.0
    elapsed: float = 0.0
    count: int = 0
    last_sent_ts: float = 0.0
    last_attempt_ts: float = 0.0
    state_data: Dict[str, Any] = field(default_factory=dict)

    default_next_check: int = 300
    min_gap_seconds: int = 600
    daily_limit: int = 20

    push_schedule: Dict[str, Any] = field(default_factory=dict)
    quiet_hours: Dict[str, Any] = field(default_factory=dict)

    conversation_incomplete: bool = False
    incomplete_type: str = ""
    incomplete_hint: str = ""

    reduced_mode_active: bool = False
    reduced_mode_reason: str = "none"
    sleep_session_active: bool = False
    quiet_mode_active: bool = False

    latest_user_signal_ts: float = 0.0
    client_type: str = ""

    workspace_snapshot: Dict[str, Any] = field(default_factory=dict)
    recent_history: List[Dict[str, Any]] = field(default_factory=list)
    history_msgs: List[Dict[str, Any]] = field(default_factory=list)
    full_history: List[Dict[str, Any]] = field(default_factory=list)

    life_stats: Dict[str, Any] = field(default_factory=dict)
    immune_stats: Dict[str, Any] = field(default_factory=dict)
    user_bio_state: Optional[Dict[str, Any]] = None
    emo_payload: Dict[str, Any] = field(default_factory=dict)
    urgent_needs: List[str] = field(default_factory=list)
    safe_device_context: Dict[str, Any] = field(default_factory=dict)

    priority_focus: Dict[str, Any] = field(default_factory=dict)
    priority_analysis: Dict[str, Any] = field(default_factory=dict)
    probe_policy: Dict[str, Any] = field(default_factory=dict)

    decision_persona_prompt: str = ""
    decision_user_display_name: str = ""
    primary_cid: str = "default"

    last_goodnight_ts: float = 0.0
    last_goodmorning_ts: float = 0.0

    active_care_mode_info: Dict[str, Any] = field(default_factory=dict)

    non_response_count: int = 0

    # 用户进程活动检测结果
    activity_result: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_early_morning(self) -> bool:
        if self.now_dt is None:
            return False
        try:
            return 0 <= self.now_dt.hour < 6
        except (AttributeError, TypeError):
            return False

    @property
    def has_non_response_pressure(self) -> bool:
        return self.non_response_count > 0

    @property
    def long_silence_seconds(self) -> float:
        return max(self.min_gap_seconds * 3, 3600) if self.min_gap_seconds > 1200 else 3600

    @property
    def has_long_silence(self) -> bool:
        last_attempt = max(self.last_sent_ts, self.last_attempt_ts)
        return (last_attempt <= 0) or ((self.now - last_attempt) >= self.long_silence_seconds)

    @property
    def has_recent_signal_for_long_silence(self) -> bool:
        return (
            self.latest_user_signal_ts > 0
            and (self.now - self.latest_user_signal_ts) <= (6 * 3600)
        )

    @property
    def no_send_for_too_long(self) -> bool:
        last_attempt = max(self.last_sent_ts, self.last_attempt_ts)
        return (
            last_attempt <= 0
            or (self.now - last_attempt) >= max(self.min_gap_seconds * 4, 3600)
        )

    @property
    def user_silent_long_enough(self) -> bool:
        return self.elapsed >= max(self.min_gap_seconds * 2, 1800)
