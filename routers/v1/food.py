# -*- coding: utf-8 -*-
"""食物（food）域。

管理菜单、库存，以及购买 / 食用食物的动作。
"""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from typing import List

from core.food.manager import get_food_manager, FoodManager
from core.food.models import FoodItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/food", tags=["食物系统"])


def _infer_persona_scope(
    persona_scope: str,
    role_id: str = "",
    persona_filename: str = "",
) -> str:
    scope = str(persona_scope or "").strip().lower()
    if scope in {"ling", "aveline"}:
        return scope
    explicit_role = str(role_id or "").strip().lower()
    if explicit_role in {"ling", "aveline"}:
        return explicit_role
    try:
        from core.services.dual_role.personas import resolve_role_id_from_persona

        resolved_role = str(
            resolve_role_id_from_persona(persona_filename=persona_filename)
        ).strip().lower()
        if resolved_role in {"ling", "aveline"}:
            return resolved_role
    except Exception:
        pass
    try:
        from core.character.managers.persona_manager import get_persona_manager

        filename = str(get_persona_manager().get_current_filename() or "").lower()
        if "ling" in filename:
            return "ling"
    except Exception:
        return "aveline"
    return "aveline"


@router.get("/menu", response_model=List[FoodItem], summary="获取食物菜单")
async def get_menu(
    type: str = Query(None, description="Filter by food type: meal, snack, drink"),
    manager: FoodManager = Depends(get_food_manager),
):
    return manager.get_menu(food_type=type)


@router.get("/shop/menu", summary="获取商城商品列表(分页)")
async def get_shop_menu(
    category: str = Query(None, description="商品类别: food/gift/toy/book/clothing, 空=全部"),
    page: int = Query(1, ge=1, description="页码(从1开始)"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    manager: FoodManager = Depends(get_food_manager),
):
    """商城商品列表, 支持按类别过滤和分页(懒加载)。"""
    return manager.get_shop_menu(category=category, page=page, page_size=page_size)


@router.get("/inventory", summary="获取食物库存")
async def get_inventory(manager: FoodManager = Depends(get_food_manager)):
    return {"success": True, "data": manager.get_inventory()}


@router.post("/buy/{food_id}", summary="购买商品(食物/礼物/玩具/书籍/服饰)")
async def buy_food(
    food_id: str,
    quantity: int = Query(1, ge=1, le=99),
    recipient: str = Query("self", description="给谁买: self/aveline/ling"),
    manager: FoodManager = Depends(get_food_manager),
):
    result = await manager.buy(food_id, quantity=quantity, recipient=recipient)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.get("/gift-inventory", summary="获取礼物/非食物商品库存")
async def get_gift_inventory(manager: FoodManager = Depends(get_food_manager)):
    """查看已购买的非食物商品(礼物/玩具/书籍/服饰/科技/奢侈品)。"""
    return {"success": True, "data": manager.get_gift_inventory()}


@router.post("/use-gift/{item_id}", summary="使用/赠送非食物商品")
async def use_gift_item(
    item_id: str,
    recipient: str = Query("self", description="给谁用: self/aveline/ling"),
    role_id: str = Query("", description="角色ID"),
    persona_filename: str = Query("", description="人设文件名"),
    manager: FoodManager = Depends(get_food_manager),
):
    """使用礼物库存中的非食物商品，执行效果(改变心情/精力等状态)。"""
    try:
        result = await manager.use_gift_item(
            item_id,
            recipient=recipient,
            role_id=role_id,
            persona_filename=persona_filename,
        )
        if not result.get("success"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        logger.error(f"使用礼物异常: item_id={item_id}, error={e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"使用处理异常: {type(e).__name__}: {e}"},
        )


@router.post("/eat/{food_id}", summary="食用食物")
async def eat_food(
    food_id: str,
    from_inventory: bool = Query(True),
    eater: str = Query("user"),
    persona_scope: str = Query("auto", description="角色作用域(auto/aveline/ling)"),
    role_id: str = Query("", description="显式角色ID（aveline/ling）"),
    persona_filename: str = Query("", description="当前会话人设文件名"),
    manager: FoodManager = Depends(get_food_manager),
):
    try:
        resolved_scope = _infer_persona_scope(
            persona_scope,
            role_id=role_id,
            persona_filename=persona_filename,
        )
        result = await manager.eat(
            food_id,
            from_inventory=from_inventory,
            eater=eater,
            persona_scope=resolved_scope,
            role_id=role_id,
            persona_filename=persona_filename,
        )
        if not result.get("success"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        logger.error(f"进食端点异常: food_id={food_id}, eater={eater}, error={e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"进食处理异常: {type(e).__name__}: {e}"},
        )
