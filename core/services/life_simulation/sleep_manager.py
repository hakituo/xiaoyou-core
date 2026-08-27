"""角色睡眠管理器。"""

from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.services.character_daily.config import (
    CharacterDailyConfig,
    RoleScheduleTemplate,
    SleepProfileConfig,
    load_character_daily_config,
    load_schedule_templates,
)
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from .sleep_decision import build_fallback_decision, call_llm_sleep_decision
from .sleep_models import (
    NightWakeContext,
    SleepDecision,
    SleepPhase,
    SleepQualityImpact,
    SleepRuntimeState,
)
from .sleep_state_store import SleepStateStore

# 必须用 get_logger，否则日志只走 root logger（仅 console handler），不写入 xiaoyou_main.log，
# 导致 _on_enter_sleeping / _on_enter_waking_up 的触发记录无法通过日志文件验证
logger = get_logger(__name__)

_ROLE_NAMES = {
    "aveline": "七濑澪",
    "ling": "Ling",
    "yeye": "Coco",
    "xiaolu": "小鹿",
    "rushuang": "Frost",
    "mianmian": "Mian",
    "chiba": "Chiba",
}
_WAKING_UP_OVERRIDE_WINDOW_SECONDS = 20 * 60

# 接入 active_care 主动消息的角色白名单。
# 设计依据：core/services/character_daily/engine.py 的 KNOWN_ROLES 中，
# xiaolu/mianmian 仅推进作息状态机，不接 active_care；
# yeye/rushuang 已有独立 QQ 账号（NapCat 3004/3003），接入主动消息。
# 若触发命中 goodnight_proactive/good_morning_proactive 的 fallback（默认 aveline），
# 会以"七濑澪"名义误发消息并污染 aveline 的会话历史，故白名单外角色一律跳过。
#
# 默认白名单硬编码在此处作为 fallback；可通过配置文件
# (config/yaml/app.yaml 的 life_simulation.active_care_enabled_roles)
# 覆盖，格式为角色 ID 列表，例如：
#   active_care_enabled_roles: ["aveline", "ling", "yeye", "rushuang"]
# 留空或省略配置项时回退到下方默认值。
_ACTIVE_CARE_ENABLED_ROLES_DEFAULT = frozenset({"aveline", "ling", "yeye", "rushuang"})


def _load_active_care_enabled_roles() -> frozenset:
    """从配置文件读取可发 active_care 的角色白名单，读取失败回退到默认值。"""
    try:
        from core.utils.config_accessor import get_active_care_config

        roles = get_active_care_config("active_care_enabled_roles", default=None)
        if isinstance(roles, (list, tuple, set, frozenset)) and roles:
            return frozenset(str(r).strip() for r in roles if str(r).strip())
    except Exception as exc:  # noqa: BLE001 - 配置缺失不应阻断睡眠管理器初始化
        logger.warning("读取 active_care_enabled_roles 配置失败，使用默认白名单: %s", exc)
    return _ACTIVE_CARE_ENABLED_ROLES_DEFAULT


_ACTIVE_CARE_ENABLED_ROLES = _load_active_care_enabled_roles()


def _parse_hhmm_to_minutes(value: str, fallback: int) -> int:
    try:
        hour_str, minute_str = str(value or "").split(":")
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
        return hour * 60 + minute
    except Exception:
        return fallback


def _minutes_to_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


