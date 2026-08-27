import json
from typing import Optional, Type
from pydantic import BaseModel, Field
from core.tools.base import BaseTool
from core.food.manager import get_food_manager
from core.food.data import get_food, get_all_food
from core.services.dual_role.personas import resolve_role_id_from_persona
from core.utils.logger import get_logger
from core.utils.data_paths import get_aveline_life_records_dir, get_ling_life_records_dir
from core.utils.time_utils import get_current_time

logger = get_logger("FOOD_TOOL")


def _resolve_food_id(name: str, allow_random: bool = False) -> Optional[str]:
    name = str(name or "").strip().lower()
    if not name:
        return None

    if allow_random and name in ("随便", "任意", "都行", "都可以", "你选", "你决定"):
        import random
        all_foods = get_all_food()
        if all_foods:
            return random.choice(all_foods).id
        return None

    all_foods = get_all_food()
    for food in all_foods:
        if food.id == name:
            return food.id
        if name in food.name.lower():
            return food.id
        if food.name.lower() in name:
            return food.id

    for food in all_foods:
        food_name_lower = food.name.lower()
        if name in food_name_lower or food_name_lower in name:
            return food.id

    return None


def _get_food_list_description() -> str:
    foods = get_all_food()
    drinks = [f.name for f in foods if f.type == "drink"]
    snacks = [f.name for f in foods if f.type == "snack"]
    meals = [f.name for f in foods if f.type == "meal"]
    return (
        f"可用食物：\n"
        f"- 饮料：{', '.join(drinks)}\n"
        f"- 零食：{', '.join(snacks)}\n"
        f"- 正餐：{', '.join(meals)}\n"
        f"如果用户没有指定具体食物，可以选择一个合适的食物购买。"
    )


class BuyFoodInput(BaseModel):
    food_name: str = Field(
        description="食物名称或ID。例如：可乐、奶茶、拉面、汉堡、蛋糕等。"
        "如果用户没有指定具体食物，可以填'随便'或'任意'。"
    )
    quantity: int = Field(
        default=1,
        description="购买数量，默认为1。例如'买两杯奶茶'时quantity=2。"
    )


class BuyFoodTool(BaseTool):
    name = "buy_food"
    description = (
        "给Aveline购买食物，添加到她的库存中。"
        "当用户说'买点吃的'、'给我买杯奶茶'、'买两瓶可乐'时调用。\n" + _get_food_list_description()
    )
    args_schema: Type[BaseModel] = BuyFoodInput

    async def _run(self, food_name: str, quantity: int = 1) -> str:
        food_id = _resolve_food_id(food_name, allow_random=True)
        if not food_id:
            available = [f.name for f in get_all_food()[:10]]
            return f"找不到'{food_name}'这种食物。可用的食物有：{', '.join(available)}等。"

        quantity = max(1, min(quantity, 99))

        manager = get_food_manager()
        result = await manager.buy(food_id, quantity)

        if result.get("success"):
            food = get_food(food_id)
            name = food.name if food else food_id
            icon = food.icon if food else ""
            return f"已购买 {icon} {name} x{quantity}，已添加到库存！"
        else:
            return f"购买失败：{result.get('message', '未知错误')}"


class FeedFoodInput(BaseModel):
    food_name: str = Field(
        description="食物名称或ID。例如：可乐、奶茶、拉面等。"
    )


