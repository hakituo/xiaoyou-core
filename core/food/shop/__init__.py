# -*- coding: utf-8 -*-
"""非食物商城商品聚合层。按 category 拆分子文件，此处汇总为 SHOP_ITEMS / EXTRA_ITEMS。"""
from .gifts import GIFTS
from .toys import TOYS
from .books import BOOKS
from .clothing import CLOTHING
from .tech import TECH
from .luxury import LUXURY

# shop_data 原有 4 类 -> SHOP_ITEMS
SHOP_ITEMS: list = []
SHOP_ITEMS.extend(GIFTS)
SHOP_ITEMS.extend(TOYS)
SHOP_ITEMS.extend(BOOKS)
SHOP_ITEMS.extend(CLOTHING)

# shop_extra 原有 2 类 -> EXTRA_ITEMS
EXTRA_ITEMS: list = []
EXTRA_ITEMS.extend(TECH)
EXTRA_ITEMS.extend(LUXURY)
