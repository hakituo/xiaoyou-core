import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from clients.bots.handlers.command_router import CommandRouter


class _Dummy:
    def __init__(self):
        self.called = []
        self.api_response_map = {}
        self.cfg = type("Cfg", (), {"role_id": ""})()
        self.system_handler = self
        self.dashboard_handler = self
        self.resource_handler = self
        self.food_handler = self
        self.config_handler = self
        self.openclaw_handler = _OpenClawDummy(self.called)
        self.meme_handler = _MemeDummy(self.called)

    async def send_to_napcat(self, session_id, content):
        self.called.append(("send", session_id, content))

    async def show_help(self, session_id):
        self.called.append(("help", session_id))

    async def show_module_docs(self, session_id, rest):
        self.called.append(("docs", session_id, rest))

    async def handle_remote_screenshot(self, session_id, rest):
        self.called.append(("screenshot", session_id, rest))

    async def handle_remote_file(self, session_id, rest):
        self.called.append(("file_ops", session_id, rest))

    async def handle_approval(self, session_id, rest, is_reject):
        self.called.append(("approval", session_id, rest, is_reject))

    async def show_status(self, session_id, prefs, is_master, rest):
        self.called.append(("status", session_id, rest))

    async def show_models(self, session_id, prefs, rest):
        self.called.append(("models", session_id, rest))

    async def show_voices(self, session_id, prefs):
        self.called.append(("voices", session_id))

    async def show_food_menu(self, session_id, rest):
        self.called.append(("food_menu", session_id, rest))

    async def show_food_inventory(self, session_id):
        self.called.append(("food_inv", session_id))

    async def handle_food_buy(self, session_id, rest):
        self.called.append(("food_buy", session_id, rest))

    async def handle_food_eat(self, session_id, rest, prefs=None):
        self.called.append(("food_eat", session_id, rest, prefs))

    async def handle_switch_model(self, session_id, rest, prefs, user_id):
        self.called.append(("switch_model", session_id, rest, user_id))

    async def handle_switch_persona(self, session_id, rest, prefs, user_id):
        self.called.append(("switch_persona", session_id, rest, user_id))

    async def persist_user_override(self, qq_user_id, prefs):
        self.called.append(("save", qq_user_id))
        return True

    async def update_session_config(self, session_id, key, value):
        self.called.append(("update_session_config", session_id, key, value))
        return True

    async def _send_voice_response(self, session_id, text, reference_audio=None):
        self.called.append(("tts", session_id, text))
        return True

    async def _api_request(
        self,
        method,
        path,
        json_body=None,
        params=None,
        timeout_seconds=None,
    ):
        self.called.append(("api", method, path, json_body, params))
        key = (method, path)
        if key in self.api_response_map:
            return self.api_response_map[key]
        if method == "GET" and path == "/api/v1/sessions":
            return 200, {
                "status": "success",
                "data": [
                    {"id": "private_1", "title": "私聊会话"},
                    {"id": "group_100_2", "title": "群聊会话"},
                ],
            }
        if method == "GET" and path.startswith("/api/v1/sessions/") and path.endswith("/history"):
            return 200, {
                "status": "success",
                "data": [
                    {"id": "m1", "role": "user", "content": "你好"},
                    {"id": "m2", "role": "assistant", "content": "你好呀"},
                ],
            }
        return 200, {"status": "success"}

class _OpenClawDummy:
    def __init__(self, called):
        self.called = called

    async def show_help(self, session_id):
        self.called.append(("oc_help", session_id))

    async def show_status(self, session_id, prefs):
        self.called.append(("oc_status", session_id))

    async def set_or_show_model(self, session_id, prefs, model_arg):
        self.called.append(("oc_model", session_id, model_arg))

    async def show_models(self, session_id):
        self.called.append(("oc_models", session_id))

    async def handle_web_search(self, session_id, query, prefs):
        self.called.append(("oc_search", session_id, query))

    async def handle_task(self, session_id, task_text, prefs):
        self.called.append(("oc_task", session_id, task_text))


class _MemeDummy:
    def __init__(self, called):
        self.called = called

    async def show_categories(self, session_id):
        self.called.append(("meme_list", session_id))

    async def send_meme(self, session_id, query):
        self.called.append(("meme_send", session_id, query))
        return True


