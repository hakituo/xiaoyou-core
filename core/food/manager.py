
from core.utils.logger import get_logger
import json
import time
from typing import Any, Dict, List

from core.food.models import FoodItem, ShopItem
from core.food.data import get_food, get_all_food, get_all_shop_items, get_shop_item
from core.utils.atomic_io import safe_json_dump
from core.utils.data_paths import get_aveline_life_records_dir, get_ling_life_records_dir
from core.utils.time_utils import get_current_time
# Import services lazily to avoid circular imports

logger = get_logger(__name__)


class FoodManager:
    """
    Manages food consumption, inventory (future), and effects.
    """

    def __init__(self):
        # User preferences could be loaded from a DB
        # Format: { "sweet": 1.2, "spicy": 0.5 } (Multiplier for enjoyment)
        self.preferences = {
            "sweet": 1.2,  # Likes sweet
            "spicy": 0.8,  # Can handle some spice but not too much
            "bitter": 0.6,  # Dislikes bitter
            "sour": 1.0,
            "salty": 1.0,
            "umami": 1.1,
        }

    def _normalize_persona_scope(
        self,
        persona_scope: str,
        role_id: str = "",
        persona_filename: str = "",
    ) -> str:
        text = str(persona_scope or "").strip().lower()
        if text in {"ling", "wangling", "wang_ling", "Ling"}:
            return "ling"
        if text in {"aveline", "七濑澪", "七濑 澪", "澪"}:
            return "aveline"

        explicit_role = str(role_id or "").strip().lower()
        if explicit_role in {"aveline", "ling"}:
            return explicit_role

        try:
            from core.services.dual_role.personas import resolve_role_id_from_persona

            resolved_role = str(
                resolve_role_id_from_persona(persona_filename=persona_filename)
            ).strip().lower()
            if resolved_role in {"aveline", "ling"}:
                return resolved_role
        except Exception:
            pass

        if text in {"auto", ""}:
            try:
                from core.character.managers.persona_manager import get_persona_manager

                current_filename = str(
                    get_persona_manager().get_current_filename() or ""
                ).lower()
                if "ling" in current_filename:
                    return "ling"
            except Exception:
                return "aveline"
            return "aveline"
        return "aveline"

    def _record_self_meal(
        self,
        meal_type: str,
        content: str,
        persona_scope: str = "aveline",
        role_id: str = "",
        persona_filename: str = "",
    ) -> None:
        scope = self._normalize_persona_scope(
            persona_scope,
            role_id=role_id,
            persona_filename=persona_filename,
        )
        base_dir = (
            get_ling_life_records_dir()
            if scope == "ling"
            else get_aveline_life_records_dir()
        )
        now_dt = get_current_time()
        day_dir = base_dir / now_dt.strftime("%Y") / str(now_dt.month) / str(now_dt.day)
        day_dir.mkdir(parents=True, exist_ok=True)
        file_path = day_dir / "daily_record.json"
        payload = {"date": now_dt.strftime("%Y-%m-%d"), "meals": []}
        if file_path.exists():
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {"date": now_dt.strftime("%Y-%m-%d"), "meals": []}
        meals = payload.get("meals")
        if not isinstance(meals, list):
            meals = []
            payload["meals"] = meals
        meals.append(
            {
                "type": meal_type,
                "content": content,
                "time": now_dt.strftime("%H:%M"),
            }
        )
        # P0-17: 用原子写入保存食事记录，避免进程崩溃导致当日记录损坏
        safe_json_dump(payload, file_path, encoding="utf-8")

    def get_menu(self, food_type: str = None) -> List[FoodItem]:
        all_food = get_all_food()
        normalized = []
        for item in all_food:
            normalized.append(item.model_copy(update={"min_level": 1}))
        if not food_type:
            return normalized
        return [f for f in normalized if f.type == food_type]

    def get_shop_menu(
        self,
        category: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """获取商城商品列表(支持分页和类别过滤)。

        Args:
            category: 商品类别(food/gift/toy/book/clothing), None=全部
            page: 页码(从1开始)
            page_size: 每页数量

        Returns:
            {"items": [...], "total": int, "page": int, "page_size": int, "has_more": bool}
        """
        all_items = get_all_shop_items()
        # 按 category 过滤
        if category and category != "all":
            filtered = [i for i in all_items if i.category == category]
        else:
            filtered = all_items
        total = len(filtered)
        # 分页
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        start = (page - 1) * page_size
        end = start + page_size
        page_items = filtered[start:end]
        # 序列化(把 ShopItem 转成 dict, 统一 min_level=1)
        items_out = []
        for item in page_items:
            d = item.model_dump()
            d["min_level"] = 1
            # nutrition/taste 为 None 时不输出
            if d.get("nutrition") is None:
                d.pop("nutrition", None)
            if d.get("taste") is None:
                d.pop("taste", None)
            items_out.append(d)
        return {
            "items": items_out,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        }

    def get_inventory(self) -> List[Dict[str, Any]]:
        from core.services.life_simulation.service import get_life_simulation_service

        life_service = get_life_simulation_service()
        inv = life_service.life_stats.get("food_inventory")
        if not isinstance(inv, list):
            return []
        now = time.time()
        out: List[Dict[str, Any]] = []
        for item in inv:
            if not isinstance(item, dict):
                continue
            food_id = str(item.get("food_id") or "").strip()
            if not food_id:
                continue
            try:
                quantity = int(item.get("quantity") or 0)
            except Exception:
                quantity = 0
            if quantity <= 0:
                continue
            try:
                expire_at = float(item.get("expire_at") or 0.0)
            except Exception:
                expire_at = 0.0
            if expire_at and expire_at <= now:
                continue
            food = get_food(food_id)
            out.append(
                {
                    "food_id": food_id,
                    "name": food.name if food else food_id,
                    "icon": food.icon if food else "",
                    "quantity": quantity,
                    "expire_at": expire_at,
                }
            )
        out.sort(key=lambda x: float(x.get("expire_at") or 0.0))
        return out

    async def buy(self, item_id: str, quantity: int = 1, recipient: str = "self") -> Dict[str, Any]:
        """购买商城商品。

        Args:
            item_id: 商品ID(食物或非食物)
            quantity: 购买数量(1-99)
            recipient: 给谁买(self/aveline/ling)
        """
        item = get_shop_item(item_id)
        if not item:
            return {"success": False, "message": "商品不存在"}

        try:
            quantity = int(quantity)
        except Exception:
            quantity = 0
        if quantity <= 0:
            return {"success": False, "message": "数量不合法"}
        quantity = min(quantity, 99)

        from core.services.life_simulation.service import get_life_simulation_service

        life_service = get_life_simulation_service()
        if hasattr(life_service, "_ensure_food_state"):
            life_service._ensure_food_state()

        life_service.life_stats["coins"] = max(
            int(life_service.life_stats.get("coins", 0) or 0),
            999999999,
        )

        result = {
            "success": True,
            "message": f"已购买 {item.name} x{quantity}",
            "item_id": item.id,
            "item_name": item.name,
            "category": item.category,
            "quantity": quantity,
            "coins_spent": 0,
            "unlimited_coins": True,
            "recipient": recipient,
        }

        # 食物类商品加入库存(带过期时间)
        if item.category == "food" and item.nutrition:
            expire_at = time.time() + float(item.expire_hours) * 3600.0
            if hasattr(life_service, "add_food_to_inventory"):
                life_service.add_food_to_inventory(
                    food_id=item.id, quantity=quantity, expire_at_ts=expire_at
                )
            else:
                inv = life_service.life_stats.get("food_inventory")
                if not isinstance(inv, list):
                    inv = []
                    life_service.life_stats["food_inventory"] = inv
                inv.append(
                    {"food_id": item.id, "quantity": quantity, "expire_at": expire_at}
                )
        else:
            # 非食物商品: 记录到 gift_inventory(赠送记录)
            gift_inv = life_service.life_stats.get("gift_inventory")
            if not isinstance(gift_inv, list):
                gift_inv = []
                life_service.life_stats["gift_inventory"] = gift_inv
            gift_inv.append({
                "item_id": item.id,
                "item_name": item.name,
                "category": item.category,
                "quantity": quantity,
                "recipient": recipient,
                "purchased_at": time.time(),
                "effect_desc": item.effect_desc or "",
            })

        return result

    async def eat(
        self,
        food_id: str,
        from_inventory: bool = True,
        eater: str = "user",
        persona_scope: str = "auto",
        role_id: str = "",
        persona_filename: str = "",
    ) -> Dict[str, Any]:
        """
        Process the eating action.
        Returns the result dict with effects and message.
        """
        food = get_food(food_id)
        if not food:
            return {"success": False, "message": "食物不存在"}

        # 1. Get Services
        from core.services.life_simulation.service import get_life_simulation_service

        life_service = get_life_simulation_service()
        if hasattr(life_service, "_ensure_food_state"):
            life_service._ensure_food_state()
        resolved_scope = self._normalize_persona_scope(
            persona_scope,
            role_id=role_id,
            persona_filename=persona_filename,
        )

        hunger_now_value = float(life_service.life_stats.get("hunger", 0.0) or 0.0)
        if eater == "user" and hunger_now_value >= 92.0:
            return {
                "success": False,
                "message": "她现在已经很饱了，拒绝投喂。",
                "reason": "too_full",
            }

        used_inventory = False
        coins_spent = 0

        if from_inventory and hasattr(life_service, "take_food_from_inventory"):
            taken = life_service.take_food_from_inventory(food_id=food.id, quantity=1)
            if taken >= 1:
                used_inventory = True

        if not used_inventory:
            life_service.life_stats["coins"] = max(
                int(life_service.life_stats.get("coins", 0) or 0),
                999999999,
            )

        digestion_seconds = 600.0
        if food.type == "drink":
            digestion_seconds = 180.0
        elif food.type == "snack":
            digestion_seconds = 300.0
        elif food.type == "meal":
            digestion_seconds = 900.0

        immediate_ratio = 0.4
        remaining_ratio = 1.0 - immediate_ratio

        hunger_now = float(food.nutrition.hunger) * immediate_ratio
        thirst_now = float(food.nutrition.thirst) * immediate_ratio
        energy_now = float(food.nutrition.energy) * immediate_ratio
        health_now = float(food.nutrition.health) * immediate_ratio

        life_service.life_stats["hunger"] = min(
            100.0, float(life_service.life_stats.get("hunger", 0.0) or 0.0) + hunger_now
        )
        life_service.life_stats["thirst"] = min(
            100.0, float(life_service.life_stats.get("thirst", 0.0) or 0.0) + thirst_now
        )
        life_service.life_stats["energy"] = min(
            100.0, float(life_service.life_stats.get("energy", 0.0) or 0.0) + energy_now
        )

        if health_now:
            current_immune = float(
                life_service.life_stats.get("immune_damage", 0.0) or 0.0
            )
            life_service.life_stats["immune_damage"] = max(
                0.0, current_immune - health_now
            )

        remaining_effects = {
            "hunger": float(food.nutrition.hunger) * remaining_ratio,
            "thirst": float(food.nutrition.thirst) * remaining_ratio,
            "energy": float(food.nutrition.energy) * remaining_ratio,
            "health": float(food.nutrition.health) * remaining_ratio,
        }
        if hasattr(life_service, "add_digestion_effect"):
            life_service.add_digestion_effect(
                remaining_effects,
                duration_seconds=digestion_seconds,
                buff_desc=food.buff_desc,
            )

        # 4. Calculate Taste/Emotional Impact
        taste_score = self._calculate_taste_score(food)

        # Base mood boost from eating
        mood_boost = 2.0

        # Rarity bonus
        rarity_multipliers = {"common": 1.0, "rare": 1.5, "epic": 2.5, "legendary": 5.0}
        mood_boost *= rarity_multipliers.get(food.rarity, 1.0)

        # Bonus from taste
        if taste_score > 1.2:
            mood_boost += 5.0
            reaction = "delicious"
        elif taste_score < 0.8:
            mood_boost -= 2.0
            reaction = "dislike"
        else:
            mood_boost += 1.0
            reaction = "normal"

        # Apply mood
        current_mood = life_service.life_stats.get("mood_score", 0)
        life_service.life_stats["mood_score"] = min(
            100, max(0, current_mood + mood_boost)
        )

        try:
            from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

            engine = CPPSchedulerEngine()
            if engine.enabled and engine.bio_system:
                bio = engine.bio_system
                dopamine_delta = max(0.01, (taste_score - 1.0) * 0.05)
                bio.adjustNeurotransmitter("dopamine", dopamine_delta)

                serotonin_map = {
                    "common": 0.0,
                    "rare": 0.02,
                    "epic": 0.05,
                    "legendary": 0.1,
                }
                bio.adjustNeurotransmitter(
                    "serotonin", serotonin_map.get(food.rarity, 0.0)
                )

                if food.type == "drink" and food.nutrition.energy > 10:
                    bio.adjustNeurotransmitter("norepinephrine", 0.05)

                if food.taste.sweet > 0.5:
                    bio.adjustNeurotransmitter("cortisol", -0.03)

                logger.info(
                    f"Biological Link Applied: Dopamine+{dopamine_delta:.3f}, Serotonin+{serotonin_map.get(food.rarity, 0):.2f}"
                )
        except Exception as e:
            logger.warning(f"Failed to apply biological link: {e}")

        logger.info(
            f"Ate {food.name}: Taste={taste_score:.2f}, Mood={mood_boost}, Rarity={food.rarity}"
        )
        try:
            meal_type = "正餐" if food.type == "meal" else ("零食" if food.type == "snack" else "饮品")
            # 自主进食前缀带角色 scope，便于后续按角色归位（与 ling 自主进食约定一致）
            if eater == "self":
                if resolved_scope == "ling":
                    eater_prefix = "自主进食(ling):"
                else:
                    eater_prefix = "自主进食:"
                self._record_self_meal(
                    meal_type,
                    f"{eater_prefix}{food.name}",
                    persona_scope=resolved_scope,
                    role_id=role_id,
                    persona_filename=persona_filename,
                )
            else:
                # 投喂：用户用 /吃 /喝 指令投喂给角色，按角色落到对应 life_records 目录，
                # 与自主进食统一存储，避免两条数据流割裂（角色读不到自己的被投喂记录）。
                if resolved_scope == "ling":
                    eater_prefix = "投喂(ling):"
                else:
                    eater_prefix = "投喂:"
                self._record_self_meal(
                    meal_type,
                    f"{eater_prefix}{food.name}",
                    persona_scope=resolved_scope,
                    role_id=role_id,
                    persona_filename=persona_filename,
                )
                # 同时写入用户侧 daily_records，兼容用户画像通用记录
                from core.services.daily.manager import get_daily_manager

                get_daily_manager().record_meal(meal_type, f"{eater_prefix}{food.name}")
        except Exception:
            pass

        # 用户投喂时，注入提示信息到对话上下文
        if eater == "user":
            try:
                life_service.life_stats["_last_meal"] = {
                    "food_name": food.name,
                    "food_id": food.id,
                    "food_type": food.type,
                    "source": "user_feed",
                    "timestamp": time.time(),
                }
            except Exception:
                pass

        # 联动 food_cravings：吃掉的食物如果在愿望清单里，标记为已满足
        try:
            satisfied_by = "user_feed" if eater == "user" else "auto_eat"
            life_service.mark_craving_satisfied(food.id, satisfied_by=satisfied_by)
        except Exception:
            pass

        return {
            "success": True,
            "message": ("她自己吃了" if eater == "self" else "食用了") + f" {food.name}",
            "effects": {
                "hunger": float(food.nutrition.hunger),
                "thirst": float(food.nutrition.thirst),
                "energy": float(food.nutrition.energy),
                "mood": mood_boost,
                "buff": food.buff_desc,
            },
            "reaction": reaction,
            "rarity": food.rarity,
            "used_inventory": used_inventory,
            "coins_spent": coins_spent,
            "unlimited_coins": True,
            "eater": eater,
            "persona_scope": resolved_scope,
        }

    def get_gift_inventory(self) -> List[Dict[str, Any]]:
        """查看已购买的非食物商品库存。

        返回 gift_inventory 中的物品列表，合并同 item_id 的数量。
        """
        from core.services.life_simulation.service import get_life_simulation_service

        life_service = get_life_simulation_service()
        gift_inv = life_service.life_stats.get("gift_inventory")
        if not isinstance(gift_inv, list):
            return []

        # 合并同 item_id + recipient 的条目
        merged: Dict[str, Dict[str, Any]] = {}
        for entry in gift_inv:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id") or "").strip()
            if not item_id:
                continue
            recipient = str(entry.get("recipient") or "self").strip()
            key = f"{item_id}::{recipient}"
            if key in merged:
                merged[key]["quantity"] = int(merged[key].get("quantity", 0)) + int(
                    entry.get("quantity", 1)
                )
            else:
                merged[key] = {
                    "item_id": item_id,
                    "item_name": entry.get("item_name", item_id),
                    "category": entry.get("category", ""),
                    "quantity": int(entry.get("quantity", 1)),
                    "recipient": recipient,
                    "effect_desc": entry.get("effect_desc", ""),
                    "purchased_at": entry.get("purchased_at", 0),
                }
        return list(merged.values())

    # effect_desc 中文属性名 → life_stats 字段名的映射
    _EFFECT_ATTR_MAP = {
        "心情": "mood_score",
        "情绪": "mood_score",
        "快乐": "mood_score",
        "能量": "energy",
        "精力": "energy",
        "专注": "energy",
        "效率": "energy",
        "沉浸": "energy",
        "放松": "mood_score",
        "饥饿": "hunger",
        "美食": "hunger",
        "口渴": "thirst",
        "健康": "immune_damage",  # 注意：immune_damage 越低越健康，效果取负
        "安全感": "mood_score",
        "社交": "mood_score",
        "浪漫": "mood_score",
        "承诺": "mood_score",
        "温暖": "mood_score",
        "舒适": "mood_score",
        "氛围": "mood_score",
        "仪式": "mood_score",
        "魅力": "mood_score",
        "优雅": "mood_score",
        "时尚": "mood_score",
        "潮流": "mood_score",
        "气场": "mood_score",
        "个性": "mood_score",
        "审美": "mood_score",
        "创作": "mood_score",
        "探索": "mood_score",
        "运动": "energy",
        "户外": "energy",
        "旅行": "mood_score",
        "阅读": "mood_score",
        "护眼": "mood_score",
        "学习": "mood_score",
        "计算": "mood_score",
        "家庭": "mood_score",
        "生活": "mood_score",
        "便利": "energy",
        "科技": "mood_score",
        "未来": "mood_score",
        "游戏": "mood_score",
        "视觉": "mood_score",
        "品味": "mood_score",
        "身份": "mood_score",
        "奢华": "mood_score",
        "传承": "mood_score",
        "收藏": "mood_score",
        "设计": "mood_score",
        "低调": "mood_score",
        "简约": "mood_score",
        "清新": "mood_score",
        "安神": "mood_score",
        "精准": "energy",
        "沉浸": "energy",
        "出行": "energy",
        "创造力": "mood_score",
        "恢复": "energy",
    }

    # 不映射到 life_stats 但可以影响 C++ 神经递质的属性
    _NEURO_ATTR_MAP = {
        "放松": ("cortisol", -0.05),
        "安神": ("cortisol", -0.05),
        "专注": ("norepinephrine", 0.03),
        "快乐": ("dopamine", 0.04),
        "浪漫": ("serotonin", 0.05),
        "魅力": ("dopamine", 0.03),
    }

    def _parse_effect_desc(self, effect_desc: str) -> list:
        """解析 effect_desc 文本，返回 [(attr_name, delta), ...]。

        格式示例: "心情+15, 专注+12" → [("心情", 15.0), ("专注", 12.0)]
        "送礼时心情值+10" → [("心情", 10.0)]（取末尾有效属性名）
        """
        import re

        if not effect_desc:
            return []
        results = []
        # 匹配 "中文/英文属性名 + ±数字" 的模式
        matches = re.findall(r"([\u4e00-\u9fa5a-zA-Z]+)\s*[+\-]\s*(\d+)", effect_desc)
        for attr_name, value_str in matches:
            # 判断是 + 还是 -
            sign = 1.0
            idx = effect_desc.find(attr_name)
            if idx >= 0:
                after = effect_desc[idx + len(attr_name): idx + len(attr_name) + 5]
                if "-" in after and "+" not in after[: after.find("-")]:
                    sign = -1.0

            # 归一化：去掉"值""度"等后缀，再去掉前缀修饰词
            attr_name = attr_name.rstrip("值度量级")
            # 如果属性名很长，尝试取末尾2-4字（去掉"送礼时""使用时"等前缀）
            if len(attr_name) > 4:
                # 取末尾的属性词
                for length in [2, 3, 4]:
                    tail = attr_name[-length:]
                    if tail in self._EFFECT_ATTR_MAP:
                        attr_name = tail
                        break

            results.append((attr_name.strip(), sign * float(value_str)))
        return results

    async def use_gift_item(
        self,
        item_id: str,
        recipient: str = "self",
        role_id: str = "",
        persona_filename: str = "",
    ) -> Dict[str, Any]:
        """使用/赠送非食物商品。

        从 gift_inventory 中扣除一件，解析 effect_desc，
        实际改变 mood_score / energy 等状态，联动 C++ 神经递质。

        Args:
            item_id: 商品ID
            recipient: 给谁用(self/aveline/ling)
            role_id: 当前角色ID
            persona_filename: 人设文件名
        """
        from core.services.life_simulation.service import get_life_simulation_service

        life_service = get_life_simulation_service()
        gift_inv = life_service.life_stats.get("gift_inventory")
        if not isinstance(gift_inv, list):
            return {"success": False, "message": "没有可使用的物品"}

        # 查找并扣除一件
        found_idx = -1
        item_info = None
        for i, entry in enumerate(gift_inv):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("item_id") or "").strip() == item_id:
                found_idx = i
                item_info = entry
                break

        if found_idx < 0:
            return {"success": False, "message": f"库存中没有该物品: {item_id}"}

        # 扣除数量
        current_qty = int(item_info.get("quantity", 1))
        if current_qty > 1:
            item_info["quantity"] = current_qty - 1
        else:
            gift_inv.pop(found_idx)

        # 获取商品信息
        shop_item = get_shop_item(item_id)
        item_name = shop_item.name if shop_item else item_info.get("item_name", item_id)
        item_icon = shop_item.icon if shop_item else ""
        effect_desc = shop_item.effect_desc if shop_item else item_info.get("effect_desc", "")
        rarity = shop_item.rarity if shop_item else "common"
        category = shop_item.category if shop_item else item_info.get("category", "")

        # 解析效果
        effects = self._parse_effect_desc(effect_desc)

        # 稀有度倍率
        rarity_mult = {"common": 1.0, "rare": 1.2, "epic": 1.5, "legendary": 2.0}.get(
            rarity, 1.0
        )

        # recipient 效果系数：给自己用 100%，送别人 80%（间接开心）
        recipient_mult = 1.0 if recipient == "self" else 0.8

        # 应用效果到 life_stats
        applied_effects = {}
        for attr_name, raw_delta in effects:
            stat_key = self._EFFECT_ATTR_MAP.get(attr_name)
            if not stat_key:
                continue

            delta = raw_delta * rarity_mult * recipient_mult
            # immune_damage 是反向的：减少 = 更健康
            if stat_key == "immune_damage":
                life_service.life_stats[stat_key] = max(
                    0.0,
                    float(life_service.life_stats.get(stat_key, 0.0)) - abs(delta),
                )
            else:
                life_service.life_stats[stat_key] = min(
                    100.0,
                    max(0.0, float(life_service.life_stats.get(stat_key, 0.0)) + delta),
                )

            applied_effects[attr_name] = delta

        # 联动 C++ 神经递质
        neuro_applied = {}
        try:
            from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

            engine = CPPSchedulerEngine()
            if engine.enabled and engine.bio_system:
                bio = engine.bio_system
                for attr_name, _ in effects:
                    neuro_info = self._NEURO_ATTR_MAP.get(attr_name)
                    if neuro_info:
                        nt_name, nt_delta = neuro_info
                        scaled = nt_delta * rarity_mult
                        bio.adjustNeurotransmitter(nt_name, scaled)
                        neuro_applied[attr_name] = f"{nt_name}{scaled:+.3f}"

                # 所有使用物品都给一点 dopamine（获得新东西的快感）
                base_dopamine = 0.02 * rarity_mult
                bio.adjustNeurotransmitter("dopamine", base_dopamine)
                neuro_applied["_base"] = f"dopamine{base_dopamine:+.3f}"
        except Exception as e:
            logger.warning(f"use_gift_item: 神经递质联动失败: {e}")

        # 记录使用事件
        try:
            events = life_service.life_stats.get("gift_events")
            if not isinstance(events, list):
                events = []
                life_service.life_stats["gift_events"] = events
            events.append({
                "type": "use",
                "item_id": item_id,
                "item_name": item_name,
                "category": category,
                "recipient": recipient,
                "effect_desc": effect_desc,
                "applied_effects": applied_effects,
                "timestamp": time.time(),
            })
            # 只保留最近 50 条
            if len(events) > 50:
                life_service.life_stats["gift_events"] = events[-50:]
        except Exception:
            pass

        # 标记最近使用的礼物（供对话上下文引用）
        life_service.life_stats["_last_gift_used"] = {
            "item_name": item_name,
            "item_id": item_id,
            "category": category,
            "recipient": recipient,
            "effect_desc": effect_desc,
            "timestamp": time.time(),
        }

        logger.info(
            f"使用物品: {item_name}({category}), recipient={recipient}, "
            f"effects={applied_effects}, neuro={neuro_applied}"
        )

        return {
            "success": True,
            "message": f"使用了 {item_name}",
            "item_id": item_id,
            "item_name": item_name,
            "icon": item_icon,
            "category": category,
            "rarity": rarity,
            "recipient": recipient,
            "applied_effects": applied_effects,
            "neuro_effects": neuro_applied,
        }

    def _calculate_taste_score(self, food: FoodItem) -> float:
        """
        Calculate how much the user likes the food based on preferences.
        1.0 is neutral. >1.0 is like. <1.0 is dislike.
        """
        score = 1.0
        t = food.taste

        # Weighted product of flavors
        if t.sweet > 0:
            score *= self.preferences["sweet"] * (1 + t.sweet)
        if t.spicy > 0:
            score *= self.preferences["spicy"] * (1 + t.spicy)
        if t.bitter > 0:
            score *= self.preferences["bitter"] * (1 - t.bitter * 0.5)
        if t.sour > 0:
            score *= self.preferences["sour"] * (1 + t.sour)

        # Normalize a bit
        return score


# Singleton
_food_manager = FoodManager()


def get_food_manager() -> FoodManager:
    return _food_manager
