"""主动关怀频控守卫（Cadence Guard）

2026-09-04 改造：频控不止一个 10 分钟 cooldown，拆成多层：

    1. 全局冷却（GLOBAL_PROACTIVE_COOLDOWN）：任意两条主动消息之间。
    2. 提问冷却（QUESTION_COOLDOWN）：问过一次问题后，短时间内不再问。
    3. 同组题材冷却（SAME_TOPIC_COOLDOWN）：换措辞追同一件事（吃饭没/外卖点了/饭到了）。
    4. 未回复抑制（MAX_UNANSWERED_PROACTIVE）：上一条主动消息用户没回时，
       默认不再发普通好奇提问。
    5. 每日软上限（MAX_CURIOUS_QUESTION_PER_DAY）：达到后优先 defer。
    6. 正式 FocusSession 门控：active/paused 时硬拦普通 Active Care，用户提醒等硬事件豁免。

触发时机（由 checker 调用，具体接入见 checker_action_flow）：
- LLM 决策前跑一次"预检"，挡掉明显不该发的轮次，省一次 LLM 调用；
- LLM 决策后（decision 携带 planned_topic / text）再跑一次"复检"，
  用模型自己选的话题做同题材判定，防止模型换措辞绕过。

硬事件类 intent（真实提醒/通知/数字健康/早安晚安等固定任务）不属于这里的
"普通主动消息"，全部豁免——它们是"只有非常特殊的新事件才允许突破"里的
"新事件"。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.integrated_config import get_settings
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_module_logger
from core.services.active_care.cadence.topic_groups import (
    group_for_topic_label,
    is_eligible_for_group_cooldown,
)

logger = get_module_logger("ACTIVE_CARE_CADENCE", "active_care_schedule.log")

# 默认频控参数（config 缺失时兜底；实际运行优先读 config）
DEFAULT_GLOBAL_PROACTIVE_COOLDOWN = 40 * 60       # 40 分钟
DEFAULT_QUESTION_COOLDOWN = 75 * 60               # 75 分钟
DEFAULT_SAME_TOPIC_COOLDOWN = 3 * 3600            # 3 小时
DEFAULT_MAX_UNANSWERED_PROACTIVE = 1              # 最多悬着 1 条未回复
DEFAULT_MAX_CURIOUS_QUESTION_PER_DAY = 3          # 每天最多 3 条好奇提问
DEFAULT_UNANSWERED_SUPPRESS_WINDOW = 6 * 3600     # 未回复抑制最多持续 6 小时

# 硬事件类 intent：真实到期提醒/通知转述/数字健康/早安晚安/专注探班等，
# 属于"特殊新事件"，豁免所有普通主动消息的频控与正式 FocusSession 门控。
COOLDOWN_EXEMPT_INTENTS = frozenset({
    "reminder",
    "notification_assistant",
    "usage_limit_exceeded",
    "goodnight_proactive",
    "good_morning_proactive",
    "wake_up_greeting",
    "morning_report",
    "activity_return_proactive",
    "sleep_again_proactive",
    "insomnia",
    "focus_nudge",
    "bio_complaint",
    "user_health_reminder",
})

# 普通提问类 intent：未回复抑制 & 每日软上限 & 提问冷却只针对这类。
QUESTION_INTENTS = frozenset({"curious_question", "checking"})

# 需要跨文案归属同一个 topic_group 做同题材冷却的 intent
GROUP_COOLDOWN_INTENTS = frozenset({
    "curious_question",
    "checking",
    "share_thought",
    "emotional_support",
    "gossip_share",
    "weather_complaint",
    "share_peer_chat",
    "planned_topic",
})


@dataclass
class CadenceVerdict:
    """频控判定结果。allowed=False 表示本轮应 defer。"""

    allowed: bool
    reason: str = ""
    retry_after_minutes: int = 30

    @classmethod
    def allow(cls) -> "CadenceVerdict":
        return cls(allowed=True)

    @classmethod
    def block(cls, reason: str, retry_after_minutes: int) -> "CadenceVerdict":
        return cls(
            allowed=False,
            reason=reason,
            retry_after_minutes=max(5, int(retry_after_minutes)),
        )


class CadenceGuard:
    """主动关怀频控守卫。纯状态判定，不直接写状态（写状态由调用方负责）。"""

    def __init__(self, settings=None):
        self.settings = settings if settings is not None else get_settings()

    # ==================== 配置读取 ====================

    def _cfg(self, key: str, default: Any) -> Any:
        return get_active_care_config(key, default=default, settings=self.settings)

    @property
    def global_cooldown_seconds(self) -> int:
        return int(
            self._cfg(
                "active_care_global_proactive_cooldown_seconds",
                DEFAULT_GLOBAL_PROACTIVE_COOLDOWN,
            )
            or DEFAULT_GLOBAL_PROACTIVE_COOLDOWN
        )

    @property
    def question_cooldown_seconds(self) -> int:
        return int(
            self._cfg(
                "active_care_question_cooldown_seconds",
                DEFAULT_QUESTION_COOLDOWN,
            )
            or DEFAULT_QUESTION_COOLDOWN
        )

    @property
    def same_topic_cooldown_seconds(self) -> int:
        return int(
            self._cfg(
                "active_care_same_topic_cooldown_seconds",
                DEFAULT_SAME_TOPIC_COOLDOWN,
            )
            or DEFAULT_SAME_TOPIC_COOLDOWN
        )

    @property
    def max_unanswered_proactive(self) -> int:
        return max(0, int(
            self._cfg(
                "active_care_max_unanswered_proactive",
                DEFAULT_MAX_UNANSWERED_PROACTIVE,
            )
            or DEFAULT_MAX_UNANSWERED_PROACTIVE
        ))

    @property
    def max_curious_question_per_day(self) -> int:
        return max(0, int(
            self._cfg(
                "active_care_max_curious_question_per_day",
                DEFAULT_MAX_CURIOUS_QUESTION_PER_DAY,
            )
            or DEFAULT_MAX_CURIOUS_QUESTION_PER_DAY
        ))

    @property
    def unanswered_suppress_window_seconds(self) -> int:
        return int(
            self._cfg(
                "active_care_unanswered_suppress_window_seconds",
                DEFAULT_UNANSWERED_SUPPRESS_WINDOW,
            )
            or DEFAULT_UNANSWERED_SUPPRESS_WINDOW
        )

    @staticmethod
    def _formal_focus_session_active() -> bool:
        """正式番茄/专注会话是真实执行态；active/paused 都禁止普通主动关怀。"""
        try:
            from core.services.study.focus_session_service import get_focus_session_service

            return get_focus_session_service().has_active_session(
                "default", include_paused=True
            )
        except Exception as exc:
            # Active Care 不能因为学习子系统读取失败而整体失效；失败时退回原有频控。
            logger.debug("读取 FocusSession 状态失败，跳过正式专注门控: %s", exc)
            return False

    # ==================== 判定入口 ====================

    def evaluate(
        self,
        *,
        now: float,
        chosen_action: str,
        proactive_state: Optional[Dict[str, Any]] = None,
        planned_topic: str = "",
        candidate_topic_label: str = "",
        non_response_count: int = 0,
    ) -> CadenceVerdict:
        """对一次主动关怀的发送做频控判定。

        Args:
            now: 当前时间戳。
            chosen_action: 已选动作/intent。
            proactive_state: 持久化主动状态（读 last_proactive_* / today_sent_events）。
            planned_topic: LLM 决策输出的计划话题（可选，用于同题材判定）。
            candidate_topic_label: 候选题材标签 "<intent>:<subtopic>"（可选）。
            non_response_count: 连续未回复计数。

        Returns:
            CadenceVerdict：allowed=False 时携带 defer 原因与重试间隔。
        """
        state = proactive_state if isinstance(proactive_state, dict) else {}
        intent = str(chosen_action or "").strip()
        if not intent:
            return CadenceVerdict.block("cadence_no_intent", 30)

        # 硬事件类 intent 直接放行（真实提醒/通知/数字健康等特殊新事件）。
        if intent in COOLDOWN_EXEMPT_INTENTS:
            return CadenceVerdict.allow()

        # 正式 FocusSession 是比 reduced_mode=focus 更强的事实状态：
        # 普通 Active Care 一律硬挡；手动提醒/专注探班等硬事件已在上方豁免。
        if self._formal_focus_session_active():
            return CadenceVerdict.block("formal_focus_session_active", 5)

        is_question = intent in QUESTION_INTENTS
        in_group_cooldown = intent in GROUP_COOLDOWN_INTENTS

        # ---- 1. 未回复抑制（只针对普通提问类） ----
        last_replied = bool(state.get("last_proactive_replied", True))
        last_proactive_at = float(state.get("last_proactive_at") or 0.0)
        if (
            is_question
            and self.max_unanswered_proactive >= 1
            and not last_replied
            and last_proactive_at > 0
        ):
            suppressed_remaining = self.unanswered_suppress_window_seconds - (now - last_proactive_at)
            if suppressed_remaining > 0:
                retry_minutes = min(
                    max(15, int(suppressed_remaining / 60) + 5),
                    self.question_cooldown_seconds // 60,
                )
                return CadenceVerdict.block(
                    "last_proactive_unanswered", retry_minutes
                )

        # 非提问类在全局冷却内的普通消息
        last_sent_ts = float(state.get("last_proactive_at") or state.get("last_sent_ts") or 0.0)

        # ---- 2. 全局冷却 ----
        if last_sent_ts > 0 and (now - last_sent_ts) < self.global_cooldown_seconds:
            remaining = int(self.global_cooldown_seconds - (now - last_sent_ts))
            return CadenceVerdict.block(
                "cadence_global_cooldown", max(10, int(remaining / 60) + 1)
            )

        # ---- 3. 提问冷却（问过一次后，短时间内不再问） ----
        if is_question:
            last_type = str(state.get("last_proactive_type") or "").strip()
            if (
                last_type in QUESTION_INTENTS
                and last_proactive_at > 0
                and (now - last_proactive_at) < self.question_cooldown_seconds
            ):
                remaining = int(self.question_cooldown_seconds - (now - last_proactive_at))
                return CadenceVerdict.block(
                    "cadence_question_cooldown", max(15, int(remaining / 60) + 1)
                )

        # ---- 4. 同组题材冷却（换措辞追同一件事） ----
        if in_group_cooldown:
            current_group = self._resolve_current_group(intent, planned_topic, candidate_topic_label)
            if current_group and is_eligible_for_group_cooldown(current_group):
                last_topic_label = str(state.get("last_sent_topic") or "").strip()
                last_group = group_for_topic_label(last_topic_label)
                if (
                    last_group == current_group
                    and last_proactive_at > 0
                    and (now - last_proactive_at) < self.same_topic_cooldown_seconds
                ):
                    remaining = int(self.same_topic_cooldown_seconds - (now - last_proactive_at))
                    return CadenceVerdict.block(
                        "cadence_same_topic_group",
                        max(30, int(remaining / 60) + 5),
                    )

        # ---- 5. 每日好奇提问软上限 ----
        if is_question and self.max_curious_question_per_day >= 1:
            today_questions = self._count_question_today(state, intent)
            if today_questions >= self.max_curious_question_per_day:
                return CadenceVerdict.block(
                    "cadence_curious_question_daily_cap",
                    max(60, self.question_cooldown_seconds // 60),
                )

        return CadenceVerdict.allow()

    # ==================== 内部辅助 ====================

    def _resolve_current_group(
        self, intent: str, planned_topic: str, candidate_topic_label: str
    ) -> str:
        """判定本条消息所属的 topic_group。

        优先级：候选题材标签（LLM 已给）→ planned_topic → 默认 general。
        """
        if candidate_topic_label:
            group = group_for_topic_label(candidate_topic_label)
            if group != "general":
                return group
        if planned_topic and planned_topic.strip():
            try:
                from core.services.active_care.decision.topic_classifier import (
                    classify_topic,
                )
                label = classify_topic(intent, planned_topic=planned_topic)
                return group_for_topic_label(label)
            except Exception:
                pass
        return "general"

    @staticmethod
    def _count_question_today(state: Dict[str, Any], intent: str) -> int:
        """统计今天已发送的好奇提问数（用 today_sent_events 计数）。"""
        events = state.get("today_sent_events") or []
        if not isinstance(events, list):
            return 0
        count = 0
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if str(ev.get("sys_prompt_type") or "") == intent:
                count += 1
        return count


__all__ = [
    "CadenceGuard",
    "CadenceVerdict",
    "DEFAULT_GLOBAL_PROACTIVE_COOLDOWN",
    "DEFAULT_QUESTION_COOLDOWN",
    "DEFAULT_SAME_TOPIC_COOLDOWN",
    "DEFAULT_MAX_UNANSWERED_PROACTIVE",
    "DEFAULT_MAX_CURIOUS_QUESTION_PER_DAY",
    "COOLDOWN_EXEMPT_INTENTS",
    "QUESTION_INTENTS",
]
