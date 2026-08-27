# -*- coding: utf-8 -*-
"""商城 AI 工具集。

让 AI 角色可以：
1. 浏览商城（先选类别再看商品，不全量注入 LLM）
2. 自主购买任何类别商品（食物/礼物/玩具/书籍/服饰/科技/奢侈品）
3. 查看已购买的非食物物品库存
4. 使用/赠送非食物商品，执行 effect_desc 效果
"""
import re
import time
from typing import Optional, Type
from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.food.manager import get_food_manager
from core.food.data import get_all_shop_items, get_shop_item
from core.utils.logger import get_logger

logger = get_logger("SHOP_TOOL")


# ==================== 1. 浏览商城 ====================

class BrowseShopInput(BaseModel):
    category: Optional[str] = Field(
        default=None,
        description=(
            "商品类别筛选。可选值: food(食物), gift(礼物), toy(玩具), "
            "book(书籍), clothing(服饰), tech(科技), luxury(奢侈品)。"
            "不填则列出所有类别的概览。"
        ),
    )
    page: int = Field(
        default=1,
        description="页码，从1开始。每页返回20个商品。",
    )


class BrowseShopTool(BaseTool):
    name = "browse_shop"
    description = (
        "浏览商城，查看可购买的商品。"
        "可以按类别筛选(food/gift/toy/book/clothing/tech/luxury)，也可以翻页。"
        "当用户说'看看商城'、'有什么可以买的'、'想买个礼物'、'看看有什么科技产品'时调用。"
        "不传 category 时会先列出所有类别和商品数量，帮你选类别。"
    )
    short_description = "浏览商城(选类别看商品,支持分页)"
    args_schema: Type[BaseModel] = BrowseShopInput
    category = "life"

    async def _run(
        self,
        category: Optional[str] = None,
        page: int = 1,
    ) -> str:
        manager = get_food_manager()

        # 没指定类别 → 列出所有类别概览
        if not category or category == "all":
            all_items = get_all_shop_items()
            cat_counts: dict[str, int] = {}
            for item in all_items:
                cat_counts[item.category] = cat_counts.get(item.category, 0) + 1

            cat_names = {
                "food": "食物",
                "gift": "礼物",
                "toy": "玩具",
                "book": "书籍",
                "clothing": "服饰",
                "tech": "科技产品",
                "luxury": "奢侈品",
            }
            lines = ["🏪 商城概览："]
            for cat_key in ["food", "gift", "toy", "book", "clothing", "tech", "luxury"]:
                count = cat_counts.get(cat_key, 0)
                display = cat_names.get(cat_key, cat_key)
                lines.append(f"  {display}({cat_key}) - {count} 件商品")
            lines.append(
                "\n💡 想看某个类别，告诉我类别名即可。"
                "比如'看看礼物'、'有什么科技产品'。"
            )
            return "\n".join(lines)

        # 指定了类别 → 分页返回商品
        result = manager.get_shop_menu(
            category=category, page=page, page_size=20
        )
        items = result.get("items", [])
        total = result.get("total", 0)
        has_more = result.get("has_more", False)

        if not items:
            return f"商城里没有找到 '{category}' 类别的商品。"

        cat_names = {
            "food": "食物",
            "gift": "礼物",
            "toy": "玩具",
            "book": "书籍",
            "clothing": "服饰",
            "tech": "科技产品",
            "luxury": "奢侈品",
        }
        cat_display = cat_names.get(category, category)
        lines = [f"🏪 {cat_display} 商城（第 {page} 页，共 {total} 件）："]

        for item in items:
            name = item.get("name", "")
            icon = item.get("icon", "")
            price = item.get("price", 0)
            rarity = item.get("rarity", "common")
            effect = item.get("effect_desc", "")

            rarity_icon = ""
            if rarity == "rare":
                rarity_icon = "⭐"
            elif rarity == "epic":
                rarity_icon = "💜"
            elif rarity == "legendary":
                rarity_icon = "💛"

            effect_text = f" [{effect}]" if effect else ""
            lines.append(f"  {icon} {name} {rarity_icon}- {price}金币{effect_text}")

        if has_more:
            lines.append(f"\n💡 还有更多，翻到第 {page + 1} 页看看？")
        else:
            lines.append("\n已经到底啦！")

        return "\n".join(lines)


# ==================== 2. 购买商品 ====================

