#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ruff: noqa: E401,E702,F401,F811,F841
import time
import asyncio
import threading
from typing import Any, Dict, Optional

from config.integrated_config import get_settings
from core.utils.logger import get_module_logger
from core.utils.config_accessor import get_active_care_config
from core.utils.async_locks import LazyAsyncLock

# 拆分出的子模块
from core.services.active_care.core.proactive_loop import ProactiveLoopRunner
from core.services.active_care.core.user_response_handler import UserResponseHandler
from core.services.active_care.scheduling.delayed_task_handler import DelayedTaskHandler
from core.services.active_care.core.watchdog import WatchdogManager
from core.services.active_care.core.startup_handler import StartupHandler

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")

_active_care_service = None
_active_care_service_lock = threading.Lock()


class ActiveCareService:
    """
    Active Care 服务主类

    功能：
    - 主动关怀调度
    - 延迟任务跟进
    - 睡眠模式管理
    - 用户交互响应

    配置：
    - enable_proactive_checker: 是否启用主动关怀检查器（默认 False）

    作为门面层，将具体逻辑委托给子模块：
    - ProactiveLoopRunner: 主循环调度
    - UserResponseHandler: 用户响应处理
    - DelayedTaskHandler: 延迟任务处理
    - WatchdogManager: 看门狗与维护
    - StartupHandler: 启动推断
    """

    def __init__(self, enable_proactive_checker: bool = False):
        self._running = False
        self.settings = get_settings()
        self._enable_proactive_checker = enable_proactive_checker

        # 延迟初始化的组件
        self._storage = None
        self._context = None
        self._scheduler_logic = None
        self._decision = None
        self._executor = None
        self._vocab = None
        self._state_manager = None
        self._delayed_scheduler = None
        self._emotion_manager = None
        self._life_sim_service = None
        self._health_checker = None
        self._bert_analyzer = None

        # 可选：主动关怀检查器
        self.checker: Optional[Any] = None
        if self._enable_proactive_checker:
            from core.services.active_care.core.proactive_checker import ProactiveChecker
            from core.services.active_care.storage.user_profile_service import UserProfileService
            # 创建用户画像服务（独立于状态追踪）
            self._user_profile_service = UserProfileService(self.storage)
            self.checker = ProactiveChecker(
                storage=self.storage,
                context=self.context,
                scheduler_logic=self.scheduler_logic,
                decision=self.decision,
                executor=self.executor,
                user_profile_service=self._user_profile_service,
            )
            logger.info("Active Care: 主动关怀检查器已启用")
        else:
            self._user_profile_service = None
            logger.info("Active Care: 主动关怀检查器未启用")

        # 双角色互聊独立调度器（延迟初始化，在 initialize() 中启动）
        self._peer_chat_scheduler = None
        try:
            from core.services.active_care.peer_chat.peer_chat_scheduler import init_peer_chat_scheduler
            self._peer_chat_scheduler = init_peer_chat_scheduler(
                storage=self.storage,
                context=self.context,
                decision=self.decision,
                executor=self.executor,
                settings=self.settings,
            )
            logger.info("Active Care: PeerChatScheduler 已初始化")
        except Exception as e:
            logger.warning("Active Care: PeerChatScheduler 初始化失败: %s", e)

        # 运行时状态
        self._proactive_task: Optional[asyncio.Task] = None
        self._startup_task: Optional[asyncio.Task] = None
        self._maintenance_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._proactive_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._wakeup_event = asyncio.Event()
        self._event_bus = None
        self._device_context_subscription_handler = None
        self._health_checker_registered = False
        # P1-2: 跟踪 fire-and-forget 延迟初始化任务，防止被 GC 后失败被静默吞掉
        self._pending_init_tasks: set = set()

        self._latest_device_context: Dict[str, Any] = {}
        self._last_schedule_log_ts = 0.0
        self._last_loop_iteration_ts: float = 0.0
        self._last_sleep_started_ts: float = 0.0
        self._last_sleep_seconds: float = 0.0
        self._expected_wakeup_ts: float = 0.0
        self._loop_phase = "init"
        self._loop_phase_started_ts: float = 0.0
        self._loop_restart_count: int = 0

        self._last_processed_user_msg_signatures: Dict[str, str] = {}
        self.last_intent = "none"

        # 初始化子模块
        self._loop_runner = ProactiveLoopRunner(self)
        self._user_response_handler = UserResponseHandler(self)
        self._delayed_task_handler = DelayedTaskHandler(self)
        self._watchdog_manager = WatchdogManager(self)
        self._startup_handler = StartupHandler(self)

    def _set_loop_phase(self, phase: str):
        self._loop_phase = phase
        self._loop_phase_started_ts = time.time()

    @property
    def storage(self):
        if self._storage is None:
            from core.services.active_care.storage.storage import ActiveCareStorage
            self._storage = ActiveCareStorage()
        return self._storage

    @property
    def context(self):
        if self._context is None:
            from core.services.active_care.core.context import ActiveCareContext
            self._context = ActiveCareContext(self.storage)
        return self._context

    @property
    def scheduler_logic(self):
        if self._scheduler_logic is None:
            from core.services.active_care.scheduling.scheduler_logic import ActiveCareSchedulerLogic
            self._scheduler_logic = ActiveCareSchedulerLogic()
        return self._scheduler_logic

    @property
    def decision(self):
        if self._decision is None:
            from core.services.active_care.decision.decision import ActiveCareDecision
            self._decision = ActiveCareDecision(self.storage)
        return self._decision

    @property
    def executor(self):
        if self._executor is None:
            from core.services.active_care.core.executor import ActiveCareExecutor
            self._executor = ActiveCareExecutor(self.context, self.storage)
        return self._executor

    @property
    def vocab(self):
        if self._vocab is None:
            from core.services.active_care.shared.vocabulary import ActiveCareVocabulary
            self._vocab = ActiveCareVocabulary(self.storage)
        return self._vocab

    @property
    def state_manager(self):
        if self._state_manager is None:
            from core.services.active_care.state import get_state_manager
            self._state_manager = get_state_manager()
        return self._state_manager

    @property
    def delayed_scheduler(self):
        if self._delayed_scheduler is None:
            from core.services.active_care.scheduling.delayed_scheduler import get_delayed_scheduler
            self._delayed_scheduler = get_delayed_scheduler()
        return self._delayed_scheduler

    @property
    def emotion_manager(self):
        if self._emotion_manager is None:
            from core.emotion import get_emotion_manager
            self._emotion_manager = get_emotion_manager()
        return self._emotion_manager

    @property
    def life_sim_service(self):
        if self._life_sim_service is None:
            from core.services.life_simulation.service import get_life_simulation_service
            self._life_sim_service = get_life_simulation_service()
        return self._life_sim_service

    @property
    def health_checker(self):
        if self._health_checker is None:
            from core.async_monitor import get_health_checker
            self._health_checker = get_health_checker()
        return self._health_checker

    @property
    def bert_analyzer(self):
        if self._bert_analyzer is None:
            from core.services.data_ops.bert_analyzer import get_bert_analyzer
            self._bert_analyzer = get_bert_analyzer()
        return self._bert_analyzer

    @property
    def peer_chat_scheduler(self):
        """双角色互聊独立调度器（可能为 None）"""
        return self._peer_chat_scheduler

    @property
    def consecutive_non_responses(self) -> int:
        """返回所有 persona 中最大的非响应计数（向后兼容）"""
        if isinstance(self.executor.consecutive_non_responses, dict):
            return max(self.executor.consecutive_non_responses.values()) if self.executor.consecutive_non_responses else 0
        return int(self.executor.consecutive_non_responses or 0)

    @consecutive_non_responses.setter
    def consecutive_non_responses(self, value):
        """设置非响应计数（初始化时使用，设置为所有 persona 的默认值）"""
        if isinstance(self.executor.consecutive_non_responses, dict):
            # 初始化时填充所有已知 persona
            for key in list(self.executor.consecutive_non_responses.keys()):
                self.executor.consecutive_non_responses[key] = int(value or 0)
            if "" not in self.executor.consecutive_non_responses:
                self.executor.consecutive_non_responses[""] = int(value or 0)
        else:
            self.executor.consecutive_non_responses = value

    # ==================== 生命周期 ====================

    async def initialize(self):
        """初始化并启动 Active Care 调度器"""
        logger.info("Initializing ActiveCareService...")
        self._running = True

        await self.storage.load_policy_scores()

        state_data = await self.storage.get_proactive_state()
        persisted_non_responses = state_data.get("consecutive_non_responses", 0)
        # 兼容旧格式（int）和新格式（dict per-persona）
        if isinstance(persisted_non_responses, dict):
            self.executor.consecutive_non_responses = {
                str(k): int(v or 0) for k, v in persisted_non_responses.items()
            }
        else:
            self.consecutive_non_responses = int(persisted_non_responses or 0)

        if self.checker:
            await self.checker.initialize()

        self.delayed_scheduler.set_callback(self._on_delayed_task_trigger)
        await self.delayed_scheduler.start()

        await self._setup_event_subscriptions()
        self._register_health_checker()

        if self._proactive_task is None or self._proactive_task.done():
            self._proactive_task = asyncio.create_task(self._proactive_loop())
            if self._startup_task is None or self._startup_task.done():
                self._startup_task = asyncio.create_task(self._startup_check())

        if self._maintenance_task is None or self._maintenance_task.done():
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())

        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        # 启动双角色互聊独立调度器
        if self._peer_chat_scheduler:
            try:
                self._peer_chat_scheduler.start()
                logger.info("Active Care: PeerChatScheduler 已启动")
            except Exception as e:
                logger.warning("Active Care: PeerChatScheduler 启动失败: %s", e)

        # 启动角色日常引擎（CharacterDailyEngine）
        # 如果启用，它会接管 peer chat 的调度
        self._character_daily_engine = None
        try:
            from core.services.character_daily.engine import (
                init_character_daily_engine,
            )
            self._character_daily_engine = init_character_daily_engine()
            # 注入 PeerChatScheduler，让 CharacterDailyEngine 可以复用其管线
            if self._peer_chat_scheduler:
                self._character_daily_engine.set_peer_chat_scheduler(
                    self._peer_chat_scheduler
                )
            self._character_daily_engine.start()
            logger.info("Active Care: CharacterDailyEngine 已启动")
        except Exception as e:
            logger.warning("Active Care: CharacterDailyEngine 启动失败: %s", e)

        logger.info("ActiveCareService initialized.")

    async def _setup_event_subscriptions(self):
        """设置事件订阅"""
        if self._device_context_subscription_handler is not None:
            return

        try:
            from core.core_engine.event_bus import get_event_bus
            self._event_bus = get_event_bus()

            async def _on_device_context_updated(context: Optional[Dict[str, Any]] = None, **kwargs):
                if not self._running:
                    return
                if context:
                    self._latest_device_context = context
                self._wakeup_event.set()

            self._device_context_subscription_handler = _on_device_context_updated
            await self._event_bus.subscribe(
                "device.context_updated",
                self._device_context_subscription_handler,
            )
        except Exception as e:
            logger.warning(f"Active Care: 订阅设备上下文事件失败: {e}")

    def _register_health_checker(self):
        """注册健康检查"""
        if self._health_checker_registered:
            return

        async def _health_check():
            now = time.time()
            next_decision_in = 0
            if self.checker:
                next_decision_in = max(0, int(self.checker.next_decision_ts - now))

            proactive_alive = bool(self._proactive_task and not self._proactive_task.done())
            loop_stuck_seconds = 0.0
            if self._last_loop_iteration_ts > 0:
                loop_stuck_seconds = now - self._last_loop_iteration_ts

            is_healthy = self._running and proactive_alive
            sleep_overdue_seconds = 0.0
            if self._expected_wakeup_ts > 0:
                sleep_overdue_seconds = max(0.0, now - self._expected_wakeup_ts)

            if sleep_overdue_seconds > 300:
                is_healthy = False

            return {
                "status": "healthy" if is_healthy else "unhealthy",
                "details": {
                    "running": self._running,
                    "proactive_task_alive": proactive_alive,
                    "loop_stuck_seconds": int(loop_stuck_seconds),
                    "sleep_overdue_seconds": int(sleep_overdue_seconds),
                    "expected_wakeup_in_seconds": int(
                        self._expected_wakeup_ts - now
                    ) if self._expected_wakeup_ts > 0 else 0,
                    "loop_phase": self._loop_phase,
                    "loop_phase_seconds": int(now - self._loop_phase_started_ts)
                    if self._loop_phase_started_ts > 0 else 0,
                    "loop_restart_count": self._loop_restart_count,
                    "lock_locked": self._proactive_lock.locked(),
                    "next_llm_decision_in_seconds": next_decision_in,
                    "checker_enabled": bool(self.checker),
                },
            }

        self.health_checker.register_health_checker(
            "active_care_service", _health_check, interval=60.0
        )
        self._health_checker_registered = True

    async def shutdown(self):
        """停止调度器"""
        if not self._running:
            return

        logger.info("Shutting down ActiveCareService...")
        self._running = False

        self._wakeup_event.set()
        if self._event_bus and self._device_context_subscription_handler:
            try:
                await self._event_bus.unsubscribe(
                    "device.context_updated",
                    self._device_context_subscription_handler,
                )
            except Exception:
                pass

        tasks = [t for t in [
            self._startup_task, self._proactive_task,
            self._maintenance_task, self._watchdog_task
        ] if t is not None]

        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # 停止双角色互聊调度器
        if self._peer_chat_scheduler:
            try:
                await self._peer_chat_scheduler.stop()
            except Exception as e:
                logger.warning("Active Care: PeerChatScheduler 停止异常: %s", e)

        # 停止角色日常引擎
        if hasattr(self, "_character_daily_engine") and self._character_daily_engine:
            try:
                await self._character_daily_engine.stop()
            except Exception as e:
                logger.warning("Active Care: CharacterDailyEngine 停止异常: %s", e)

        await self.delayed_scheduler.stop()
        logger.info("ActiveCareService shutdown complete.")

    # ==================== 外部接口 ====================

    async def check_active_care(self, is_startup: bool = False):
        """手动触发 Active Care 检查"""
        if not self.checker:
            logger.warning("Active Care: 主动关怀检查器未启用")
            return

        lock_acquired = False
        try:
            try:
                await asyncio.wait_for(self._proactive_lock.acquire(), timeout=120.0)
                lock_acquired = True
            except asyncio.TimeoutError:
                logger.error("Active Care: 手动触发获取锁超时(120s)，可能主循环持有锁未释放")
                return
            try:
                await asyncio.wait_for(
                    self.checker.perform_check(is_startup=is_startup), timeout=120.0
                )
            except asyncio.TimeoutError:
                logger.error("Active Care: 手动触发 perform_check 超时(120s)")
            finally:
                if lock_acquired:
                    self._proactive_lock.release()
        except asyncio.CancelledError:
            if lock_acquired:
                try:
                    self._proactive_lock.release()
                except RuntimeError:
                    pass
            raise
        except Exception as e:
            logger.error(f"Active Care manual check error: {e}", exc_info=True)

    def get_runtime_status(self) -> Dict[str, Any]:
        """获取运行时状态"""
        now = time.time()
        next_decision_in = 0
        last_skip_reason = "none"
        last_check_phase = "none"
        if self.checker:
            next_decision_in = max(0, int(self.checker.next_decision_ts - now))
            last_skip_reason = str(self.checker.last_skip_reason or "none")
            last_check_phase = str(self.checker.last_check_phase or "none")

        pending_tasks_count = 0
        try:
            pending_tasks_count = len(self.delayed_scheduler.get_pending_tasks() or [])
        except Exception:
            pass

        loop_stuck_seconds = 0.0
        if self._last_loop_iteration_ts > 0:
            loop_stuck_seconds = now - self._last_loop_iteration_ts

        return {
            "running": self._running,
            "checker_enabled": bool(self.checker),
            "enable_proactive_checker": self._enable_proactive_checker,
            "tasks": {
                "proactive": bool(self._proactive_task and not self._proactive_task.done()),
                "startup": bool(self._startup_task and not self._startup_task.done()),
                "maintenance": bool(self._maintenance_task and not self._maintenance_task.done()),
                "watchdog": bool(self._watchdog_task and not self._watchdog_task.done()),
            },
            "next_decision_in_seconds": next_decision_in,
            "last_intent": self.checker.last_intent if self.checker else self.last_intent,
            "last_skip_reason": last_skip_reason,
            "last_check_phase": last_check_phase,
            "consecutive_non_responses": self.consecutive_non_responses,
            "delayed_tasks_pending": pending_tasks_count,
            "lock_locked": self._proactive_lock.locked(),
            "loop_stuck_seconds": int(loop_stuck_seconds),
            "sleep_overdue_seconds": int(max(0.0, now - self._expected_wakeup_ts))
            if self._expected_wakeup_ts > 0
            else 0,
            "expected_wakeup_in_seconds": int(self._expected_wakeup_ts - now)
            if self._expected_wakeup_ts > 0
            else 0,
            "loop_phase": self._loop_phase,
            "loop_phase_seconds": int(now - self._loop_phase_started_ts)
            if self._loop_phase_started_ts > 0
            else 0,
            "loop_restart_count": self._loop_restart_count,
        }

    async def on_user_interaction(self, persona_filename: str = ""):
        """用户交互时调用（外部接口）

        Args:
            persona_filename: 人设文件名，双QQ模式下只更新对应 persona 的状态
        """
        if not self._running:
            return

        try:
            await self._reset_interaction_state(persona_filename=persona_filename)
        except Exception as e:
            logger.error(f"Active Care on_user_interaction error: {e}")

    async def notify_workspace_reminder_updated(
        self,
        *,
        trigger_ts: float | None = None,
    ) -> None:
        """工作空间提醒更新后，唤醒主循环重新计算最近检查时间。"""
        if not self._running:
            return

        try:
            now = time.time()
            target_ts = float(trigger_ts or 0.0)
            if self.checker:
                if target_ts > now:
                    await self.checker.set_next_decision_ts(
                        target_ts,
                        source="workspace_reminder_updated",
                    )
                else:
                    await self.checker.set_next_decision_ts(
                        now + 1.0,
                        source="workspace_reminder_due_now",
                    )
            self._wakeup_event.set()
        except Exception as e:
            logger.warning("Active Care: reminder 更新唤醒失败: %s", e)

    async def notify_workspace_plan_updated(
        self,
        *,
        first_trigger_ts: float | None = None,
    ) -> None:
        """兼容旧调用方：计划更新后唤醒主动关怀循环。"""
        await self.notify_workspace_reminder_updated(trigger_ts=first_trigger_ts)

    async def set_sleep_mode(
        self, active: bool, reason: str = "user_request", delay_next_check_seconds: int = 7200
    ) -> bool:
        """设置/取消睡眠模式"""
        try:
            now = time.time()
            try:
                before_state = await self.storage.get_proactive_state()
            except Exception:
                before_state = {}

            if active:
                await self.state_manager.sleep.enter_low_disturbance_mode(
                    started_ts=now,
                    source="user_message",
                )
                if self.checker:
                    await self.checker.set_next_decision_ts(
                        now + delay_next_check_seconds, source="set_sleep_mode"
                    )
            else:
                await self.state_manager.sleep.exit_low_disturbance_mode(
                    exit_ts=now,
                    source="user_message",
                )
                if self.checker:
                    # 退出睡眠模式后尽快恢复主动关怀检查，避免继续卡在旧的长延迟。
                    await self.checker.set_next_decision_ts(
                        now + 1.0, source="clear_sleep_mode"
                    )

            try:
                after_state = await self.storage.get_proactive_state()
            except Exception:
                after_state = {}

            return True
        except Exception as e:
            logger.error(f"Active Care: set_sleep_mode 失败: {e}")
            return False

    async def pause(self, duration_seconds: int = 3600) -> bool:
        """暂停 Active Care"""
        try:
            if self.checker:
                await self.checker.set_next_decision_ts(
                    time.time() + duration_seconds, source="user_pause"
                )
            return True
        except Exception as e:
            logger.error(f"Active Care: pause 失败: {e}")
            return False

    async def on_mode_switch(self, new_mode: str, old_mode: str):
        """模式切换回调"""
        logger.info(f"Active Care: Mode switch {old_mode} -> {new_mode}")

    async def on_assistant_message_sent(self, timestamp: float = 0.0, persona_filename: str = ""):
        """聊天系统发送消息后通知主动关怀系统，避免短时间内重复发送

        双QQ模式下：
        - 当前 persona 推迟 min_gap_seconds
        - 其他 persona 仅推迟 2~5 分钟短间隔错开（不再完全同步）

        Args:
            timestamp: 消息发送时间戳
            persona_filename: 发送消息的人设文件名，双QQ模式下只更新对应 persona 的时间戳
        """
        import random as _random
        now = time.time()
        effective_ts = timestamp if timestamp > 0 else now

        min_gap_seconds = int(
            get_active_care_config(
                "active_care_min_gap_seconds", default=600, settings=self.settings
            )
            or 600
        )

        if self.executor and hasattr(self.executor, "_last_trigger_ts_by_persona"):
            if persona_filename:
                scope = self.storage.resolve_scope_from_persona_filename(persona_filename)
                persona_key = scope if scope else ""
                old_ts = self.executor._last_trigger_ts_by_persona.get(persona_key, 0.0)
                self.executor._last_trigger_ts_by_persona[persona_key] = effective_ts
                self.executor._last_trigger_ts_by_persona[""] = effective_ts
                logger.info(
                    "Active Care: on_assistant_message_sent 更新 _last_trigger_ts_by_persona[%s] %.0f -> %.0f",
                    persona_key, old_ts, effective_ts,
                )
            else:
                old_ts = min(self.executor._last_trigger_ts_by_persona.values()) if self.executor._last_trigger_ts_by_persona else 0.0
                for key in list(self.executor._last_trigger_ts_by_persona.keys()):
                    self.executor._last_trigger_ts_by_persona[key] = effective_ts
                logger.info(
                    "Active Care: on_assistant_message_sent 更新所有 _last_trigger_ts_by_persona %.0f -> %.0f",
                    old_ts, effective_ts,
                )

        if self.checker:
            next_allowed_ts = effective_ts + min_gap_seconds
            if persona_filename:
                # 当前 persona：正常推迟
                persona_next_ts = self.checker.get_next_decision_ts_for_persona(persona_filename)
                if next_allowed_ts > persona_next_ts:
                    await self.checker.set_next_decision_ts(
                        next_allowed_ts, source="assistant_message_sent",
                        persona_filename=persona_filename,
                    )
                    logger.info(
                        "Active Care: on_assistant_message_sent 更新 persona=%s next_decision_ts -> %.0f (min_gap=%ds)",
                        persona_filename, next_allowed_ts, min_gap_seconds,
                    )

                # 跨persona协调：短间隔错开而非完全同步
                # 其他 persona 只需等 2~5 分钟，保证不撞车但可以各自独立发送
                stagger_delay = _random.randint(120, 300)
                stagger_ts = now + stagger_delay
                other_personas = self.checker.get_all_persona_keys()
                current_scope = self.storage.resolve_scope_from_persona_filename(persona_filename)
                for other_key in other_personas:
                    if other_key == current_scope:
                        continue
                    other_next_ts = self.checker._next_decision_ts_by_persona.get(other_key, 0.0)
                    if stagger_ts > other_next_ts:
                        self.checker._next_decision_ts_by_persona[other_key] = stagger_ts
                        self.checker._next_llm_decision_ts_by_persona[other_key] = stagger_ts
                        logger.info(
                            "Active Care: on_assistant_message_sent 跨persona错开，%s next_decision_ts -> %.0f (stagger=%ds)",
                            other_key, stagger_ts, stagger_delay,
                        )
                # 更新全局最早时间戳
                earliest_ts = self.checker._get_earliest_next_decision_ts()
                self.checker.next_decision_ts = earliest_ts
                self.checker._next_llm_decision_ts = earliest_ts
            else:
                current_next = self.checker.next_decision_ts
                if next_allowed_ts > current_next:
                    await self.checker.set_next_decision_ts(
                        next_allowed_ts, source="assistant_message_sent"
                    )
                    logger.info(
                        "Active Care: on_assistant_message_sent 更新 next_decision_ts -> %.0f (min_gap=%ds)",
                        next_allowed_ts, min_gap_seconds,
                    )

        try:
            # per-persona 保存 last_sent_ts/last_attempt_ts
            scope = None
            if persona_filename:
                scope = self.storage.resolve_scope_from_persona_filename(persona_filename)
            await self.storage.save_proactive_state({
                "last_sent_ts": effective_ts,
                "last_attempt_ts": effective_ts,
            }, scope=scope)
            # 双QQ模式下也更新全局存档（向后兼容）
            if scope:
                await self.storage.save_proactive_state({
                    "last_sent_ts": effective_ts,
                    "last_attempt_ts": effective_ts,
                })
        except Exception as e:
            logger.warning(f"Active Care: on_assistant_message_sent 保存状态失败: {e}")

    # ==================== 委托给子模块的方法 ====================

    async def _on_delayed_task_trigger(
        self, task_id: str, task_type: str, context: Dict[str, Any],
        source_message: str, action_hint: str,
    ):
        """延迟任务触发回调（委托给 DelayedTaskHandler）"""
        await self._delayed_task_handler.on_delayed_task_trigger(
            task_id, task_type, context, source_message, action_hint
        )

    def _resolve_delayed_task_action(
        self, task_type: str, context: Dict[str, Any], action_hint: str,
    ) -> tuple:
        """解析延迟任务动作（委托给 DelayedTaskHandler）"""
        return self._delayed_task_handler.resolve_delayed_task_action(
            task_type, context, action_hint
        )

    async def _startup_check(self):
        """启动时检查（委托给 StartupHandler）"""
        await self._startup_handler.run_startup_check()

    async def _proactive_loop(self):
        """主动关怀主循环（委托给 ProactiveLoopRunner）"""
        await self._loop_runner.run_proactive_loop()

    async def _process_user_response(self):
        """处理用户响应（委托给 UserResponseHandler）"""
        await self._user_response_handler.process_user_response()

    async def _reset_interaction_state(self, interaction_ts: float = 0.0, persona_filename: str = ""):
        """重置交互状态（委托给 UserResponseHandler）"""
        await self._user_response_handler.reset_interaction_state(interaction_ts, persona_filename=persona_filename)

    async def _maintenance_loop(self):
        """维护循环（委托给 WatchdogManager）"""
        await self._watchdog_manager.run_maintenance_loop()

    async def _watchdog_loop(self):
        """看门狗循环（委托给 WatchdogManager）"""
        await self._watchdog_manager.run_watchdog_loop()


