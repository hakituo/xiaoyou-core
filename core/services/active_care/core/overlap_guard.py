"""Active Care 重叠保护（间隔保护）

职责：防止主动关怀消息在短时间内重复触发（重叠保护）。

从 executor.py 拆分，收敛以下状态与逻辑：
- 按 persona 独立追踪的最近触发时间戳
- 各类 sys_prompt_type 的豁免列表
- 触发失败时的回退时间戳
- 最近一次跳过原因（供调用方区分"被间隔保护拦住"与"真正发送失败"）

对外接口：
- OverlapGuard(settings) --- 接收 settings 取 min_gap_seconds
- check(sys_prompt_type, now, persona_key) --- 是否允许触发
- get_guard_seconds(sys_prompt_type) --- 间隔保护秒数
- record_attempt(persona_key, now) --- 记录触发时刻
- rollback_on_failure(attempt_ts, persona_key, sys_prompt_type) --- 触发失败回退
- record_skip(is_interval_blocked, reason) --- 记录跳过原因
"""

from typing import Dict

from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class OverlapGuard:
    """Active Care 重叠保护（间隔保护）"""

    def __init__(self, settings):
        self.settings = settings
        # 按 persona 独立追踪，空字符串 key 为单 QQ 兼容
        self._last_trigger_ts_by_persona: Dict[str, float] = {}
        self._last_skip_is_interval_blocked = False
        self._last_skip_reason = ""

    @property
    def last_skip_is_interval_blocked(self) -> bool:
        return self._last_skip_is_interval_blocked

    @property
    def last_skip_reason(self) -> str:
        return self._last_skip_reason

    @staticmethod
    def _normalize_persona_key(persona_key: str) -> str:
        """把 persona 文件名 / slug 收敛为统一 scope key。

        ``ActiveCareService.on_assistant_message_sent`` 按稳定 scope（如 ``aveline``）
        回写最近发送时间，而 executor 历史上把 ``core_aveline.json`` 原样作为 key。
        两边 key 不一致会让 overlap guard 看不到普通聊天刚刚发生过。
        这里复用项目现有 scope registry，避免再维护一份角色映射。
        """
        raw = str(persona_key or "").strip()
        if not raw:
            return ""
        try:
            from core.utils.data.scope_registry import resolve_persona_slug_scope

            scope = str(resolve_persona_slug_scope(raw) or "").strip().lower()
            if scope:
                return scope
        except Exception:
            pass

        try:
            from core.services.active_care.shared.text_utils import normalize_persona_token

            token = normalize_persona_token(raw)
            if token.startswith("core_"):
                token = token[len("core_") :]
            return token or raw
        except Exception:
            return raw

    def record_skip(self, is_interval_blocked: bool, reason: str) -> None:
        """记录最近一次跳过原因"""
        self._last_skip_is_interval_blocked = is_interval_blocked
        self._last_skip_reason = reason

    def get_guard_seconds(self, sys_prompt_type: str) -> int:
        """获取间隔保护秒数（所有类型统一使用 min_gap_seconds）"""
        min_gap_seconds = int(
            get_active_care_config(
                "active_care_min_gap_seconds", default=600, settings=self.settings
            )
            or 600
        )
        return min_gap_seconds

    def check(self, sys_prompt_type: str, now: float, persona_key: str = "") -> bool:
        """检查重叠保护

        Args:
            persona_key: persona 标识，用于按 persona 独立追踪触发时间。
                         为空时使用全局追踪（兼容单QQ模式）。
        """
        # 作息事件触发的必要通知，不受间隔保护限制：
        # - activity_return_proactive: 活动回归通知（中断窗口结束）
        # - sleep_again_proactive: 半夜被叫醒后睡回去的告别
        # - goodnight_proactive: 按作息时间首次入睡的晚安告别
        #    （曾因未豁免被 2400s 间隔保护拦截，导致角色入睡时发不出晚安）
        if sys_prompt_type in (
            "activity_return_proactive",
            "sleep_again_proactive",
            "goodnight_proactive",
            "focus_nudge",  # 专注番茄钟探班：策略层已内置冷却/上限，豁免全局重叠保护
        ):
            return True

        persona_key = self._normalize_persona_key(persona_key)
        overlap_guard_seconds = self.get_guard_seconds(sys_prompt_type)
        last_trigger_ts = self._last_trigger_ts_by_persona.get(persona_key, 0.0)

        if (
            sys_prompt_type != "startup"
            and (now - last_trigger_ts) < overlap_guard_seconds
        ):
            logger.warning(
                "Active Care: Trigger skipped to avoid overlap (persona=%s). "
                "Last trigger was %ss ago (guard=%ss).",
                persona_key or "global",
                int(now - last_trigger_ts),
                int(overlap_guard_seconds),
            )
            return False
        return True

    def record_attempt(self, persona_key: str, now: float) -> None:
        """记录一次触发尝试时间戳"""
        persona_key = self._normalize_persona_key(persona_key)
        self._last_trigger_ts_by_persona[persona_key] = now

    def rollback_on_failure(
        self, attempt_ts: float, persona_key: str, sys_prompt_type: str
    ) -> None:
        """触发失败时回退时间戳，避免阻挡后续合理触发"""
        persona_key = self._normalize_persona_key(persona_key)
        overlap_guard_seconds = self.get_guard_seconds(sys_prompt_type)
        if self._last_trigger_ts_by_persona.get(persona_key, 0.0) == attempt_ts:
            self._last_trigger_ts_by_persona[persona_key] = (
                attempt_ts - overlap_guard_seconds - 1
            )
