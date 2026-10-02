import os
import tempfile
import unittest

from clients.bots.handlers.meme import MemeHandler


class _DummyAdapter:
    def __init__(self, project_root: str):
        self._project_root = project_root
        self.logger = None
        self.sent = []

    async def send_to_napcat(self, session_id, content):
        self.sent.append((session_id, content))


class TestMemeHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = self._tmp.name
        self.memes_root = os.path.join(
            self.project_root,
            "data",
            "memes",
        )
        # 创建普通分类目录 + manual 目录（应被 _list_categories 排除）
        for cat in ("happy", "angry", "morning"):
            os.makedirs(os.path.join(self.memes_root, cat), exist_ok=True)
        os.makedirs(os.path.join(self.memes_root, "manual", "sensitive"), exist_ok=True)
        for cat in ("happy", "angry", "morning"):
            with open(os.path.join(self.memes_root, cat, "1.png"), "wb") as f:
                f.write(b"fake")
        self.adapter = _DummyAdapter(self.project_root)
        self.handler = MemeHandler(self.adapter)

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_categories_excludes_manual(self):
        """_list_categories 应排除 manual 子目录。"""
        cats = self.handler._list_categories()
        self.assertIn("happy", cats)
        self.assertIn("angry", cats)
        self.assertIn("morning", cats)
        self.assertNotIn("manual", cats)

    async def test_send_meme_by_category(self):
        """send_meme 按分类名发图。"""
        ok = await self.handler.send_meme("s1", "happy")
        self.assertTrue(ok)
        self.assertEqual(len(self.adapter.sent), 1)
        self.assertIn("[CQ:image", self.adapter.sent[0][1])

    async def test_send_meme_random(self):
        """send_meme 随机发图。"""
        ok = await self.handler.send_meme("s2", "")
        self.assertTrue(ok)
        self.assertEqual(len(self.adapter.sent), 1)

    async def test_send_meme_chinese_alias(self):
        """send_meme 支持中文别名（开心→happy）。"""
        ok = await self.handler.send_meme("s3", "开心")
        self.assertTrue(ok)
        self.assertEqual(len(self.adapter.sent), 1)

    async def test_send_meme_unknown_category(self):
        """send_meme 未知分类应提示。"""
        ok = await self.handler.send_meme("s4", "不存在的分类")
        self.assertTrue(ok)
        self.assertIn("未找到匹配分类", self.adapter.sent[0][1])

    async def test_show_categories(self):
        """show_categories 应列出所有分类（不含 manual）。"""
        await self.handler.show_categories("s5")
        self.assertEqual(len(self.adapter.sent), 1)
        msg = self.adapter.sent[0][1]
        self.assertIn("happy", msg)
        self.assertIn("angry", msg)
        self.assertNotIn("manual", msg)


if __name__ == "__main__":
    unittest.main()
