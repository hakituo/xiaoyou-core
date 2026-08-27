"""食物库存和消化系统模块"""


from core.utils.logger import get_logger
import time
from typing import Any, Dict, List

logger = get_logger(__name__)


class FoodSystem:
    """管理食物库存和消化系统"""

    def __init__(self, life_stats: Dict[str, Any], status: Dict[str, Any]):
        self.life_stats = life_stats
        self.status = status
        self._last_digestion_tick_ts = time.time()
        self._ensure_food_state()

    def _ensure_food_state(self):
        """确保食物相关状态存在（仅在初始化时调用）"""
        if not isinstance(self.life_stats.get("food_inventory"), list):
            self.life_stats["food_inventory"] = []
        if not isinstance(self.life_stats.get("digestion_queue"), list):
            self.life_stats["digestion_queue"] = []
        if not isinstance(self.life_stats.get("food_events"), list):
            self.life_stats["food_events"] = []
        if not isinstance(self.life_stats.get("food_cravings"), list):
            self.life_stats["food_cravings"] = []

    def add_food_to_inventory(self, food_id: str, quantity: int, expire_at_ts: float):
        """添加食物到库存"""
        food_id = str(food_id or "").strip()
        if not food_id:
            return
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return
        if quantity <= 0:
            return
        try:
            expire_at_ts = float(expire_at_ts)
        except (TypeError, ValueError):
            return
        if expire_at_ts <= 0:
            return
        self.life_stats["food_inventory"].append(
            {
                "food_id": food_id,
                "quantity": quantity,
                "expire_at": expire_at_ts,
            }
        )

    def take_food_from_inventory(self, food_id: str, quantity: int) -> int:
        """从库存中取出食物（单次遍历，优先取快过期的）"""
        food_id = str(food_id or "").strip()
        if not food_id:
            return 0
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return 0
        if quantity <= 0:
            return 0

        now = time.time()
        matching: List[Dict[str, Any]] = []
        other: List[Dict[str, Any]] = []

        for item in self.life_stats.get("food_inventory") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("food_id") or "").strip() != food_id:
                other.append(item)
                continue
            try:
                exp = float(item.get("expire_at") or 0.0)
            except (TypeError, ValueError):
                continue
            if exp and exp <= now:
                continue
            matching.append(item)

        matching.sort(key=lambda x: float(x.get("expire_at") or 0.0))

        taken = 0
        remaining: List[Dict[str, Any]] = []
        for item in matching:
            if taken >= quantity:
                remaining.append(item)
                continue
            try:
                q = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            if q <= 0:
                continue
            can_take = min(q, quantity - taken)
            item["quantity"] = q - can_take
            taken += can_take
            if item["quantity"] > 0:
                remaining.append(item)

        self.life_stats["food_inventory"] = other + remaining
        return taken

    def cleanup_expired_food(self) -> int:
        """清理过期食物"""
        now = time.time()
        removed = 0
        kept: List[Dict[str, Any]] = []
        for item in self.life_stats.get("food_inventory") or []:
            if not isinstance(item, dict):
                continue
            try:
                exp = float(item.get("expire_at") or 0.0)
            except (TypeError, ValueError):
                continue
            try:
                q = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            if q <= 0:
                continue
            if exp and exp <= now:
                removed += q
                continue
            kept.append(item)
        self.life_stats["food_inventory"] = kept
        return removed

    def add_digestion_effect(
        self, effects: Dict[str, float], duration_seconds: float, buff_desc: str = ""
    ):
        """添加消化效果"""
        if not isinstance(effects, dict) or not effects:
            return
        try:
            duration_seconds = float(duration_seconds)
        except (TypeError, ValueError):
            duration_seconds = 0.0
        duration_seconds = max(1.0, duration_seconds)
        now = time.time()
        self.life_stats["digestion_queue"].append(
            {
                "start_ts": now,
                "end_ts": now + duration_seconds,
                "last_ts": now,
                "effects": {
                    "hunger": float(effects.get("hunger") or 0.0),
                    "thirst": float(effects.get("thirst") or 0.0),
                    "energy": float(effects.get("energy") or 0.0),
                    "health": float(effects.get("health") or 0.0),
                },
                "buff_desc": buff_desc,
            }
        )

    def tick_digestion(self):
        """处理消化队列"""
        now = time.time()
        last = self._last_digestion_tick_ts or now
        self._last_digestion_tick_ts = now
        elapsed = now - last
        if elapsed <= 0:
            return

        cpu_temp = float(self.status.get("cpu_temp") or 45.0)
        metabolism_multiplier = 1.0 + max(0.0, (cpu_temp - 45.0) / 50.0)

        queue: List[Dict[str, Any]] = []
        for entry in self.life_stats.get("digestion_queue") or []:
            if not isinstance(entry, dict):
                continue
            try:
                start_ts = float(entry.get("start_ts") or 0.0)
                end_ts = float(entry.get("end_ts") or 0.0)
                last_ts = float(entry.get("last_ts") or start_ts)
            except (TypeError, ValueError):
                continue
            if end_ts <= start_ts:
                continue

            apply_until = min(now, last_ts + elapsed * metabolism_multiplier)
            apply_until = min(apply_until, end_ts)

            dt = apply_until - last_ts
            if dt <= 0:
                if now < end_ts:
                    queue.append(entry)
                continue

            frac = dt / (end_ts - start_ts)
            try:
                eff = (
                    entry.get("effects")
                    if isinstance(entry.get("effects"), dict)
                    else {}
                )
                hunger = float(eff.get("hunger") or 0.0) * frac
                thirst = float(eff.get("thirst") or 0.0) * frac
                energy = float(eff.get("energy") or 0.0) * frac
                health = float(eff.get("health") or 0.0) * frac
            except (TypeError, ValueError):
                hunger = thirst = energy = health = 0.0

            if hunger:
                self.life_stats["hunger"] = min(
                    100.0, self.life_stats["hunger"] + hunger
                )
            if thirst:
                self.life_stats["thirst"] = min(
                    100.0, self.life_stats["thirst"] + thirst
                )
            if energy:
                self.life_stats["energy"] = min(
                    100.0, self.life_stats["energy"] + energy
                )
            if health:
                self.life_stats["immune_damage"] = max(
                    0.0, self.life_stats["immune_damage"] - health
                )

            entry["last_ts"] = apply_until
            if apply_until < end_ts:
                queue.append(entry)

        self.life_stats["digestion_queue"] = queue

    def get_food_inventory(self) -> List[Dict[str, Any]]:
        """获取食物库存"""
        return list(self.life_stats.get("food_inventory") or [])

    def record_food_event(self, role_id: str, **event: Any) -> None:
        """记录进食事件，供夜宵与餐窗联动诊断使用。"""
        entry = {
            "ts": float(event.get("ts") or time.time()),
            "role_id": str(role_id or "").strip() or "unknown",
            "food_id": str(event.get("food_id") or "").strip(),
            "food_type": str(event.get("food_type") or "").strip(),
            "meal_window": str(event.get("meal_window") or "").strip(),
            "is_late_snack": bool(event.get("is_late_snack")),
            "reason": str(event.get("reason") or "").strip(),
        }
        self.life_stats["food_events"].append(entry)
        self.life_stats["food_events"] = self.life_stats["food_events"][-50:]

    def get_recent_food_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的进食事件。"""
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 20
        events = self.life_stats.get("food_events") or []
        return list(events[-limit:])

    # ==================== 食物愿望清单（food_cravings） ====================
    # 角色自主调用 crave_food 工具记录"想吃X"，进入愿望清单；
    # 做饭产出逻辑会优先读 wishlist 满足嘴馋，不满足时回退到默认 _COOKING_OUTPUTS。

    _DEFAULT_CRAVING_TTL_SECONDS = 3 * 24 * 3600.0  # 默认 3 天过期
    _MAX_ACTIVE_CRAVINGS = 10  # 同一时刻最多保留 10 条未满足的愿望

    def add_food_craving(
        self,
        food_id: str,
        reason: str = "",
        ttl_seconds: float | None = None,
    ) -> Dict[str, Any]:
        """添加一条"想吃X"愿望。同一食物已有未满足项时刷新 added_at 和 reason。"""
        food_id = str(food_id or "").strip()
        if not food_id:
            return {}
        try:
            from core.food.data import get_food

            food = get_food(food_id)
            if not food:
                return {}
        except Exception:
            return {}

        now = time.time()
        if ttl_seconds is None:
            ttl_seconds = self._DEFAULT_CRAVING_TTL_SECONDS
        try:
            ttl_seconds = float(ttl_seconds)
        except (TypeError, ValueError):
            ttl_seconds = self._DEFAULT_CRAVING_TTL_SECONDS
        expire_at = now + max(60.0, ttl_seconds)

        cravings = self.life_stats.get("food_cravings")
        if not isinstance(cravings, list):
            cravings = []
            self.life_stats["food_cravings"] = cravings

        # 已存在未满足的同食物项 → 刷新时间窗和理由
        for item in cravings:
            if not isinstance(item, dict):
                continue
            if str(item.get("food_id") or "").strip() == food_id and not item.get(
                "satisfied"
            ):
                item["added_at"] = now
                item["expire_at"] = expire_at
                if reason:
                    item["reason"] = str(reason)[:120]
                item["food_name"] = food.name
                item["food_type"] = food.type
                item["icon"] = food.icon
                return item

        # 上限保护：未满足项过多时丢弃最早的
        active = [c for c in cravings if isinstance(c, dict) and not c.get("satisfied")]
        if len(active) >= self._MAX_ACTIVE_CRAVINGS:
            active.sort(key=lambda x: float(x.get("added_at") or 0.0))
            oldest = active[0]
            try:
                cravings.remove(oldest)
            except Exception:
                pass

        entry = {
            "food_id": food_id,
            "food_name": food.name,
            "food_type": food.type,
            "icon": food.icon,
            "added_at": now,
            "expire_at": expire_at,
            "reason": str(reason or "")[:120],
            "satisfied": False,
            "satisfied_at": None,
            "satisfied_by": None,
        }
        cravings.append(entry)
        return entry

    def get_food_cravings(
        self,
        only_active: bool = False,
        food_type: str | None = None,
    ) -> List[Dict[str, Any]]:
        """读取愿望清单。only_active=True 时只返回未满足且未过期的项。"""
        cravings = self.life_stats.get("food_cravings")
        if not isinstance(cravings, list):
            return []
        now = time.time()
        out: List[Dict[str, Any]] = []
        for item in cravings:
            if not isinstance(item, dict):
                continue
            if only_active:
                if item.get("satisfied"):
                    continue
                try:
                    exp = float(item.get("expire_at") or 0.0)
                except (TypeError, ValueError):
                    exp = 0.0
                if exp and exp <= now:
                    continue
            if food_type:
                if str(item.get("food_type") or "").strip() != food_type:
                    continue
            out.append(dict(item))
        # 仅活跃时按添加时间倒序（最近的优先），否则保留原顺序
        if only_active:
            out.sort(key=lambda x: float(x.get("added_at") or 0.0), reverse=True)
        return out

    def mark_craving_satisfied(
        self,
        food_id: str,
        satisfied_by: str = "cooking",
    ) -> bool:
        """标记某条愿望已满足（做饭产出 / 投喂 / 自动食用均会调用）。"""
        food_id = str(food_id or "").strip()
        if not food_id:
            return False
        cravings = self.life_stats.get("food_cravings")
        if not isinstance(cravings, list):
            return False
        now = time.time()
        for item in cravings:
            if not isinstance(item, dict):
                continue
            if str(item.get("food_id") or "").strip() != food_id:
                continue
            if item.get("satisfied"):
                continue
            item["satisfied"] = True
            item["satisfied_at"] = now
            item["satisfied_by"] = str(satisfied_by or "")[:32]
            return True
        return False

    def cleanup_expired_cravings(self) -> int:
        """清理过期愿望（保留已满足的最近 20 条作为历史，便于复盘）。"""
        cravings = self.life_stats.get("food_cravings")
        if not isinstance(cravings, list):
            return 0
        now = time.time()
        kept: List[Dict[str, Any]] = []
        removed = 0
        for item in cravings:
            if not isinstance(item, dict):
                continue
            try:
                exp = float(item.get("expire_at") or 0.0)
            except (TypeError, ValueError):
                exp = 0.0
            if exp and exp <= now and not item.get("satisfied"):
                removed += 1
                continue
            kept.append(item)
        # 已满足的历史保留最近 20 条
        satisfied = [c for c in kept if isinstance(c, dict) and c.get("satisfied")]
        if len(satisfied) > 20:
            satisfied.sort(key=lambda x: float(x.get("satisfied_at") or 0.0))
            keep_ids = {id(c) for c in satisfied[-20:]}
            kept = [
                c
                for c in kept
                if not (isinstance(c, dict) and c.get("satisfied"))
                or id(c) in keep_ids
            ]
        self.life_stats["food_cravings"] = kept
        return removed
