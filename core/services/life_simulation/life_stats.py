"""生命状态管理模块"""

import json
import os
import time
from typing import Any, Dict, Optional

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

logger = get_logger("LIFE_STATS")

_INITIAL_COINS = 100
_STATE_FILE = os.path.join("cache", "life_stats_state.json")
_RECOVERY_ACTIVITIES = {"waking_up", "overslept_recovery", "sleep_recovery"}
_LIGHT_ACTIVITIES = {
    "idle",
    "reading",
    "phone_scrolling",
    "gaming",
    "creative_hobby",
    "gardening",
}
_NORMAL_ACTIVITIES = {
    "walking",
    "housework",
    "shopping",
    "studying",
    "cooking",
}
_HEAVY_ACTIVITIES = {
    "working",
    "working_hard",
    "exercising",
    "late_snack",
    "staying_up_late",
}

_cached_cpp_engine = None


def get_cpp_engine():
    """获取全局缓存的 CPPSchedulerEngine 单例（供多个子模块复用）"""
    global _cached_cpp_engine
    if _cached_cpp_engine is None:
        try:
            from core.services.scheduler.cpp_scheduler_engine import (
                CPPSchedulerEngine,
            )
            _cached_cpp_engine = CPPSchedulerEngine()
        except Exception as e:
            if is_debug_enabled("life_stats"):
                logger.info(f"CPPSchedulerEngine 不可用: {e}")
    return _cached_cpp_engine


def compute_bionic_health(
    energy: float, hunger: float, thirst: float, mood_score: float
) -> float:
    """计算仿生健康值（公共公式，供 ActorManager 复用）"""
    return energy * 0.3 + hunger * 0.3 + thirst * 0.1 + mood_score * 0.3


def resolve_vitals_decay(
    activity: str,
    *,
    sleep_phase: str = "",
    impact_level: str = "none",
) -> tuple[float, float]:
    """根据角色活动/睡眠阶段，返回更平滑的饱食度和口渴度衰减。"""
    activity = str(activity or "idle")
    sleep_phase = str(sleep_phase or "")
    impact_level = str(impact_level or "none")

    if sleep_phase == "sleeping" or activity == "sleeping":
        hunger_decay, thirst_decay = 0.035, 0.055
    elif sleep_phase == "waking_up" or activity in _RECOVERY_ACTIVITIES:
        hunger_decay, thirst_decay = 0.05, 0.085
    elif activity in _LIGHT_ACTIVITIES:
        hunger_decay, thirst_decay = 0.065, 0.11
    elif activity in _NORMAL_ACTIVITIES:
        hunger_decay, thirst_decay = 0.08, 0.13
    elif activity in _HEAVY_ACTIVITIES:
        hunger_decay, thirst_decay = 0.105, 0.17
    else:
        hunger_decay, thirst_decay = 0.07, 0.12

    if impact_level == "medium":
        thirst_decay += 0.015
    elif impact_level == "severe":
        hunger_decay += 0.01
        thirst_decay += 0.03
    return hunger_decay, thirst_decay


