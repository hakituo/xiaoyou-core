import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from unittest.mock import AsyncMock, MagicMock, patch


class TestCommandPrefix(unittest.IsolatedAsyncioTestCase):
    async def test_exclamation_marks_not_treated_as_commands(self):
        """测试 !!! 不应被视为指令，应返回 False 走普通聊天流程"""
        from clients.bots.qq.main import QQAdapter

        adapter = QQAdapter()
        adapter.system_handler = MagicMock()
        adapter.system_handler.show_help = AsyncMock()
        adapter.send_to_napcat = AsyncMock()

        result = await adapter._try_handle_command(
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            raw_message="!!!",
            group_id="",
        )
        self.assertFalse(result)
        adapter.system_handler.show_help.assert_not_called()
        adapter.send_to_napcat.assert_not_called()

    async def test_exclamation_with_text_not_treated_as_command(self):
        """测试 !!!后面跟文字不应被视为指令"""
        from clients.bots.qq.main import QQAdapter

        adapter = QQAdapter()
        adapter.system_handler = MagicMock()
        adapter.system_handler.show_help = AsyncMock()
        adapter.send_to_napcat = AsyncMock()

        result = await adapter._try_handle_command(
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            raw_message="!!!你好啊",
            group_id="",
        )
        self.assertFalse(result)
        adapter.system_handler.show_help.assert_not_called()
        adapter.send_to_napcat.assert_not_called()

    async def test_chinese_exclamation_marks_not_treated_as_commands(self):
        """测试中文感叹号！！！不应被视为指令"""
        from clients.bots.qq.main import QQAdapter

        adapter = QQAdapter()
        adapter.system_handler = MagicMock()
        adapter.system_handler.show_help = AsyncMock()
        adapter.send_to_napcat = AsyncMock()

        result = await adapter._try_handle_command(
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            raw_message="！！！今天天气真好",
            group_id="",
        )
        self.assertFalse(result)
        adapter.system_handler.show_help.assert_not_called()
        adapter.send_to_napcat.assert_not_called()

    async def test_slash_still_triggers_help(self):
        """测试单独发送 / 仍应触发帮助面板"""
        from clients.bots.qq.main import QQAdapter

        adapter = QQAdapter()
        adapter.system_handler = MagicMock()
        adapter.system_handler.show_help = AsyncMock()

        result = await adapter._try_handle_command(
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            raw_message="/",
            group_id="",
        )
        self.assertTrue(result)
        adapter.system_handler.show_help.assert_called_once_with("private_1")

    async def test_slash_help_triggers_help(self):
        """测试 /help 应触发帮助面板"""
        from clients.bots.qq.main import QQAdapter

        adapter = QQAdapter()
        adapter.system_handler = MagicMock()
        adapter.system_handler.show_help = AsyncMock()

        result = await adapter._try_handle_command(
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            raw_message="/help",
            group_id="",
        )
        self.assertTrue(result)
        adapter.system_handler.show_help.assert_called_once_with("private_1")

    async def test_slash_unknown_command_shows_error(self):
        """测试 /未知指令应显示错误提示"""
        from clients.bots.qq.main import QQAdapter

        adapter = QQAdapter()
        adapter.system_handler = MagicMock()
        adapter.system_handler.show_help = AsyncMock()
        adapter.send_to_napcat = AsyncMock()

        result = await adapter._try_handle_command(
            session_id="private_1",
            msg_type="private",
            qq_user_id="1",
            raw_message="/unknown",
            group_id="",
        )
        self.assertTrue(result)
        adapter.system_handler.show_help.assert_not_called()
        adapter.send_to_napcat.assert_called_once()
        call_args = adapter.send_to_napcat.call_args[0]
        self.assertIn("未识别的指令", call_args[1])


if __name__ == "__main__":
    unittest.main()
