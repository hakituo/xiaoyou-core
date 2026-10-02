"""
元认知（Metacognition）服务 — 待定模块

当前状态：此模块的功能已被现有系统覆盖，暂不接入主流程。

覆盖情况：
- 意图追踪 → PersistentStateTracker + BERT 意图检测
- 主动提醒 → Active Care（reminder / health_reminder / wake_up_greeting）
- 历史检索 → RAG search_memory（语义级检索）
- 行为记录 → 日记系统（Journal）+ tomorrow_tone 回注
- 去重/防重复 → Active Care 三层去重 + 二次改写

潜在方向（待讨论）：
- AI 回复风格的量化追踪与自适应（如：连续N次用了相同句式开头时自动调整）
- 对话节奏感知（如：用户回复间隔变化趋势，AI 主动调整发消息频率）
- 跨人设行为一致性校验（如：同一用户在不同人设下的体验是否矛盾）
"""

from core.utils.logger import get_logger
import asyncio
import json

import os
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from config.integrated_config import get_settings
from core.utils.atomic_io import safe_json_dump as safe_json_dump_atomic
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("metacognition")

_STOP_WORDS_CN: frozenset = frozenset({
    "这个", "那个", "然后", "但是", "因为", "所以", "就是", "还是",
    "可以", "需要", "觉得", "问题", "一下", "现在", "今天", "之前",
    "上次", "我们", "你们", "你", "我", "他", "她", "它",
    "的", "了", "吗", "呢", "啊", "哦", "嗯",
})

_STOP_WORDS_EN: frozenset = frozenset({
    "and", "or", "the", "a", "an", "to", "for", "in", "on", "with",
    "of", "is", "are",
})

_ALL_STOP_WORDS: frozenset = _STOP_WORDS_CN | _STOP_WORDS_EN

_INTENT_PATTERNS: List[Tuple[str, List[str], bool]] = [
    ("request", ["请", "帮我", "麻烦", "做一个", "实现", "加一个", "改成", "修复", "优化", "写一个", "搞一个"], False),
    ("reminder_or_plan", ["提醒", "定时", "过会", "稍后", "分钟后", "小时后", "明天", "后天", "下周", "周末", "考试", "面试", "deadline"], False),
    ("commitment", ["我会", "我要", "我一定", "我打算", "我准备", "我决定", "我保证"], False),
    ("preference", ["喜欢", "讨厌", "偏好", "更想", "不想", "倾向", "最讨厌", "最喜欢"], False),
    ("emotion_negative", ["难过", "伤心", "焦虑", "紧张", "害怕", "烦", "累", "疲惫", "压力", "崩溃", "受不了"], False),
    ("emotion_positive", ["开心", "高兴", "兴奋", "期待", "幸福", "舒服", "满足"], False),
    ("self_reflection", ["我觉得", "我认为", "我发现", "我意识到", "其实", "原来"], False),
]

_FOLLOW_UP_KEYWORDS: List[str] = [
    "我需要", "我得", "我应该", "下次", "之后", "再说", "回头",
]

_RESOLVE_KEYWORDS: List[str] = [
    "搞定了", "完成了", "做好了", "解决了", "不用了", "已经",
    "取消了", "算了", "放弃了", "没事了", "好了",
]

_MAX_LOCKS = 256

_INTENT_TTL_SECONDS = 7 * 24 * 3600


@dataclass
class TrackedIntent:
    id: str
    user_id: str
    scope: str
    created_at: float
    message_id: str
    user_text: str
    assistant_text: str
    intent_type: str
    keywords: List[str]
    status: str = "pending"
    resolved_at: Optional[float] = None
    followup_count: int = 0
    last_followup_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "scope": self.scope,
            "created_at": self.created_at,
            "message_id": self.message_id,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
            "intent_type": self.intent_type,
            "keywords": self.keywords,
            "status": self.status,
            "resolved_at": self.resolved_at,
            "followup_count": self.followup_count,
            "last_followup_at": self.last_followup_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrackedIntent":
        return cls(
            id=str(d.get("id", "")),
            user_id=str(d.get("user_id", "")),
            scope=str(d.get("scope", "local")),
            created_at=float(d.get("created_at", 0.0) or 0.0),
            message_id=str(d.get("message_id", "")),
            user_text=str(d.get("user_text", "")),
            assistant_text=str(d.get("assistant_text", "")),
            intent_type=str(d.get("intent_type", "")),
            keywords=[str(x) for x in (d.get("keywords") or []) if str(x)],
            status=str(d.get("status", "pending")),
            resolved_at=float(d["resolved_at"]) if d.get("resolved_at") is not None else None,
            followup_count=int(d.get("followup_count", 0) or 0),
            last_followup_at=float(d["last_followup_at"]) if d.get("last_followup_at") is not None else None,
        )