class BuyShopItemInput(BaseModel):
    item_name: str = Field(
        description=(
            "商品名称或ID。例如：玫瑰花束、旗舰手机、劳力士手表、机械键盘等。"
            "支持模糊匹配。如果不确定具体商品名，可以先调用 browse_shop 浏览。"
        )
    )
    quantity: int = Field(
        default=1,
        description="购买数量，默认为1。",
    )
    recipient: str = Field(
        default="self",
        description=(
            "给谁买的。可选: self(给自己), aveline(给Aveline/七濑澪), ling(给Ling)。"
            "默认 self。"
        ),
    )


class BuyShopItemTool(BaseTool):
    name = "buy_shop_item"
    description = (
        "在商城购买商品（食物/礼物/玩具/书籍/服饰/科技/奢侈品均可）。"
        "购买后食物进食物库存，非食物进礼物库存。"
        "当用户说'买个礼物'、'买个手机'、'给我买块手表'、'送她一束花'时调用。"
        "支持指定给谁买(recipient)。\n"
        "如果想看有什么可买，先调用 browse_shop 浏览商城。"
    )
    short_description = "购买商城商品(礼物/科技/奢侈品等,可选给谁买)"
    args_schema: Type[BaseModel] = BuyShopItemInput
    category = "life"

    async def _run(
        self,
        item_name: str,
        quantity: int = 1,
        recipient: str = "self",
    ) -> str:
        # 模糊匹配商品
        item_id = _resolve_shop_item_id(item_name)
        if not item_id:
            return f"在商城里找不到 '{item_name}'。可以调用 browse_shop 看看有什么可买的。"

        quantity = max(1, min(quantity, 99))

        manager = get_food_manager()
        result = await manager.buy(item_id, quantity, recipient=recipient)

        if result.get("success"):
            item = get_shop_item(item_id)
            name = item.name if item else item_id
            icon = item.icon if item else ""
            cat_display = _get_category_display(item.category if item else "")

            recipient_text = ""
            if recipient and recipient != "self":
                recipient_names = {"aveline": "Aveline", "ling": "Ling"}
                recipient_text = f"，送给{recipient_names.get(recipient, recipient)}"

            return f"已购买 {icon} {name} x{quantity}{recipient_text}！({cat_display})"
        else:
            return f"购买失败：{result.get('message', '未知错误')}"


# ==================== 3. 查看礼物库存 ====================

class ShowGiftInventoryInput(BaseModel):
    pass


class ShowGiftInventoryTool(BaseTool):
    name = "show_gift_inventory"
    description = (
        "查看已购买的非食物商品库存（礼物/玩具/书籍/服饰/科技/奢侈品）。"
        "当用户问'我买了什么'、'库存有什么礼物'、'还有什么没用'时调用。"
        "食物库存请用 show_inventory 工具查看。"
    )
    short_description = "查看礼物/非食物商品库存"
    args_schema: Type[BaseModel] = ShowGiftInventoryInput
    category = "life"

    async def _run(self) -> str:
        manager = get_food_manager()
        inventory = manager.get_gift_inventory()

        if not inventory:
            return "📦 礼物库存是空的！说'买个礼物'或调用 browse_shop 看看有什么可买的。"

        cat_names = {
            "gift": "礼物",
            "toy": "玩具",
            "book": "书籍",
            "clothing": "服饰",
            "tech": "科技",
            "luxury": "奢侈品",
        }

        # 按类别分组展示
        by_category: dict[str, list] = {}
        for item in inventory:
            cat = item.get("category", "other")
            by_category.setdefault(cat, []).append(item)

        lines = ["📦 礼物库存："]
        for cat_key in ["gift", "toy", "book", "clothing", "tech", "luxury"]:
            items = by_category.get(cat_key)
            if not items:
                continue
            cat_display = cat_names.get(cat_key, cat_key)
            lines.append(f"\n【{cat_display}】")
            for item in items:
                shop_item = get_shop_item(item["item_id"])
                icon = shop_item.icon if shop_item else ""
                name = item.get("item_name", item["item_id"])
                qty = item.get("quantity", 1)
                effect = item.get("effect_desc", "")
                recipient = item.get("recipient", "self")
                recipient_text = ""
                if recipient and recipient != "self":
                    recipient_names = {"aveline": "→Aveline", "ling": "→Ling"}
                    recipient_text = f" {recipient_names.get(recipient, recipient)}"
                effect_text = f" [{effect}]" if effect else ""
                lines.append(f"  {icon} {name} x{qty}{recipient_text}{effect_text}")

        lines.append("\n💡 说'使用[商品名]'或调用 use_gift_item 来使用/赠送！")
        return "\n".join(lines)


# ==================== 4. 使用/赠送商品 ====================