class TestCommandRouter(unittest.IsolatedAsyncioTestCase):
    async def test_basic_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="help",
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            group_id="",
            rest="",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "help" for x in adapter.called))

    async def test_master_guard(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="切模型",
            session_id="private_2",
            msg_type="private",
            qq_user_id="2",
            group_id="",
            rest="abc",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "send" and "权限不足" in x[2] for x in adapter.called))

    async def test_short_memory_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="clear",
            session_id="private_3",
            msg_type="private",
            qq_user_id="3",
            group_id="",
            rest="",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "api" and x[2] == "/api/v1/memories/clear" for x in adapter.called))
        clear_calls = [x for x in adapter.called if x[0] == "api" and x[2] == "/api/v1/memories/clear"]
        self.assertEqual(len(clear_calls), 1)
        self.assertEqual(clear_calls[0][3], {"user_id": "private_3", "mode": "short"})

    async def test_short_memory_route_with_persona(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="clear",
            session_id="private_3",
            msg_type="private",
            qq_user_id="3",
            group_id="",
            rest="",
            prefs={"persona_filename": "core/character/configs/core_ling.json"},
            is_master=False,
        )
        self.assertTrue(ok)
        clear_calls = [x for x in adapter.called if x[0] == "api" and x[2] == "/api/v1/memories/clear"]
        self.assertEqual(len(clear_calls), 3)
        self.assertEqual(clear_calls[0][3]["mode"], "short")
        self.assertTrue(
            str(clear_calls[0][3]["user_id"]).startswith("private_3__scope__")
        )
        self.assertEqual(
            clear_calls[1][3],
            {"user_id": "private_3__persona__core_ling", "mode": "short"},
        )
        self.assertEqual(clear_calls[2][3], {"user_id": "private_3", "mode": "short"})

    async def test_study_mode_on_off(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        prefs = {"mode": "normal"}

        ok = await router.dispatch(
            cmd_lower="学习模式",
            session_id="private_mode_1",
            msg_type="private",
            qq_user_id="31",
            group_id="",
            rest="on",
            prefs=prefs,
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(
            any(
                x[0] == "update_session_config"
                and x[2] == "mode"
                and x[3] == "study"
                for x in adapter.called
            )
        )

        adapter.called = []
        ok = await router.dispatch(
            cmd_lower="学习模式",
            session_id="private_mode_1",
            msg_type="private",
            qq_user_id="31",
            group_id="",
            rest="off",
            prefs={"mode": "study"},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(
            any(
                x[0] == "update_session_config"
                and x[2] == "mode"
                and x[3] == "normal"
                for x in adapter.called
            )
        )

    async def test_privacy_mode_on_off(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)

        ok = await router.dispatch(
            cmd_lower="私密模式",
            session_id="private_mode_2",
            msg_type="private",
            qq_user_id="32",
            group_id="",
            rest="on",
            prefs={"mode": "normal"},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(
            any(
                x[0] == "update_session_config"
                and x[2] == "mode"
                and x[3] == "privacy"
                for x in adapter.called
            )
        )

        adapter.called = []
        ok = await router.dispatch(
            cmd_lower="隐私模式",
            session_id="private_mode_2",
            msg_type="private",
            qq_user_id="32",
            group_id="",
            rest="off",
            prefs={"mode": "privacy"},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(
            any(
                x[0] == "update_session_config"
                and x[2] == "mode"
                and x[3] == "normal"
                for x in adapter.called
            )
        )

    async def test_openclaw_status_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="oc",
            session_id="private_4",
            msg_type="private",
            qq_user_id="4",
            group_id="",
            rest="状态",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "oc_status" for x in adapter.called))

    async def test_openclaw_model_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="oc",
            session_id="private_5",
            msg_type="private",
            qq_user_id="5",
            group_id="",
            rest="模型 anthropic/claude-opus-4-1",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "oc_model" and "anthropic/claude-opus-4-1" in x[2] for x in adapter.called))

    async def test_openclaw_model_list_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="oc",
            session_id="private_6",
            msg_type="private",
            qq_user_id="6",
            group_id="",
            rest="模型列表",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "oc_models" for x in adapter.called))

    async def test_search_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="搜索",
            session_id="private_7",
            msg_type="private",
            qq_user_id="7",
            group_id="",
            rest="今天金价",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "oc_search" and "今天金价" in x[2] for x in adapter.called))

    async def test_screenshot_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="截图",
            session_id="private_9",
            msg_type="private",
            qq_user_id="9",
            group_id="",
            rest="",
            prefs={},
            is_master=True,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "screenshot" for x in adapter.called))

    async def test_file_ops_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="文件",
            session_id="private_f1",
            msg_type="private",
            qq_user_id="12",
            group_id="",
            rest="读 notes/todo.md",
            prefs={},
            is_master=True,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "file_ops" and "读 notes/todo.md" in x[2] for x in adapter.called))

    async def test_approval_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        # Test Approve
        ok = await router.dispatch(
            cmd_lower="批准",
            session_id="private_a1",
            msg_type="private",
            qq_user_id="13",
            group_id="",
            rest="abcd-1234",
            prefs={},
            is_master=True,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "approval" and x[3] is False for x in adapter.called))
        
        # Test Reject
        adapter.called = []
        ok = await router.dispatch(
            cmd_lower="拒绝",
            session_id="private_a1",
            msg_type="private",
            qq_user_id="13",
            group_id="",
            rest="abcd-1234",
            prefs={},
            is_master=True,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "approval" and x[3] is True for x in adapter.called))

    async def test_sid_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="sid",
            session_id="group_111_222",
            msg_type="group",
            qq_user_id="222",
            group_id="111",
            rest="",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "send" and "Session ID: group_111_222" in x[2] for x in adapter.called))

    async def test_meme_route(self):
        adapter = _Dummy()
        router = CommandRouter(adapter)
        ok = await router.dispatch(
            cmd_lower="表情",
            session_id="private_m1",
            msg_type="private",
            qq_user_id="20",
            group_id="",
            rest="开心",
            prefs={},
            is_master=False,
        )
        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "meme_send" and "开心" in x[2] for x in adapter.called))

    async def test_sleep_wake_route_uses_current_persona_scope(self):
        adapter = _Dummy()
        adapter.api_response_map[("POST", "/api/v1/life/sleep/wake")] = (
            200,
            {
                "status": "success",
                "action": "woken_up",
                "role_id": "ling",
                "sleep_summary": {"phase": "night_awake"},
            },
        )
        router = CommandRouter(adapter)

        ok = await router.dispatch(
            cmd_lower="唤醒",
            session_id="private_3",
            msg_type="private",
            qq_user_id="3",
            group_id="",
            rest="",
            prefs={"persona_filename": "core/character/configs/core_ling.json"},
            is_master=True,
        )

        self.assertTrue(ok)
        wake_calls = [
            x for x in adapter.called if x[0] == "api" and x[2] == "/api/v1/life/sleep/wake"
        ]
        self.assertEqual(len(wake_calls), 1)
        self.assertEqual(
            wake_calls[0][3],
            {
                "role_id": "",
                "persona_filename": "core/character/configs/core_ling.json",
                "conversation_id": "private_3__persona__core_ling",
                "message": "QQ命令立即唤醒",
            },
        )
        self.assertTrue(any(x[0] == "send" and "已立即唤醒" in x[2] for x in adapter.called))

    async def test_sleep_wake_route_reports_already_awake(self):
        adapter = _Dummy()
        adapter.api_response_map[("POST", "/api/v1/life/sleep/wake")] = (
            200,
            {
                "status": "success",
                "action": "already_awake",
                "role_id": "aveline",
                "sleep_summary": {"phase": "fully_awake"},
            },
        )
        router = CommandRouter(adapter)

        ok = await router.dispatch(
            cmd_lower="wake",
            session_id="private_9",
            msg_type="private",
            qq_user_id="9",
            group_id="",
            rest="起来",
            prefs={"persona_filename": "qq/Aveline_QQ_Master.json"},
            is_master=True,
        )

        self.assertTrue(ok)
        self.assertTrue(any(x[0] == "send" and "当前没在睡" in x[2] for x in adapter.called))

    async def test_activity_interrupt_route_opens_chat_window(self):
        adapter = _Dummy()
        adapter.api_response_map[("POST", "/api/v1/life/activity/interrupt")] = (
            200,
            {
                "status": "success",
                "action": "interrupted",
                "role_id": "ling",
                "activity": "studying",
                "window_seconds": 600,
            },
        )
        router = CommandRouter(adapter)

        ok = await router.dispatch(
            cmd_lower="打断",
            session_id="private_3",
            msg_type="private",
            qq_user_id="3",
            group_id="",
            rest="先别学了陪我聊会",
            prefs={"persona_filename": "core/character/configs/core_ling.json"},
            is_master=True,
        )

        self.assertTrue(ok)
        interrupt_calls = [
            x for x in adapter.called if x[0] == "api" and x[2] == "/api/v1/life/activity/interrupt"
        ]
        self.assertEqual(len(interrupt_calls), 1)
        self.assertEqual(
            interrupt_calls[0][3],
            {
                "role_id": "",
                "persona_filename": "core/character/configs/core_ling.json",
                "conversation_id": "private_3__persona__core_ling",
                "message": "先别学了陪我聊会",
            },
        )
        self.assertTrue(any(x[0] == "send" and "已打断" in x[2] for x in adapter.called))