def get_active_care_service(enable_proactive_checker: bool = False):
    """获取 Active Care 服务单例

    如果单例已存在但 enable_proactive_checker 不匹配，会升级单例
    （处理被其他模块提前无参调用导致的竞态条件）

    使用 threading.Lock 保护，避免并发调用导致创建多个实例
    （参考 get_auto_heal_service 的实现方式）
    """
    global _active_care_service
    with _active_care_service_lock:
        if _active_care_service is None:
            _active_care_service = ActiveCareService(enable_proactive_checker=enable_proactive_checker)
        elif enable_proactive_checker and not _active_care_service._enable_proactive_checker:
            if _active_care_service.checker is not None:
                logger.info("Active Care: ProactiveChecker 已存在，跳过升级")
                return _active_care_service
            logger.warning(
                "Active Care: 单例已存在但 checker 未启用，正在升级 (enable_proactive_checker=%s)",
                enable_proactive_checker,
            )
            _active_care_service._enable_proactive_checker = True
            from core.services.active_care.core.proactive_checker import ProactiveChecker
            _active_care_service.checker = ProactiveChecker(
                storage=_active_care_service.storage,
                context=_active_care_service.context,
                scheduler_logic=_active_care_service.scheduler_logic,
                decision=_active_care_service.decision,
                executor=_active_care_service.executor,
            )
            if _active_care_service._running:
                try:
                    asyncio.get_running_loop()
                    # P1-2: 保存任务引用，避免被 GC 后延迟初始化静默失败
                    _task = asyncio.ensure_future(_active_care_service.checker.initialize())
                    _active_care_service._pending_init_tasks.add(_task)

                    def _on_done(t: asyncio.Task) -> None:
                        _active_care_service._pending_init_tasks.discard(t)
                        if t.cancelled():
                            return
                        exc = t.exception()
                        if exc is not None:
                            logger.error(
                                "Active Care: ProactiveChecker 延迟初始化失败: %r",
                                exc, exc_info=exc,
                            )

                    _task.add_done_callback(_on_done)
                    logger.info("Active Care: ProactiveChecker 已延迟初始化（升级模式）")
                except RuntimeError:
                    logger.warning("Active Care: ProactiveChecker 升级初始化失败（无事件循环）")
            else:
                logger.info("Active Care: ProactiveChecker 已创建，将在 initialize() 时初始化")

            # 升级时也初始化 PeerChatScheduler（如果尚未初始化）
            if _active_care_service._peer_chat_scheduler is None:
                try:
                    from core.services.active_care.peer_chat.peer_chat_scheduler import init_peer_chat_scheduler
                    _active_care_service._peer_chat_scheduler = init_peer_chat_scheduler(
                        storage=_active_care_service.storage,
                        context=_active_care_service.context,
                        decision=_active_care_service.decision,
                        executor=_active_care_service.executor,
                        settings=_active_care_service.settings,
                    )
                    if _active_care_service._running:
                        _active_care_service._peer_chat_scheduler.start()
                        logger.info("Active Care: PeerChatScheduler 已延迟初始化并启动")
                except Exception as e:
                    logger.warning("Active Care: PeerChatScheduler 升级初始化失败: %s", e)

    return _active_care_service
