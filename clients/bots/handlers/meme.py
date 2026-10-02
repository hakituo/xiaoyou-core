import logging
import os
import random

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.utils import _build_cq_image

logger = logging.getLogger("MemeHandler")

# 普通表情包目录下需要排除的子目录名（小写匹配）
_EXCLUDED_MEME_DIRS = {"manual"}


class MemeHandler(BaseHandler):
    """表情包处理器 —— 仅负责手动 /表情 命令。

    自动触发（send_auto_meme）已移除，改为 LLM 通过 [MEME:分类] 标签手动触发，
    实现见 clients/bots/qq/media_tags.py 的 pick_meme_image。
    """

    def __init__(self, adapter):
        super().__init__(adapter)
        self._memes_root = os.path.join(
            getattr(adapter, "_project_root", ""),
            "data",
            "memes",
        )
        # 中文别名 → 分类名（供 /表情 命令按中文查找）
        self._alias_map = {
            "开心": "happy",
            "高兴": "happy",
            "微笑": "happy",
            "笑": "happy",
            "难过": "sad",
            "伤心": "sad",
            "生气": "angry",
            "愤怒": "angry",
            "害羞": "shy",
            "惊讶": "surprised",
            "疑问": "confused",
            "问号": "confused",
            "懵": "confused",
            "困倦": "sleep",
            "困": "sleep",
            "疲惫": "sleep",
            "早安": "morning",
            "猫猫": "meow",
            "猫": "meow",
            "点赞": "like",
            "看看": "see",
        }

    def _list_categories(self) -> list[str]:
        """列出 data/memes/ 下的分类（排除 manual 子目录）。"""
        if not os.path.isdir(self._memes_root):
            return []
        out = []
        for name in sorted(os.listdir(self._memes_root)):
            path = os.path.join(self._memes_root, name)
            if not os.path.isdir(path):
                continue
            if name.lower() in _EXCLUDED_MEME_DIRS:
                continue
            out.append(name)
        return out

    def _list_images(self, category: str) -> list[str]:
        c = str(category or "").strip()
        if not c:
            return []
        path = os.path.join(self._memes_root, c)
        if not os.path.isdir(path):
            return []
        files = []
        for name in os.listdir(path):
            p = os.path.join(path, name)
            if not os.path.isfile(p):
                continue
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                files.append(p)
        return files

    def _resolve_category(self, query: str) -> str | None:
        q = str(query or "").strip().lower()
        if not q:
            return None
        categories = self._list_categories()
        if not categories:
            return None
        for c in categories:
            if c.lower() == q:
                return c
        mapped = self._alias_map.get(q)
        if mapped and mapped in categories:
            return mapped
        for c in categories:
            if q in c.lower() or c.lower() in q:
                return c
        return None

    async def show_categories(self, session_id: str) -> None:
        categories = self._list_categories()
        if not categories:
            await self.send_text(session_id, "未找到可用表情包目录。")
            return
        await self.send_text(
            session_id,
            "【表情分类】\n" + "\n".join(f"- {c}" for c in categories[:80]),
        )

    async def send_meme(self, session_id: str, query: str = "") -> bool:
        categories = self._list_categories()
        if not categories:
            await self.send_text(session_id, "表情包目录不存在或为空，无法发送。")
            return True
        q = str(query or "").strip()
        if q.lower() in {"", "随机", "random"}:
            category = random.choice(categories)
        else:
            category = self._resolve_category(q)
            if not category:
                await self.send_text(session_id, f"未找到匹配分类：{q}。可用 /表情 列表")
                return True
        files = self._list_images(category)
        if not files:
            await self.send_text(session_id, f"分类 {category} 没有可发送图片。")
            return True
        file_path = random.choice(files)
        await self.send_text(session_id, _build_cq_image(file_path))
        return True