class FeedFoodTool(BaseTool):
    name = "feed_food"
    description = (
        "给Aveline投喂食物，让她直接吃掉。"
        "当用户说'给你吃个蛋糕'、'请你喝奶茶'、'投喂汉堡'、'吃点东西'时调用。\n"
        "如果库存有该食物会从库存扣除，没有则自动购买。\n" + _get_food_list_description()
    )
    args_schema: Type[BaseModel] = FeedFoodInput

    def _resolve_current_role_context(self) -> tuple[str, str]:
        agent = self._get_ctx("agent")
        user_id = str(self._get_ctx("user_id", "") or "").strip().lower()
        persona_filename = ""

        if agent and hasattr(agent, "persona_filename"):
            persona_filename = str(getattr(agent, "persona_filename", "") or "").strip()

        if not persona_filename:
            try:
                from core.character.managers.persona_manager import get_persona_manager

                persona_filename = str(
                    get_persona_manager().get_current_filename() or ""
                ).strip()
            except Exception:
                persona_filename = ""

        if "core_ling" in user_id or user_id.endswith("__ling") or "persona__core_ling" in user_id:
            return "ling", persona_filename
        if "aveline" in user_id or "persona__qq_aveline" in user_id:
            return "aveline", persona_filename

        role_id = str(
            resolve_role_id_from_persona(persona_filename=persona_filename)
        ).strip().lower()
        if role_id in {"aveline", "ling"}:
            return role_id, persona_filename
        return "aveline", persona_filename

    async def _run(self, food_name: str) -> str:
        food_id = _resolve_food_id(food_name)
        if not food_id:
            available = [f.name for f in get_all_food()[:10]]
            return f"找不到'{food_name}'这种食物。可用的有：{', '.join(available)}等。"

        manager = get_food_manager()
        role_id, persona_filename = self._resolve_current_role_context()
        result = await manager.eat(
            food_id,
            from_inventory=True,
            eater="user",
            role_id=role_id,
            persona_filename=persona_filename,
        )

        if result.get("success"):
            food = get_food(food_id)
            name = food.name if food else food_id
            icon = food.icon if food else ""
            reaction = result.get("reaction", "normal")
            rarity = result.get("rarity", "common")
            used_inventory = result.get("used_inventory", False)

            source_text = "从库存拿出" if used_inventory else "现买的"
            reaction_text = ""
            if reaction == "delicious":
                reaction_text = "她看起来很喜欢！"
            elif reaction == "dislike":
                reaction_text = "她好像不太喜欢..."
            else:
                reaction_text = "她开心地接受了。"

            rarity_text = ""
            if rarity == "rare":
                rarity_text = "（稀有食物！）"
            elif rarity == "epic":
                rarity_text = "（史诗级美食！）"
            elif rarity == "legendary":
                rarity_text = "（传说级盛宴！！）"

            target_name = "Ling" if role_id == "ling" else "Aveline"
            return f"投喂了 {icon} {name} 给{target_name}（{source_text}）。{reaction_text}{rarity_text}"
        else:
            return f"投喂失败：{result.get('message', '她拒绝了')}"


class ListFoodInput(BaseModel):
    food_type: Optional[str] = Field(
        default=None,
        description="食物类型筛选：drink(饮料)、snack(零食)、meal(正餐)。不填则列出全部。"
    )


class ListFoodTool(BaseTool):
    name = "list_food"
    description = (
        "列出可购买的食物列表。当用户问'有什么吃的'、'能买什么'、'看看菜单'时调用。"
    )
    args_schema: Type[BaseModel] = ListFoodInput

    async def _run(self, food_type: Optional[str] = None) -> str:
        manager = get_food_manager()
        foods = manager.get_menu(food_type)

        if not foods:
            return "没有找到可用的食物。"

        lines = ["📋 可购买的食物："]
        current_type = None

        for food in foods:
            if food.type != current_type:
                current_type = food.type
                type_names = {"drink": "饮料", "snack": "零食", "meal": "正餐"}
                lines.append(f"\n【{type_names.get(current_type, current_type)}】")

            rarity_icon = ""
            if food.rarity == "rare":
                rarity_icon = "⭐"
            elif food.rarity == "epic":
                rarity_icon = "💜"
            elif food.rarity == "legendary":
                rarity_icon = "💛"

            lines.append(f"  {food.icon} {food.name} {rarity_icon}- 饥饿+{food.nutrition.hunger}, 口渴+{food.nutrition.thirst}")

        lines.append("\n💡 说'买点[食物名]'即可购买！")
        return "\n".join(lines)


class GetAvelineMealsInput(BaseModel):
    pass


