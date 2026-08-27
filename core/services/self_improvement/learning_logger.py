"""
自我改进系统 — 结构化学习/错误/功能请求日志记录器

管理 .learnings/ 目录下的 LEARNINGS.md、ERRORS.md、FEATURE_REQUESTS.md 文件。
支持条目的增删改查、状态流转、模式检测去重。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from .models import (
    LearningEntry,
    ErrorEntry,
    FeatureRequestEntry,
    LearningCategory,
    EntryPriority,
    EntryArea,
)
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("LearningLogger")


class LearningLogger:
    """结构化学习/错误/功能请求日志记录器"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir / ".learnings"
        self._learnings_file = self._base_dir / "LEARNINGS.md"
        self._errors_file = self._base_dir / "ERRORS.md"
        self._features_file = self._base_dir / "FEATURE_REQUESTS.md"
        self._json_index = self._base_dir / "_index.json"
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 30.0

    # ── 初始化 ──────────────────────────────────────────

    def ensure_dirs(self) -> None:
        """确保目录存在"""
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ── 索引管理（JSON 格式，便于查询） ──────────────────

    def _load_index(self) -> Dict[str, Any]:
        """加载 JSON 索引"""
        if not self._json_index.exists():
            return {"learnings": [], "errors": [], "features": []}
        try:
            with open(self._json_index, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("加载学习索引失败: %s", e)
            return {"learnings": [], "errors": [], "features": []}

    def _save_index(self, data: Dict[str, Any]) -> None:
        """保存 JSON 索引"""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._json_index, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存学习索引失败: %s", e)

    def _get_cached_index(self) -> Dict[str, Any]:
        """带缓存的索引读取"""
        now = time.time()
        if self._cache is not None and (now - self._cache_ts) < self._cache_ttl:
            return self._cache
        data = self._load_index()
        self._cache = data
        self._cache_ts = now
        return data

    def _invalidate_cache(self) -> None:
        self._cache = None

    # ── 学习条目 ────────────────────────────────────────

    async def log_learning(self, entry: LearningEntry) -> str:
        """记录学习条目"""
        async with self._lock:
            data = self._get_cached_index()
            # 模式检测：如果 pattern_key 已存在，更新现有条目
            if entry.pattern_key:
                existing = self._find_by_pattern_key(data["learnings"], entry.pattern_key)
                if existing:
                    existing["recurrence_count"] = existing.get("recurrence_count", 1) + 1
                    existing["last_seen"] = time.strftime("%Y-%m-%d")
                    if entry.see_also:
                        see_also = set(existing.get("see_also", []))
                        see_also.update(entry.see_also)
                        existing["see_also"] = list(see_also)
                    # 优先级提升
                    if existing.get("recurrence_count", 0) >= 3:
                        existing["priority"] = "high"
                    self._save_index(data)
                    self._invalidate_cache()
                    await self._append_to_md("learning", entry)
                    return existing.get("id", entry.id)

            entry.first_seen = entry.first_seen or time.strftime("%Y-%m-%d")
            entry.last_seen = time.strftime("%Y-%m-%d")
            data["learnings"].insert(0, entry.to_dict())
            # 限制条目数量
            if len(data["learnings"]) > 200:
                data["learnings"] = data["learnings"][:200]
            self._save_index(data)
            self._invalidate_cache()
            await self._append_to_md("learning", entry)
            return entry.id

    async def log_error(self, entry: ErrorEntry) -> str:
        """记录错误条目"""
        async with self._lock:
            data = self._get_cached_index()
            # 关联检测
            if entry.see_also:
                for existing in data["errors"]:
                    if any(s in existing.get("see_also", []) for s in entry.see_also):
                        if existing.get("status") == "pending":
                            existing["priority"] = "high"
                        break
            data["errors"].insert(0, entry.to_dict())
            if len(data["errors"]) > 100:
                data["errors"] = data["errors"][:100]
            self._save_index(data)
            self._invalidate_cache()
            await self._append_to_md("error", entry)
            return entry.id

    async def log_feature_request(self, entry: FeatureRequestEntry) -> str:
        """记录功能请求条目"""
        async with self._lock:
            data = self._get_cached_index()
            # 去重：如果已有相同 capability，提升频率
            for existing in data["features"]:
                if existing.get("capability") == entry.capability:
                    existing["frequency"] = "recurring"
                    existing["priority"] = "high"
                    self._save_index(data)
                    self._invalidate_cache()
                    return existing.get("id", entry.id)
            data["features"].insert(0, entry.to_dict())
            if len(data["features"]) > 50:
                data["features"] = data["features"][:50]
            self._save_index(data)
            self._invalidate_cache()
            await self._append_to_md("feature", entry)
            return entry.id

    # ── 查询 ────────────────────────────────────────────

    async def get_pending_learnings(
        self,
        *,
        area: Optional[EntryArea] = None,
        category: Optional[LearningCategory] = None,
        min_priority: Optional[EntryPriority] = None,
        limit: int = 10,
    ) -> List[LearningEntry]:
        """获取待处理的学习条目"""
        data = self._get_cached_index()
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        min_p = priority_order.get(min_priority.value if min_priority else "low", 3)
        results = []
        for item in data.get("learnings", []):
            if item.get("status") != "pending":
                continue
            if area and item.get("area") != area.value:
                continue
            if category and item.get("category") != category.value:
                continue
            p = priority_order.get(item.get("priority", "medium"), 2)
            if p > min_p:
                continue
            results.append(LearningEntry.from_dict(item))
            if len(results) >= limit:
                break
        return results

    async def get_pending_errors(self, limit: int = 10) -> List[ErrorEntry]:
        """获取待处理的错误条目"""
        data = self._get_cached_index()
        results = []
        for item in data.get("errors", []):
            if item.get("status") != "pending":
                continue
            results.append(ErrorEntry.from_dict(item))
            if len(results) >= limit:
                break
        return results

    async def get_recurring_patterns(self, min_recurrence: int = 3) -> List[LearningEntry]:
        """获取重复出现的模式（达到晋升阈值）"""
        data = self._get_cached_index()
        results = []
        for item in data.get("learnings", []):
            if item.get("recurrence_count", 0) >= min_recurrence and item.get("status") == "pending":
                results.append(LearningEntry.from_dict(item))
        return results

    # ── 状态更新 ────────────────────────────────────────

    async def resolve_entry(self, entry_id: str, notes: str = "") -> bool:
        """标记条目为已解决"""
        async with self._lock:
            data = self._get_cached_index()
            for collection in ["learnings", "errors", "features"]:
                for item in data.get(collection, []):
                    if item.get("id") == entry_id:
                        item["status"] = "resolved"
                        item["resolved_at"] = time.time()
                        if notes:
                            item["resolution_notes"] = notes
                        self._save_index(data)
                        self._invalidate_cache()
                        return True
            return False

    async def promote_entry(self, entry_id: str, target: str) -> bool:
        """标记条目为已晋升"""
        async with self._lock:
            data = self._get_cached_index()
            for collection in ["learnings", "errors", "features"]:
                for item in data.get(collection, []):
                    if item.get("id") == entry_id:
                        item["status"] = "promoted"
                        item["promoted_to"] = target
                        self._save_index(data)
                        self._invalidate_cache()
                        return True
            return False

    # ── 统计 ────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        data = self._get_cached_index()
        learnings = data.get("learnings", [])
        errors = data.get("errors", [])
        features = data.get("features", [])
        return {
            "learnings_total": len(learnings),
            "learnings_pending": sum(1 for x in learnings if x.get("status") == "pending"),
            "learnings_promoted": sum(1 for x in learnings if x.get("status") == "promoted"),
            "errors_total": len(errors),
            "errors_pending": sum(1 for x in errors if x.get("status") == "pending"),
            "features_total": len(features),
            "features_pending": sum(1 for x in features if x.get("status") == "pending"),
            "recurring_patterns": sum(
                1 for x in learnings if x.get("recurrence_count", 0) >= 3
            ),
        }

    # ── 内部方法 ────────────────────────────────────────

    def _find_by_pattern_key(self, items: List[Dict], pattern_key: str) -> Optional[Dict]:
        """按 pattern_key 查找已有条目"""
        for item in items:
            if item.get("pattern_key") == pattern_key:
                return item
        return None

    async def _append_to_md(self, entry_type: str, entry: Any) -> None:
        """追加条目到对应的 Markdown 文件（人类可读）"""
        try:
            if entry_type == "learning":
                path = self._learnings_file
                if not path.exists():
                    header = "# Learnings\n\n纠正、洞察、知识缺口和最佳实践记录。\n\n---\n"
                else:
                    header = ""
                content = _format_learning_md(entry)
            elif entry_type == "error":
                path = self._errors_file
                if not path.exists():
                    header = "# Errors\n\n命令失败和集成错误。\n\n---\n"
                else:
                    header = ""
                content = _format_error_md(entry)
            else:
                path = self._features_file
                if not path.exists():
                    header = "# Feature Requests\n\n用户请求的功能。\n\n---\n"
                else:
                    header = ""
                content = _format_feature_md(entry)

            self._base_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(header + content + "\n")
        except Exception as e:
            logger.warning("追加 Markdown 日志失败: %s", e)


# ── Markdown 格式化 ────────────────────────────────────


def _format_learning_md(entry: LearningEntry) -> str:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entry.logged_at))
    lines = [
        f"\n## [{entry.id}] {entry.category.value}",
        f"**Logged**: {ts}",
        f"**Priority**: {entry.priority.value} | **Status**: {entry.status.value} | **Area**: {entry.area.value}",
        f"\n### Summary\n{entry.summary}",
    ]
    if entry.details:
        lines.append(f"\n### Details\n{entry.details}")
    if entry.suggested_action:
        lines.append(f"\n### Suggested Action\n{entry.suggested_action}")
    meta = [f"- Source: {entry.source}"]
    if entry.related_files:
        meta.append(f"- Related Files: {', '.join(entry.related_files)}")
    if entry.tags:
        meta.append(f"- Tags: {', '.join(entry.tags)}")
    if entry.see_also:
        meta.append(f"- See Also: {', '.join(entry.see_also)}")
    if entry.pattern_key:
        meta.append(f"- Pattern-Key: {entry.pattern_key}")
        meta.append(f"- Recurrence-Count: {entry.recurrence_count}")
    if entry.first_seen:
        meta.append(f"- First-Seen: {entry.first_seen}")
    if entry.last_seen:
        meta.append(f"- Last-Seen: {entry.last_seen}")
    lines.append("\n### Metadata\n" + "\n".join(meta))
    lines.append("\n---")
    return "\n".join(lines)


