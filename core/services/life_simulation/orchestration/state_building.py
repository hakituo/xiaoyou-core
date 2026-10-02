"""生命模拟的状态构建职责（从 orchestrator.py 拆出）。

负责把硬件、生命统计、睡眠、角色计划聚合成对外状态快照：
- ``update`` / ``_update_activity_and_mood``：活动与情绪推导
- ``_resolve_planned_activity``：向 character_daily 问「角色现在在做什么」
- ``_resolve_primary_role_id`` / ``_known_role_ids``：主角色与可用角色解析
- ``build_state``：对外状态快照
"""

from __future__ import annotations

import time
from typing import Any

from core.utils.time_utils import get_current_time

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

from ..life_stats import get_cpp_engine
from ..service_state_helpers import (
    build_bio_stats,
    derive_activity_and_mood,
    get_vision_summary,
    read_active_care_sleep_state,
)

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

# 主角色 ID：用于生命统计与 bio 展示（status["activity"]、role_sleep 等）。
# 优先从配置读取，否则取运行时已知角色的第一个，最后才回退到这个常量。
# 2026-09-03：不再直接硬编码使用，改经 _resolve_primary_role_id() 解析，
# 避免角色增减或改名时静默失效。
_FALLBACK_PRIMARY_ROLE_ID = "aveline"


class LifeStateMixin:
    """状态聚合相关方法集合（配合 LifeOrchestrator 使用）。"""

    def update(self) -> None:
        """更新内部硬件状态和活动/情绪推导。"""
        current_time = time.time()
        if current_time - self.last_update < 0.5:
            return

        self.last_update = current_time

        hw_stats = self.hardware_coordinator.get_stats()
        self.status.update(hw_stats)
        self._update_activity_and_mood()

    @staticmethod
    def _resolve_planned_activity(role_id: str) -> str:
        """从 character_daily 取角色当前活动，作为活动的唯一真相源。

        历史问题：本模块曾按小时段硬猜活动（9-18 点一律 "working"），
        而 character_daily 有自己的 24 值 ActivityType 且**没有 working**，
        两套词表交集只有 sleeping/waking_up/idle。结果前端与 prompt 看到的
        "角色在做什么"与生命衰减实际使用的活动互相矛盾。

        现在以 character_daily 为准；引擎未运行时返回空串，由调用方回退。
        """
        try:
            from core.services.character_daily.engine import (
                get_character_daily_engine,
            )

            engine = get_character_daily_engine()
            if engine is not None and getattr(engine, "_running", False):
                return str(engine.get_current_activity(role_id).value or "")
        except Exception:
            if is_debug_enabled("life_stats"):
                logger.info("查询 character_daily 活动失败，回退小时段推导", exc_info=True)
        return ""

    @staticmethod
    def _resolve_primary_role_id() -> str:
        """解析主角色 ID。

        主角色用于生命统计与 bio 展示（status["activity"] / role_sleep 等），
        这个概念需要保留；但取值不应硬编码——优先取配置，
        否则取已知角色列表中的第一个，最后才回退到默认常量。
        """
        try:
            from config.integrated_config import get_settings

            # 注意：段名是 life_simulation，不是 life；且 primary_role_id 必须在
            # LifeSimulationSettings 中声明，否则 app.yaml 配了也会被丢弃。
            configured = str(
                getattr(
                    getattr(get_settings(), "life_simulation", None),
                    "primary_role_id",
                    "",
                )
                or ""
            ).strip()
            if configured:
                return configured
        except Exception:  # noqa: BLE001, S110 - 探测失败按设计静默回退
            pass

        return _FALLBACK_PRIMARY_ROLE_ID

    def _known_role_ids(self) -> list:
        """当前可用的角色 ID 列表。"""
        try:
            roles = list(self._actor_life_states.keys())
            if roles:
                return [str(r) for r in roles]
        except Exception:  # noqa: BLE001, S110 - 探测失败按设计静默回退
            pass
        try:
            roles = list(self.sleep_coordinator._templates.keys())
            if roles:
                return [str(r) for r in roles]
        except Exception:  # noqa: BLE001, S110 - 探测失败按设计静默回退
            pass
        return [self._resolve_primary_role_id()]

    def _activities_by_role(self, fallback: str) -> dict[str, str]:
        """为每个角色解析当前活动，避免全角色共用同一个活动。

        优先级：睡眠 override（SleepManager 判定为 SLEEPING）>
        character_daily 计划 > 传入的回退值。
        睡眠 override 必须按角色分别查询，否则只有主角色睡着时会被识别。
        """
        result: dict[str, str] = {}
        for role_id in self._known_role_ids():
            try:
                override = self.sleep_coordinator.get_activity_override(str(role_id))
                if override:
                    result[str(role_id)] = str(override)
                    continue
            except Exception:  # noqa: BLE001, S110 - 探测失败按设计静默回退
                pass
            planned = self._resolve_planned_activity(str(role_id))
            result[str(role_id)] = planned or fallback
        return result

    def _update_activity_and_mood(self) -> None:
        """根据时间和硬件状态推导活动和情绪。

        活动优先取 character_daily 的计划（唯一真相源），
        小时段推导仅作为引擎不可用时的回退。
        """
        hour = get_current_time().hour
        sleep_override = self.sleep_coordinator.get_activity_override(
            self._resolve_primary_role_id()
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

        # 活动以 character_daily 的计划为准：小时段推导只是回退。
        # 这样前端、prompt 注入与生命衰减看到的是同一个活动。
        planned_activity = self._resolve_planned_activity(self._resolve_primary_role_id())
        if planned_activity:
            activity = planned_activity

        self.status["activity"] = activity
        self.status["activity_by_role"] = self._activities_by_role(activity)
        self.status["mood"] = mood
        self.life_stats["activity"] = activity
        self.life_stats_manager.update_sleep_metrics(
            self.sleep_coordinator.get_sleep_summary(self._resolve_primary_role_id())
        )
        self.status["life"] = self.life_stats

    def build_state(self) -> dict[str, Any]:
        """构建完整状态快照（供外部 get_state 调用）。"""
        self.update()

        sleep_summaries = self.sleep_coordinator.get_all_states()
        primary_sleep_summary = sleep_summaries.get(self._resolve_primary_role_id(), {})
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