class UseGiftItemInput(BaseModel):
    item_name: str = Field(
        description=(
            "要使用的商品名称或ID。例如：玫瑰花束、降噪耳机、机械键盘等。"
            "必须是礼物库存里已有的商品。"
        )
    )
    recipient: str = Field(
        default="self",
        description=(
            "给谁用。可选: self(自己用), aveline(给Aveline), ling(给Ling)。"
            "默认 self。送别人时效果会稍微降低但仍然有效。"
        ),
    )


class UseGiftItemTool(BaseTool):
    name = "use_gift_item"
    description = (
        "使用或赠送礼物库存里的非食物商品。"
        "使用后会消耗一件，并根据商品效果实际改变心情、精力等状态。"
        "当用户说'戴上手表'、'用这个耳机'、'把礼物送给她'、'穿上裙子'时调用。"
        "注意：只能使用礼物库存里已有的商品，先调用 show_gift_inventory 查看。"
    )
    short_description = "使用/赠送礼物(执行效果,改变状态)"
    args_schema: Type[BaseModel] = UseGiftItemInput
    category = "life"

    async def _run(
        self,
        item_name: str,
        recipient: str = "self",
    ) -> str:
        # 先模糊匹配商品ID
        item_id = _resolve_shop_item_id(item_name)
        if not item_id:
            return f"找不到 '{item_name}' 这种商品。可以调用 show_gift_inventory 看看库存有什么。"

        # 检查库存里有没有
        manager = get_food_manager()
        inventory = manager.get_gift_inventory()
        found = False
        for inv_item in inventory:
            if inv_item.get("item_id") == item_id:
                found = True
                break

        if not found:
            item = get_shop_item(item_id)
            name = item.name if item else item_name
            return f"礼物库存里没有 '{name}'。需要先购买才能使用。"

        # 解析角色上下文
        agent = self._get_ctx("agent")
        user_id = str(self._get_ctx("user_id", "") or "").strip().lower()
        persona_filename = ""
        if agent and hasattr(agent, "persona_filename"):
            persona_filename = str(getattr(agent, "persona_filename", "") or "").strip()

        role_id = ""
        if "ling" in user_id or "core_ling" in user_id:
            role_id = "ling"
        elif "aveline" in user_id:
            role_id = "aveline"

        result = await manager.use_gift_item(
            item_id=item_id,
            recipient=recipient,
            role_id=role_id,
            persona_filename=persona_filename,
        )

        if result.get("success"):
            item = get_shop_item(item_id)
            name = result.get("item_name", item.name if item else item_id)
            icon = item.icon if item else ""
            effects = result.get("applied_effects", {})

            effect_lines = []
            for attr, delta in effects.items():
                sign = "+" if delta >= 0 else ""
                effect_lines.append(f"{attr}{sign}{delta:.0f}")
            effect_text = "，".join(effect_lines) if effect_lines else "无效果"

            recipient_names = {"self": "自己", "aveline": "Aveline", "ling": "Ling"}
            recipient_text = recipient_names.get(recipient, recipient)

            return f"✨ {recipient_text}使用了 {icon} {name}！效果: {effect_text}"
        else:
            return f"使用失败：{result.get('message', '未知错误')}"


# ==================== 辅助函数 ====================

def _resolve_shop_item_id(name: str) -> Optional[str]:
    """模糊匹配商品名称到 ID。"""
    name = str(name or "").strip().lower()
    if not name:
        return None

    all_items = get_all_shop_items()

    # 精确匹配 ID
    for item in all_items:
        if item.id == name:
            return item.id

    # 精确匹配名称
    for item in all_items:
        if item.name.lower() == name:
            return item.id

    # 模糊匹配：名称包含
    for item in all_items:
        if name in item.name.lower():
            return item.id

    # 模糊匹配：名称被包含
    for item in all_items:
        if item.name.lower() in name:
            return item.id

    # 分词模糊匹配：去掉"花""子""机"等常见后缀再匹配
    import re as _re
    # 去掉常见后缀字
    suffixes = ["花束", "花", "子", "机", "的", "一个", "个", "台", "块", "件", "本", "双", "只", "条", "瓶", "束"]
    cleaned = name
    for s in suffixes:
        cleaned = cleaned.replace(s, "")
    if cleaned and cleaned != name:
        for item in all_items:
            if cleaned in item.name.lower() or item.name.lower() in cleaned:
                return item.id

    return None


def _get_category_display(category: str) -> str:
    """类别英文转中文。"""
    names = {
        "food": "食物",
        "gift": "礼物",
        "toy": "玩具",
        "book": "书籍",
        "clothing": "服饰",
        "tech": "科技",
        "luxury": "奢侈品",
    }
    return names.get(category, category)