def _format_error_md(entry: ErrorEntry) -> str:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entry.logged_at))
    lines = [
        f"\n## [{entry.id}] {entry.summary[:50]}",
        f"**Logged**: {ts}",
        f"**Priority**: {entry.priority.value} | **Status**: {entry.status.value} | **Area**: {entry.area.value}",
        f"\n### Summary\n{entry.summary}",
    ]
    if entry.error_message:
        lines.append(f"\n### Error\n```\n{entry.error_message}\n```")
    if entry.context:
        lines.append(f"\n### Context\n{entry.context}")
    if entry.suggested_fix:
        lines.append(f"\n### Suggested Fix\n{entry.suggested_fix}")
    meta = [f"- Reproducible: {entry.reproducible}"]
    if entry.related_files:
        meta.append(f"- Related Files: {', '.join(entry.related_files)}")
    if entry.see_also:
        meta.append(f"- See Also: {', '.join(entry.see_also)}")
    lines.append("\n### Metadata\n" + "\n".join(meta))
    lines.append("\n---")
    return "\n".join(lines)


def _format_feature_md(entry: FeatureRequestEntry) -> str:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entry.logged_at))
    lines = [
        f"\n## [{entry.id}] {entry.capability[:50]}",
        f"**Logged**: {ts}",
        f"**Priority**: {entry.priority.value} | **Status**: {entry.status.value} | **Area**: {entry.area.value}",
        f"\n### Requested Capability\n{entry.capability}",
    ]
    if entry.user_context:
        lines.append(f"\n### User Context\n{entry.user_context}")
    lines.append(f"\n### Complexity\n{entry.complexity}")
    if entry.suggested_implementation:
        lines.append(f"\n### Suggested Implementation\n{entry.suggested_implementation}")
    meta = [f"- Frequency: {entry.frequency}"]
    if entry.related_features:
        meta.append(f"- Related Features: {', '.join(entry.related_features)}")
    lines.append("\n### Metadata\n" + "\n".join(meta))
    lines.append("\n---")
    return "\n".join(lines)
