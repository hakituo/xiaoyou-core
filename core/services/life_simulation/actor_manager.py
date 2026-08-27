"""角色状态和关系管理模块"""

from core.utils.logger import get_logger
import json

import time
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.atomic_io import safe_json_dump
from core.utils.time_utils import now_iso
from .life_stats import compute_bionic_health, resolve_vitals_decay

logger = get_logger(__name__)


class ActorManager:
    """管理多角色的生命状态和关系"""

    def __init__(self):
        self._actor_life_states: Dict[str, Dict[str, Any]] = {}
        self._actor_relationships: Dict[str, float] = {}
        self._actor_state_file = self._get_actor_state_file_path()
        self._last_actor_save_ts: float = 0.0
        self._load_actor_states()

    def _get_actor_state_file_path(self) -> Path:
        from core.utils.data_paths import get_aveline_data_dir
        return get_aveline_data_dir() / "actor_states.json"

    def _load_actor_states(self) -> None:
        """从文件加载角色状态"""
        try:
            if self._actor_state_file.exists():
                data = json.loads(self._actor_state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if isinstance(data.get("life_states"), dict):
                        self._actor_life_states = data["life_states"]
                    if isinstance(data.get("relationships"), dict):
                        self._actor_relationships = data["relationships"]
                    logger.info(
                        f"已加载角色状态：{list(self._actor_life_states.keys())}，"
                        f"关系：{list(self._actor_relationships.keys())}"
                    )
        except Exception as e:
            logger.warning(f"加载角色状态失败: {e}")

    def _save_actor_states(self) -> None:
        """保存角色状态到文件"""
        try:
            data = {
                "life_states": self._actor_life_states,
                "relationships": self._actor_relationships,
                "updated_at": now_iso(),
            }
            self._actor_state_file.parent.mkdir(parents=True, exist_ok=True)
            # P0-17: 用原子写入保存角色状态，避免进程崩溃导致状态文件被截断
            safe_json_dump(data, self._actor_state_file, encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存角色状态失败: {e}")

    def _maybe_save_actor_states(self) -> None:
        """定期保存角色状态"""
        now = time.time()
        if now - self._last_actor_save_ts >= 60.0:
            self._last_actor_save_ts = now
            self._save_actor_states()

    @staticmethod
    def _normalize_actor_id(actor_id: Optional[str]) -> str:
        """标准化角色ID"""
        raw = str(actor_id or "").strip()
        return raw if raw else "aveline"

    @staticmethod
    def _make_base_actor_state() -> Dict[str, Any]:
        """创建基础角色状态"""
        return {
            "energy": 100.0,
            "hunger": 100.0,
            "thirst": 100.0,
            "mood_score": 80.0,
            "shyness_score": 0.0,
            "immune_damage": 0.0,
            "is_sick": False,
            "level": 1,
            "xp": 0,
            "coins": 100,
            "food_inventory": [],
            "digestion_queue": [],
        }

    def _get_actor_state_mut(self, actor_id: Optional[str]) -> Dict[str, Any]:
        """获取可修改的角色状态"""
        aid = self._normalize_actor_id(actor_id)
        st = self._actor_life_states.get(aid)
        if isinstance(st, dict):
            return st
        st = self._make_base_actor_state()
        self._actor_life_states[aid] = st
        return st

    def get_actor_life_state(self, actor_id: Optional[str]) -> Dict[str, Any]:
        """获取角色生命状态的拷贝"""
        st = self._get_actor_state_mut(actor_id)
        return dict(st)

    def update_actor_interaction(self, actor_id: Optional[str], xp_gain: int = 2):
        """更新角色交互"""
        st = self._get_actor_state_mut(actor_id)
        try:
            xp_gain = int(xp_gain)
        except (TypeError, ValueError):
            xp_gain = 0
        if xp_gain > 0:
            st["xp"] = int(st.get("xp", 0) or 0) + xp_gain
        st["mood_score"] = min(100.0, float(st.get("mood_score", 0.0) or 0.0) + 0.1)

    def feed_actor(
        self, actor_id: Optional[str], hunger_amount: float = 8.0
    ) -> Dict[str, Any]:
        """喂食角色"""
        st = self._get_actor_state_mut(actor_id)
        try:
            hunger_amount = float(hunger_amount)
        except (TypeError, ValueError):
            hunger_amount = 0.0
        if hunger_amount <= 0:
            return dict(st)
        st["hunger"] = min(100.0, float(st.get("hunger", 0.0) or 0.0) + hunger_amount)
        st["mood_score"] = min(
            100.0, float(st.get("mood_score", 0.0) or 0.0) + hunger_amount * 0.2
        )
        return dict(st)

    def _relationship_key(self, actor_a: Optional[str], actor_b: Optional[str]) -> str:
        """生成关系键"""
        a = self._normalize_actor_id(actor_a)
        b = self._normalize_actor_id(actor_b)
        if a <= b:
            return f"{a}|{b}"
        return f"{b}|{a}"

    def get_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str]
    ) -> float:
        """获取两个角色之间的关系值"""
        key = self._relationship_key(actor_a, actor_b)
        return float(self._actor_relationships.get(key) or 0.0)

    def add_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str], delta: float = 0.0
    ) -> float:
        """增加两个角色之间的关系值"""
        key = self._relationship_key(actor_a, actor_b)
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            delta = 0.0
        val = float(self._actor_relationships.get(key) or 0.0) + delta
        val = max(0.0, min(100.0, val))
        self._actor_relationships[key] = val
        self._maybe_save_actor_states()
        return val

    def share_food_between_actors(
        self,
        actor_a: Optional[str],
        actor_b: Optional[str],
        hunger_amount: float = 6.0,
    ) -> Dict[str, Any]:
        """两个角色分享食物"""
        a_state = self.feed_actor(actor_a, hunger_amount=hunger_amount)
        b_state = self.feed_actor(actor_b, hunger_amount=hunger_amount)
        relation = self.add_actor_relationship(actor_a, actor_b, delta=1.2)
        return {
            "actor_a": a_state,
            "actor_b": b_state,
            "relationship": relation,
        }

    def tick_actor_life_states(self, activity: str):
        """更新所有角色的生命状态"""
        for aid, st in list(self._actor_life_states.items()):
            if not isinstance(st, dict):
                continue
            energy_decay = 0.2 if activity in ["working", "working_hard"] else 0.1
            energy = float(st.get("energy", 0.0) or 0.0)
            hunger = float(st.get("hunger", 0.0) or 0.0)
            thirst = float(st.get("thirst", 0.0) or 0.0)
            mood = float(st.get("mood_score", 0.0) or 0.0)

            if activity == "sleeping":
                energy = min(100.0, energy + 0.4)
            else:
                energy = max(0.0, energy - energy_decay)
            hunger_decay, thirst_decay = resolve_vitals_decay(activity)
            hunger = max(0.0, hunger - hunger_decay)
            thirst = max(0.0, thirst - thirst_decay)

            # 当 hunger 或 thirst 低于阈值时，mood 会下降
            # 但当 hunger 和 thirst 恢复到足够水平时，mood 应该缓慢恢复
            if hunger < 15.0 or thirst < 15.0:
                mood = max(10.0, mood - 0.6)  # 最低保留 10 分，避免完全归零无法恢复
            else:
                # 当基本需求满足时，mood 缓慢恢复
                mood = max(0.0, min(100.0, mood + 0.2))

            st["energy"] = energy
            st["hunger"] = hunger
            st["thirst"] = thirst
            st["mood_score"] = mood
            st["bionic_health"] = round(
                compute_bionic_health(energy, hunger, thirst, mood), 1
            )

        self._maybe_save_actor_states()

    def get_all_actor_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有角色状态（浅拷贝，不修改返回值即可安全使用）"""
        return {
            str(k): dict(v)
            for k, v in self._actor_life_states.items()
            if isinstance(v, dict)
        }

    def get_all_relationships(self) -> Dict[str, float]:
        """获取所有关系"""
        return dict(self._actor_relationships)
