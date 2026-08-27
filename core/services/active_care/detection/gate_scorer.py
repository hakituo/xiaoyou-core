"""
软评分门控系统
替代原来的7层硬拦截门控链，改为评分制。

核心思想：
- 每个门控不再做硬性的"通过/拦截"，而是给出一个分数（0.0-1.0）
- 分数越高，表示越应该放行（1.0=完全放行，0.0=完全拦截）
- 最终综合所有门控的分数，做概率决策
- 某些门控（如私密模式）仍然是硬拦截，不可软化

门控评分规则：
1. 客户端门控：无活跃客户端 → 0.0（硬拦截）或 1.0
2. 私密模式门控：私密模式 → 0.0（硬拦截）或 1.0
3. 手动延迟门控：延迟未到 → 0.0（硬拦截）或 1.0
4. 用户活动门控：忙碌 → 0.1-0.5（软拦截，根据忙碌程度），不忙碌 → 1.0
5. 专注模式门控：专注中 → 0.2-0.6（软拦截，根据安静时长），非专注 → 1.0
6. 睡眠探针门控：睡眠中 → 0.3-0.7（软拦截，根据探针策略），非睡眠 → 1.0
7. 交互保护门控：最近交互 → 0.3-0.8（软拦截，根据交互时长），无交互 → 1.0

综合评分策略：
- 硬拦截门控（客户端/私密/延迟）：任一为0则总分0
- 软拦截门控（活动/专注/睡眠/交互）：取加权几何平均
- 最终分数 >= 阈值（默认0.5）则放行
- 分数在0.3-0.5之间时，根据上下文做概率决策（如紧急需求时降低阈值）
"""
import time
from typing import Dict, Optional

from core.utils.logger import get_module_logger
from core.services.active_care.shared.constants import (
    MIN_QUIET_EVEN_INCOMPLETE_SECONDS,
)

logger = get_module_logger("GATE_SCORER", "active_care_schedule.log")

# 默认放行阈值
_DEFAULT_PASS_THRESHOLD = 0.50
# 紧急需求时的降低阈值
_URGENT_PASS_THRESHOLD = 0.30

# 门控权重（软门控的相对重要性）
_GATE_WEIGHTS = {
    "activity": 0.35,   # 用户活动（权重最高，忙碌时不应打扰）
    "focus": 0.20,      # 专注模式
    "sleep_probe": 0.25, # 睡眠探针
    "interaction": 0.20, # 交互保护
}


class GateScore:
    """门控评分结果"""

    def __init__(self, gate_name: str, score: float, is_hard: bool = False, reason: str = ""):
        self.gate_name = gate_name
        self.score = max(0.0, min(1.0, score))
        self.is_hard = is_hard
        self.reason = reason

    def __repr__(self):
        tag = "硬" if self.is_hard else "软"
        return f"GateScore({self.gate_name}, {self.score:.2f}, {tag}, {self.reason})"


class GateScoringResult:
    """门控评分综合结果"""

    def __init__(self):
        self.scores: list = []
        self.final_score: float = 1.0
        self.passed: bool = True
        self.block_reason: str = ""
        self.is_adaptive: bool = False  # 是否经过概率决策

    def __repr__(self):
        status = "放行" if self.passed else "拦截"
        adaptive = "(概率决策)" if self.is_adaptive else ""
        return f"GateScoringResult({status}{adaptive}, score={self.final_score:.2f}, reason={self.block_reason})"


