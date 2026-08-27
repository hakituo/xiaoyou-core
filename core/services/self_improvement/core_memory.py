"""
自我改进系统 — MEMORY.md 核心记忆管理

轻量级核心记忆文件（≤5KB），每次 session 自动加载。
分层结构：用户偏好 / 角色定位 / 业务经验 / 活跃任务 / 纠正记录 / 对话摘要

与 WeightedMemoryManager 的关系：
- MEMORY.md 是轻量摘要，供 prompt 注入
- WeightedMemoryManager 是详细加权记忆，供检索
- 两者互为补充，MEMORY.md 从加权记忆中提炼关键信息
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.atomic_io import safe_write_text
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time
from .models import (
    MemorySection,
    MEMORY_SECTION_LIMITS,
    MEMORY_MAX_SIZE_BYTES,
)
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("CoreMemory")

# ── 语义去重配置 ─────────────────────────────────────
# 偏好/经验等长期条目用 embedding 语义相似度去重，避免措辞略变导致重复堆积。
# 0.85 是 MiniLM/L12-v2 经验阈值：高于此值视为"在说同一件事"。
SEMANTIC_DEDUP_THRESHOLD = 0.85
# embedding 不可用（hash fallback 模式）时的相似度阈值（hash 嵌入精度低，要求更严格）
SEMANTIC_DEDUP_THRESHOLD_HASH_FALLBACK = 0.95
# 同关键词桶的条目用更宽松的阈值（MiniLM 对中文长句语义区分能力有限，
# 3 条"回复简短"措辞不同时 embedding 相似度只有 0.68-0.74，低于 0.85）
SEMANTIC_DEDUP_THRESHOLD_SAME_BUCKET = 0.65

# 关键词桶定义：命中同一桶的条目语义必然相关，用更宽松的阈值合并
# 解决 MiniLM-L6-v2 对中文长句语义区分能力不足的问题
_KEYWORD_BUCKETS = {
    "reply_style": [
        "回复", "消息", "字数", "简短", "碎片", "长篇", "简洁", "精炼",
        "少于用户", "和用户差不多", "不要发大段",
    ],
    "diet": [
        "饮食", "不吃", "忌口", "海鲜", "腊肠", "能吃辣", "烧腊", "鲜味",
        "味精", "鱼", "讨厌",
    ],
    "location": ["居住", "住在", "地址", "九龙坡", "重庆"],
    "emoji_style": ["表情", "emoji", "偷笑", "🖤"],
}


def _get_keyword_bucket(text: str) -> str:
    """返回文本所属的关键词桶，不属于任何桶返回 'other'"""
    text_lower = text.lower()
    for bucket, keywords in _KEYWORD_BUCKETS.items():
        for kw in keywords:
            if kw in text_lower:
                return bucket
    return "other"

# ── MEMORY.md 模板 ─────────────────────────────────────

_MEMORY_TEMPLATE = """# MEMORY.md - 核心记忆（自动加载）

## 🔒 用户偏好（永久保留）

## 💼 角色定位（永久保留）

## 📝 业务经验（长期保留，≤15条）

## 📋 活跃任务（完成后删）

## 🔄 纠正记录（≤10条）

