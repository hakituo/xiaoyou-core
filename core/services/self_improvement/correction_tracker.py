"""
自我改进系统 — 通用纠正检测与记录

扩展现有 correction.py（仅处理生活类纠正），新增通用纠正检测：
- 6种纠正信号检测
- 纠正记录写入 .learnings/corrections.md
- 纠正晋升（2条相似纠正 → 永久规则）
- 与 MEMORY.md 纠正记录区联动
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from core.utils.logger import get_logger
from .models import (
    CorrectionEntry,
    CorrectionSignal,
    EntryStatus,
    LearningCategory,
    LearningEntry,
)
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("CorrectionTracker")


# ── 纠正信号检测模式 ──────────────────────────────────

_CORRECTION_PATTERNS: List[Tuple[CorrectionSignal, List[str]]] = [
    # 直接否定
    (CorrectionSignal.DIRECT_DENY, [
        "不对", "错了", "不是这样的", "你搞错了", "说错了",
        "不对吧", "那不对", "这不对", "完全不对", "根本不对",
        "no", "wrong", "incorrect", "that's wrong",
    ]),
    # 给出不同答案
    (CorrectionSignal.DIFFERENT_ANSWER, [
        "应该是", "其实是", "实际上是", "正确的是", "事实上",
        "actually", "in fact", "the correct",
    ]),
    # 温和引导
    (CorrectionSignal.GENTLE_GUIDE, [
        "其实", "不过呢", "话说回来", "换个角度", "换个说法",
        "well actually", "technically",
    ]),
    # 质疑
    (CorrectionSignal.QUESTIONING, [
        "你确定", "真的吗", "是这样吗", "不会吧", "确定？",
        "are you sure", "really", "is that right",
    ]),
    # 放弃（强失败信号）
    (CorrectionSignal.GIVE_UP, [
        "算了我来", "算了算了", "我自己来", "不用你了",
        "forget it", "never mind", "I'll do it",
    ]),
]

# 示范正确做法的检测（不说你错，直接展示）
_DEMONSTRATION_PATTERNS = [
    r"正确的做法是[：:]",
    r"应该这样[：:]",
    r"来，(我|你)看",
    r"像这样[：:]",
]


class CorrectionTracker:
    """通用纠正检测与记录器"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir / ".learnings"
        self._corrections_file = self._base_dir / "corrections.md"
        # P1-5: 新增 JSON 索引文件，持久化 _recent_corrections 列表
        # 解决"晋升失忆"问题：重启后从磁盘加载历史纠正，才能正确触发晋升检测
        self._index_file = self._base_dir / "corrections_index.json"
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._recent_corrections: List[CorrectionEntry] = []
        self._max_recent = 50
        # P1-5: 启动时同步加载持久化状态（在事件循环外，不能用 await）
        self._load_index_sync()

    def _load_index_sync(self) -> None:
        """P1-5: 启动时从 corrections_index.json 加载历史纠正"""
        if not self._index_file.exists():
            return
        try:
            with open(self._index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries_data = data.get("entries") or []
            loaded: List[CorrectionEntry] = []
            for e_dict in entries_data:
                try:
                    entry = CorrectionEntry.from_dict(e_dict)
                    if entry.id:
                        loaded.append(entry)
                except Exception as e:
                    logger.warning("加载纠正条目失败（跳过）: %s", e)
            # 按时间倒序保持（最近的在前）
            loaded.sort(key=lambda x: x.logged_at, reverse=True)
            self._recent_corrections = loaded[: self._max_recent]
            logger.info(
                "CorrectionTracker 已加载持久化纠正: %d 条",
                len(self._recent_corrections),
            )
        except Exception as e:
            logger.warning("加载纠正索引失败（忽略，使用空列表）: %s", e)

    async def _save_index_async(self) -> None:
        """P1-5: 异步原子写入 corrections_index.json"""
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "entries": [e.to_dict() for e in self._recent_corrections],
                "saved_at": time.time(),
            }

            def _write_atomic():
                tmp_path = str(self._index_file) + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp_path, self._index_file)  # 原子替换

            await asyncio.to_thread(_write_atomic)
        except Exception as e:
            logger.warning("保存纠正索引失败: %s", e)

    # ── 纠正检测 ────────────────────────────────────────

    @staticmethod
    def detect_correction_signal(text: str) -> Optional[CorrectionSignal]:
        """
        检测文本中的纠正信号。

        返回最强信号类型，或 None（无纠正意图）。
        优先级：GIVE_UP > DIRECT_DENY > DIFFERENT_ANSWER > QUESTIONING > GENTLE_GUIDE > DEMONSTRATION
        """
        raw = str(text or "").strip()
        if not raw:
            return None

        lower = raw.lower()

        # 按优先级检查
        priority_order = [
            CorrectionSignal.GIVE_UP,
            CorrectionSignal.DIRECT_DENY,
            CorrectionSignal.DIFFERENT_ANSWER,
            CorrectionSignal.QUESTIONING,
            CorrectionSignal.GENTLE_GUIDE,
        ]

        for signal in priority_order:
            patterns = [p for s, p in _CORRECTION_PATTERNS if s == signal]
            for pattern_list in patterns:
                if any(kw in lower for kw in pattern_list):
                    return signal

        # 示范正确做法
        for pattern in _DEMONSTRATION_PATTERNS:
            if re.search(pattern, raw):
                return CorrectionSignal.DEMONSTRATION

        return None

    @staticmethod
    def has_correction_intent(text: str) -> bool:
        """快速判断是否有纠正意图"""
        return CorrectionTracker.detect_correction_signal(text) is not None

    # ── 纠正记录 ────────────────────────────────────────

    async def record_correction(
        self,
        *,
        signal_type: CorrectionSignal,
        title: str,
        correction: str,
        my_error: str = "",
        root_cause: str = "",
        lesson: str = "",
        how_to_apply: str = "",
        tags: Optional[List[str]] = None,
    ) -> CorrectionEntry:
        """记录一条纠正"""
        entry = CorrectionEntry(
            signal_type=signal_type,
            title=title,
            correction=correction,
            my_error=my_error,
            root_cause=root_cause,
            lesson=lesson or f"下次遇到类似情况，{correction}",
            how_to_apply=how_to_apply,
            tags=tags or [],
        )

        async with self._lock:
            self._recent_corrections.insert(0, entry)
            if len(self._recent_corrections) > self._max_recent:
                self._recent_corrections = self._recent_corrections[:self._max_recent]

        # 写入 corrections.md
        await self._append_correction_md(entry)

        # 检查是否需要晋升（_check_promotion 会修改 entry.status）
        await self._check_promotion(entry)

        # P1-5: 持久化纠正索引（含最新状态，支持重启后晋升检测）
        await self._save_index_async()

        logger.info(
            "记录纠正: %s [%s] — %s",
            entry.id, signal_type.value, title[:40],
        )
        return entry

    # ── 纠正晋升检测 ────────────────────────────────────

    async def _check_promotion(self, new_entry: CorrectionEntry) -> Optional[str]:
        """
        检查纠正晋升条件：
        - 2条相似纠正 → 晋升到永久规则
        - 返回晋升目标路径，或 None
        """
        async with self._lock:
            similar = []
            for existing in self._recent_corrections:
                if existing.id == new_entry.id:
                    continue
                if existing.status != EntryStatus.PENDING:
                    continue
                # 简单相似度：标签重叠或标题关键词重叠
                if self._is_similar_correction(existing, new_entry):
                    similar.append(existing)

            if len(similar) >= 1:  # 已有1条相似 + 当前1条 = 2条
                # 晋升两条
                for entry in [new_entry] + similar[:1]:
                    entry.status = EntryStatus.PROMOTED
                    entry.promoted_at = time.time()
                    entry.promoted_to = "project_rules"

                # 生成晋升规则
                rule = self._generate_promotion_rule(new_entry, similar[0])
                logger.info("纠正晋升: %s → %s", new_entry.title[:30], rule[:50])
                return rule

        return None

    @staticmethod
    def _is_similar_correction(a: CorrectionEntry, b: CorrectionEntry) -> bool:
        """判断两条纠正是否相似"""
        # 标签重叠
        if a.tags and b.tags:
            overlap = set(a.tags) & set(b.tags)
            if len(overlap) >= 1:
                return True
        # 标题关键词重叠（简单分词）
        a_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", a.title.lower()))
        b_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", b.title.lower()))
        if a_words and b_words:
            overlap = a_words & b_words
            if len(overlap) >= 2:
                return True
        return False

    @staticmethod
    def _generate_promotion_rule(a: CorrectionEntry, b: CorrectionEntry) -> str:
        """从两条相似纠正生成晋升规则"""
        lesson = a.lesson or b.lesson or a.correction
        how = a.how_to_apply or b.how_to_apply
        rule = f"规则：{lesson}"
        if how:
            rule += f"（适用场景：{how}）"
        return rule

    # ── 查询 ────────────────────────────────────────────

    async def get_recent_corrections(
        self, limit: int = 10, status: Optional[EntryStatus] = None
    ) -> List[CorrectionEntry]:
        """获取最近的纠正记录"""
        async with self._lock:
            results = list(self._recent_corrections)
        if status:
            results = [e for e in results if e.status == status]
        return results[:limit]

    async def get_pending_corrections(self, limit: int = 10) -> List[CorrectionEntry]:
        """获取待处理的纠正"""
        return await self.get_recent_corrections(limit=limit, status=EntryStatus.PENDING)

    # ── 转换为 LearningEntry ────────────────────────────

    def to_learning_entry(self, correction: CorrectionEntry) -> LearningEntry:
        """将纠正记录转换为学习条目（用于写入 LEARNINGS.md）"""
        return LearningEntry(
            category=LearningCategory.CORRECTION,
            priority=correction.priority,
            status=correction.status,
            summary=correction.title,
            details=f"正确做法: {correction.correction}\n我的错误: {correction.my_error}\n根因: {correction.root_cause}",
            suggested_action=correction.lesson,
            source="user_feedback",
            tags=correction.tags,
        )

    # ── 内部方法 ────────────────────────────────────────

    async def _append_correction_md(self, entry: CorrectionEntry) -> None:
        """追加纠正到 corrections.md"""
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.logged_at))
            content = (
                f"\n## {ts} — {entry.title}\n"
                f"- **纠正**: {entry.correction}\n"
                f"- **我的错误**: {entry.my_error}\n"
                f"- **根因**: {entry.root_cause}\n"
                f"- **教训**: {entry.lesson}\n"
                f"- **状态**: {'⏳待验证' if entry.status == EntryStatus.PENDING else '✅已晋升'}\n"
                f"---\n"
            )
            if not self._corrections_file.exists():
                header = "# 纠正详细记录\n\n晋升源：当两条相似纠正出现时，自动晋升为永久规则。\n\n---\n"
                content = header + content
            with open(self._corrections_file, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.warning("追加纠正 Markdown 失败: %s", e)
