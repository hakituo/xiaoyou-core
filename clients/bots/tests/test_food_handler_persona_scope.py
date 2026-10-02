import os
import sys
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from clients.bots.handlers.food import FoodHandler


class _Adapter:
    def __init__(self):
        self.called = []
        self.cfg = type(
            "Cfg",
            (),
            {"role_id": "", "persona_filename": ""},
        )()
        self.logger = None

    async def _api_request(
        self,
        method,
        path,
        json_body=None,
        params=None,
        timeout_seconds=None,
    ):
        self.called.append(("api", method, path, json_body, params))
        return 200, {"success": True, "message": "食用了 寿司"}

    async def send_to_napcat(self, session_id, content):
        self.called.append(("send", session_id, content))

    async def _send_friendly_error(self, session_id, context, error):
        self.called.append(("error", session_id, context, error))


class TestFoodHandlerPersonaScope(unittest.IsolatedAsyncioTestCase):
    async def test_handle_food_eat_uses_session_persona_filename(self):
        adapter = _Adapter()
        handler = FoodHandler(adapter)

        await handler.handle_food_eat(
            "private_1",
            "sushi",
            {"persona_filename": "core/character/configs/core_aveline.json"},
        )

        api_calls = [item for item in adapter.called if item[0] == "api"]
        self.assertEqual(len(api_calls), 1)
        self.assertEqual(api_calls[0][1], "POST")
        self.assertEqual(api_calls[0][2], "/api/v1/food/eat/sushi")
        self.assertEqual(
            api_calls[0][4],
            {
                "from_inventory": "true",
                "eater": "user",
                "role_id": "aveline",
                "persona_filename": "core/character/configs/core_aveline.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