## 💬 对话摘要（7天后精简）
"""

# ── 分区标题映射 ───────────────────────────────────────

_SECTION_HEADERS = {
    MemorySection.PREFERENCES: "## 🔒 用户偏好（永久保留）",
    MemorySection.ROLE: "## 💼 角色定位（永久保留）",
    MemorySection.EXPERIENCE: "## 📝 业务经验（长期保留，≤15条）",
    MemorySection.ACTIVE_TASKS: "## 📋 活跃任务（完成后删）",
    MemorySection.CORRECTIONS: "## 🔄 纠正记录（≤10条）",
    MemorySection.SUMMARIES: "## 💬 对话摘要（7天后精简）",
}

_SECTION_ORDER = [
    MemorySection.PREFERENCES,
    MemorySection.ROLE,
    MemorySection.EXPERIENCE,
    MemorySection.ACTIVE_TASKS,
    MemorySection.CORRECTIONS,
    MemorySection.SUMMARIES,
]


class CoreMemory:
    """MEMORY.md 核心记忆管理器

    支持 scope 隔离：
    - aveline → aveline_data/MEMORY.md
    - ling → ling_data/MEMORY.md
    - user → user_data/MEMORY.md
    """

    def __init__(self, base_dir: Path, scope: str = "user"):
        self._scope = scope
        self._base_dir = base_dir
        self._memory_file = base_dir / "MEMORY.md"
        # 归档目录与 DailyLogger 共用 memories/core_memory/，避免再生成旧版 memory/ 目录
        self._archive_dir = base_dir / "memories" / "core_memory" / "archive"
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._sections: Dict[MemorySection, List[str]] = {}
        self._loaded = False
        # 缓存每条条目的 embedding，避免重复推理（条目变更时清缓存）
        # 结构: {MemorySection: List[np.ndarray]}
        self._embeddings_cache: Dict[MemorySection, List[Any]] = {}
        self._embedding_gen = None  # 懒加载，避免在 __init__ 触发模型加载
        self._embedding_checked = False

    # ── embedding 工具 ────────────────────────────────

    def _get_embedding_generator(self):
        """懒加载 embedding 生成器（首次调用时才加载模型）"""
        if not self._embedding_checked:
            self._embedding_checked = True
            try:
                from memory.embedding_generator import get_embedding_generator
                self._embedding_gen = get_embedding_generator()
            except Exception as e:
                logger.warning("无法加载 EmbeddingGenerator，去重将退回全等匹配: %s", e)
                self._embedding_gen = None
        return self._embedding_gen

    def _is_hash_fallback(self) -> bool:
        """检查 embedding 生成器是否处于 hash fallback 模式（精度低）"""
        gen = self._embedding_gen
        if gen is None:
            return True
        return bool(getattr(gen, "_use_hash_fallback", False))

    def _compute_embedding(self, text: str) -> Optional[Any]:
        """同步计算单条文本 embedding，失败返回 None"""
        gen = self._get_embedding_generator()
        if gen is None:
            return None
        try:
            return gen.generate_embedding(text)
        except Exception as e:
            logger.debug("计算 embedding 失败，退回全等匹配: %s", e)
            return None

    def _find_semantic_duplicate(
        self, section: MemorySection, new_text: str, new_emb: Any
    ) -> Tuple[bool, int]:
        """在 section 内查找语义重复条目。
        返回 (是否找到重复, 重复条目索引)。找不到返回 (False, -1)。
        """
        items = self._sections.get(section, [])
        if not items:
            return False, -1

        # 先做一次全等匹配，命中直接返回（避免无谓的 embedding 计算）
        for i, item in enumerate(items):
            if item == new_text:
                return True, i

        if new_emb is None:
            return False, -1

        # 计算与现有每条条目的余弦相似度
        try:
            from memory.embedding_generator import EmbeddingGenerator
        except Exception:
            return False, -1

        threshold = (
            SEMANTIC_DEDUP_THRESHOLD_HASH_FALLBACK
            if self._is_hash_fallback()
            else SEMANTIC_DEDUP_THRESHOLD
        )

        # 优先用缓存的 embedding，没有就现算并缓存
        cached = self._embeddings_cache.get(section, [])
        # 缓存与 items 长度不一致时重建
        if len(cached) != len(items):
            cached = []
            for item in items:
                emb = self._compute_embedding(item)
                if emb is None:
                    break
                cached.append(emb)
            # 只有完整算完所有条目才进缓存
            if len(cached) == len(items):
                self._embeddings_cache[section] = cached
            else:
                # embedding 不可用，全等匹配已经做过了，直接返回不重复
                return False, -1

        best_sim = -1.0
        best_idx = -1
        new_bucket = _get_keyword_bucket(new_text)
        for i, emb in enumerate(cached):
            sim = EmbeddingGenerator.cosine_similarity(new_emb, emb)
            if sim > best_sim:
                best_sim = sim
                best_idx = i

        # 判断是否命中：同关键词桶用更宽松的阈值（解决 MiniLM 对中文长句漏判）
        # 不同桶用严格阈值（避免误杀不同主题的偏好）
        item_bucket = _get_keyword_bucket(items[best_idx]) if best_idx >= 0 else "other"
        if new_bucket != "other" and new_bucket == item_bucket:
            actual_threshold = SEMANTIC_DEDUP_THRESHOLD_SAME_BUCKET
            threshold_type = "same_bucket"
        else:
            actual_threshold = threshold
            threshold_type = "normal"

        if best_sim >= actual_threshold:
            logger.info(
                "语义去重命中 (section=%s, sim=%.3f, threshold=%s/%.2f, idx=%d): new=%s | old=%s",
                section.value, best_sim, threshold_type, actual_threshold, best_idx,
                new_text[:40], items[best_idx][:40],
            )
            return True, best_idx
        return False, -1

    def _invalidate_section_cache(self, section: MemorySection) -> None:
        """某 section 条目变更时清掉其 embedding 缓存"""
        self._embeddings_cache.pop(section, None)

    # ── 初始化 ──────────────────────────────────────────

    def ensure_initialized(self) -> None:
        """确保 MEMORY.md 和目录结构存在"""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        if not self._memory_file.exists():
            # P0-16: 用原子写入创建初始文件，避免进程崩溃导致文件被截断
            safe_write_text(_MEMORY_TEMPLATE, self._memory_file, encoding="utf-8")
            logger.info("创建 MEMORY.md: %s", self._memory_file)

    # ── 加载与保存 ──────────────────────────────────────

    async def load(self) -> Dict[MemorySection, List[str]]:
        """加载 MEMORY.md 内容"""
        async with self._lock:
            return await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> Dict[MemorySection, List[str]]:
        """同步加载"""
        if not self._memory_file.exists():
            self.ensure_initialized()

        try:
            content = self._memory_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("加载 MEMORY.md 失败: %s", e)
            return {s: [] for s in _SECTION_ORDER}

        sections: Dict[MemorySection, List[str]] = {s: [] for s in _SECTION_ORDER}
        current_section = None

        for line in content.split("\n"):
            # 检测分区标题
            for section, header in _SECTION_HEADERS.items():
                if line.strip().startswith(header):
                    current_section = section
                    break
            else:
                # 内容行
                if current_section is not None:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        sections[current_section].append(stripped)

        self._sections = sections
        self._loaded = True
        # 重新加载后旧缓存失效
        self._embeddings_cache.clear()
        return sections

    async def save(self) -> None:
        """保存 MEMORY.md 内容"""
        async with self._lock:
            await asyncio.to_thread(self._save_sync)

    def _save_sync(self) -> None:
        """同步保存"""
        lines = ["# MEMORY.md - 核心记忆（自动加载）\n"]
        for section in _SECTION_ORDER:
            header = _SECTION_HEADERS[section]
            lines.append(f"\n{header}\n")
            items = self._sections.get(section, [])
            for item in items:
                lines.append(f"{item}\n")
        try:
            # P0-16: 用原子写入保存核心记忆，避免进程崩溃导致 MEMORY.md
            # 被截断为 0 字节或半截内容（核心记忆丢失不可恢复）
            safe_write_text("\n".join(lines), self._memory_file, encoding="utf-8")
        except Exception as e:
            logger.error("保存 MEMORY.md 失败: %s", e)

    # ── 读写操作 ────────────────────────────────────────

    async def add_item(self, section: MemorySection, item: str) -> bool:
        """向指定分区添加条目（带语义去重）

        - 全等匹配命中 → 不写入，返回 False
        - embedding 语义相似度 ≥ 阈值 → 用新条目替换旧条目（保留最新最全表述），返回 True
        - 否则 → 追加新条目，返回 True
        """
        # NOT-to-save 检查
        if self._should_not_save(item):
            if is_debug_enabled("core_memory"):
                logger.info("跳过 NOT-to-save 条目: %s", item[:30])
            return False

        if not self._loaded:
            await self.load()

        # 同步计算新条目 embedding（CPU 推理，丢到线程池避免阻塞事件循环）
        new_emb = await asyncio.to_thread(self._compute_embedding, item)

        async with self._lock:
            items = self._sections.setdefault(section, [])
            # 语义去重（含全等匹配）
            is_dup, dup_idx = self._find_semantic_duplicate(section, item, new_emb)
            if is_dup:
                if items[dup_idx] == item:
                    # 全等命中，无变化
                    return False
                # 语义相似但不全等 → 用新表述替换旧条目（用户逐步细化偏好时保留最完整的）
                logger.info(
                    "替换语义重复条目 (section=%s): old=%s → new=%s",
                    section.value, items[dup_idx][:40], item[:40],
                )
                items[dup_idx] = item
                self._invalidate_section_cache(section)
                await asyncio.to_thread(self._save_sync)
                return True

            # 无重复，追加
            items.append(item)
            # 维护缓存：把新条目 embedding 追加进去
            if new_emb is not None:
                cache = self._embeddings_cache.get(section)
                if cache is not None and len(cache) == len(items) - 1:
                    cache.append(new_emb)
                else:
                    # 缓存不可用或失效，整体重建交给下次调用
                    self._invalidate_section_cache(section)

            # 限制条目数量
            limit = MEMORY_SECTION_LIMITS.get(section, 0)
            if limit > 0 and len(items) > limit:
                # 超出限制，移除最旧的
                removed = items[:len(items) - limit]
                items[:] = items[len(items) - limit:]
                self._invalidate_section_cache(section)
                # 归档移除的内容
                await self._archive_items(section, removed)
            await asyncio.to_thread(self._save_sync)
            return True

    async def remove_item(self, section: MemorySection, item: str) -> bool:
        """从指定分区移除条目"""
        if not self._loaded:
            await self.load()

        async with self._lock:
            items = self._sections.get(section, [])
            if item in items:
                items.remove(item)
                self._invalidate_section_cache(section)
                await asyncio.to_thread(self._save_sync)
                return True
            return False

    async def update_item(
        self, section: MemorySection, old_item: str, new_item: str
    ) -> bool:
        """更新指定分区的条目"""
        if not self._loaded:
            await self.load()

        async with self._lock:
            items = self._sections.get(section, [])
            if old_item in items:
                idx = items.index(old_item)
                items[idx] = new_item
                self._invalidate_section_cache(section)
                await asyncio.to_thread(self._save_sync)
                return True
            return False

    async def get_section(self, section: MemorySection) -> List[str]:
        """获取指定分区内容"""
        if not self._loaded:
            await self.load()
        return list(self._sections.get(section, []))

    async def get_all(self) -> Dict[MemorySection, List[str]]:
        """获取所有分区内容"""
        if not self._loaded:
            await self.load()
        return {k: list(v) for k, v in self._sections.items()}

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """搜索核心记忆"""
        if not self._loaded:
            await self.load()

        query_lower = query.lower()
        results = []
        for section, items in self._sections.items():
            for item in items:
                if query_lower in item.lower():
                    results.append({
                        "section": section.value,
                        "content": item,
                    })
        return results

    # ── 自动瘦身 ────────────────────────────────────────

    async def auto_slim(self) -> Dict[str, int]:
        """
        自动瘦身 MEMORY.md（超 5KB 时触发）。

        策略：
        - 🔒 用户偏好：永不删
        - 💼 角色定位：永不删
        - 📝 业务经验：>15条时合并相似项
        - 📋 活跃任务：已完成的删除
        - 🔄 纠正记录：已晋升的删除
        - 💬 对话摘要：>7天的精简合并或归档

        返回各分区删除数量。
        """
        if not self._loaded:
            await self.load()

        # 检查是否需要瘦身
        try:
            size = self._memory_file.stat().st_size
        except Exception:
            return {}

        if size <= MEMORY_MAX_SIZE_BYTES:
            return {}

        logger.info("MEMORY.md 超限 (%d > %d)，开始瘦身", size, MEMORY_MAX_SIZE_BYTES)
        removed_counts: Dict[str, int] = {}

        async with self._lock:
            # 活跃任务：删除已完成的
            tasks = self._sections.get(MemorySection.ACTIVE_TASKS, [])
            done_tasks = [t for t in tasks if t.startswith("✅") or "[完成]" in t]
            for t in done_tasks:
                tasks.remove(t)
            if done_tasks:
                removed_counts["active_tasks"] = len(done_tasks)
                self._invalidate_section_cache(MemorySection.ACTIVE_TASKS)
                await self._archive_items(MemorySection.ACTIVE_TASKS, done_tasks)

            # 纠正记录：删除已晋升的
            corrections = self._sections.get(MemorySection.CORRECTIONS, [])
            promoted = [c for c in corrections if "[已晋升]" in c or "✅" in c]
            for c in promoted:
                corrections.remove(c)
            if promoted:
                removed_counts["corrections"] = len(promoted)
                self._invalidate_section_cache(MemorySection.CORRECTIONS)
                await self._archive_items(MemorySection.CORRECTIONS, promoted)

            # 对话摘要：>7天的精简
            summaries = self._sections.get(MemorySection.SUMMARIES, [])
            cutoff = (get_current_time() - timedelta(days=7)).strftime("%Y-%m-%d")
            old_summaries = [s for s in summaries if self._is_older_than(s, cutoff)]
            for s in old_summaries:
                summaries.remove(s)
            if old_summaries:
                removed_counts["summaries"] = len(old_summaries)
                self._invalidate_section_cache(MemorySection.SUMMARIES)
                await self._archive_items(MemorySection.SUMMARIES, old_summaries)

            # 业务经验：合并相似项
            experience = self._sections.get(MemorySection.EXPERIENCE, [])
            if len(experience) > 15:
                merged, removed = self._merge_similar_items(experience)
                self._sections[MemorySection.EXPERIENCE] = merged
                if removed:
                    removed_counts["experience"] = len(removed)
                    self._invalidate_section_cache(MemorySection.EXPERIENCE)
                    await self._archive_items(MemorySection.EXPERIENCE, removed)

            await asyncio.to_thread(self._save_sync)

        return removed_counts

    # ── LLM 语义合并（夜间兜底） ────────────────────────

    async def llm_merge_preferences(self, model_hint: Optional[str] = None) -> Dict[str, Any]:
        """用 LLM 合并 PREFERENCES 区的语义重复条目

        平时 add_item 走 embedding + 关键词桶去重（实时、低成本），但中文同义改写容易漏判；
        本方法在夜间兜底，用 LLM 把 embedding 漏掉的语义重复条目合并掉。

        Args:
            model_hint: LLM 模型提示（默认用 journal_model_hint = siliconflow MiniMax-M2.5）

        Returns:
            诊断信息字典（合并前后数量、LLM 响应摘要等）
        """
        if not self._loaded:
            await self.load()

        prefs = self._sections.get(MemorySection.PREFERENCES, [])
        original_count = len(prefs)
        if original_count <= 1:
            return {"skipped": "too_few_items", "before": original_count, "after": original_count}

        from .core_memory_llm_merge import llm_merge_preferences

        new_prefs, removed, diag = await llm_merge_preferences(prefs, model_hint=model_hint)
        if removed == 0:
            return {"skipped": diag.get("skipped", "no_change"), "before": original_count, "after": original_count, "diag": diag}

        # 落盘
        self._sections[MemorySection.PREFERENCES] = new_prefs
        self._invalidate_section_cache(MemorySection.PREFERENCES)
        await asyncio.to_thread(self._save_sync)

        logger.info(
            "LLM 合并偏好 (scope=%s): %d → %d 条（移除 %d）",
            self._scope, original_count, len(new_prefs), removed,
        )
        return {
            "before": original_count,
            "after": len(new_prefs),
            "removed": removed,
            "diag": diag,
        }

    # ── 生成 prompt 注入文本 ────────────────────────────

    async def build_injection_text(self) -> str:
        """生成用于 prompt 注入的核心记忆文本

        对话摘要区从 JournalService 获取（避免与日记系统重复存储）。

        返回空字符串表示"无实质内容，不应注入 prompt"——调用方据此判断是否注入。
        """
        if not self._loaded:
            await self.load()

        lines = ["【核心记忆（MEMORY.md）】"]
        has_content = False  # 是否有任何实质条目（不含模板标题）
        for section in _SECTION_ORDER:
            # 对话摘要区：从 JournalService 获取，而非 MEMORY.md
            if section == MemorySection.SUMMARIES:
                journal_summary = await self._get_journal_summary()
                if journal_summary:
                    header = _SECTION_HEADERS[section].replace("## ", "").strip()
                    lines.append(f"\n{header}")
                    lines.append(journal_summary)
                    has_content = True
                continue

            items = self._sections.get(section, [])
            if not items:
                continue
            header = _SECTION_HEADERS[section].replace("## ", "").strip()
            lines.append(f"\n{header}")
            for item in items:
                lines.append(f"- {item}")
            has_content = True

        # 全空时不注入（避免给 LLM 喂一个空模板，浪费 tokens 且无信息量）
        if not has_content:
            return ""
        return "\n".join(lines)

    def build_injection_text_sync(self) -> str:
        """build_injection_text 的同步版本，供同步调用方使用（如 assembler.py 的 build_persona_prompt_split）。

        与异步版本的差异：跳过对话摘要区（JournalService 调用是异步的），
        只读 MEMORY.md 本地文件。如果调用方需要日记摘要，应使用异步版本。
        """
        if not self._loaded:
            # 同步加载（_load_sync 已存在）
            self._load_sync()

        lines = ["【核心记忆（MEMORY.md）】"]
        has_content = False
        for section in _SECTION_ORDER:
            # 同步版本跳过摘要区（JournalService 是异步的）
            if section == MemorySection.SUMMARIES:
                continue
            items = self._sections.get(section, [])
            if not items:
                continue
            header = _SECTION_HEADERS[section].replace("## ", "").strip()
            lines.append(f"\n{header}")
            for item in items:
                lines.append(f"- {item}")
            has_content = True

        if not has_content:
            return ""
        return "\n".join(lines)

    async def _get_journal_summary(self) -> str:
        """从 JournalService 获取最近的日记摘要"""
        try:
            from core.services.journal.service import JournalService
            js = JournalService()
            # 获取最近3天的日记摘要
            summaries = []
            for i in range(3):
                date = get_current_time() - timedelta(days=i)
                date_str = date.strftime("%Y-%m-%d")
                try:
                    daily = await js.storage.get_daily_summary(date_str)
                    if daily and hasattr(daily, "summary") and daily.summary:
                        summaries.append(f"- [{date_str}] {str(daily.summary)[:100]}")
                except Exception:
                    continue
            return "\n".join(summaries) if summaries else ""
        except Exception:
            # JournalService 不可用时，回退到 MEMORY.md 中的摘要
            items = self._sections.get(MemorySection.SUMMARIES, [])
            if items:
                return "\n".join(f"- {item}" for item in items)
            return ""

    # ── 内部方法 ────────────────────────────────────────

    @staticmethod
    def _should_not_save(item: str) -> bool:
        """检查是否属于 NOT-to-save 列表"""
        item_lower = item.lower()
        # 代码模式/文件路径（grep 可查）
        if re.search(r"(?:import |from |class |def |function |\.py|\.js|\.ts)\b", item_lower):
            return True
        # Git 历史
        if any(kw in item_lower for kw in ["git log", "git blame", "commit", "pr #"]):
            return True
        # 调试步骤
        if any(kw in item_lower for kw in ["debug", "断点", "step", "stack trace"]):
            return True
        return False

    @staticmethod
    def _is_older_than(item: str, cutoff_date: str) -> bool:
        """检查条目是否早于截止日期"""
        # 尝试从条目中提取日期
        m = re.search(r"(\d{4}-\d{2}-\d{2})", item)
        if m:
            return m.group(1) < cutoff_date
        return False

    @staticmethod
    def _merge_similar_items(items: List[str]) -> tuple:
        """合并相似条目，返回 (合并后列表, 被移除的条目)"""
        if len(items) <= 15:
            return items, []

        # 简单合并：按关键词分组
        groups: Dict[str, List[str]] = {}
        for item in items:
            # 提取前两个中文词或英文词作为分组键
            words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", item.lower())
            key = " ".join(words[:2]) if words else item[:10]
            groups.setdefault(key, []).append(item)

        merged = []
        removed = []
        for key, group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                # 合并为一条
                merged_item = group[0]
                if len(group) > 1:
                    merged_item += f"（含{len(group)}条相似经验）"
                merged.append(merged_item)
                removed.extend(group[1:])

        # 如果仍然超限，保留前15条
        if len(merged) > 15:
            removed.extend(merged[15:])
            merged = merged[:15]

        return merged, removed

    async def _archive_items(self, section: MemorySection, items: List[str]) -> None:
        """归档移除的条目"""
        if not items:
            return
        try:
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            date_str = time.strftime("%Y-%m-%d")
            archive_file = self._archive_dir / f"{section.value}_{date_str}.md"
            content = f"# {section.value} 归档 ({date_str})\n\n"
            for item in items:
                content += f"- {item}\n"
            with open(archive_file, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.warning("归档失败: %s", e)
