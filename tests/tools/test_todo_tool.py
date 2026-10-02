"""待办清单存储与工具测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.services.workspace.todo_store import TodoStore
from core.tools.todo_tool import ManageTodoTool, _resolve_scope


class _TodoStoreFixture:
    """给存储用例和工具用例共用一份临时清单文件。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="todo_store_")
        self.store = TodoStore(file_path=Path(self._tmp.name) / "todo_list.json")

    def tearDown(self):
        self._tmp.cleanup()


class TestTodoStore(_TodoStoreFixture, unittest.TestCase):
    def test_add_then_list(self):
        item = self.store.add_item("交数学作业", priority="high", due="周五前")
        self.assertEqual(item["id"], "1")
        self.assertEqual(item["priority"], "high")
        self.assertEqual(self.store.count_pending(), 1)
        self.assertEqual([row["title"] for row in self.store.list_items()], ["交数学作业"])

    def test_duplicate_pending_is_rejected(self):
        self.store.add_item("买牛奶")
        with self.assertRaises(ValueError):
            self.store.add_item("买牛奶")
        # 划掉之后可以重新记
        self.store.update_item("1", {"status": "done"})
        self.store.add_item("买牛奶")
        self.assertEqual(self.store.count_pending(), 1)

    def test_done_item_hidden_by_default(self):
        self.store.add_item("洗衣服")
        self.store.update_item("1", {"status": "done"})
        self.assertEqual(self.store.list_items(), [])
        self.assertEqual(self.store.count_pending(), 0)
        done_item = self.store.list_items(include_done=True)[0]
        self.assertEqual(done_item["status"], "done")
        self.assertTrue(done_item["completed_at"])

    def test_reopen_clears_completed_at(self):
        self.store.add_item("洗衣服")
        self.store.update_item("1", {"status": "done"})
        self.store.update_item("1", {"status": "pending"})
        self.assertEqual(self.store.list_items()[0]["completed_at"], "")

    def test_invalid_status_rejected(self):
        self.store.add_item("洗衣服")
        with self.assertRaises(ValueError):
            self.store.update_item("1", {"status": "finished"})

    def test_missing_item_rejected(self):
        with self.assertRaises(ValueError):
            self.store.update_item("99", {"status": "done"})
        with self.assertRaises(ValueError):
            self.store.remove_item("99")

    def test_remove_keeps_others(self):
        self.store.add_item("第一件")
        self.store.add_item("第二件")
        self.store.remove_item("1")
        self.assertEqual([row["title"] for row in self.store.list_items()], ["第二件"])

    def test_last_item_removed_deletes_file(self):
        self.store.add_item("第一件")
        self.assertTrue(self.store.file_path.exists())
        self.store.remove_item("1")
        self.assertFalse(self.store.file_path.exists())

    def test_high_priority_sorts_first(self):
        self.store.add_item("普通的")
        self.store.add_item("要紧的", priority="high")
        self.assertEqual(
            [row["title"] for row in self.store.list_items()], ["要紧的", "普通的"]
        )

    def test_corrupted_file_falls_back_to_empty(self):
        self.store.file_path.write_text("{不是合法 json", encoding="utf-8")
        self.assertEqual(self.store.list_items(), [])
        self.store.add_item("重新记一条")
        self.assertEqual(self.store.count_pending(), 1)

    def test_active_limit(self):
        for index in range(50):
            self.store.add_item(f"待办{index}")
        with self.assertRaises(ValueError):
            self.store.add_item("第五十一条")

    def test_format_for_prompt_empty_and_limited(self):
        self.assertEqual(self.store.format_for_prompt(), "")
        for index in range(6):
            self.store.add_item(f"待办{index}")
        text = self.store.format_for_prompt(limit=3)
        self.assertIn("当前待办 6 条", text)
        self.assertIn("只列前 3 条", text)
        self.assertEqual(len(text.strip().splitlines()), 4)


class TestTodoStoreScopeIsolation(unittest.TestCase):
    def test_each_role_has_its_own_file(self):
        with tempfile.TemporaryDirectory(prefix="todo_scope_") as directory:
            root = Path(directory)
            with patch("core.services.workspace.todo_store.get_role_data_dir") as get_dir:
                get_dir.side_effect = lambda scope: root / f"{scope}_data"
                aveline = TodoStore("aveline")
                ye = TodoStore("ye")
            self.assertNotEqual(aveline.file_path, ye.file_path)
            self.assertTrue(aveline.file_path.name.endswith("todo_list.json"))


class TestTodoTool(_TodoStoreFixture, unittest.IsolatedAsyncioTestCase):
    def _make_tool(self, persona: str = "core/character/configs/core_aveline.json"):
        tool = ManageTodoTool()
        tool.set_runtime_context({"persona_filename": persona, "user_id": "u1"})
        return tool

    async def test_add_done_remove_roundtrip(self):
        tool = self._make_tool()
        with patch("core.tools.todo_tool.get_todo_store", return_value=self.store):
            self.assertIn("现在没有待办", await tool._run("list"))

            added = await tool._run("add", title="提醒主人交作业")
            self.assertIn("记下了", added)
            self.assertIn("提醒主人交作业", added)

            listed = await tool._run("list")
            self.assertIn("待办 1 条", listed)

            done = await tool._run("done", item_id="1")
            self.assertIn("已划掉", done)
            self.assertIn("现在没有待办", await tool._run("list"))

            removed = await tool._run("remove", item_id="1")
            self.assertIn("删掉了", removed)
        self.assertFalse(self.store.file_path.exists())

    async def test_scope_is_resolved_from_persona(self):
        self.assertNotEqual(
            _resolve_scope("core/character/configs/core_aveline.json"),
            _resolve_scope("core/character/configs/ye/core_ye.json"),
        )

    async def test_tool_uses_role_scoped_store(self):
        tool = self._make_tool("core/character/configs/core_aveline.json")
        other = TodoStore(file_path=Path(self._tmp.name) / "other.json")
        with patch("core.tools.todo_tool.get_todo_store", return_value=other) as getter:
            await tool._run("add", title="只属于这个角色")
        self.assertTrue(getter.called)
        self.assertEqual(getter.call_args.args[0], "aveline")
        self.assertEqual(other.count_pending(), 1)
        self.assertEqual(self.store.count_pending(), 0)

    async def test_add_without_title_is_rejected(self):
        tool = self._make_tool()
        with patch("core.tools.todo_tool.get_todo_store", return_value=self.store):
            self.assertIn("title", await tool._run("add"))

    async def test_unknown_action_is_rejected(self):
        tool = self._make_tool()
        with patch("core.tools.todo_tool.get_todo_store", return_value=self.store):
            self.assertIn("action 只能是", await tool._run("archive"))

    async def test_unknown_item_returns_message(self):
        tool = self._make_tool()
        with patch("core.tools.todo_tool.get_todo_store", return_value=self.store):
            self.assertIn("找不到待办", await tool._run("done", item_id="42"))

    async def test_duplicate_add_returns_message(self):
        tool = self._make_tool()
        with patch("core.tools.todo_tool.get_todo_store", return_value=self.store):
            await tool._run("add", title="买牛奶")
            result = await tool._run("add", title="买牛奶")
        self.assertIn("已经有同样的待办", result)
        self.assertEqual(self.store.count_pending(), 1)

    async def test_store_file_shape(self):
        tool = self._make_tool()
        with patch("core.tools.todo_tool.get_todo_store", return_value=self.store):
            await tool._run("add", title="写周报")
        raw = json.loads(self.store.file_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertEqual(raw["items"][0]["title"], "写周报")


if __name__ == "__main__":
    unittest.main()
