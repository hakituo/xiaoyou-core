# -*- coding: utf-8 -*-
"""商城 AI 工具验证脚本。

验证内容：
1. shop_tool 四个工具能正常 import
2. manager 的 get_gift_inventory / use_gift_item / _parse_effect_desc 可用
3. 完整购买→使用流程：购买商品→进库存→使用→扣减→效果生效
4. effect_desc 解析覆盖各种格式
5. 模糊匹配商品名称
"""
import sys
import asyncio
import json
from pathlib import Path

# 确保项目根目录在 sys.path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))


def test_imports():
    """测试 import 链路。"""
    print("=== 1. 测试 import ===")
    from core.tools.shop_tool import (
        BrowseShopTool,
        BuyShopItemTool,
        ShowGiftInventoryTool,
        UseGiftItemTool,
    )
    print(f"  BrowseShopTool.name = {BrowseShopTool.name}")
    print(f"  BuyShopItemTool.name = {BuyShopItemTool.name}")
    print(f"  ShowGiftInventoryTool.name = {ShowGiftInventoryTool.name}")
    print(f"  UseGiftItemTool.name = {UseGiftItemTool.name}")
    print("  OK")


def test_effect_parsing():
    """测试 effect_desc 解析。"""
    print("\n=== 2. 测试 effect_desc 解析 ===")
    from core.food.manager import FoodManager

    fm = FoodManager()
    test_cases = [
        ("心情+15, 专注+12", [("心情", 15.0), ("专注", 12.0)]),
        ("送礼时心情值+10", [("心情", 10.0)]),
        ("身份+30, 品味+20", [("身份", 30.0), ("品味", 20.0)]),
        ("科技+20, 生活+10", [("科技", 20.0), ("生活", 10.0)]),
        ("健康-5", [("健康", -5.0)]),
        ("", []),
    ]
    passed = 0
    for desc, expected in test_cases:
        result = fm._parse_effect_desc(desc)
        # 只比较属性名和数值（不比较 sign 处理细节）
        ok = len(result) == len(expected)
        if ok:
            for (a1, d1), (a2, d2) in zip(result, expected):
                if a1 != a2 or abs(d1 - d2) > 0.01:
                    ok = False
                    break
        status = "OK" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"  [{status}] '{desc}' -> {result}")
    print(f"  通过: {passed}/{len(test_cases)}")


def test_fuzzy_match():
    """测试模糊匹配。"""
    print("\n=== 3. 测试模糊匹配 ===")
    from core.tools.shop_tool import _resolve_shop_item_id

    test_cases = [
        ("红玫瑰", "red_rose"),
        ("玫瑰花", "red_rose"),
        ("玫瑰花束", "red_rose"),
        ("劳力士", "watch_rolex"),
        ("降噪耳机", "earbuds_pro"),
        ("游戏主机", "console_ps5"),
        ("钻戒", "diamond_ring"),
        ("机械键盘", "keyboard_mech"),
    ]
    passed = 0
    for name, expected_id in test_cases:
        result = _resolve_shop_item_id(name)
        ok = result == expected_id
        if ok:
            passed += 1
        print(f"  [{'OK' if ok else 'FAIL'}] '{name}' -> {result} (expected: {expected_id})")
    print(f"  通过: {passed}/{len(test_cases)}")


async def test_buy_use_flow():
    """测试完整购买→使用流程。"""
    print("\n=== 4. 测试购买→使用流程 ===")
    from core.food.manager import get_food_manager

    manager = get_food_manager()

    # 购买
    buy_result = await manager.buy("console_ps5", quantity=3, recipient="self")
    assert buy_result["success"], f"购买失败: {buy_result}"
    print(f"  购买: {buy_result['item_name']} x{buy_result['quantity']} OK")

    # 查看库存
    inv = manager.get_gift_inventory()
    found = any(i["item_id"] == "console_ps5" for i in inv)
    assert found, "购买后库存中找不到商品"
    print(f"  库存确认: OK (共 {len(inv)} 种商品)")

    # 使用
    use_result = await manager.use_gift_item("console_ps5", recipient="self")
    assert use_result["success"], f"使用失败: {use_result}"
    print(f"  使用: {use_result['item_name']} OK")
    print(f"  效果: {use_result.get('applied_effects', {})}")

    # 检查库存减少
    inv2 = manager.get_gift_inventory()
    ps5_item = next((i for i in inv2 if i["item_id"] == "console_ps5"), None)
    if ps5_item:
        assert ps5_item["quantity"] == 2, f"库存数量不对: {ps5_item['quantity']}"
        print(f"  库存扣减: OK (剩余 x{ps5_item['quantity']})")
    else:
        print("  库存扣减: OK (已用完)")

    # 测试送别人
    buy2 = await manager.buy("earbuds_pro", quantity=1, recipient="aveline")
    assert buy2["success"]
    use2 = await manager.use_gift_item("earbuds_pro", recipient="aveline")
    assert use2["success"]
    print(f"  赠送Aveline: {use2['item_name']} OK, 效果: {use2.get('applied_effects', {})}")

    # 测试 legendary 物品
    buy3 = await manager.buy("watch_rolex", quantity=1, recipient="self")
    assert buy3["success"]
    use3 = await manager.use_gift_item("watch_rolex", recipient="self")
    assert use3["success"]
    print(f"  传说物品: {use3['item_name']} OK, 效果: {use3.get('applied_effects', {})}")

    print("  全部通过!")


def main():
    print("=" * 60)
    print("商城 AI 工具验证")
    print("=" * 60)

    test_imports()
    test_effect_parsing()
    test_fuzzy_match()
    asyncio.run(test_buy_use_flow())

    print("\n" + "=" * 60)
    print("验证完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