def _extract_keywords(text: str, limit: int = 10) -> List[str]:
    t = (text or "").strip().lower()
    if not t:
        return []

    tokens: List[str] = []

    for m in re.finditer(r"[a-zA-Z0-9_]{2,}", t):
        tok = m.group(0)
        if tok not in _ALL_STOP_WORDS:
            tokens.append(tok)

    for m in re.finditer(r"[\u4e00-\u9fff]{2,}", t):
        s = m.group(0)
        if not s:
            continue
        if len(s) <= 6:
            if s not in _STOP_WORDS_CN:
                tokens.append(s)
            continue
        for size in (2, 3):
            for i in range(0, min(len(s) - size + 1, 10)):
                tok = s[i : i + size]
                if tok and tok not in _STOP_WORDS_CN:
                    tokens.append(tok)

    freq: Dict[str, int] = {}
    for tok in tokens:
        if len(tok) < 2:
            continue
        freq[tok] = freq.get(tok, 0) + 1

    ranked = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    return [tok for tok, _c in ranked[:limit]]


def _classify_intent(user_text: str, assistant_text: str) -> Optional[str]:
    ut = (user_text or "").strip()
    ul = ut.lower()

    for intent_type, keywords, case_insensitive in _INTENT_PATTERNS:
        source = ul if case_insensitive else ut
        if any(x in source for x in keywords):
            return intent_type

    at = (assistant_text or "").strip().lower()
    if any(x in at for x in _FOLLOW_UP_KEYWORDS):
        return "follow_up"

    return None


def _check_resolution(user_text: str) -> bool:
    ut = (user_text or "").strip().lower()
    return any(x in ut for x in _RESOLVE_KEYWORDS)


