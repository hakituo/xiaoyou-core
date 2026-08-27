"""
睡眠会话状态机管理器

从 proactive_checker.py 拆分而来，负责处理睡眠会话的状态机逻辑：
- 检测清醒信号并尝试退出晚安模式
- 检测晚安意图并尝试进入晚安模式
- 退出晚安模式并归档睡眠会话
- 同步睡眠/起床时间到 Daily Record

注：probable_sleep（基于长时间无响应推断入睡）机制已于 2026-07-30 移除，
因为该机制会把用户忙/离开误判为睡觉并覆盖 UIE 正确记录的作息数据。
夜间降频现在依赖 goodnight（用户说晚安）和 sleep_hint（用户暗示"不回就是睡了"），
以及 prompt_builder.py 中"距上次发言 X 小时"的上下文注入，由 AI 自行判断。

依赖通过构造函数注入：
- intent_detector: IntentDetector，提供意图检测能力
- sleep_policy: SleepPolicy，提供睡眠策略
- storage: 存储层，提供 save_proactive_state 等方法
- get_config_value: 可调用对象，用于读取配置
"""
import time
import weakref
from typing import Any, Callable, Dict

from core.utils.logger import get_module_logger
from core.utils.timestamp_utils import safe_timestamp
from core.utils.time_utils import from_timestamp
from core.services.active_care.shared.constants import (
    AUTO_WAKE_MAX_HOURS,
    GOODNIGHT_SIGNAL_GAP_SECONDS,
)

