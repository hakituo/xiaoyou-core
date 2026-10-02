# -*- coding: utf-8 -*-
"""专注监控协调器策略（决定何时探班、探班文案）。

设计原则（来自施工计划）：
- 只在连续高置信度分心后才提醒，单次误判不提醒。
- 两次提醒有冷却间隔。
- 低置信度 / 镜头遮挡 / 网络掉线 不作指责。
- 用户暂停或关闭提醒后立即停止。
- AI 不得自行开启摄像头（策略层不触发任何摄像头操作）。
- 文案表达为"是不是有点走神了"，不宣称"我看到你在玩"。

策略只做判定，不直接发消息；发消息由 router/service 通过
Active Care 的 executor.trigger_message() 统一链路完成。
"""
from __future__ import annotations

import time

from config.focus_monitor_config import get_focus_monitor_config
from core.services.study.focus_session_models import (
    ActivityState,
    FocusSession,
    PresenceState,
)
from core.utils.logger import get_logger

logger = get_logger("FOCUS_POLICY")


class NudgeDecision:
    """策略判定结果。should_nudge=False 时无 message。

    新增 vision_review=True 表示：策略认为应当发起一次低频视觉复核
    （严格模式下，分心持续且用户已授权摄像头时）。视觉复核的触发
    由 service/router 异步执行，策略层不接触任何图像数据。
    """
    def __init__(self, should_nudge: bool, reason: str = "", message: str = "",
                 vision_review: bool = False):
        self.should_nudge = should_nudge
        self.reason = reason
        self.message = message
        self.vision_review = vision_review


# ---- 温柔模式文案（不指责、不宣称确定性）----
_GENTLE_TEMPLATES = {
    "first_checkin": [
        "已经专注一会儿啦，状态看起来不错～要不要喝口水再继续？",
        "刚刚那段挺专注的，我在这儿陪着你呢。",
    ],
    "distraction": [
        "是不是有点走神了？没事，先把视线拉回来就好。",
        "感觉好像飘远了一点，慢慢回来，不用急。",
    ],
    "recover_praise": [
        "回来啦，刚刚那一段又接上了，很棒。",
        "重新进入状态了，继续保持～",
    ],
}

# ---- 严格督学模式文案（更直接，但仍避免羞辱/追债感/虚假断言）----
_STRICT_TEMPLATES = {
    "first_checkin": [
        "已经学了十分钟，节奏不错，继续推进这一段。",
        "前十分钟稳住了，接下来这二十分钟我们一口气做完。",
    ],
    "distraction": [
        "先回来，把手机放下，完成这一小段再休息。",
        "注意力刚才散了，现在把视线收回到屏幕上，再坚持一会儿。",
    ],
    "recover_praise": [
        "对，就是这样，继续往下走。",
        "找回状态了，这段趁热打铁做完。",
    ],
}


def _pick(templates: dict, key: str, salt: int) -> str:
    arr = templates.get(key, [""])
    return arr[salt % len(arr)]