class MetaIntentService:
    def __init__(self):
        # P1-7: 用 OrderedDict 实现 LRU，每次 _get_lock 访问时移到末尾，
        # 驱逐时只删头部（最久未访问）且未被持有的锁
        self._locks: "OrderedDict[str, LazyAsyncLock]" = OrderedDict()
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_ttl: float = 30.0
        self._store_dir: Optional[Path] = None

    def _get_lock(self, user_id: str) -> LazyAsyncLock:
        """获取 user_id 对应的锁，按 LRU 策略管理缓存

        使用 LazyAsyncLock 避免在无事件循环时创建 asyncio.Lock 出错。
        驱逐时跳过 locked() 为 True 的锁（正在持有或有人在等）。
        若所有锁都被持有，允许突破上限创建新锁（正确性优先）。
        """
        lock = self._locks.get(user_id)
        if lock is not None:
            # 命中：移到末尾标记为最近访问
            self._locks.move_to_end(user_id)
            return lock

        # 未命中：需要创建新锁
        if len(self._locks) >= _MAX_LOCKS:
            # 驱逐头部（最久未访问）且未被持有的锁
            evicted = 0
            target_evict = max(1, _MAX_LOCKS // 8)  # 一次驱逐 1/8，更平滑
            keys_to_check = list(self._locks.keys())
            for k in keys_to_check:
                if evicted >= target_evict:
                    break
                candidate = self._locks.get(k)
                if candidate is None:
                    continue
                # 关键：只驱逐没人持有、也没人在等待的锁
                # lock.locked() 为 True 表示锁被持有 OR 有等待者
                if candidate.locked():
                    continue
                del self._locks[k]
                evicted += 1
            # 即使没驱逐够，也允许突破上限创建新锁（正确性优先于内存上限）

        lock = LazyAsyncLock()
        self._locks[user_id] = lock
        return lock

    def _release_lock(self, user_id: str, lock: LazyAsyncLock) -> None:
        """使用完成后清理锁引用，避免 _locks 字典无限增长

        只有当锁未被持有时才清理，保证并发安全。
        """
        if not lock.locked():
            self._locks.pop(user_id, None)

    def _get_store_dir(self) -> Path:
        if self._store_dir is not None:
            return self._store_dir
        settings = get_settings()
        base = Path(settings.memory.history_dir)
        if not base.is_absolute():
            base = Path(os.getcwd()) / base
        out = base / "metacognition"
        out.mkdir(parents=True, exist_ok=True)
        self._store_dir = out
        return out

    def _get_store_path(self, user_id: str, scope: str) -> Path:
        safe_user = re.sub(r"[^a-zA-Z0-9_.\-]", "_", str(user_id or "default"))
        safe_scope = re.sub(r"[^a-zA-Z0-9_.\-]", "_", str(scope or "local"))
        return self._get_store_dir() / f"{safe_user}.{safe_scope}.json"

    def _cache_key(self, user_id: str, scope: str) -> str:
        return f"{user_id}:{scope}"

    def _invalidate_cache(self, user_id: str, scope: str):
        self._cache.pop(self._cache_key(user_id, scope), None)

    def _load_items_sync(self, user_id: str, scope: str) -> List[Dict[str, Any]]:
        key = self._cache_key(user_id, scope)
        cached = self._cache.get(key)
        if cached is not None:
            ts, items = cached
            if time.time() - ts < self._cache_ttl:
                return [dict(it) for it in items]

        path = self._get_store_path(user_id, scope)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items: List[Dict[str, Any]] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and isinstance(data.get("items"), list):
                items = data["items"]
            self._cache[key] = (time.time(), items)
            return [dict(it) for it in items]
        except Exception as e:
            logger.warning("加载元认知数据失败 %s: %s", path, e)
            return []

    def _save_items_sync(self, user_id: str, scope: str, items: List[Dict[str, Any]]):
        path = self._get_store_path(user_id, scope)
        try:
            safe_json_dump_atomic({"items": items}, path, "utf-8")
            key = self._cache_key(user_id, scope)
            self._cache[key] = (time.time(), items)
        except Exception as e:
            logger.error("保存元认知数据失败 %s: %s", path, e)
            self._invalidate_cache(user_id, scope)
            raise

    def _prune_items(
        self, items: List[Dict[str, Any]], max_items: int = 500
    ) -> List[Dict[str, Any]]:
        if not items:
            return []
        now = time.time()
        alive = [
            it for it in items
            if it.get("status") == "pending"
            or (now - float(it.get("created_at", 0.0) or 0.0)) < _INTENT_TTL_SECONDS
        ]
        if len(alive) <= max_items:
            return alive
        alive.sort(key=lambda x: float(x.get("created_at", 0.0) or 0.0), reverse=True)
        return alive[:max_items]

    async def precompute_after_turn(
        self,
        *,
        user_id: str,
        scope: str,
        message_id: str,
        user_text: str,
        assistant_text: str,
    ) -> Optional[TrackedIntent]:
        ut = (user_text or "").strip()
        if not ut:
            return None

        intent_type = _classify_intent(ut, assistant_text)
        keywords = _extract_keywords(ut, limit=10)

        if _check_resolution(ut):
            await self._try_resolve_intents(user_id, scope, ut)
            return None

        if not intent_type and not keywords:
            return None

        actionable_types = {"request", "reminder_or_plan", "commitment", "follow_up"}
        status = "pending" if intent_type in actionable_types else "noted"

        item = TrackedIntent(
            id=str(uuid.uuid4()),
            user_id=str(user_id),
            scope=str(scope or "local"),
            created_at=time.time(),
            message_id=str(message_id or ""),
            user_text=ut[:240],
            assistant_text=(assistant_text or "")[:240],
            intent_type=intent_type or "general",
            keywords=keywords[:12],
            status=status,
        )

        lock = self._get_lock(user_id)
        try:
            async with lock:
                items = await asyncio.to_thread(self._load_items_sync, user_id, scope)
                items.insert(0, item.to_dict())
                items = self._prune_items(items)
                await asyncio.to_thread(self._save_items_sync, user_id, scope, items)
        finally:
            self._release_lock(user_id, lock)

        if is_debug_enabled("metacognition"):
            logger.info(
                "元认知追踪: user=%s intent=%s status=%s kw=%s",
                user_id, intent_type, status, keywords[:3],
            )
        return item

    async def _try_resolve_intents(
        self, user_id: str, scope: str, user_text: str
    ) -> int:
        msg_kw = set(_extract_keywords(user_text, limit=12))
        if not msg_kw:
            return 0

        lock = self._get_lock(user_id)
        try:
            async with lock:
                items = await asyncio.to_thread(self._load_items_sync, user_id, scope)
                resolved = 0
                now = time.time()
                for it in items:
                    if it.get("status") != "pending":
                        continue
                    it_kw = set(str(x) for x in (it.get("keywords") or []) if str(x))
                    if not it_kw:
                        continue
                    overlap = len(msg_kw & it_kw)
                    if overlap >= max(1, len(it_kw) // 2):
                        it["status"] = "resolved"
                        it["resolved_at"] = now
                        resolved += 1
                if resolved > 0:
                    await asyncio.to_thread(self._save_items_sync, user_id, scope, items)
                    logger.info("元认知: 自动解决 %d 条意图 user=%s", resolved, user_id)
        finally:
            self._release_lock(user_id, lock)
        return resolved

    async def get_pending_intents(
        self,
        *,
        user_id: str,
        scope: str,
        max_items: int = 5,
        min_age_hours: float = 0.5,
        max_followup_count: int = 3,
    ) -> List[TrackedIntent]:
        lock = self._get_lock(user_id)
        try:
            async with lock:
                items = await asyncio.to_thread(self._load_items_sync, user_id, scope)
        finally:
            self._release_lock(user_id, lock)

        now = time.time()
        result: List[TrackedIntent] = []
        for it in items:
            if it.get("status") != "pending":
                continue
            age_h = (now - float(it.get("created_at", 0.0) or 0.0)) / 3600.0
            if age_h < min_age_hours:
                continue
            fc = int(it.get("followup_count", 0) or 0)
            if fc >= max_followup_count:
                continue
            result.append(TrackedIntent.from_dict(it))
            if len(result) >= max_items:
                break
        return result

    async def build_injection(
        self,
        *,
        user_id: str,
        scope: str,
        message: str,
        max_items: int = 2,
        cooldown_seconds: int = 3 * 3600,
    ) -> Optional[Tuple[str, List[str]]]:
        msg = (message or "").strip()
        if not msg:
            return None

        msg_kw = set(_extract_keywords(msg, limit=12))

        lock = self._get_lock(user_id)
        try:
            async with lock:
                items = await asyncio.to_thread(self._load_items_sync, user_id, scope)
                if not items:
                    return None

                now = time.time()
                matched: List[Tuple[int, Dict[str, Any]]] = []
                for it in items:
                    if it.get("status") != "pending":
                        continue
                    last_fu = it.get("last_followup_at")
                    if last_fu is not None:
                        try:
                            if now - float(last_fu) < float(cooldown_seconds):
                                continue
                        except (ValueError, TypeError):
                            pass
                    it_kw = set(str(x) for x in (it.get("keywords") or []) if str(x))
                    overlap = len(msg_kw & it_kw)
                    if overlap <= 0:
                        continue
                    age_h = max(0.0, (now - float(it.get("created_at", 0.0) or 0.0)) / 3600.0)
                    fc = int(it.get("followup_count", 0) or 0)
                    if age_h > 48 or fc >= 3:
                        continue
                    matched.append((overlap, it))

                if not matched:
                    return None

                matched.sort(key=lambda x: x[0], reverse=True)
                chosen = [it for _, it in matched[: max(1, int(max_items))]]

                chosen_ids: List[str] = []
                dirty = False
                for it in chosen:
                    it_id = str(it.get("id") or "")
                    if not it_id:
                        continue
                    chosen_ids.append(it_id)
                    it["followup_count"] = int(it.get("followup_count", 0) or 0) + 1
                    it["last_followup_at"] = now
                    dirty = True

                if dirty:
                    await asyncio.to_thread(self._save_items_sync, user_id, scope, items)
        finally:
            self._release_lock(user_id, lock)

        lines: List[str] = []
        for it in chosen:
            intent = str(it.get("intent_type") or "")
            src = str(it.get("user_text") or "").strip().replace("\n", " ")
            if len(src) > 80:
                src = src[:80] + "..."
            age_h = (now - float(it.get("created_at", 0.0) or 0.0)) / 3600.0
            if age_h < 1:
                age_str = "刚刚"
            elif age_h < 24:
                age_str = f"{int(age_h)}小时前"
            else:
                age_str = f"{int(age_h / 24)}天前"

            intent_label = {
                "request": "请求",
                "reminder_or_plan": "计划/提醒",
                "commitment": "承诺",
                "follow_up": "待跟进",
                "preference": "偏好",
                "emotion_negative": "负面情绪",
                "emotion_positive": "正面情绪",
                "self_reflection": "自我反思",
            }.get(intent, "")

            line = f"- [{age_str}]"
            if intent_label:
                line += f" {intent_label}："
            else:
                line += " "
            line += f"\u201c{src}\u201d"
            fc = int(it.get("followup_count", 0) or 0)
            if fc > 0:
                line += f"（已跟进{fc}次）"
            lines.append(line)

        if not lines:
            return None

        content = (
            "【未完成意图追踪（隐藏，仅供参考）】\n"
            "以下是用户之前表达过但尚未确认完成的意图，如果当前话题相关，可以自然地跟进一句。\n"
            + "\n".join(lines)
            + "\n\n要求：只在话题高度相关时自然带出，例如：\n"
            "\u201c对了，你之前说要做那个……后来怎么样了？\u201d\n"
            "不要提到\u2018意图/追踪/系统/注入\u2019，不要显得刻意，最多一句。"
        )
        if is_debug_enabled("metacognition"):
            logger.info("元认知注入: user=%s chosen=%s", user_id, chosen_ids)
        return content, chosen_ids

    async def build_active_care_hint(
        self,
        *,
        user_id: str,
        scope: str,
        max_items: int = 2,
        min_age_hours: float = 1.0,
        max_followup_count: int = 2,
    ) -> Optional[str]:
        pending = await self.get_pending_intents(
            user_id=user_id,
            scope=scope,
            max_items=max_items,
            min_age_hours=min_age_hours,
            max_followup_count=max_followup_count,
        )
        if not pending:
            return None

        now = time.time()
        lines: List[str] = []
        for it in pending:
            src = it.user_text.strip().replace("\n", " ")
            if len(src) > 80:
                src = src[:80] + "..."
            age_h = (now - it.created_at) / 3600.0
            if age_h < 24:
                age_str = f"{int(age_h)}小时前"
            else:
                age_str = f"{int(age_h / 24)}天前"

            intent_label = {
                "request": "请求",
                "reminder_or_plan": "计划/提醒",
                "commitment": "承诺",
                "follow_up": "待跟进",
            }.get(it.intent_type, "意图")

            line = f"- [{age_str}] {intent_label}：\u201c{src}\u201d"
            if it.followup_count > 0:
                line += f"（已跟进{it.followup_count}次）"
            lines.append(line)

        lock = self._get_lock(user_id)
        try:
            async with lock:
                items = await asyncio.to_thread(self._load_items_sync, user_id, scope)
                pending_ids = {it.id for it in pending}
                dirty = False
                for it in items:
                    if it.get("id") in pending_ids:
                        it["followup_count"] = int(it.get("followup_count", 0) or 0) + 1
                        it["last_followup_at"] = now
                        dirty = True
                if dirty:
                    await asyncio.to_thread(self._save_items_sync, user_id, scope, items)
        finally:
            self._release_lock(user_id, lock)

        return (
            "【用户未完成意图（可选择性跟进）】\n"
            + "\n".join(lines)
            + "\n\n如果合适，可以自然地跟进其中一条。不要生硬，不要全部都提。"
        )


_global_meta_intent_service: Optional[MetaIntentService] = None


def get_meta_intent_service() -> MetaIntentService:
    global _global_meta_intent_service
    if _global_meta_intent_service is None:
        _global_meta_intent_service = MetaIntentService()
    return _global_meta_intent_service
