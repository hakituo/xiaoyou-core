"""
自我改进系统 — 主服务类

统一入口，整合所有子模块：
- LearningLogger: 结构化学习/错误/功能请求日志
- CorrectionTracker: 通用纠正检测与记录
- CoreMemory: MEMORY.md 核心记忆管理
- LearningPromoter: 学习晋升与模式检测
- DailyLogger: 每日日志生成
- DriftGuard: 记忆漂移防护

与现有系统的集成点：
- WeightedMemoryManager: 记忆检索与存储
- AutoHealService: 自愈发现的模式 → 晋升为规则
- JournalService: 日记联动
- correction.py: 生活类纠正保留，通用纠正扩展
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.common import get_project_root

from .learning_logger import LearningLogger
from .correction_tracker import CorrectionTracker
from .core_memory import CoreMemory, MemorySection
from .learning_promoter import LearningPromoter
from .daily_logger import DailyLogger
from .drift_guard import DriftGuard
from .models import (
    LearningEntry,
    ErrorEntry,
    FeatureRequestEntry,
    CorrectionEntry,
    LearningCategory,
    EntryPriority,
    EntryArea,
)

logger = get_logger("SelfImprovementService")


class SelfImprovementService:
    """自我改进系统主服务

    支持 scope 隔离（双角色）：
    - aveline → aveline_data/
    - ling → ling_data/
    - user → user_data/
    """

    def __init__(self, base_dir: Optional[Path] = None, project_root: Optional[Path] = None, scope: str = "user"):
        self._scope = scope
        self._base_dir = base_dir
        self._project_root = project_root or Path(get_project_root())
        self._initialized = False

        # 子模块（延迟初始化）
        self._learning_logger: Optional[LearningLogger] = None
        self._correction_tracker: Optional[CorrectionTracker] = None
        self._core_memory: Optional[CoreMemory] = None
        self._learning_promoter: Optional[LearningPromoter] = None
        self._daily_logger: Optional[DailyLogger] = None
        self._drift_guard: Optional[DriftGuard] = None

    # ── 初始化 ──────────────────────────────────────────

    def initialize(self, base_dir: Optional[Path] = None) -> None:
        """初始化服务（必须在使用前调用）"""
        if base_dir:
            self._base_dir = base_dir

        if not self._base_dir:
            # 根据 scope 确定数据目录
            from core.utils.data_paths import get_role_data_dir
            self._base_dir = get_role_data_dir(self._scope)

        self._base_dir = Path(self._base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        # 初始化子模块
        self._learning_logger = LearningLogger(self._base_dir)
        self._correction_tracker = CorrectionTracker(self._base_dir)
        self._core_memory = CoreMemory(self._base_dir, scope=self._scope)
        # P2-7: 注入 CoreMemory 实例到 LearningPromoter，避免重复创建与缓存不一致
        self._learning_promoter = LearningPromoter(
            self._base_dir,
            self._project_root,
            core_memory=self._core_memory,
        )
        self._daily_logger = DailyLogger(self._base_dir)
        self._drift_guard = DriftGuard(self._project_root)

        # 确保目录和文件存在
        self._learning_logger.ensure_dirs()
        self._core_memory.ensure_initialized()
        self._daily_logger.ensure_dirs()

        self._initialized = True
        logger.info("自我改进系统初始化完成: %s", self._base_dir)

    def _ensure_initialized(self) -> None:
        """确保已初始化"""
        if not self._initialized:
            self.initialize()

    # ── 属性访问 ────────────────────────────────────────

    @property
    def learning_logger(self) -> LearningLogger:
        self._ensure_initialized()
        return self._learning_logger

    @property
    def correction_tracker(self) -> CorrectionTracker:
        self._ensure_initialized()
        return self._correction_tracker

    @property
    def core_memory(self) -> CoreMemory:
        self._ensure_initialized()
        return self._core_memory

    @property
    def learning_promoter(self) -> LearningPromoter:
        self._ensure_initialized()
        return self._learning_promoter

    @property
    def daily_logger(self) -> DailyLogger:
        self._ensure_initialized()
        return self._daily_logger

    @property
    def drift_guard(self) -> DriftGuard:
        self._ensure_initialized()
        return self._drift_guard

    # ── 学习日志 ────────────────────────────────────────

    async def log_learning(
        self,
        *,
        category: LearningCategory = LearningCategory.INSIGHT,
        priority: EntryPriority = EntryPriority.MEDIUM,
        area: EntryArea = EntryArea.BACKEND,
        summary: str = "",
        details: str = "",
        suggested_action: str = "",
        source: str = "conversation",
        related_files: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        pattern_key: str = "",
        recurrence_count: int = 1,
    ) -> str:
        """记录学习条目"""
        entry = LearningEntry(
            category=category,
            priority=priority,
            area=area,
            summary=summary,
            details=details,
            suggested_action=suggested_action,
            source=source,
            related_files=related_files or [],
            tags=tags or [],
            pattern_key=pattern_key,
            recurrence_count=recurrence_count,
        )
        entry_id = await self.learning_logger.log_learning(entry)

        # 同时写入 MEMORY.md 业务经验区
        if summary:
            await self.core_memory.add_item(
                MemorySection.EXPERIENCE,
                f"[{category.value}] {summary}",
            )

        # 写入每日日志
        self.daily_logger.append_event(
            f"学习: {summary[:50]}",
            category="learning",
            tags=[category.value],
        )

        return entry_id

    async def log_error(
        self,
        *,
        priority: EntryPriority = EntryPriority.HIGH,
        area: EntryArea = EntryArea.BACKEND,
        summary: str = "",
        error_message: str = "",
        context: str = "",
        suggested_fix: str = "",
        reproducible: str = "unknown",
        related_files: Optional[List[str]] = None,
    ) -> str:
        """记录错误条目"""
        entry = ErrorEntry(
            priority=priority,
            area=area,
            summary=summary,
            error_message=error_message,
            context=context,
            suggested_fix=suggested_fix,
            reproducible=reproducible,
            related_files=related_files or [],
        )
        entry_id = await self.learning_logger.log_error(entry)

        # 写入每日日志
        self.daily_logger.append_event(
            f"错误: {summary[:50]}",
            category="error",
            details=error_message[:100] if error_message else "",
        )

        return entry_id

    async def log_feature_request(
        self,
        *,
        capability: str = "",
        user_context: str = "",
        area: EntryArea = EntryArea.BACKEND,
        complexity: str = "medium",
    ) -> str:
        """记录功能请求"""
        entry = FeatureRequestEntry(
            area=area,
            capability=capability,
            user_context=user_context,
            complexity=complexity,
        )
        return await self.learning_logger.log_feature_request(entry)

    # ── 纠正追踪 ────────────────────────────────────────

    async def detect_and_record_correction(
        self,
        text: str,
        *,
        context: str = "",
    ) -> Optional[CorrectionEntry]:
        """检测并记录纠正（如果文本包含纠正信号）"""
        signal = CorrectionTracker.detect_correction_signal(text)
        if signal is None:
            return None

        # 记录纠正
        entry = await self.correction_tracker.record_correction(
            signal_type=signal,
            title=text[:50],
            correction=context or text,
            my_error="",
            root_cause="",
            lesson="",
            how_to_apply="",
        )

        # 同时写入 LEARNINGS.md（作为 correction 类别）
        learning = self.correction_tracker.to_learning_entry(entry)
        await self.learning_logger.log_learning(learning)

        # 写入 MEMORY.md 纠正记录区
        await self.core_memory.add_item(
            MemorySection.CORRECTIONS,
            f"[{time.strftime('%Y-%m-%d')}] {text[:60]}",
        )

        # 写入每日日志
        self.daily_logger.append_correction_event(
            text[:50],
            root_cause="",
        )

        return entry

    # ── 核心记忆 ────────────────────────────────────────

    async def add_preference(self, preference: str) -> bool:
        """添加用户偏好到 MEMORY.md"""
        result = await self.core_memory.add_item(MemorySection.PREFERENCES, preference)
        if result:
            self.daily_logger.append_event(
                f"偏好: {preference[:50]}",
                category="preference",
            )
        return result

    async def add_experience(self, experience: str, tags: Optional[List[str]] = None) -> bool:
        """添加业务经验到 MEMORY.md"""
        tag_str = " ".join(f"[{t}]" for t in (tags or []))
        item = f"{tag_str} {experience}".strip() if tag_str else experience
        return await self.core_memory.add_item(MemorySection.EXPERIENCE, item)

    async def add_active_task(self, task: str) -> bool:
        """添加活跃任务到 MEMORY.md"""
        return await self.core_memory.add_item(MemorySection.ACTIVE_TASKS, task)

    async def complete_task(self, task: str) -> bool:
        """完成任务（从活跃任务中移除）"""
        result = await self.core_memory.remove_item(MemorySection.ACTIVE_TASKS, task)
        if result:
            self.daily_logger.append_task_progress(task, "完成")
        return result

    async def add_summary(self, summary: str) -> bool:
        """添加对话摘要到 MEMORY.md"""
        date_tag = f"[{time.strftime('%Y-%m-%d')}]"
        return await self.core_memory.add_item(
            MemorySection.SUMMARIES,
            f"{date_tag} {summary}",
        )

    # ── 记忆漂移防护 ────────────────────────────────────

    def verify_memory(self, content: str) -> Dict[str, Any]:
        """验证记忆内容准确性（同步兼容入口）"""
        return self.drift_guard.verify_memory(content)

    async def verify_memory_async(self, content: str) -> Dict[str, Any]:
        """验证记忆内容准确性（异步入口，P2-6）。

        将重 IO 的函数名索引构建放到线程池，避免阻塞事件循环。
        """
        return await self.drift_guard.verify_memory_async(content)

    def invalidate_drift_cache(self) -> None:
        """失效 DriftGuard 缓存（项目结构变更后调用）"""
        self.drift_guard.invalidate_cache()

    # ── 晋升与模式检测 ──────────────────────────────────

    async def check_promotions(self) -> List[Dict[str, Any]]:
        """检查并执行晋升"""
        learnings = await self.learning_logger.get_recurring_patterns(min_recurrence=3)
        corrections = await self.correction_tracker.get_pending_corrections()

        candidates = await self.learning_promoter.find_promotion_candidates(
            learnings=learnings,
            corrections=corrections,
        )

        promoted = []
        for candidate in candidates:
            success = await self.learning_promoter.promote(candidate)
            if success:
                # 更新原始条目状态
                entry = candidate.get("entry")
                if entry and hasattr(entry, "id"):
                    await self.learning_logger.promote_entry(
                        entry.id, candidate.get("target", "")
                    )
                promoted.append(candidate)
                logger.info(
                    "晋升成功: %s → %s",
                    candidate.get("rule", "")[:40],
                    candidate.get("target", ""),
                )

        return promoted

    # ── 自动瘦身 ────────────────────────────────────────

    async def auto_slim(self) -> Dict[str, int]:
        """执行 MEMORY.md 自动瘦身"""
        return await self.core_memory.auto_slim()

    # ── Session 启动 ────────────────────────────────────

    async def on_session_start(self) -> Dict[str, Any]:
        """
        Session 启动时调用：
        1. 加载 MEMORY.md
        2. 检查是否需要瘦身
        3. 返回核心记忆摘要
        """
        self._ensure_initialized()

        # 加载核心记忆
        sections = await self.core_memory.load()

        # 检查是否需要瘦身
        slim_result = await self.auto_slim()

        # 获取统计
        stats = await self.learning_logger.get_stats()

        # 归档旧日志
        archived = self.daily_logger.archive_old_logs()

        return {
            "memory_sections": {k.value: len(v) for k, v in sections.items()},
            "slim_result": slim_result,
            "stats": stats,
            "archived_logs": archived,
        }

    # ── 对话轮次结束 ────────────────────────────────────

    async def on_turn_end(
        self,
        *,
        user_text: str = "",
        assistant_text: str = "",
        had_correction: bool = False,
        task_completed: str = "",
        decision_made: str = "",
    ) -> None:
        """
        对话轮次结束时调用：
        1. 检测纠正
        2. 记录决策
        3. 更新活跃任务
        4. 检查晋升
        """
        self._ensure_initialized()

        # 检测纠正
        if user_text:
            await self.detect_and_record_correction(user_text, context=assistant_text)

        # 记录决策
        if decision_made:
            self.daily_logger.append_decision(decision_made)

        # 更新活跃任务
        if task_completed:
            await self.complete_task(task_completed)

        # 定期检查晋升（每10次轮次检查一次）
        # 这里简化为每次都检查，实际可以加计数器
        try:
            await self.check_promotions()
        except Exception as e:
            logger.warning("晋升检查失败: %s", e)

    # ── Prompt 注入 ─────────────────────────────────────

    async def build_prompt_injection(self) -> str:
        """生成用于 prompt 注入的核心记忆文本（异步版本，含 JournalService 日记摘要）"""
        self._ensure_initialized()
        return await self.core_memory.build_injection_text()

    def build_prompt_injection_sync(self) -> str:
        """生成用于 prompt 注入的核心记忆文本（同步版本，跳过日记摘要区）

        供同步调用方使用（如 assembler.py 的 build_persona_prompt_split）。
        全空时返回空字符串，调用方据此判断是否注入。
        """
        self._ensure_initialized()
        return self.core_memory.build_injection_text_sync()

    # ── LLM 语义合并（夜间兜底） ────────────────────────

    async def llm_merge_preferences(self, model_hint: Optional[str] = None) -> Dict[str, Any]:
        """用 LLM 合并 PREFERENCES 区的语义重复条目（夜间调用）

        平时 add_item 走 embedding + 关键词桶去重，本方法用 LLM 兜底处理漏判的中文同义改写。
        """
        self._ensure_initialized()
        return await self.core_memory.llm_merge_preferences(model_hint=model_hint)

    # ── 统计 ────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """获取自我改进系统统计"""
        self._ensure_initialized()
        stats = await self.learning_logger.get_stats()
        sections = await self.core_memory.get_all()
        stats["memory_sections"] = {k.value: len(v) for k, v in sections.items()}
        return stats


# ── 全局单例（按 scope 缓存） ─────────────────────────────

_global_services: Dict[str, SelfImprovementService] = {}


def get_self_improvement_service(
    base_dir: Optional[Path] = None,
    scope: str = "user",
) -> SelfImprovementService:
    """获取指定 scope 的自我改进服务实例"""
    global _global_services
    if scope not in _global_services:
        _global_services[scope] = SelfImprovementService(base_dir=base_dir, scope=scope)
    return _global_services[scope]
