# -*- coding: utf-8 -*-
"""食物商品数据聚合层。

食物数据按类别拆分到独立文件管理：
  - drinks.py  -> DRINKS  (type=drink 饮料)
  - snacks.py  -> SNACKS  (type=snack 零食/小吃/甜点)
  - meals.py   -> MEALS   (type=meal  正餐/汤/粥/地方菜/国际菜/节日正餐)

本文件汇总为统一的 FOOD_DB，并对调用方暴露原有接口，
因此 food_tool.py / shop_tool.py / auto_eat.py 等无需改动。
"""
from .models import FoodItem, ShopItem
from .drinks import DRINKS
from .snacks import SNACKS
from .meals import MEALS

# 统一食物库：按类别文件汇总
FOOD_DB: dict[str, FoodItem] = {}
for _db in (DRINKS, SNACKS, MEALS):
    FOOD_DB.update(_db)


def get_all_food() -> list[FoodItem]:
    return list(FOOD_DB.values())


def get_food(food_id: str) -> FoodItem | None:
    return FOOD_DB.get(food_id)


# 按类别查询
def get_foods_by_type(food_type: str) -> list[FoodItem]:
    return [f for f in FOOD_DB.values() if f.type == food_type]


# ===== 商城非食物商品（按 category 拆分子文件，见 core/food/shop/）=====
from .shop import SHOP_ITEMS, EXTRA_ITEMS

# 所有商品(食物+非食物)的统一查询接口
_ALL_SHOP_ITEMS: list[ShopItem] = []
_SHOP_ITEM_MAP: dict[str, ShopItem] = {}

# 把 FoodItem 转成 ShopItem 统一管理
for _f in FOOD_DB.values():
    _si = ShopItem(
        id=_f.id, name=_f.name, description=_f.description, price=_f.price,
        category="food", sub_type=_f.type, icon=_f.icon,
        nutrition=_f.nutrition, taste=_f.taste, expire_hours=_f.expire_hours,
        min_level=_f.min_level, rarity=_f.rarity, buff_desc=_f.buff_desc,
    )
    _ALL_SHOP_ITEMS.append(_si)
    _SHOP_ITEM_MAP[_f.id] = _si

# 追加非食物商品
for _si2 in SHOP_ITEMS:
    _ALL_SHOP_ITEMS.append(_si2)
    _SHOP_ITEM_MAP[_si2.id] = _si2

# 追加科技产品和奢侈品
for _si3 in EXTRA_ITEMS:
    _ALL_SHOP_ITEMS.append(_si3)
    _SHOP_ITEM_MAP[_si3.id] = _si3


def get_all_shop_items() -> list[ShopItem]:
    """返回全部商城商品(食物+礼物+玩具+书籍+服饰)。"""
    return list(_ALL_SHOP_ITEMS)


def get_shop_item(item_id: str) -> ShopItem | None:
    """按 id 查询单个商城商品(食物或非食物)。"""
    return _SHOP_ITEM_MAP.get(item_id)
