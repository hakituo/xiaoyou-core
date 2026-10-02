"""商城钱包契约回归。"""

import pytest

from routers.v1.food import get_shop_menu


class _StubFoodManager:
    def get_shop_menu(self, category=None, page=1, page_size=20):
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "has_more": False,
        }


@pytest.mark.asyncio
async def test_shop_menu_exposes_authoritative_unlimited_wallet() -> None:
    result = await get_shop_menu(
        category=None,
        page=1,
        page_size=20,
        manager=_StubFoodManager(),
    )

    assert result["coins"] == 999_999_999
    assert result["unlimited_coins"] is True
    assert result["items"] == []