class SleepManager:
    """统一管理角色睡眠状态。"""

    def __init__(self, store: Optional[SleepStateStore] = None):
        self._store = store or SleepStateStore()
        self._templates: Dict[str, RoleScheduleTemplate] = load_schedule_templates()
        self._runtime_config: CharacterDailyConfig = load_character_daily_config()
        self._states: Dict[str, SleepRuntimeState] = self._store.load()

    def reload_templates(self) -> None:
        """重载角色配置。"""
        self._templates = load_schedule_templates()
        self._runtime_config = load_character_daily_config()

    def get_state(self, role_id: str, now: Optional[datetime] = None) -> SleepRuntimeState:
        """获取并刷新角色睡眠状态。"""
        state = self._ensure_role_state(role_id, now=now)
        self._update_runtime_state(role_id, state, now=now)
        return state

    def get_all_states(self, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
        """获取所有角色的睡眠状态摘要。"""
        result: Dict[str, Dict[str, Any]] = {}
        for role_id in self._templates.keys():
            result[role_id] = self.get_summary(role_id, now=now)
        return result

    def notify_sleep_interruption(
        self,
        role_id: str,
        message: str = "",
        conversation_id: str = "",
        now: Optional[datetime] = None,
    ) -> SleepRuntimeState:
        """记录角色夜间被叫醒。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        profile = self._get_profile(role_id)
        state.phase = SleepPhase.NIGHT_AWAKE
        state.is_sleeping = False
        state.last_wake_ts = dt.timestamp()
        state.last_chat_ts = dt.timestamp()
        state.night_wake_count += 1
        state.night_wake.wake_ts = dt.timestamp()
        state.night_wake.last_chat_ts = dt.timestamp()
        state.night_wake.silence_window_seconds = int(profile.silence_window_seconds)
        state.night_wake.wake_reason = "user_message"
        if message:
            state.night_wake.messages.append(str(message))
            state.night_wake.messages = state.night_wake.messages[-10:]
        state.push_event(
            "sleep_interruption",
            dt.timestamp(),
            detail="夜间被消息叫醒",
            conversation_id=conversation_id,
        )
        self._persist()
        return state

    def notify_sleep_chat_activity(
        self,
        role_id: str,
        message: str = "",
        now: Optional[datetime] = None,
    ) -> SleepRuntimeState:
        """记录被叫醒后的后续聊天。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        state.last_chat_ts = dt.timestamp()
        state.night_wake.last_chat_ts = dt.timestamp()
        if message:
            state.night_wake.messages.append(str(message))
            state.night_wake.messages = state.night_wake.messages[-10:]
        if state.phase == SleepPhase.SLEEPING:
            state.phase = SleepPhase.NIGHT_AWAKE
            state.is_sleeping = False
        self._persist()
        return state

    def _on_enter_sleeping(
        self,
        role_id: str,
        prev_phase: "SleepPhase",
        now: datetime,
        is_sleep_again: bool = False,
    ) -> None:
        """角色刚进入 SLEEPING 状态时触发主动晚安消息。

        仅在 phase 真实转换（prev_phase != SLEEPING）时触发，
        避免每次 _update_runtime_state 重复调用都发消息。
        通过 asyncio.ensure_future 异步触发，不阻塞睡眠状态机更新。

        发送链路：active_care.goodnight_proactive.trigger_character_goodnight
        注意：角色说晚安不再写入用户睡眠会话（2026-08-16 起移除自动闭环），
        角色睡眠不影响 nightly_processor / peer_chat 对"用户入睡"的判定。

        Args:
            role_id: 角色 ID
            prev_phase: 转换前的 phase
            now: 当前时间
            is_sleep_again: True 表示半夜被叫醒后睡回去（使用 sleep_again_proactive
                模板，发"我又去睡了"类消息，冷却去重）；False 表示按作息时间首次
                入睡（使用 goodnight_proactive 模板，每日去重）
        """
        if prev_phase == SleepPhase.SLEEPING:
            return
        # 白名单过滤：只有接入 active_care 的角色才触发主动晚安消息。
        # xiaolu/mianmian 未接入，跳过避免误挂 aveline 名义发出污染会话历史。
        if role_id not in _ACTIVE_CARE_ENABLED_ROLES:
            logger.debug(
                "角色 %s 未接入 active_care，跳过%s主动消息触发",
                role_id,
                "睡回去" if is_sleep_again else "晚安",
            )
            return
        try:
            from core.services.active_care.goodnight_proactive import (
                trigger_character_goodnight_async,
            )

            trigger_character_goodnight_async(role_id, is_sleep_again=is_sleep_again)
            logger.info(
                "角色 %s 进入 SLEEPING（prev=%s, is_sleep_again=%s），已异步触发%s主动消息",
                role_id,
                getattr(prev_phase, "value", prev_phase),
                is_sleep_again,
                "睡回去" if is_sleep_again else "晚安",
            )
        except Exception as exc:
            logger.warning(
                "角色 %s 触发%s主动消息失败: %s",
                role_id,
                "睡回去" if is_sleep_again else "晚安",
                exc,
            )

    def _on_enter_waking_up(
        self,
        role_id: str,
        prev_phase: "SleepPhase",
        now: datetime,
        wake_dt: datetime,
        is_stay_up_recovery: bool = False,
    ) -> None:
        """角色刚进入 WAKING_UP 状态时触发主动起床问候消息。

        仅在 phase 真实转换（prev_phase != WAKING_UP）时触发，
        避免每次 _update_runtime_state 重复调用都发消息。
        通过 asyncio.ensure_future 异步触发，不阻塞睡眠状态机更新。

        去重保护：由 good_morning_proactive._sent_today 按 role_id 维度做每日去重，
        同一角色一天最多发一次起床问候，避免服务多次重启导致重复发送。

        发送链路：active_care.good_morning_proactive.trigger_character_good_morning
        LLM 会自动通过 sleep_context_text 拿到睡眠摘要（时长/噩梦/惯性等），
        根据上下文和当前时间生成自然的起床问候（早安/午安/下午好），而非固定模板。

        Args:
            role_id: 角色 ID
            prev_phase: 转换前的 phase
            now: 当前时间
            wake_dt: 计划起床时间（保留参数兼容调用方，不再用于窗口判断）
            is_stay_up_recovery: True 表示熬夜后白天恢复清醒（消息可体现疲惫）；
                False 表示按作息正常起床
        """
        if prev_phase == SleepPhase.WAKING_UP:
            return
        # 白名单过滤：只有接入 active_care 的角色才触发主动起床消息。
        # xiaolu/mianmian 未接入，跳过避免误挂 aveline 名义发出污染会话历史。
        if role_id not in _ACTIVE_CARE_ENABLED_ROLES:
            logger.debug(
                "角色 %s 未接入 active_care，跳过起床问候消息触发",
                role_id,
            )
            return
        try:
            from core.services.active_care.good_morning_proactive import (
                trigger_character_good_morning_async,
            )

            trigger_character_good_morning_async(
                role_id, is_stay_up_recovery=is_stay_up_recovery,
            )
            logger.info(
                "角色 %s 进入 WAKING_UP（prev=%s, is_stay_up_recovery=%s），已异步触发起床问候消息",
                role_id,
                getattr(prev_phase, "value", prev_phase),
                is_stay_up_recovery,
            )
        except Exception as exc:
            logger.warning(
                "角色 %s 触发起床问候消息失败: %s",
                role_id,
                exc,
            )

    async def finalize_sleep_recovery_check(
        self,
        role_id: str,
        now: Optional[datetime] = None,
    ) -> SleepRuntimeState:
        """在静默窗口结束后，判断角色是否睡回去或继续醒着。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        profile = self._get_profile(role_id)
        silence_seconds = max(0.0, dt.timestamp() - float(state.last_chat_ts or 0.0))
        if silence_seconds < float(profile.silence_window_seconds):
            return state
        if state.phase not in (
            SleepPhase.NIGHT_AWAKE,
            SleepPhase.STAY_UP_LATE,
            SleepPhase.SLEEP_LATER,
        ):
            return state

        # 被叫醒（NIGHT_AWAKE）：静默窗口已到即确定性睡回，
        # 不再让 LLM 自行决定"稍后睡几十分钟 / 继续不睡"。
        # 与"打断做事后回到原活动"共用同一套"交互结束→回原状态"逻辑：
        # 用户在静默窗口内没再发消息（silence_seconds 已达），说明聊完了，就回去睡觉。
        if state.phase == SleepPhase.NIGHT_AWAKE:
            prev_phase = state.phase
            state.phase = SleepPhase.SLEEPING
            state.is_sleeping = True
            if state.actual_sleep_start_ts <= 0:
                state.actual_sleep_start_ts = dt.timestamp()
            state.stay_up_activity = "idle"
            state.sleep_later_until_ts = 0.0
            # 半夜被叫醒后睡回去，主动给用户发"我又去睡了"告别消息
            self._on_enter_sleeping(
                role_id, prev_phase, dt, is_sleep_again=True,
            )
            state.push_event(
                "sleep_recovery_decision",
                dt.timestamp(),
                detail="夜间被叫醒后静默结束，确定性睡回",
                decision=SleepDecision.RETURN_TO_SLEEP.value,
                stay_up_activity="idle",
                sleep_after_minutes=0,
            )
            self._persist()
            return state

        decision = await self._decide_after_silence(role_id, state, dt)
        if decision["decision"] == SleepDecision.RETURN_TO_SLEEP.value:
            prev_phase = state.phase
            state.phase = SleepPhase.SLEEPING
            state.is_sleeping = True
            if state.actual_sleep_start_ts <= 0:
                state.actual_sleep_start_ts = dt.timestamp()
            state.stay_up_activity = "idle"
            state.sleep_later_until_ts = 0.0
            # 半夜被叫醒后睡回去，主动给用户发"我又去睡了"告别消息
            self._on_enter_sleeping(
                role_id, prev_phase, dt, is_sleep_again=True,
            )
        elif decision["decision"] == SleepDecision.SLEEP_LATER.value:
            state.phase = SleepPhase.SLEEP_LATER
            state.is_sleeping = False
            state.stay_up_activity = decision["stay_up_activity"]
            minutes = max(5, min(180, int(decision["sleep_after_minutes"] or 15)))
            state.sleep_later_until_ts = dt.timestamp() + minutes * 60
        else:
            state.phase = SleepPhase.STAY_UP_LATE
            state.is_sleeping = False
            state.stay_up_activity = decision["stay_up_activity"]
            state.sleep_later_until_ts = 0.0
            if state.nightly_done_for_date == state.date:
                state.patch_pending = True

        state.push_event(
            "sleep_recovery_decision",
            dt.timestamp(),
            detail=str(decision.get("reason") or ""),
            decision=decision["decision"],
            stay_up_activity=decision["stay_up_activity"],
            sleep_after_minutes=decision["sleep_after_minutes"],
        )
        self._persist()
        return state

    def mark_nightly_done(self, role_id: str, date_str: str) -> None:
        """标记某角色当日 nightly 已完成。"""
        state = self.get_state(role_id)
        state.nightly_done_for_date = str(date_str or "")
        self._persist()

    def get_summary(self, role_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        """获取供其他模块使用的摘要状态。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        next_wake_dt = self._resolve_next_wake_dt(role_id, dt)
        profile = self._get_profile(role_id)
        minutes_until_wakeup = int((next_wake_dt - dt).total_seconds() / 60)
        return {
            "role_id": role_id,
            "role_name": _ROLE_NAMES.get(role_id, role_id),
            "date": state.date,
            "phase": state.phase.value,
            "is_sleeping": state.is_sleeping,
            "planned_sleep_time": state.planned_sleep_time,
            "planned_wake_time": state.planned_wake_time,
            "last_sleep_duration_hours": round(state.last_sleep_duration_hours, 2),
            "current_sleep_duration_hours": round(state.current_sleep_duration_hours, 2),
            "sleep_debt_hours": round(state.sleep_debt_hours, 2),
            "sleep_quality_score": round(state.sleep_quality_score, 1),
            "sleep_inertia_score": round(state.sleep_inertia_score, 1),
            "nightmare_level": state.nightmare_level,
            "impact_level": state.impact_level,
            "night_wake_count": state.night_wake_count,
            "overslept": state.overslept,
            "stay_up_activity": state.stay_up_activity,
            "minutes_until_wakeup": minutes_until_wakeup,
            "patch_pending": state.patch_pending,
            "silence_window_seconds": int(profile.silence_window_seconds),
            "last_wake_ts": float(state.last_wake_ts or 0.0),
            "last_chat_ts": float(state.last_chat_ts or 0.0),
            "actual_wakeup_ts": float(state.actual_wakeup_ts or 0.0),
        }

    def get_prompt_summary(self, role_id: str, now: Optional[datetime] = None) -> str:
        """构建简洁的睡眠摘要文本。"""
        summary = self.get_summary(role_id, now=now)
        lines = [
            f"{summary['role_name']}当前睡眠状态：{summary['phase']}",
            f"计划作息：{summary['planned_sleep_time']}睡，{summary['planned_wake_time']}起",
        ]
        if summary["is_sleeping"]:
            lines.append("现在处于睡眠中。")
        if summary["night_wake_count"] > 0:
            lines.append(f"今夜被吵醒 {summary['night_wake_count']} 次。")
        if summary["sleep_debt_hours"] > 0.3:
            lines.append(f"睡眠债约 {summary['sleep_debt_hours']:.1f} 小时。")
        if summary["sleep_inertia_score"] > 0.1:
            lines.append(f"睡眠惯性偏强（{summary['sleep_inertia_score']:.1f}/100）。")
        if summary["nightmare_level"] != "none":
            lines.append(f"噩梦/睡眠质量问题等级：{summary['nightmare_level']}。")
        if summary["impact_level"] != "none":
            lines.append(f"今日状态影响等级：{summary['impact_level']}。")
        if summary["stay_up_activity"] and summary["phase"] in (
            SleepPhase.STAY_UP_LATE.value,
            SleepPhase.SLEEP_LATER.value,
        ):
            lines.append(f"当前偏向在深夜做：{summary['stay_up_activity']}。")
        return "\n".join(lines)

    def get_activity_override(self, role_id: str, now: Optional[datetime] = None) -> Optional[str]:
        """为角色日常提供高优先级活动覆盖。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        if state.phase == SleepPhase.SLEEPING:
            return "sleeping"
        wake_elapsed = (
            dt.timestamp() - float(state.actual_wakeup_ts or 0.0)
            if float(state.actual_wakeup_ts or 0.0) > 0
            else float("inf")
        )
        if (
            state.phase == SleepPhase.WAKING_UP
            and state.sleep_inertia_score > 15
            and wake_elapsed <= _WAKING_UP_OVERRIDE_WINDOW_SECONDS
        ):
            return "waking_up"
        if state.phase == SleepPhase.NIGHT_AWAKE:
            # 夜间被叫醒：角色清醒但可能有点困，不应继续睡觉。
            # 必须返回非 DND 活动，否则 engine._update_current_activity 会使用
            # planned_activity（半夜通常是 sleeping），导致 reply_policy 错误地
            # 走 DND 分支静默累积消息，角色被唤醒后仍不回复。
            return "idle"
        if state.phase == SleepPhase.STAY_UP_LATE:
            return "phone_scrolling" if state.stay_up_activity == "phone_scrolling" else "idle"
        if state.phase == SleepPhase.SLEEP_LATER:
            if state.stay_up_activity == "reading":
                return "reading"
            if state.stay_up_activity == "late_snack":
                return "idle"
            return "idle"
        return None

    def consume_patch_pending(self, role_id: str) -> bool:
        """消费熬夜补丁标记。"""
        state = self.get_state(role_id)
        if not state.patch_pending:
            return False
        state.patch_pending = False
        self._persist()
        return True

    def _ensure_role_state(self, role_id: str, now: Optional[datetime] = None) -> SleepRuntimeState:
        role_id = str(role_id or "").strip().lower()
        if role_id in self._states:
            return self._states[role_id]
        dt = now or get_current_time()
        state = SleepRuntimeState(role_id=role_id, date=dt.strftime("%Y-%m-%d"))
        self._states[role_id] = state
        return state

    def _get_profile(self, role_id: str) -> SleepProfileConfig:
        template = self._templates.get(role_id)
        if template and template.sleep_profile:
            return template.sleep_profile
        return SleepProfileConfig()

    def _update_runtime_state(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: Optional[datetime] = None,
    ) -> None:
        dt = now or get_current_time()
        today = dt.strftime("%Y-%m-%d")
        # 跨天重置：检测到 state.date 与今天不一致时，清零昨日夜间统计字段，
        # 避免 nightmare_level / impact_level / sleep_quality_score 等僵尸值
        # 跨天残留导致后续白天持续衰减精力、永久卡在 SLEEP_RECOVERY 等问题。
        if state.date and state.date != today:
            self._reset_daily_fields(state, dt)
        state.date = today
        sleep_dt, wake_dt = self._resolve_sleep_window(role_id, dt)
        state.planned_sleep_time = sleep_dt.strftime("%H:%M")
        state.planned_wake_time = wake_dt.strftime("%H:%M")
        state.current_sleep_duration_hours = 0.0

        if state.phase == SleepPhase.SLEEP_LATER and state.sleep_later_until_ts > 0:
            if dt.timestamp() >= state.sleep_later_until_ts:
                prev_phase = state.phase
                state.phase = SleepPhase.SLEEPING
                state.is_sleeping = True
                state.actual_sleep_start_ts = dt.timestamp()
                state.stay_up_activity = "idle"
                self._on_enter_sleeping(role_id, prev_phase, dt)

        in_sleep_window = sleep_dt <= dt < wake_dt
        if in_sleep_window and state.phase not in (
            SleepPhase.NIGHT_AWAKE,
            SleepPhase.STAY_UP_LATE,
            SleepPhase.SLEEP_LATER,
        ):
            prev_phase = state.phase
            state.phase = SleepPhase.SLEEPING
            state.is_sleeping = True
            if state.actual_sleep_start_ts <= 0:
                state.actual_sleep_start_ts = max(sleep_dt.timestamp(), 0.0)
            self._on_enter_sleeping(role_id, prev_phase, dt)

        if state.is_sleeping and state.actual_sleep_start_ts > 0:
            state.current_sleep_duration_hours = max(
                0.0,
                (dt.timestamp() - state.actual_sleep_start_ts) / 3600.0,
            )

        if dt >= wake_dt and state.phase == SleepPhase.SLEEPING:
            effective_sleep_start_ts = self._resolve_effective_sleep_start_ts(
                state,
                sleep_dt=sleep_dt,
                wake_dt=wake_dt,
            )
            effective_wakeup_ts = min(dt.timestamp(), wake_dt.timestamp())
            prev_phase = state.phase
            state.phase = SleepPhase.WAKING_UP
            state.is_sleeping = False
            state.actual_wakeup_ts = effective_wakeup_ts
            state.last_wake_ts = effective_wakeup_ts
            state.last_sleep_duration_hours = max(
                0.0,
                (effective_wakeup_ts - effective_sleep_start_ts) / 3600.0,
            )
            state.sleep_debt_hours = self._estimate_sleep_debt(role_id, state)
            state.sleep_inertia_score = self._estimate_sleep_inertia(role_id, state)
            state.overslept = dt > (wake_dt + timedelta(minutes=25))
            state.impact_level = self._estimate_impact_level(state)
            state.actual_sleep_start_ts = 0.0
            state.current_sleep_duration_hours = 0.0
            state.push_event("wakeup", dt.timestamp(), detail="按作息起床")
            # 按作息正常起床，主动给用户发起床问候消息（LLM 会根据时间和睡眠摘要生成自然消息）
            self._on_enter_waking_up(
                role_id, prev_phase, dt, wake_dt, is_stay_up_recovery=False,
            )

        # 熬夜后白天恢复：已过计划起床时间，夜间清醒/熬夜/延迟睡眠状态需恢复为清醒
        # 修复 STAY_UP_LATE 白天卡死 bug：此前只在用户发消息触发
        # finalize_sleep_recovery_check 时才会转换，导致角色永久停在 phone_scrolling，
        # 日常 plan 中的 reading/studying/cooking 等活动被 activity_override 完全覆盖。
        if dt >= wake_dt and state.phase in (
            SleepPhase.STAY_UP_LATE,
            SleepPhase.NIGHT_AWAKE,
            SleepPhase.SLEEP_LATER,
        ):
            prev_phase = state.phase
            state.phase = SleepPhase.WAKING_UP
            state.is_sleeping = False
            state.actual_wakeup_ts = wake_dt.timestamp()
            state.last_wake_ts = max(
                float(state.last_wake_ts or 0.0), wake_dt.timestamp()
            )
            state.stay_up_activity = "idle"
            state.sleep_later_until_ts = 0.0
            # 若熬夜期间有实际入睡记录，估算睡眠时长用于睡眠惯性计算
            if state.actual_sleep_start_ts > 0:
                state.last_sleep_duration_hours = max(
                    0.0,
                    (wake_dt.timestamp() - state.actual_sleep_start_ts) / 3600.0,
                )
                state.actual_sleep_start_ts = 0.0
            state.sleep_debt_hours = self._estimate_sleep_debt(role_id, state)
            state.sleep_inertia_score = self._estimate_sleep_inertia(role_id, state)
            state.impact_level = self._estimate_impact_level(state)
            state.current_sleep_duration_hours = 0.0
            state.push_event(
                "wakeup", dt.timestamp(), detail="熬夜后白天恢复清醒"
            )
            # 熬夜后白天恢复清醒，主动给用户发起床问候消息（消息可体现疲惫感）
            self._on_enter_waking_up(
                role_id, prev_phase, dt, wake_dt, is_stay_up_recovery=True,
            )

        if state.phase == SleepPhase.WAKING_UP:
            elapsed = dt.timestamp() - float(state.actual_wakeup_ts or 0.0)
            if elapsed > 3600:
                state.phase = SleepPhase.FULLY_AWAKE
                state.sleep_inertia_score = max(0.0, state.sleep_inertia_score * 0.5)

        if not in_sleep_window and state.phase == SleepPhase.FULLY_AWAKE:
            state.is_sleeping = False

        self._maybe_roll_nightmare(role_id, state, dt)
        self._persist()

    def _reset_daily_fields(self, state: SleepRuntimeState, dt: datetime) -> None:
        """跨天时重置日级睡眠字段，避免昨日夜间统计值残留污染今天的状态。

        重置范围：
        - nightmare_level / impact_level：避免噩梦僵尸值导致 impact 永久非 none
        - sleep_quality_score：恢复基线 82.0，避免只减不增的单调下降
        - sleep_inertia_score / sleep_debt_hours：清零，让今天从清醒状态开始
        - night_wake_count / night_wake / quality_impact：清零夜间觉醒统计
        - last_sleep_duration_hours / overslept：清零昨日睡眠时长与睡过头标记
        保留字段：phase / is_sleeping / actual_sleep_start_ts 等运行时状态由后续
        睡眠窗口计算自动修正，不在此处重置。
        """
        state.nightmare_level = "none"
        state.impact_level = "none"
        state.sleep_quality_score = 82.0
        state.sleep_inertia_score = 0.0
        state.sleep_debt_hours = 0.0
        state.night_wake_count = 0
        state.last_sleep_duration_hours = 0.0
        state.overslept = False
        state.night_wake = NightWakeContext()
        state.quality_impact = SleepQualityImpact()
        state.push_event(
            "daily_reset",
            dt.timestamp(),
            detail=f"跨天重置日级睡眠字段（{state.date} → {dt.strftime('%Y-%m-%d')}）",
        )
        logger.info(
            "角色 %s 跨天重置睡眠字段：%s → %s",
            state.role_id,
            state.date,
            dt.strftime("%Y-%m-%d"),
        )

    def _resolve_sleep_window(self, role_id: str, now: datetime) -> tuple[datetime, datetime]:
        sleep_minutes, wake_minutes = self._get_planned_minutes(role_id, now)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        candidate_windows = [
            self._build_sleep_window(day_start - timedelta(days=1), sleep_minutes, wake_minutes),
            self._build_sleep_window(day_start, sleep_minutes, wake_minutes),
            self._build_sleep_window(day_start + timedelta(days=1), sleep_minutes, wake_minutes),
        ]

        for sleep_dt, wake_dt in candidate_windows:
            if sleep_dt <= now < wake_dt:
                return sleep_dt, wake_dt

        ended_windows = [window for window in candidate_windows if window[1] <= now]
        if ended_windows:
            return max(ended_windows, key=lambda item: item[1])

        return min(candidate_windows, key=lambda item: item[0])

    def _resolve_next_wake_dt(self, role_id: str, now: datetime) -> datetime:
        """获取从当前时刻开始的下一次计划起床时间。"""
        sleep_minutes, wake_minutes = self._get_planned_minutes(role_id, now)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        candidate_windows = [
            self._build_sleep_window(day_start - timedelta(days=1), sleep_minutes, wake_minutes),
            self._build_sleep_window(day_start, sleep_minutes, wake_minutes),
            self._build_sleep_window(day_start + timedelta(days=1), sleep_minutes, wake_minutes),
            self._build_sleep_window(day_start + timedelta(days=2), sleep_minutes, wake_minutes),
        ]
        future_wakes = [wake_dt for _, wake_dt in candidate_windows if wake_dt > now]
        if future_wakes:
            return min(future_wakes)
        return max(wake_dt for _, wake_dt in candidate_windows)

    def _get_planned_minutes(self, role_id: str, now: datetime) -> tuple[int, int]:
        """解析角色在指定日期应使用的计划睡眠/起床分钟数。"""
        profile = self._get_profile(role_id)
        is_weekend = now.weekday() >= 5
        wake_time = profile.weekend_wake_time if is_weekend else profile.weekday_wake_time
        sleep_time = profile.weekend_sleep_time if is_weekend else profile.weekday_sleep_time
        fallback_sleep = _parse_hhmm_to_minutes(
            getattr(self._templates.get(role_id), "sleep_time", "23:00"),
            23 * 60,
        )
        fallback_wake = _parse_hhmm_to_minutes(
            getattr(self._templates.get(role_id), "wake_time", "07:00"),
            7 * 60,
        )
        sleep_minutes = _parse_hhmm_to_minutes(sleep_time, fallback_sleep)
        wake_minutes = _parse_hhmm_to_minutes(wake_time, fallback_wake)
        wake_minutes += self._weekday_offset_minutes(profile, now)
        sleep_minutes += self._rest_day_sleep_offset(profile, now)

        wake_minutes = max(0, min((24 * 60) - 1, wake_minutes))
        sleep_minutes = max(0, min((24 * 60) - 1, sleep_minutes))
        return sleep_minutes, wake_minutes

    @staticmethod
    def _build_sleep_window(
        base_day_start: datetime,
        sleep_minutes: int,
        wake_minutes: int,
    ) -> tuple[datetime, datetime]:
        """根据某天的作息配置构造单个睡眠窗口。"""
        sleep_dt = base_day_start + timedelta(minutes=sleep_minutes)
        wake_dt = base_day_start + timedelta(minutes=wake_minutes)
        if wake_dt <= sleep_dt:
            wake_dt += timedelta(days=1)
        return sleep_dt, wake_dt

    @staticmethod
    def _resolve_effective_sleep_start_ts(
        state: SleepRuntimeState,
        *,
        sleep_dt: datetime,
        wake_dt: datetime,
    ) -> float:
        """纠正被旧状态污染的睡眠起点，避免白天补算出几十小时睡眠。"""
        planned_sleep_ts = sleep_dt.timestamp()
        planned_wake_ts = wake_dt.timestamp()
        recorded_sleep_ts = float(state.actual_sleep_start_ts or 0.0)
        if recorded_sleep_ts <= 0:
            return planned_sleep_ts
        if recorded_sleep_ts < planned_sleep_ts:
            return planned_sleep_ts
        if recorded_sleep_ts > planned_wake_ts:
            return planned_sleep_ts
        return recorded_sleep_ts

    def _weekday_offset_minutes(self, profile: SleepProfileConfig, now: datetime) -> int:
        if now.weekday() >= 5:
            return int(profile.oversleep_tendency * 25)
        return int(profile.sleep_inertia_tendency * 8)

    def _rest_day_sleep_offset(self, profile: SleepProfileConfig, now: datetime) -> int:
        if now.weekday() < 5:
            return 0
        return int(profile.night_owl_tendency * 30)

    def _estimate_sleep_debt(self, role_id: str, state: SleepRuntimeState) -> float:
        profile = self._get_profile(role_id)
        target = 8.0 - (profile.night_owl_tendency * 0.5)
        return max(0.0, round(target - float(state.last_sleep_duration_hours or 0.0), 2))

    def _estimate_sleep_inertia(self, role_id: str, state: SleepRuntimeState) -> float:
        profile = self._get_profile(role_id)
        base = profile.sleep_inertia_tendency * 65.0
        debt_penalty = min(25.0, state.sleep_debt_hours * 12.0)
        nightmare_penalty = {"none": 0.0, "mild": 8.0, "medium": 16.0, "severe": 28.0}.get(
            state.nightmare_level,
            0.0,
        )
        return min(100.0, base + debt_penalty + nightmare_penalty)

    def _estimate_impact_level(self, state: SleepRuntimeState) -> str:
        if state.nightmare_level == "severe" or state.sleep_debt_hours >= 2.5:
            return "severe"
        if state.nightmare_level == "medium" or state.sleep_debt_hours >= 1.2:
            return "medium"
        if state.nightmare_level == "mild" or state.sleep_debt_hours >= 0.4:
            return "mild"
        return "none"

    def _maybe_roll_nightmare(self, role_id: str, state: SleepRuntimeState, now: datetime) -> None:
        if state.date != now.strftime("%Y-%m-%d"):
            return
        if state.phase != SleepPhase.SLEEPING:
            return
        if state.nightmare_level != "none":
            return
        profile = self._get_profile(role_id)
        threshold = max(0.02, min(0.25, profile.nightmare_tendency / 20.0))
        if random.random() >= threshold:
            return
        roll = random.random()
        if roll < 0.55:
            level = "mild"
        elif roll < 0.85:
            level = "medium"
        else:
            level = "severe"
        state.nightmare_level = level
        state.sleep_quality_score = max(
            25.0,
            state.sleep_quality_score - {"mild": 8.0, "medium": 18.0, "severe": 30.0}[level],
        )
        state.quality_impact.level = level
        state.quality_impact.duration_hours = {"mild": 2.0, "medium": 4.0, "severe": 10.0}[level]
        state.quality_impact.reason = "nightmare"
        state.push_event("nightmare", now.timestamp(), detail=f"噩梦等级 {level}")

    async def _decide_after_silence(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
    ) -> Dict[str, Any]:
        result = await self._call_llm_decision(role_id, state, now)
        if result:
            return result
        return self._fallback_decision(role_id, state, now)

    async def _call_llm_decision(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
    ) -> Optional[Dict[str, Any]]:
        try:
            from core.services.scheduler import get_global_scheduler

            scheduler = get_global_scheduler()
            if scheduler is None:
                return None
            profile = self._get_profile(role_id)
            _, wake_dt = self._resolve_sleep_window(role_id, now)
            return await call_llm_sleep_decision(
                scheduler=scheduler,
                model_path=self._runtime_config.sleep_runtime_decision_model,
                role_id=role_id,
                role_name=_ROLE_NAMES.get(role_id, role_id),
                state=state,
                profile=profile,
                now=now,
                wake_dt=wake_dt,
            )
        except Exception as exc:
            logger.debug("睡眠 LLM 判定失败，将回退启发式: %s", exc)
            return None

    def _fallback_decision(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
    ) -> Dict[str, Any]:
        profile = self._get_profile(role_id)
        _, wake_dt = self._resolve_sleep_window(role_id, now)
        return build_fallback_decision(
            state=state,
            profile=profile,
            now=now,
            wake_dt=wake_dt,
        )

    def _persist(self) -> None:
        self._store.save(self._states)


_sleep_manager_instance: Optional[SleepManager] = None
_sleep_manager_lock = threading.Lock()


def get_sleep_manager() -> SleepManager:
    """获取全局睡眠管理器。"""
    global _sleep_manager_instance
    if _sleep_manager_instance is None:
        with _sleep_manager_lock:
            if _sleep_manager_instance is None:
                _sleep_manager_instance = SleepManager()
    return _sleep_manager_instance
