import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.tools.food_tool import FeedFoodTool


class TestFeedFoodToolPersonaScope(unittest.IsolatedAsyncioTestCase):
    async def test_feed_food_tool_uses_runtime_persona_context(self):
        tool = FeedFoodTool()
        tool.set_runtime_context(
            {
                "user_id": "private_1__persona__core_aveline",
                "agent": SimpleNamespace(
                    persona_filename="core/character/configs/core_aveline.json"
                ),
            }
        )

        mock_manager = SimpleNamespace(
            eat=AsyncMock(
                return_value={
                    "success": True,
                    "reaction": "normal",
                    "rarity": "common",
                    "used_inventory": True,
                }
            )
        )

        with (
            patch("core.tools.food_tool._resolve_food_id", return_value="sushi"),
            patch("core.tools.food_tool.get_food_manager", return_value=mock_manager),
            patch(
                "core.tools.food_tool.get_food",
                return_value=SimpleNamespace(name="寿司", icon="🍣"),
            ),
        ):
            result = await tool._run("寿司")

        self.assertIn("给Aveline", result)
        self.assertEqual(mock_manager.eat.await_count, 1)
        self.assertEqual(
            mock_manager.eat.await_args.kwargs,
            {
                "from_inventory": True,
                "eater": "user",
                "role_id": "aveline",
                "persona_filename": "core/character/configs/core_aveline.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