logger = get_module_logger("ACTIVE_CARE_CHECKER", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class SleepSessionManager:
    """睡眠会话状态机管理器

    封装睡眠会话的状态机逻辑，由 ProactiveChecker 委托调用。
    所有方法签名与原 ProactiveChecker 中对应方法保持一致，便于反射兼容。

    配置读取通过 _get_config_value 方法，默认委托给构造时传入的 get_config_value 回调。
    若 checker 引用可用，则动态委托给 checker._get_config_value，以支持测试时
    对 checker._get_config_value 的 mock 替换。
    """

    def __init__(
        self,
        intent_detector,
        sleep_policy,
        storage,
        get_config_value: Callable[[str, Any], Any],
        checker=None,
    ):
        """
        Args:
            intent_detector: IntentDetector 实例，提供 contains_awake_presence 等方法
            sleep_policy: SleepPolicy 实例，提供 build_sleep_session_archive_updates 等方法
            storage: 存储层，提供 save_proactive_state 等方法
            get_config_value: 配置读取回调，签名 (attr: str, default: Any) -> Any
            checker: 可选的 ProactiveChecker 弱引用，用于动态委托 _get_config_value
        """
        self._intent_detector = intent_detector
        self._sleep_policy = sleep_policy
        self.storage = storage
        self._get_config_value_cb = get_config_value
        # 持有 checker 的弱引用，避免循环引用；用于动态委托 _get_config_value
        self._checker_ref = weakref.ref(checker) if checker is not None else None

    def _get_config_value(self, attr: str, default: Any) -> Any:
        """读取配置值

        优先委托给 checker._get_config_value（支持运行时 mock 替换），
        若 checker 不可用则回退到构造时传入的回调。
        """
        if self._checker_ref is not None:
            checker = self._checker_ref()
            if checker is not None:
                return checker._get_config_value(attr, default)
        return self._get_config_value_cb(attr, default)

    async def _process_sleep_session_state(
        self,
        now: float,
        state_data: Dict,
        inferred_goodnight: bool,
        inferred_goodmorning: bool,
        inferred_ts: float,
        inferred_text: str,
        workspace_snapshot: Dict,
        is_assistant_goodnight: bool = False,
        inferred_sleep_hint: bool = False,
    ) -> Dict:
        """处理睡眠会话状态更新"""
        reduced_mode_active = bool(state_data.get("reduced_mode_active"))
        reduced_mode_reason = str(state_data.get("reduced_mode_reason") or "none")

        t0 = time.monotonic()
        reduced_mode_active, reduced_mode_reason, state_data = (
            await self._clear_disabled_reduced_modes(
                state_data, reduced_mode_active, reduced_mode_reason
            )
        )
        logger.info("Active Care 计时: _clear_disabled_reduced_modes=%.1fs", time.monotonic() - t0)

        inferred_awake_presence = self._intent_detector.contains_awake_presence(inferred_text)
        current_last_goodnight_ts = safe_timestamp(state_data.get("last_goodnight_ts"))
        persisted_last_user_ts = safe_timestamp(state_data.get("last_user_interaction_ts"))
        latest_user_signal_ts = max(inferred_ts, persisted_last_user_ts)

        recent_user_signal_after_goodnight = self._check_signal_after_goodnight(
            latest_user_signal_ts, current_last_goodnight_ts
        )
        inferred_signal_after_goodnight = (
            inferred_ts > 0
            and current_last_goodnight_ts > 0
            and inferred_ts > (current_last_goodnight_ts + 1.0)
        )

        t0 = time.monotonic()
        state_data = await self._try_exit_goodnight_on_awake_signals(
            now, state_data, reduced_mode_active, reduced_mode_reason,
            inferred_goodmorning, inferred_awake_presence, inferred_signal_after_goodnight,
            recent_user_signal_after_goodnight, current_last_goodnight_ts,
            latest_user_signal_ts, inferred_ts,
        )
        logger.info("Active Care 计时: _try_exit_goodnight_on_awake_signals=%.1fs", time.monotonic() - t0)

        t0 = time.monotonic()
        state_data = await self._try_enter_goodnight_on_intent(
            now, state_data, inferred_goodnight, inferred_goodmorning, inferred_ts,
            is_assistant_goodnight=is_assistant_goodnight,
        )
        logger.info("Active Care 计时: _try_enter_goodnight_on_intent=%.1fs", time.monotonic() - t0)

        # probable_sleep 推断机制已于 2026-07-30 移除：
        # 该机制通过"用户长时间无响应"推断入睡并写入 daily_record，
        # 但会把用户忙/离开误判为睡觉，覆盖 UIE 正确记录的作息数据。
        # 夜间降频现在依赖 goodnight / sleep_hint + prompt_builder 的"距上次发言"注入。

        return state_data

    async def _try_exit_goodnight_on_awake_signals(
        self,
        now: float,
        state_data: Dict,
        reduced_mode_active: bool,
        reduced_mode_reason: str,
        inferred_goodmorning: bool,
        inferred_awake_presence: bool,
        inferred_signal_after_goodnight: bool,
        recent_user_signal_after_goodnight: bool,
        current_last_goodnight_ts: float,
        latest_user_signal_ts: float,
        inferred_ts: float,
    ) -> Dict:
        """检测清醒信号并尝试退出晚安模式"""
        last_goodmorning_ts = safe_timestamp(state_data.get("last_goodmorning_ts"))
        if last_goodmorning_ts > 0 and last_goodmorning_ts >= current_last_goodnight_ts:
            return state_data

        is_goodnight_mode = (
            reduced_mode_active
            and str(reduced_mode_reason or "") == "goodnight"
        )

        if inferred_goodmorning and is_goodnight_mode:
            wakeup_ts = latest_user_signal_ts if latest_user_signal_ts > 0 else (inferred_ts if inferred_ts > 0 else now)
            msg_logger.info(
                "Active Care: 检测到早安意图(inferred_goodmorning=%s, inferred_signal_after_goodnight=%s, "
                "recent_user_signal_after_goodnight=%s, inferred_ts=%.0f, latest_user_signal_ts=%.0f)，退出晚安模式",
                inferred_goodmorning, inferred_signal_after_goodnight,
                recent_user_signal_after_goodnight, inferred_ts, latest_user_signal_ts,
            )
            return await self._exit_goodnight_mode(
                state_data, now, wakeup_ts
            )

        if is_goodnight_mode and (
            (inferred_awake_presence and inferred_signal_after_goodnight)
            or recent_user_signal_after_goodnight
        ):
            msg_logger.info(
                "Active Care: 检测到清醒信号(awake=%s, signal_after=%s, recent_signal=%s)，退出晚安模式",
                inferred_awake_presence, inferred_signal_after_goodnight,
                recent_user_signal_after_goodnight,
            )
            return await self._exit_goodnight_mode(
                state_data, now, latest_user_signal_ts
            )

        now_hour = from_timestamp(now).hour
        # 自适应白天判定
        from core.services.active_care.scheduling.schedule_adapter import get_schedule_adapter
        adaptive_params = get_schedule_adapter().get_adaptive_params(now)
        is_daytime = self._is_adaptive_daytime(now_hour, adaptive_params)
        if is_goodnight_mode and is_daytime and recent_user_signal_after_goodnight:
            msg_logger.info(
                "Active Care: 当前为白天(%d点)且晚安后有用户信号，自动退出晚安模式",
                now_hour,
            )
            return await self._exit_goodnight_mode(state_data, now, latest_user_signal_ts)

        auto_wake_max_hours = AUTO_WAKE_MAX_HOURS
        if (
            is_goodnight_mode
            and current_last_goodnight_ts > 0
            and (now - current_last_goodnight_ts) > (auto_wake_max_hours * 3600)
        ):
            msg_logger.info(
                "Active Care: 晚安后超过%d小时无交互，自动退出晚安模式 (goodnight_ago=%.1fh)",
                auto_wake_max_hours,
                (now - current_last_goodnight_ts) / 3600,
            )
            return await self._exit_goodnight_mode(state_data, now, now)

        if inferred_goodmorning and inferred_signal_after_goodnight and (
            reduced_mode_active
            or safe_timestamp(state_data.get("last_goodnight_ts"))
            > safe_timestamp(state_data.get("last_goodmorning_ts"))
        ):
            return await self._exit_goodnight_mode(
                state_data, now, inferred_ts if inferred_ts > 0 else now
            )

        if is_goodnight_mode:
            msg_logger.info(
                "Active Care: 仍在晚安模式，无法退出 (goodmorning=%s, awake=%s, "
                "signal_after=%s, recent_signal=%s, inferred_ts=%.0f, goodnight_ts=%.0f, hour=%d)",
                inferred_goodmorning, inferred_awake_presence,
                inferred_signal_after_goodnight, recent_user_signal_after_goodnight,
                inferred_ts, current_last_goodnight_ts, now_hour,
            )

        return state_data

    async def _try_enter_goodnight_on_intent(
        self,
        now: float,
        state_data: Dict,
        inferred_goodnight: bool,
        inferred_goodmorning: bool,
        inferred_ts: float,
        is_assistant_goodnight: bool = False,
    ) -> Dict:
        """检测晚安意图并尝试进入晚安模式

        Args:
            is_assistant_goodnight: 兼容参数，已废弃。助手说晚安不再作为用户入睡信号，
                本参数不再影响任何分支（此前"助手晚安强制进入睡眠会话"会导致
                nightly_processor / peer_chat 误判用户入睡，已在 2026-08-16 移除）。
                进入睡眠会话一律以配置开关为准，仅依据用户真实晚安行为。
        """
        if not inferred_goodnight or inferred_goodmorning:
            return state_data

        # 进入睡眠会话一律受配置开关控制，不再区分是否助手晚安
        enable_auto_goodnight_reduced_mode = bool(
            self._get_config_value("active_care_enable_auto_goodnight_reduced_mode", False)
        )
        if not enable_auto_goodnight_reduced_mode:
            logger.info(
                "Active Care: inferred goodnight detected but auto goodnight reduced mode is disabled; skip auto enter."
            )
            return state_data

        if inferred_ts > 0 and (now - inferred_ts) > (12 * 3600):
            return state_data

        goodnight_ts = inferred_ts if inferred_ts > 0 else now
        last_goodnight_ts = safe_timestamp(state_data.get("last_goodnight_ts"))
        last_exit_ts = safe_timestamp(
            state_data.get("last_low_disturbance_exit_ts")
        )
        handled_ts = max(last_goodnight_ts, last_exit_ts)
        if handled_ts > 0 and goodnight_ts <= handled_ts + 1.0:
            logger.info(
                "Active Care: 晚安信号已处理，跳过重复进入和计划结算 "
                "(signal_ts=%.0f, handled_ts=%.0f)",
                goodnight_ts,
                handled_ts,
            )
            return state_data

        # 进入晚安模式即视为就寝：结算当日未完成计划项为 skipped
        try:
            from core.services.journal.service import get_journal_service

            result = await get_journal_service()._plan_checkpoint_service.settle_today_plan_on_sleep(
                sleep_ts=goodnight_ts
            )
            logger.info("Active Care: 晚安结算今日计划 -> %s", result)
        except Exception as exc:  # pragma: no cover - 失败不应阻断晚安流程
            logger.warning("Active Care: 晚安结算今日计划失败：%s", exc)

        return await self.storage.save_user_sleep_state({
            "last_goodnight_ts": goodnight_ts,
            "last_goodnight_probe_ts": 0.0,
            "reduced_mode_active": True,
            "reduced_mode_reason": "goodnight",
            "reduced_mode_label": "sleep",
            "reduced_mode_started_ts": goodnight_ts,
        }, immediate=True)

    async def _try_infer_probable_sleep(
        self,
        now: float,
        state_data: Dict,
        inferred_goodnight: bool,
        inferred_goodmorning: bool,
        inferred_awake_presence: bool,
        latest_user_signal_ts: float,
        inferred_sleep_hint: bool = False,
    ) -> Dict:
        """处理 sleep_hint 模式的进入与退出

        probable_sleep（基于长时间无响应推断入睡）已于 2026-07-30 移除，
        因为该机制会把用户忙/离开误判为睡觉并覆盖 UIE 正确记录的作息数据。
        本方法现在只处理 sleep_hint（用户明确暗示"不回就是睡了"）：
        - 进入：用户发出睡眠暗示 + 沉默超过阈值
        - 退出：检测到清醒信号 / 白天 / 超过最大睡眠时长

        保留方法名是为了兼容 _process_sleep_session_state 的调用签名
        （该方法已被 _process_sleep_session_state 移除调用，但保留为兼容入口）。
        """
        from core.services.active_care.shared.constants import (
            SLEEP_HINT_REASON,
            AUTO_WAKE_MAX_HOURS,
        )
        from core.services.active_care.scheduling.schedule_adapter import get_schedule_adapter

        adaptive_params = get_schedule_adapter().get_adaptive_params(now)

        reduced_mode_active = bool(state_data.get("reduced_mode_active"))
        reduced_mode_reason = str(state_data.get("reduced_mode_reason") or "none")

        # 仅处理 sleep_hint 模式的退出（probable_sleep 已移除）
        if reduced_mode_active and reduced_mode_reason == SLEEP_HINT_REASON:
            if inferred_goodmorning or inferred_awake_presence:
                logger.info(
                    "Active Care: 检测到清醒信号，退出 %s 模式",
                    reduced_mode_reason,
                )
                from core.services.active_care.shared.constants import build_reduced_mode_clear_updates
                return await self.storage.save_user_sleep_state(
                    build_reduced_mode_clear_updates(), immediate=True
                )

            now_hour = from_timestamp(now).hour
            is_daytime = self._is_adaptive_daytime(now_hour, adaptive_params)
            if is_daytime:
                logger.info(
                    "Active Care: 当前为白天(%d点，自适应判定)，自动退出 %s 模式",
                    now_hour, reduced_mode_reason,
                )
                from core.services.active_care.shared.constants import build_reduced_mode_clear_updates
                return await self.storage.save_user_sleep_state(
                    build_reduced_mode_clear_updates(), immediate=True
                )

            sleep_hint_started_ts = safe_timestamp(
                state_data.get("reduced_mode_started_ts")
            )
            if sleep_hint_started_ts > 0 and (now - sleep_hint_started_ts) > (AUTO_WAKE_MAX_HOURS * 3600):
                logger.info(
                    "Active Care: %s 模式超过%d小时，自动退出",
                    reduced_mode_reason, AUTO_WAKE_MAX_HOURS,
                )
                from core.services.active_care.shared.constants import build_reduced_mode_clear_updates
                return await self.storage.save_user_sleep_state(
                    build_reduced_mode_clear_updates(), immediate=True
                )

            return state_data

        if reduced_mode_active:
            return state_data

        if inferred_goodnight:
            return state_data

        # 睡眠暗示检测：用户明确表示"不回就是睡了"+ 沉默超过阈值 → 进入 sleep_hint
        evening_silence = adaptive_params.get("evening_silence_seconds", 3600)
        if inferred_sleep_hint and latest_user_signal_ts > 0:
            elapsed_since_user = max(0.0, now - latest_user_signal_ts)
            if elapsed_since_user >= evening_silence and not inferred_awake_presence and not inferred_goodmorning:
                logger.info(
                    "Active Care: 检测到睡眠暗示，用户沉默%ds（自适应阈值%ds），"
                    "进入 sleep_hint 模式（不限时段）",
                    int(elapsed_since_user), int(evening_silence),
                )
                return await self.storage.save_user_sleep_state({
                    "reduced_mode_active": True,
                    "reduced_mode_reason": SLEEP_HINT_REASON,
                    "reduced_mode_label": "sleep_hint",
                    "reduced_mode_started_ts": now,
                    "last_goodnight_probe_ts": 0.0,
                }, immediate=True)

        return state_data


    @staticmethod
    def _is_adaptive_daytime(now_hour: int, adaptive_params: Dict) -> bool:
        """根据自适应参数判断当前是否为白天

        白天定义：早上时段结束到晚间时段开始之间的时间
        默认：10-18点，自适应后根据用户作息调整
        """
        morning_end = adaptive_params.get("morning_hour_end", 10)
        evening_start = adaptive_params.get("evening_hour_start", 18)

        # 如果早上结束时间 < 晚间开始时间，白天就是中间的间隔
        if morning_end < evening_start:
            return morning_end <= now_hour < evening_start
        # 跨午夜的情况（极端夜猫子），白天取反
        return not (now_hour >= evening_start or now_hour < morning_end)

    async def _clear_disabled_reduced_modes(
        self,
        state_data: Dict,
        reduced_mode_active: bool,
        reduced_mode_reason: str,
    ) -> tuple:
        """清理被配置禁用的 reduced mode"""
        from core.services.active_care.shared.constants import (
            build_goodnight_clear_updates,
            build_reduced_mode_clear_updates,
        )

        enable_auto_goodnight_reduced_mode = bool(
            self._get_config_value("active_care_enable_auto_goodnight_reduced_mode", False)
        )
        if (
            reduced_mode_active
            and str(reduced_mode_reason or "") == "goodnight"
            and not enable_auto_goodnight_reduced_mode
        ):
            state_data = await self.storage.save_user_sleep_state(
                build_goodnight_clear_updates(), immediate=True
            )
            reduced_mode_active = False
            reduced_mode_reason = "none"
            logger.info(
                "Active Care: auto goodnight reduced mode is disabled; cleared stale goodnight reduced state."
            )

        enable_focus_reduced_mode = bool(
            self._get_config_value("active_care_enable_focus_reduced_mode", False)
        )
        if (
            reduced_mode_active
            and str(reduced_mode_reason or "") == "focus"
            and not enable_focus_reduced_mode
        ):
            state_data = await self.storage.save_proactive_state(
                build_reduced_mode_clear_updates(), immediate=True
            )
            reduced_mode_active = False
            reduced_mode_reason = "none"
            logger.info(
                "Active Care: auto focus reduced mode is disabled; cleared stale focus reduced state."
            )

        return reduced_mode_active, reduced_mode_reason, state_data

    @staticmethod
    def _check_signal_after_goodnight(
        latest_user_signal_ts: float, last_goodnight_ts: float
    ) -> bool:
        """检查用户信号是否在晚安之后"""
        has_recent_user_signal = (
            latest_user_signal_ts > 0 and (last_goodnight_ts > 0)
        )
        return bool(
            has_recent_user_signal
            and latest_user_signal_ts > (last_goodnight_ts + GOODNIGHT_SIGNAL_GAP_SECONDS)
        )

    async def _exit_goodnight_mode(
        self, state_data: Dict, now: float, wakeup_ts: float
    ) -> Dict:
        """根据清醒信号退出低打扰，不把推断时刻归档成真实作息。"""
        from core.services.active_care.shared.constants import StateKeys, build_goodnight_clear_updates

        goodnight_clear = build_goodnight_clear_updates()
        goodnight_clear[StateKeys.LAST_LOW_DISTURBANCE_EXIT_TS] = wakeup_ts
        goodnight_clear[StateKeys.LAST_LOW_DISTURBANCE_EXIT_SOURCE] = "active_care_signal"
        t0 = time.monotonic()
        result = await self.storage.save_user_sleep_state(goodnight_clear, immediate=True)
        logger.info("Active Care 计时: save_user_sleep_state(goodnight_clear)=%.1fs", time.monotonic() - t0)
        return result