class GetAvelineMealsTool(BaseTool):
    name = "get_aveline_meals"
    description = "查看你自己（Aveline/Ling）今天吃了什么，返回今日饮食记录。"
    short_description = "查看自己今日饮食记录"
    category = "food"
    args_schema: Type[BaseModel] = GetAvelineMealsInput

    async def _run(self) -> str:
        try:
            from core.character.managers.persona_manager import get_persona_manager
            current_filename = str(get_persona_manager().get_current_filename() or "").lower()
            if "ling" in current_filename:
                base_dir = get_ling_life_records_dir()
                persona_name = "Ling"
            else:
                base_dir = get_aveline_life_records_dir()
                persona_name = "Aveline"
        except Exception:
            base_dir = get_aveline_life_records_dir()
            persona_name = "Aveline"

        now_dt = get_current_time()
        day_dir = base_dir / str(now_dt.year) / str(now_dt.month) / str(now_dt.day)
        file_path = day_dir / "daily_record.json"

        if not file_path.exists():
            return f"🍽️ {persona_name}今天还没有吃过东西呢。"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return f"🍽️ {persona_name}今天还没有吃过东西呢。"

        meals = data.get("meals", [])
        if not isinstance(meals, list) or not meals:
            return f"🍽️ {persona_name}今天还没有吃过东西呢。"

        lines = [f"🍽️ {persona_name}今天的饮食记录："]
        meal_count = 0
        for meal in meals:
            if not isinstance(meal, dict):
                continue
            meal_type = meal.get("type", "未知")
            content = meal.get("content", "")
            time_str = meal.get("time", "")

            type_names = {
                "正餐": "正餐",
                "meal": "正餐",
                "零食": "零食",
                "snack": "零食",
                "饮品": "饮品",
                "drink": "饮品",
                "breakfast": "早餐",
                "lunch": "午餐",
                "dinner": "晚餐",
            }
            type_display = type_names.get(meal_type, meal_type)

            if content.startswith("自主进食(ling):"):
                content = "自主进食:" + content.replace("自主进食(ling):", "").strip()
            elif content.startswith("自主进食:"):
                # 自主进食 = Aveline/七濑澪自己主动吃喝，与"被用户投喂"严格区分
                content = "自主进食:" + content.replace("自主进食:", "").strip()
            elif content.startswith("投喂(ling):"):
                # 被投喂 = 用户用 /吃 /喝 指令投喂给Ling(ling)
                content = content.replace("投喂(ling):", "被投喂:").strip()
            elif content.startswith("投喂:"):
                # 被投喂 = 用户用 /吃 /喝 指令投喂给Aveline/七濑澪
                content = content.replace("投喂:", "被投喂:").strip()

            time_display = f" ({time_str})" if time_str else ""
            lines.append(f"  - [{type_display}] {content}{time_display}")
            meal_count += 1

        if meal_count == 0:
            return f"🍽️ {persona_name}今天还没有吃过东西呢。"

        lines.append(f"\n💡 共计 {meal_count} 次进食。")
        lines.append(
            "注意区分：前缀「自主进食:」是她自己主动吃喝的，"
            "前缀「被投喂:」才是用户用指令投喂给她的。两者来源不同，"
            "不要将「自主进食」误说成是用户投喂的。"
        )
        return "\n".join(lines)


class ShowInventoryInput(BaseModel):
    pass


class ShowInventoryTool(BaseTool):
    name = "show_inventory"
    description = "查看Aveline的食物库存。当用户问'库存有什么'、'还有什么吃的'时调用。"
    args_schema: Type[BaseModel] = ShowInventoryInput

    async def _run(self) -> str:
        manager = get_food_manager()
        inventory = manager.get_inventory()

        if not inventory:
            return "📦 库存是空的！说'买点[食物名]'来补充库存吧。"

        lines = ["📦 当前库存："]
        for item in inventory:
            expire_str = ""
            if item.get("expire_at"):
                import time
                remaining = item["expire_at"] - time.time()
                if remaining > 0:
                    hours = int(remaining / 3600)
                    if hours < 24:
                        expire_str = f"（{hours}小时后过期）"
            lines.append(f"  {item.get('icon', '🍎')} {item.get('name', item.get('food_id'))} x{item.get('quantity', 1)} {expire_str}")

        return "\n".join(lines)