class GateScorer:
    """软评分门控系统"""

    def evaluate_gates(
        self,
        *,
        # 硬门控参数
        has_active_client: bool = True,
        is_private_mode: bool = False,
        manual_delay_remaining: float = 0.0,
        # 软门控参数
        is_user_busy: bool = False,
        busy_level: float = 0.0,
        busy_category: str = "",
        is_focus_mode: bool = False,
        focus_quiet_seconds: float = 0.0,
        focus_low_disturb_gap: float = 7200,
        is_sleep_session: bool = False,
        is_reduced_mode: bool = False,
        reduced_mode_reason: str = "none",
        probe_policy: Optional[Dict] = None,
        # 交互保护参数
        last_interaction_ts: float = 0.0,
        user_quiet_seconds: float = 300,
        conversation_incomplete: bool = False,
        non_response_count: int = 0,
        # 上下文参数
        has_urgent_needs: bool = False,
        now: float = 0.0,
    ) -> GateScoringResult:
        """评估所有门控，返回综合评分结果

        Args:
            has_active_client: 是否有活跃客户端
            is_private_mode: 是否私密模式
            manual_delay_remaining: 手动延迟剩余秒数
            is_user_busy: 用户是否忙碌
            busy_level: 忙碌程度（0.0-1.0）
            busy_category: 忙碌类别
            is_focus_mode: 是否专注模式
            focus_quiet_seconds: 专注模式安静秒数
            focus_low_disturb_gap: 专注模式低打扰间隔
            is_sleep_session: 是否睡眠会话
            is_reduced_mode: 是否低打扰模式
            reduced_mode_reason: 低打扰模式原因
            probe_policy: 睡眠探针策略
            last_interaction_ts: 最后交互时间戳
            user_quiet_seconds: 用户安静阈值秒数
            conversation_incomplete: 对话是否未完成
            non_response_count: 连续无响应次数
            has_urgent_needs: 是否有紧急需求
            now: 当前时间戳

        Returns:
            GateScoringResult
        """
        result = GateScoringResult()
        now = now or time.time()

        # ==================== 硬门控 ====================

        # 门控1：客户端检测
        client_score = self._score_client_gate(has_active_client)
        result.scores.append(client_score)
        if client_score.score == 0.0:
            result.final_score = 0.0
            result.passed = False
            result.block_reason = client_score.reason
            return result

        # 门控2：私密模式
        private_score = self._score_private_gate(is_private_mode)
        result.scores.append(private_score)
        if private_score.score == 0.0:
            result.final_score = 0.0
            result.passed = False
            result.block_reason = private_score.reason
            return result

        # 门控3：手动延迟
        delay_score = self._score_delay_gate(manual_delay_remaining)
        result.scores.append(delay_score)
        if delay_score.score == 0.0:
            result.final_score = 0.0
            result.passed = False
            result.block_reason = delay_score.reason
            return result

        # ==================== 软门控 ====================

        # 门控4：用户活动
        activity_score = self._score_activity_gate(
            is_user_busy, busy_level, busy_category, has_urgent_needs
        )
        result.scores.append(activity_score)

        # 门控5：专注模式
        focus_score = self._score_focus_gate(
            is_focus_mode, focus_quiet_seconds, focus_low_disturb_gap, has_urgent_needs
        )
        result.scores.append(focus_score)

        # 门控6：睡眠探针
        sleep_score = self._score_sleep_probe_gate(
            is_sleep_session, is_reduced_mode, reduced_mode_reason, probe_policy, has_urgent_needs
        )
        result.scores.append(sleep_score)

        # 门控7：交互保护（首次探针时放宽，因为探针的目的就是确认用户是否在）
        is_first_probe = bool(probe_policy and probe_policy.get("allow_send") and probe_policy.get("is_first_probe"))
        interaction_score = self._score_interaction_gate(
            last_interaction_ts, now, user_quiet_seconds,
            conversation_incomplete, non_response_count, has_urgent_needs,
            is_first_probe=is_first_probe,
        )
        result.scores.append(interaction_score)

        # ==================== 综合评分 ====================
        result.final_score = self._compute_final_score(
            activity_score, focus_score, sleep_score, interaction_score
        )

        # 任何软门控得分极低（<0.2）时，直接拦截（除非有紧急需求）
        lowest_soft_score = min(activity_score.score, focus_score.score, sleep_score.score, interaction_score.score)
        if lowest_soft_score < 0.2 and not has_urgent_needs:
            min_gate = min(
                [activity_score, focus_score, sleep_score, interaction_score],
                key=lambda g: g.score
            )
            result.final_score = lowest_soft_score
            result.passed = False
            result.block_reason = f"soft_gate:{min_gate.gate_name}(score={min_gate.score:.2f},too_low)"
            return result

        # 确定阈值
        threshold = _URGENT_PASS_THRESHOLD if has_urgent_needs else _DEFAULT_PASS_THRESHOLD

        if result.final_score >= threshold:
            result.passed = True
            result.block_reason = ""
        elif result.final_score >= threshold * 0.6:
            # 分数接近阈值，做概率决策
            # 分数越高，放行概率越大
            import random
            pass_probability = (result.final_score - threshold * 0.6) / (threshold - threshold * 0.6)
            if random.random() < pass_probability:
                result.passed = True
                result.is_adaptive = True
                result.block_reason = ""
                logger.info(
                    "GateScorer: 概率决策放行 (score=%.2f, threshold=%.2f, prob=%.2f)",
                    result.final_score, threshold, pass_probability,
                )
            else:
                result.passed = False
                result.is_adaptive = True
                # 找到得分最低的软门控作为拦截原因
                min_gate = min(
                    [activity_score, focus_score, sleep_score, interaction_score],
                    key=lambda g: g.score
                )
                result.block_reason = f"soft_gate:{min_gate.gate_name}(score={min_gate.score:.2f})"
        else:
            result.passed = False
            min_gate = min(
                [activity_score, focus_score, sleep_score, interaction_score],
                key=lambda g: g.score
            )
            result.block_reason = f"soft_gate:{min_gate.gate_name}(score={min_gate.score:.2f})"

        return result

    # ==================== 硬门控评分 ====================

    @staticmethod
    def _score_client_gate(has_active_client: bool) -> GateScore:
        if not has_active_client:
            return GateScore("client", 0.0, is_hard=True, reason="no_active_client")
        return GateScore("client", 1.0, is_hard=True)

    @staticmethod
    def _score_private_gate(is_private_mode: bool) -> GateScore:
        if is_private_mode:
            return GateScore("private_mode", 0.0, is_hard=True, reason="private_mode_sensitive_persona")
        return GateScore("private_mode", 1.0, is_hard=True)

    @staticmethod
    def _score_delay_gate(delay_remaining: float) -> GateScore:
        if delay_remaining > 0:
            return GateScore("manual_delay", 0.0, is_hard=True, reason=f"manual_delay_{int(delay_remaining)}s")
        return GateScore("manual_delay", 1.0, is_hard=True)

    # ==================== 软门控评分 ====================

    @staticmethod
    def _score_activity_gate(
        is_busy: bool, busy_level: float, busy_category: str, has_urgent: bool
    ) -> GateScore:
        """用户活动门控评分

        不忙碌 → 1.0
        忙碌但有紧急需求 → 0.6（降级但不完全拦截）
        忙碌且忙碌程度低 → 0.5
        忙碌且忙碌程度高 → 0.1-0.3
        """
        if not is_busy:
            return GateScore("activity", 1.0)

        if has_urgent:
            return GateScore("activity", 0.6, reason=f"busy_but_urgent:{busy_category}")

        # 忙碌程度越高，分数越低
        if busy_level >= 0.8:
            score = 0.1
        elif busy_level >= 0.6:
            score = 0.3
        else:
            score = 0.5

        return GateScore("activity", score, reason=f"user_busy:{busy_category}(level={busy_level:.2f})")

    @staticmethod
    def _score_focus_gate(
        is_focus: bool, quiet_seconds: float, low_disturb_gap: float, has_urgent: bool
    ) -> GateScore:
        """专注模式门控评分

        非专注 → 1.0
        专注但有紧急需求 → 0.5
        专注且安静时间短 → 0.2
        专注且安静时间长（超过低打扰间隔）→ 0.6（允许轻量关怀）
        """
        if not is_focus:
            return GateScore("focus", 1.0)

        if has_urgent:
            return GateScore("focus", 0.5, reason="focus_but_urgent")

        if quiet_seconds >= low_disturb_gap:
            return GateScore("focus", 0.6, reason="focus_long_quiet")

        if quiet_seconds >= low_disturb_gap * 0.5:
            return GateScore("focus", 0.4, reason="focus_medium_quiet")

        return GateScore("focus", 0.2, reason="focus_short_quiet")

    @staticmethod
    def _score_sleep_probe_gate(
        is_sleep: bool, is_reduced: bool, reduced_reason: str,
        probe_policy: Optional[Dict], has_urgent: bool
    ) -> GateScore:
        """睡眠探针门控评分

        非睡眠 → 1.0
        睡眠但有紧急需求 → 0.4
        睡眠且探针策略允许 → 0.5-0.7
        睡眠且探针策略不允许 → 0.2
        """
        if not is_sleep and not is_reduced:
            return GateScore("sleep_probe", 1.0)

        if has_urgent:
            return GateScore("sleep_probe", 0.4, reason="sleep_but_urgent")

        if probe_policy and bool(probe_policy.get("allow_send")):
            # 探针策略允许发送
            # 首次探针（确认用户是否真的睡了）给更高评分，避免被交互保护拦截
            is_first_probe = bool(probe_policy.get("is_first_probe"))
            score = 0.85 if is_first_probe else 0.6
            reason = "sleep_probe_first" if is_first_probe else "sleep_probe_allowed"
            return GateScore("sleep_probe", score, reason=reason)

        if is_reduced and reduced_reason == "sleep_hint":
            return GateScore("sleep_probe", 0.3, reason=f"reduced_mode:{reduced_reason}")

        return GateScore("sleep_probe", 0.2, reason="sleep_probe_blocked")

    @staticmethod
    def _score_interaction_gate(
        last_interaction_ts: float, now: float, quiet_threshold: float,
        conversation_incomplete: bool, non_response_count: int, has_urgent: bool,
        is_first_probe: bool = False,
    ) -> GateScore:
        """交互保护门控评分

        无交互记录 → 1.0
        交互很久以前 → 1.0
        交互较近但有紧急需求 → 0.7
        交互较近且对话未完成 → 0.8（允许绕过部分保护）
        交互很近 → 0.3
        首次探针 → 放宽保护（探针的目的就是确认用户是否在）
        """
        if last_interaction_ts <= 0:
            return GateScore("interaction", 1.0)

        elapsed = max(0.0, now - last_interaction_ts)

        if elapsed >= quiet_threshold:
            return GateScore("interaction", 1.0)

        # 首次探针：用户说晚安后的交互不应阻止探针
        if is_first_probe:
            return GateScore("interaction", 0.8, reason="first_probe_interaction_bypass")

        # 计算交互保护的程度
        ratio = elapsed / max(1.0, quiet_threshold)  # 0.0-1.0，越大表示越久远

        if has_urgent:
            return GateScore("interaction", 0.7, reason="recent_interaction_but_urgent")

        if conversation_incomplete and non_response_count < 2:
            # 对话未完成，放宽保护
            if elapsed >= MIN_QUIET_EVEN_INCOMPLETE_SECONDS:
                return GateScore("interaction", 0.8, reason="conversation_incomplete_bypass")

        # 交互越近，分数越低
        score = max(0.1, ratio * 0.7 + 0.1)
        return GateScore("interaction", score, reason=f"recent_interaction({int(elapsed)}s<{int(quiet_threshold)}s)")

    # ==================== 综合评分 ====================

    @staticmethod
    def _compute_final_score(
        activity: GateScore, focus: GateScore, sleep: GateScore, interaction: GateScore
    ) -> float:
        """计算软门控的加权几何平均分

        使用几何平均而非算术平均，确保任何一个门控分数很低时，总分也会明显降低。
        """
        import math

        total_weight = 0.0
        weighted_log_sum = 0.0

        for gate, weight in [
            (activity, _GATE_WEIGHTS["activity"]),
            (focus, _GATE_WEIGHTS["focus"]),
            (sleep, _GATE_WEIGHTS["sleep_probe"]),
            (interaction, _GATE_WEIGHTS["interaction"]),
        ]:
            # 避免log(0)，最小值0.01
            score = max(0.01, gate.score)
            weighted_log_sum += weight * math.log(score)
            total_weight += weight

        if total_weight <= 0:
            return 0.0

        return math.exp(weighted_log_sum / total_weight)
