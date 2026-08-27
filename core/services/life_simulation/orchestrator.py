"""生命模拟总协调器（LifeOrchestrator）。

从 LifeSimulationService 中提取的主循环协调逻辑，负责：
- 每秒 tick：硬件采集、消化、健康检查、情绪影响、状态广播
- 每分钟 tick：角色状态衰减、过期食物清理、自动进食、每日总结
- 事件检查：仪式触发、自发反应

LifeSimulationService 作为门面保留全部外部 API，将协调职责委托给本类。
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from config.debug_config import is_debug_enabled
from config.integrated_config import get_settings
from core.services.monitoring.hardware_monitor import HardwareMonitor
from core.services.reaction.reaction_manager import ReactionManager
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, get_diary_target_date_str, now_str

from .coordinators import (
    ActorCoordinator,
    FoodCoordinator,
    HardwareCoordinator,
    ReactionCoordinator,
    SleepCoordinator,
    WebSocketCoordinator,
)
from .health_monitor import HealthMonitor
from .life_stats import LifeStatsManager, get_cpp_engine
from .ritual_manager import RitualManager
from .actor_manager import ActorManager
from .food_system import FoodSystem
from .auto_eat import AutoEatManager
from .service_state_helpers import (
    build_bio_stats,
    derive_activity_and_mood,
    get_vision_summary,
    read_active_care_sleep_state,
)
from .sleep_manager import get_sleep_manager

logger = get_logger("LIFE_SIMULATION")

# 活动时间范围常量
_ACTIVITY_TIME_RANGES = [
    (0, 6, "sleeping"),
    (6, 9, "waking_up"),
    (9, 18, "working"),
    (18, 23, "relaxing"),
    (23, 24, "preparing_sleep"),
]

# 硬件阈值常量
_HIGH_CPU_TEMP_WORKING = 60
_OVERHEAT_CPU_TEMP = 75
_LOW_BATTERY = 20
_LOW_ENERGY = 20
_LOW_HUNGER = 30
_LOW_THIRST = 30
_HIGH_MOOD_SCORE = 90
_GOOD_PHYSICAL_SCORE = 80
_PRIMARY_SLEEP_ROLE_ID = "aveline"


class LifeOrchestrator:
    """生命模拟总协调器。

    负责：
    1. 初始化和管理所有子模块及协调器
    2. 运行主监控循环（_monitor_loop）
    3. 每分钟定时任务（_process_minute_tick）
    4. 情绪影响应用
    5. 每日总结协调
    6. 状态聚合（build_state）

    外部通过 LifeSimulationService 门面间接访问，不直接实例化。
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.life_config = self.settings.life_simulation

        # ── 核心子模块 ──
        self.hardware_monitor = HardwareMonitor()
        self.reaction_manager = ReactionManager(self.life_config)

        self.life_stats_manager = LifeStatsManager(self.life_config)
        self.life_stats = self.life_stats_manager.get_life_stats()

        self.status: Dict[str, Any] = self.hardware_monitor.get_stats()
        self.status.update(
            {"mood": "calm", "activity": "idle", "life": self.life_stats}
        )

        self.actor_manager = ActorManager()
        self.food_system = FoodSystem(self.life_stats, self.status)
        self.health_monitor = HealthMonitor(
            self.life_stats, self.life_config, self.status
        )
        self.auto_eat_manager = AutoEatManager(self.life_stats, self.actor_manager)
        self.sleep_manager = get_sleep_manager()
        self.ritual_manager = RitualManager()

        # ── 专职协调器 ──
        self.hardware_coordinator = HardwareCoordinator(self.hardware_monitor)
        self.actor_coordinator = ActorCoordinator(self.actor_manager)
        self.food_coordinator = FoodCoordinator(self.food_system, self.auto_eat_manager)
        self.sleep_coordinator = SleepCoordinator(self.sleep_manager)
        self.reaction_coordinator = ReactionCoordinator(
            self.ritual_manager, self.reaction_manager
        )
        self.websocket_coordinator = WebSocketCoordinator()

        # ── 运行时状态 ──
        self.last_update = time.time()
        self._monitor_task: Optional[asyncio.Task] = None
        self.last_interaction_time = time.time()
        self._consecutive_errors = 0

        self.active_minutes_today = 0
        self.last_minute_check = time.time()
        self._active_minutes_date = now_str("%Y-%m-%d")

        # 按 persona 记录已生成的每日总结日期，确保 Aveline 与Ling都分别生成日记
        self._last_daily_summary_date: Dict[str, str] = {}
        self._daily_summary_task: Optional[asyncio.Task] = None

    # ==================== 生命周期 ====================

    async def start(self):
        """启动监控任务。"""
        await self.start_monitor()

    async def stop(self):
        """停止监控任务。"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("Life Simulation service stopped")

    async def start_monitor(self):
        """启动监控循环。"""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Life Simulation monitor task started")

    @property
    def is_running(self) -> bool:
        return self._monitor_task is not None and not self._monitor_task.done()

    # ==================== 主监控循环 ====================

    async def _monitor_loop(self):
        """每秒执行的监控循环。"""
        ws_manager = self.websocket_coordinator.ws_manager
        logger.info(
            "Life Simulation monitor loop started. "
            f"WebSocket Manager: {id(ws_manager)}"
        )

        while True:
            try:
                self.food_coordinator.tick_digestion()
                await self.health_monitor.maybe_poll_health()
                state = self.build_state()

                await self._apply_emotion_influence(state)

                now = time.time()
                if now - self.last_minute_check >= 60:
                    await self._process_minute_tick(state, now)

                await self.websocket_coordinator.broadcast_state(state)

                ritual = self.reaction_coordinator.check_rituals(
                    self.active_minutes_today
                )
                if ritual:
                    if is_debug_enabled("life_simulation"):
                        logger.info(f"Triggering ritual: {ritual}")
                    await self.websocket_coordinator.broadcast_ritual(ritual)

                reaction = await self.reaction_coordinator.check_spontaneous_reaction(
                    state, self.last_interaction_time
                )

                if reaction:
                    if is_debug_enabled("life_simulation"):
                        logger.info(f"Triggering spontaneous reaction: {reaction}")
                    await self.websocket_coordinator.broadcast_reaction(reaction)
                    self.reaction_coordinator.record_reaction()

                self._consecutive_errors = 0

            except Exception as e:
                self._consecutive_errors += 1
                backoff = min(1.0 * (2 ** min(self._consecutive_errors - 1, 5)), 30.0)
                logger.error(
                    f"Error in life simulation monitor (连续第{self._consecutive_errors}次, "
                    f"退避{backoff:.1f}s): {e}",
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(1)

    # ==================== 每分钟处理 ====================

    async def _process_minute_tick(self, state: Dict[str, Any], now: float):
        """每分钟执行的衰减与维护任务。"""
        if state["activity"] not in ["sleeping", "idle"]:
            self.active_minutes_today += 1

        sleep_summary = self.sleep_coordinator.get_sleep_summary(
            _PRIMARY_SLEEP_ROLE_ID
        )
        self.life_stats_manager.update_sleep_metrics(sleep_summary)
        self.life_stats_manager.decay_stats(
            str(state.get("activity") or "idle"),
            sleep_summary=sleep_summary,
        )
        self.life_stats_manager.decay_shyness()
        self.life_stats_manager.apply_sickness_penalty()

        self.actor_coordinator.tick_all_actors(
            str(state.get("activity") or "idle")
        )

        try:
            self.food_coordinator.cleanup_expired_food()
        except Exception as e:
            logger.warning(f"清理过期食物失败: {e}")
        try:
            await self.food_coordinator.maybe_auto_eat(now)
        except Exception as e:
            logger.warning(f"自动进食失败: {e}")
        try:
            await self._maybe_generate_daily_summary(get_current_time())
        except Exception as e:
            if is_debug_enabled("life_simulation"):
                logger.info(f"生成每日总结失败: {e}")

        self.last_minute_check = now

        today = now_str("%Y-%m-%d")
        if today != self._active_minutes_date:
            self.active_minutes_today = 0
            self._active_minutes_date = today

    # ==================== 情绪影响 ====================

    async def _apply_emotion_influence(self, state: Dict[str, Any]):
        """应用情绪影响。"""
        try:
            from core.emotion import get_emotion_manager

            mgr = get_emotion_manager()
            life_stats = dict((state or {}).get("life", {}) or {})
            weights = mgr.compute_life_influence_weights(life_stats)
            if weights:
                mgr.apply_global_influence(
                    weights,
                    source="life_simulation_tick",
                    metadata={
                        "mood_score": life_stats.get("mood_score"),
                        "shyness_score": life_stats.get("shyness_score"),
                        "immune_damage": life_stats.get("immune_damage"),
                        "is_sick": life_stats.get("is_sick"),
                    },
                )
        except ImportError:
            pass
        except Exception as e:
            if is_debug_enabled("life_simulation"):
                logger.info(f"应用情绪影响失败: {e}")

    # ==================== 每日总结 ====================

    async def _maybe_generate_daily_summary(self, now_dt: datetime):
        """生成每日总结（仅在睡眠模式下触发，作为 nightly 的兜底）。

        为所有角色（Aveline、Ling等）分别生成日记总结。

        触发前提（必须同时满足）：
        1. 处于睡眠状态（is_sleeping）；
        2. **当前在凌晨窗口（now.hour < 12）**——此时 get_diary_target_date()
           指向"昨天"（已完整结束的一天），可以安全回顾；
        3. 生成目标 date_key 的日记尚不存在（generate_daily_summary force=False
           内部会跳过已存在的，无需重复判断）。

        之所以限定 now.hour < 12：中午之后 get_diary_target_date() 才指向"今天"，
        而今天尚未结束、聊天还在持续发生。若中午后才生成，就会写出
        chat_turn_count=0 的"我没找你"空日记（这正是本 bug 的根因）。
        真正的完整日记由 nightly 在入睡后 1 小时（约 00:00-01:00，此时
        get_diary_target_date() 仍指向昨天）用 force=True 生成并覆盖。

        nightly 已在入睡后运行的前提下，本方法基本是空转兜底：date_key 的
        日记已被 nightly 生成，force=False 会直接跳过，无副作用。
        """
        # 仅在凌晨窗口生成，确保回顾的是"已完整结束的那天"而非"正在进行的今天"
        if now_dt.hour >= 12:
            return

        resolved = await self._resolve_sleep_date_key(now_dt)
        if not resolved:
            return
        date_key = resolved["date_key"]
        if self._daily_summary_task and not self._daily_summary_task.done():
            return

        # 按 (persona, date_key) 去重，一次睡眠周期每个角色只生成一次
        pending = [
            persona
            for persona in ("aveline", "ling")
            if self._last_daily_summary_date.get(persona) != date_key
        ]
        if not pending:
            return

        async def _run():
            try:
                from core.services.journal.service import get_journal_service

                journal_service = get_journal_service()
                for persona in pending:
                    try:
                        await journal_service.generate_daily_summary(
                            date_key, force=False, persona=persona
                        )
                        self._last_daily_summary_date[persona] = date_key
                    except Exception as e:
                        if is_debug_enabled("life_simulation"):
                            logger.info(f"执行 {persona} 每日总结失败: {e}")
            except ImportError:
                pass
            except Exception as e:
                if is_debug_enabled("life_simulation"):
                    logger.info(f"执行每日总结失败: {e}")

        self._daily_summary_task = asyncio.create_task(_run())

    async def _resolve_sleep_date_key(self, now_dt: datetime) -> dict:
        """检测是否在睡眠中，返回应回顾的日记日期。

        日记永远回顾"已过去的那天"，date_key 和 nightly 的 target_date
        用法对齐：用 get_diary_target_date()（凌晨 0-11 点归到前一天）。
        
        之前在此用 goodnight_ts 直接 parse 日期，用户熬夜（凌晨 1-4 点入睡）
        时会生成 date=今天的日记——而今天还没开始，chat_turn_count 必然是 0。

        Returns:
            dict | None: {"date_key": "YYYY-MM-DD"} 或 None（非睡眠状态）。
        """
        try:
            from core.services.active_care.core.service import get_active_care_service

            state = await get_active_care_service().storage.get_proactive_state()
        except ImportError:
            return None
        except Exception as e:
            if is_debug_enabled("life_simulation"):
                logger.info(f"获取睡眠状态失败: {e}")
            return None

        last_goodnight_ts = float(state.get("last_goodnight_ts") or 0.0)
        last_goodmorning_ts = float(state.get("last_goodmorning_ts") or 0.0)
        reduced_mode_active = bool(state.get("reduced_mode_active"))
        reduced_mode_reason = str(state.get("reduced_mode_reason") or "")

        is_sleeping = (
            (last_goodnight_ts > 0 and last_goodmorning_ts < last_goodnight_ts)
            or (reduced_mode_active and reduced_mode_reason == "goodnight")
        )
        if not is_sleeping:
            return None

        # date_key 和 nightly 对齐：回顾"已经过去的那天"，凌晨归到前一天
        return {"date_key": get_diary_target_date_str(now_dt)}

    # ==================== 状态构建 ====================

    def update(self):
        """更新内部硬件状态和活动/情绪推导。"""
        current_time = time.time()
        if current_time - self.last_update < 0.5:
            return

        self.last_update = current_time

        hw_stats = self.hardware_coordinator.get_stats()
        self.status.update(hw_stats)

        self._update_activity_and_mood()

    def _update_activity_and_mood(self):
        """根据时间和硬件状态推导活动和情绪。"""
        hour = get_current_time().hour
        sleep_override = self.sleep_coordinator.get_activity_override(
            _PRIMARY_SLEEP_ROLE_ID
        )
        activity, mood = derive_activity_and_mood(
            hour=hour,
            status=self.status,
            life_stats=self.life_stats,
            activity_time_ranges=_ACTIVITY_TIME_RANGES,
            active_care_sleeping=read_active_care_sleep_state(),
            sleeping_override=str(sleep_override or ""),
            high_cpu_temp_working=_HIGH_CPU_TEMP_WORKING,
            overheat_cpu_temp=_OVERHEAT_CPU_TEMP,
            low_battery=_LOW_BATTERY,
            low_energy=_LOW_ENERGY,
            low_hunger=_LOW_HUNGER,
            low_thirst=_LOW_THIRST,
            high_mood_score=_HIGH_MOOD_SCORE,
            good_physical_score=_GOOD_PHYSICAL_SCORE,
        )
        self.status["activity"] = activity
        self.status["mood"] = mood
        self.life_stats["activity"] = activity
        self.life_stats_manager.update_sleep_metrics(
            self.sleep_coordinator.get_sleep_summary(_PRIMARY_SLEEP_ROLE_ID)
        )
        self.status["life"] = self.life_stats

    def build_state(self) -> Dict[str, Any]:
        """构建完整状态快照（供外部 get_state 调用）。"""
        self.update()

        sleep_summaries = self.sleep_coordinator.get_all_states()
        primary_sleep_summary = sleep_summaries.get(_PRIMARY_SLEEP_ROLE_ID, {})
        self.life_stats_manager.update_sleep_metrics(primary_sleep_summary)
        bio_stats = build_bio_stats(get_cpp_engine())
        if primary_sleep_summary:
            bio_stats["role_sleep"] = primary_sleep_summary
        self.life_stats_manager.calculate_bionic_health()
        immune_status = self.health_monitor.get_immune_status()

        return {
            "timestamp": get_current_time().isoformat(),
            "cpu_temp": round(self.status.get("cpu_temp", 0), 1),
            "ram_usage": round(self.status.get("ram_usage", 0), 1),
            "battery": round(self.status.get("battery", 0), 1),
            "network_latency": self.status.get("network_latency", 0),
            "mood": self.status.get("mood", "unknown"),
            "activity": self.status.get("activity", "unknown"),
            "vision_summary": get_vision_summary(get_current_time().hour),
            "is_running": self.is_running,
            "life": self.life_stats,
            "bio": bio_stats,
            "immune": immune_status,
            "role_sleep_states": sleep_summaries,
            "actor_life_states": self.actor_coordinator.get_all_actor_states(),
            "actor_relationships": self.actor_coordinator.get_all_relationships(),
        }