# ==================== 食物愿望清单（cravings / 食物商城） ====================
# 角色自主调用：当 Aveline/Ling 想吃什么、看到/听到/想到某种食物时，
# 调用 crave_food 把它写进愿望清单。下一顿做饭时会优先满足愿望。


class CraveFoodInput(BaseModel):
    food_name: str = Field(
        description="想吃的东西的名字或ID。例如：拉面、火锅、提拉米苏、麻辣烫、糖炒栗子等。"
        "支持模糊匹配（如'奶茶'会匹配到珍珠奶茶）。"
    )
    reason: str = Field(
        default="",
        description="为什么想吃（简短一句话）。例如：'看剧里在吃，馋了'、'最近心情低落想吃甜的'。"
        "可为空。",
    )


class CraveFoodTool(BaseTool):
    name = "crave_food"
    description = (
        "把想吃的东西加入愿望清单（食物商城）。"
        "当你（Aveline 或 Ling）突然想吃某样东西、看到或听到某种食物觉得嘴馋时调用。"
        "加入后下一顿做饭会优先做你想吃的，可能也会主动求投喂或自己买。\n"
        "示例：'我想吃火锅了'、'突然好想喝奶茶'、'看到剧里的烤鸭好馋' → 调用本工具。\n"
        + _get_food_list_description()
    )
    args_schema: Type[BaseModel] = CraveFoodInput

    async def _run(self, food_name: str, reason: str = "") -> str:
        food_id = _resolve_food_id(food_name, allow_random=False)
        if not food_id:
            available = [f.name for f in get_all_food()[:15]]
            return f"找不到'{food_name}'这种食物。可用的有：{', '.join(available)}等。"

        try:
            from core.services.life_simulation.service import get_life_simulation_service

            life_service = get_life_simulation_service()
        except Exception as exc:
            logger.warning(f"crave_food: life_simulation 不可用: {exc}")
            return "愿望清单暂时不可用，稍后再试。"

        entry = life_service.add_food_craving(food_id, reason=reason)
        if not entry:
            return f"想加'{food_name}'到愿望清单失败了，请换种说法再试。"

        food = get_food(food_id)
        name = food.name if food else food_id
        icon = food.icon if food else "🍽️"
        reason_text = f"，理由：{reason}" if reason else ""
        return f"✨ 已加入食物愿望清单：{icon} {name}{reason_text}。下次做饭或购物会优先考虑这个！"


class ListCravingsInput(BaseModel):
    pass


class ListCravingsTool(BaseTool):
    name = "list_food_cravings"
    description = (
        "查看自己的食物愿望清单（嘴馋清单）。"
        "当用户问'你最近想吃什么'、'有什么馋的吗'、'你的wishlist'时调用。"
    )
    args_schema: Type[BaseModel] = ListCravingsInput

    async def _run(self) -> str:
        try:
            from core.services.life_simulation.service import get_life_simulation_service

            life_service = get_life_simulation_service()
        except Exception as exc:
            logger.warning(f"list_food_cravings: life_simulation 不可用: {exc}")
            return "愿望清单暂时不可用。"

        active = life_service.get_food_cravings(only_active=True)
        if not active:
            return "🍽️ 目前没有特别想吃的东西。"

        lines = ["🍽️ 最近想吃的食物清单："]
        import time as _time

        for item in active:
            icon = item.get("icon", "🍴")
            name = item.get("food_name", item.get("food_id"))
            reason = item.get("reason", "")
            added_at = float(item.get("added_at") or 0.0)
            age_hours = int((_time.time() - added_at) / 3600.0) if added_at else 0
            age_str = f"{age_hours}小时前" if age_hours < 24 else f"{age_hours // 24}天前"
            reason_str = f"（{reason}）" if reason else ""
            lines.append(f"  {icon} {name} {reason_str}- 想了 {age_str}")

        lines.append(f"\n共 {len(active)} 项。下次做饭会优先做想吃的！")
        return "\n".join(lines)