class FocusMonitorPolicy:
    """无状态策略判定器（依赖 FocusMonitorConfig 阈值）。"""

    def __init__(self):
        self.cfg = get_focus_monitor_config()

    # ---- 判定：是否应发起一次探班 ----
    def evaluate(self, session: FocusSession, now: float | None = None) -> NudgeDecision:
        now = now or time.time()

        # 1) 硬停条件：未激活、已暂停、用户静音
        if session.status != "active":
            return NudgeDecision(False, "session_not_active")
        if session.reminders_muted:
            return NudgeDecision(False, "reminders_muted")
        if not session.monitoring:
            # 无摄像头监控时只做轻量陪伴，不做分心指责
            return NudgeDecision(False, "no_camera_monitoring")

        # 2) 探班次数上限
        if len(session.nudge_events) >= self.cfg.nudge_max_per_session:
            return NudgeDecision(False, "nudge_quota_exhausted")

        # 3) 冷却间隔
        if session.nudge_events:
            last = session.nudge_events[-1]["at"]
            if now - last < self.cfg.nudge_cooldown_sec:
                return NudgeDecision(False, "cooldown")

        # 4) 掉线 / 镜头遮挡：不指责
        if session.last_presence in (PresenceState.CAMERA_BLOCKED.value, PresenceState.UNKNOWN.value):
            return NudgeDecision(False, "no_reliable_signal")
        if now - session.last_observed_at > self.cfg.heartbeat_timeout_sec:
            return NudgeDecision(False, "client_offline")

        # 5) 低置信度：不作判断
        if session.last_confidence < self.cfg.distraction_confidence_min:
            return NudgeDecision(False, "low_confidence")

        # 6) 分心持续时长
        if session.last_activity == ActivityState.POSSIBLY_DISTRACTED.value:
            since = getattr(session, "_distraction_since", 0.0)
            if since > 0 and (now - since) >= self.cfg.nudge_distraction_sec:
                msg = _pick(
                    _STRICT_TEMPLATES if session.mode == "strict" else _GENTLE_TEMPLATES,
                    "distraction",
                    len(session.nudge_events),
                )
                return NudgeDecision(True, "distraction_sustained", msg)
            return NudgeDecision(False, "distraction_too_short")

        # 7) 首次轻量探班：专注达到阈值
        if session.last_activity == ActivityState.FOCUSED.value and not session.nudge_events:
            eff = session.effective_elapsed()
            if eff >= self.cfg.nudge_min_focus_sec:
                msg = _pick(
                    _STRICT_TEMPLATES if session.mode == "strict" else _GENTLE_TEMPLATES,
                    "first_checkin",
                    len(session.nudge_events),
                )
                return NudgeDecision(True, "first_checkin", msg)
            return NudgeDecision(False, "focus_too_short")

        return NudgeDecision(False, "no_trigger")

    # ---- 严格模式：是否应发起低频视觉复核 ----
    def evaluate_strict_vision_review(
        self, session: FocusSession, now: float | None = None
    ) -> NudgeDecision:
        """仅在 strict 模式下考虑。

        触发条件（全部满足）：
        1. 会话处于 active、未静音、有摄像头监控；
        2. 已开启视觉复核（配置）；
        3. 已专注达到最短时长；
        4. 当前为持续分心（达到 strict 分心阈值）；
        5. 距上次视觉复核超过冷却间隔；
        6. 信号可靠（presence 为 present、置信度足够、未掉线）。

        返回 vision_review=True 时，service 负责异步发起对当前帧的复核，
        并把结果以新的观察信号回灌（不保存任何图像）。
        """
        now = now or time.time()
        if session.mode != "strict":
            return NudgeDecision(False, "not_strict_mode")
        if session.status != "active":
            return NudgeDecision(False, "session_not_active")
        if session.reminders_muted:
            return NudgeDecision(False, "reminders_muted")
        if not session.monitoring:
            return NudgeDecision(False, "no_camera_monitoring")
        if not self.cfg.strict_vision_review_enabled:
            return NudgeDecision(False, "vision_review_disabled")

        # 冷却 + 最短专注
        if session.vision_review_last_at > 0 and (
            now - session.vision_review_last_at < self.cfg.strict_vision_cooldown_sec
        ):
            return NudgeDecision(False, "vision_review_cooldown")
        if session.effective_elapsed() < self.cfg.strict_vision_min_focus_sec:
            return NudgeDecision(False, "vision_review_focus_too_short")

        # 信号可靠性
        if session.last_presence != PresenceState.PRESENT.value:
            return NudgeDecision(False, "no_reliable_signal")
        if now - session.last_observed_at > self.cfg.heartbeat_timeout_sec:
            return NudgeDecision(False, "client_offline")
        if session.last_confidence < self.cfg.distraction_confidence_min:
            return NudgeDecision(False, "low_confidence")

        # 持续分心
        if session.last_activity != ActivityState.POSSIBLY_DISTRACTED.value:
            return NudgeDecision(False, "not_distracted")
        since = getattr(session, "_distraction_since", 0.0)
        if not (since > 0 and (now - since) >= self.cfg.strict_distraction_sec):
            return NudgeDecision(False, "distraction_too_short")

        # 文案：基于视觉复核给出的温和提醒（具体现象由复核结果补充）
        msg = _pick(_STRICT_TEMPLATES, "distraction", len(session.nudge_events))
        return NudgeDecision(True, "vision_review_suggested", msg, vision_review=True)