class LifeStatsManager:
    """管理角色的生命状态"""

    def __init__(self, life_config: Any):
        self.life_config = life_config
        self._shyness_decay = float(
            getattr(life_config, "shyness_decay_per_minute", 6.0) or 6.0
        )
        self._sickness_penalty = float(
            getattr(life_config, "sickness_mood_penalty_per_minute", 1.0) or 1.0
        )
        self._shyness_bump = float(
            getattr(life_config, "shyness_bump_on_intimacy", 18.0) or 18.0
        )
        self.life_stats: Dict[str, Any] = {
            "energy": 100.0,
            "hunger": 100.0,
            "thirst": 100.0,
            "mood_score": 80.0,
            "shyness_score": 0.0,
            "immune_damage": 0.0,
            "is_sick": False,
            "level": 1,
            "xp": 0,
            "coins": _INITIAL_COINS,
            "food_inventory": [],
            "digestion_queue": [],
            "food_cravings": [],  # 食物愿望清单：角色自主调用 crave_food 工具记录想吃的东西
            "sleep_debt": 0.0,
            "sleep_quality_score": 82.0,
            "sleep_inertia_score": 0.0,
            "last_sleep_duration_hours": 0.0,
            "today_sleep_impact_level": "none",
            "nightmare_level": "none",
            "is_sleep_deprived": False,
        }
        self._load_state()

    def get_life_stats(self) -> Dict[str, Any]:
        """获取生命状态"""
        return self.life_stats

    def update_life_stats(self, key: str, value: Any):
        """更新单个生命状态值"""
        self.life_stats[key] = value

    def decay_stats(
        self,
        activity: str,
        sleep_summary: Optional[Dict[str, Any]] = None,
    ):
        """根据活动类型衰减状态"""
        sleep_summary = sleep_summary or {}
        energy_decay = 0.2 if activity in ["working", "working_hard"] else 0.1
        sleep_debt = float(sleep_summary.get("sleep_debt_hours", 0.0) or 0.0)
        inertia_score = float(sleep_summary.get("sleep_inertia_score", 0.0) or 0.0)
        impact_level = str(sleep_summary.get("impact_level") or "none")
        nightmare_level = str(sleep_summary.get("nightmare_level") or "none")
        sleep_phase = str(sleep_summary.get("phase") or "")
        if impact_level == "mild":
            energy_decay += 0.03
        elif impact_level == "medium":
            energy_decay += 0.06
        elif impact_level == "severe":
            energy_decay += 0.1
        if inertia_score >= 30:
            energy_decay += 0.02
        if activity == "sleeping":
            recover_bonus = 0.5 - min(0.25, sleep_debt * 0.04)
            if nightmare_level != "none":
                recover_bonus -= 0.08
            self.life_stats["energy"] = min(
                100, self.life_stats["energy"] + max(0.12, recover_bonus)
            )
        else:
            self.life_stats["energy"] = max(0, self.life_stats["energy"] - energy_decay)

        hunger_decay, thirst_decay = resolve_vitals_decay(
            activity,
            sleep_phase=sleep_phase,
            impact_level=impact_level,
        )
        self.life_stats["hunger"] = max(0, self.life_stats["hunger"] - hunger_decay)
        self.life_stats["thirst"] = max(0, self.life_stats["thirst"] - thirst_decay)

        self._handle_critical_stats()
        self.save_state()

    def update_sleep_metrics(self, summary: Optional[Dict[str, Any]] = None) -> None:
        """将睡眠摘要同步到生命状态快照。"""
        summary = summary or {}
        self.life_stats["sleep_debt"] = round(
            float(summary.get("sleep_debt_hours", 0.0) or 0.0), 2
        )
        self.life_stats["sleep_quality_score"] = round(
            float(summary.get("sleep_quality_score", 82.0) or 82.0), 1
        )
        self.life_stats["sleep_inertia_score"] = round(
            float(summary.get("sleep_inertia_score", 0.0) or 0.0), 1
        )
        self.life_stats["last_sleep_duration_hours"] = round(
            float(summary.get("last_sleep_duration_hours", 0.0) or 0.0), 2
        )
        self.life_stats["today_sleep_impact_level"] = str(
            summary.get("impact_level") or "none"
        )
        self.life_stats["nightmare_level"] = str(
            summary.get("nightmare_level") or "none"
        )
        self.life_stats["is_sleep_deprived"] = self.life_stats["sleep_debt"] >= 1.0

    def _handle_critical_stats(self):
        """处理临界状态"""
        if self.life_stats["hunger"] < 10 or self.life_stats["thirst"] < 10:
            self.life_stats["immune_damage"] = min(
                100.0, self.life_stats["immune_damage"] + 0.5
            )
            self._adjust_cortisol()

    def _adjust_cortisol(self):
        """调整皮质醇水平"""
        engine = get_cpp_engine()
        if engine and engine.enabled and engine.bio_system:
            try:
                engine.bio_system.adjustNeurotransmitter("cortisol", 0.01)
            except Exception as e:
                if is_debug_enabled("life_stats"):
                    logger.info(f"调整皮质醇失败: {e}")

    def decay_shyness(self):
        """衰减害羞分数"""
        self.life_stats["shyness_score"] = max(
            0.0, self.life_stats["shyness_score"] - self._shyness_decay
        )

    def apply_sickness_penalty(self):
        """应用生病惩罚"""
        if self.life_stats["is_sick"]:
            self.life_stats["mood_score"] = max(
                0.0, self.life_stats["mood_score"] - self._sickness_penalty
            )

    def feed(self, amount: float = 30) -> Dict[str, Any]:
        """喂食"""
        if self.life_stats["hunger"] >= 92.0:
            return {
                "rejected": True,
                "message": "已经很饱了，拒绝投喂。",
                "life": self.life_stats,
            }
        self.life_stats["hunger"] = min(100, self.life_stats["hunger"] + amount)
        self.life_stats["mood_score"] = min(100, self.life_stats["mood_score"] + 5)
        logger.info(f"Fed pet. Hunger: {self.life_stats['hunger']}")
        return {"rejected": False, "message": "谢谢投喂。", "life": self.life_stats}

    def drink(self, amount: float = 30) -> Dict[str, Any]:
        """喝水"""
        self.life_stats["thirst"] = min(100, self.life_stats["thirst"] + amount)
        self.life_stats["mood_score"] = min(100, self.life_stats["mood_score"] + 3)
        logger.info(f"Watered pet. Thirst: {self.life_stats['thirst']}")
        return self.life_stats

    def sleep(self, duration: int = 0) -> Dict[str, Any]:
        """睡觉"""
        self.life_stats["energy"] = min(100, self.life_stats["energy"] + 50)
        logger.info(f"Pet slept. Energy: {self.life_stats['energy']}")
        return self.life_stats

    def add_xp(self, amount: int):
        """添加经验值（支持多级连升）"""
        self.life_stats["xp"] += amount

        while self.life_stats["xp"] >= self.life_stats["level"] * 100:
            self.life_stats["xp"] -= self.life_stats["level"] * 100
            self.life_stats["level"] += 1
            self.life_stats["coins"] += 50
            self.life_stats["mood_score"] = min(
                100, self.life_stats["mood_score"] + 20
            )
            logger.info(
                f"LEVEL UP! New Level: {self.life_stats['level']}, coins +50"
            )

    def note_intimacy_context(self, bump: Optional[float] = None):
        """记录亲密上下文"""
        bump_val = (
            float(bump)
            if isinstance(bump, (int, float))
            else self._shyness_bump
        )
        self.life_stats["shyness_score"] = min(
            100.0, self.life_stats["shyness_score"] + max(0.0, bump_val)
        )

    def calculate_bionic_health(self) -> float:
        """计算仿生健康值"""
        bionic_health = compute_bionic_health(
            self.life_stats["energy"],
            self.life_stats["hunger"],
            self.life_stats["thirst"],
            self.life_stats["mood_score"],
        )
        self.life_stats["bionic_health"] = round(bionic_health, 1)
        return bionic_health

    # ── 持久化 ──

    _PERSIST_KEYS = [
        "energy", "hunger", "thirst", "mood_score", "shyness_score",
        "immune_damage", "is_sick", "level", "xp", "coins",
        "sleep_debt", "sleep_quality_score", "sleep_inertia_score",
        "last_sleep_duration_hours", "today_sleep_impact_level",
        "nightmare_level", "is_sleep_deprived",
    ]

    def save_state(self) -> None:
        """将关键生命状态持久化到磁盘"""
        try:
            data = {
                k: self.life_stats.get(k) for k in self._PERSIST_KEYS
            }
            data["_ts"] = time.time()
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            if is_debug_enabled("life_stats"):
                logger.info(f"保存生命状态失败: {e}")

    def _load_state(self) -> None:
        """从磁盘恢复生命状态"""
        try:
            if not os.path.isfile(_STATE_FILE):
                return
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 只恢复超过 10 分钟的离线衰减，避免频繁重启时状态不变化
            saved_ts = float(data.get("_ts", 0) or 0)
            offline_minutes = (time.time() - saved_ts) / 60.0 if saved_ts else 0

            for k in self._PERSIST_KEYS:
                if k in data:
                    self.life_stats[k] = data[k]

            # 离线期间模拟衰减（最多 8 小时）
            if offline_minutes > 1:
                capped = min(offline_minutes, 480)
                hunger_decay, thirst_decay = resolve_vitals_decay("idle")
                self.life_stats["hunger"] = max(
                    0, self.life_stats["hunger"] - capped * hunger_decay
                )
                self.life_stats["thirst"] = max(
                    0, self.life_stats["thirst"] - capped * thirst_decay
                )
                logger.info(
                    f"离线 {offline_minutes:.0f} 分钟，模拟衰减: "
                    f"hunger={self.life_stats['hunger']:.1f}, "
                    f"thirst={self.life_stats['thirst']:.1f}"
                )
            else:
                logger.info(
                    f"恢复生命状态: hunger={self.life_stats['hunger']:.1f}, "
                    f"thirst={self.life_stats['thirst']:.1f}, "
                    f"energy={self.life_stats['energy']:.1f}"
                )
        except Exception as e:
            logger.warning(f"加载生命状态失败，使用默认值: {e}")
