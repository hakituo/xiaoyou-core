from typing import Literal, Optional
from pydantic import BaseModel, Field


class NutritionProfile(BaseModel):
    hunger: float = Field(..., description="Hunger restoration (0-100)")
    thirst: float = Field(..., description="Thirst restoration (0-100)")
    energy: float = Field(0.0, description="Energy restoration (0-100)")
    health: float = Field(0.0, description="Health/Immune impact")


class TasteProfile(BaseModel):
    sweet: float = 0.0
    sour: float = 0.0
    bitter: float = 0.0
    spicy: float = 0.0
    salty: float = 0.0
    umami: float = 0.0
    temperature: Literal["hot", "cold", "room"] = "room"


class FoodItem(BaseModel):
    id: str
    name: str
    description: str
    price: int
    type: Literal["meal", "snack", "drink", "ingredient"]
    icon: str  # Emoji or URL

    nutrition: NutritionProfile
    taste: TasteProfile

    expire_hours: int = 24
    min_level: int = 1
    rarity: Literal["common", "rare", "epic", "legendary"] = "common"
    buff_desc: str = ""  # 对特殊效果的文本描述，会被注入 Prompt


class ShopItem(BaseModel):
    """通用商城商品模型，食物是其中的一个子集。

    食物类商品(food)有 nutrition/taste/expire_hours 等字段;
    非食物类商品(gift/toy/book/clothing)这些字段为 None, 用 effect_desc 描述使用效果。
    """
    id: str
    name: str
    description: str
    price: int
    category: Literal["food", "gift", "toy", "book", "clothing", "tech", "luxury"] = "food"
    # food 子类型: meal/snack/drink/ingredient; 非食物: 对应子类别
    sub_type: str = ""
    icon: str = ""

    # 食物专属字段(非食物为 None)
    nutrition: Optional[NutritionProfile] = None
    taste: Optional[TasteProfile] = None
    expire_hours: int = 24

    min_level: int = 1
    rarity: Literal["common", "rare", "epic", "legendary"] = "common"
    buff_desc: str = ""
    # 非食物商品的使用/赠送效果描述
    effect_desc: str = ""
