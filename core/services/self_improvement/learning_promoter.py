"""
自我改进系统 — 学习晋升与模式检测

将高价值学习/纠正晋升为永久规则：
- 重复模式检测（Recurrence-Count ≥ 3 → 晋升）
- 纠正晋升（2条相似纠正 → 永久规则）
- 晋升目标：project_rules.md / prompt 指令 / 配置

晋升流程：
1. 识别候选（达到阈值的学习/纠正）
2. 提炼为简洁规则
3. 写入晋升目标
4. 更新原始条目状态

P2-7 实现要点：
1. _promote_to_core_memory: 真正写入 MEMORY.md（通过注入的 CoreMemory 实例）
2. _promote_to_prompt: 真正写入 promoted_rules.md（prompt 系统可读取的规则文件）
3. _promote_to_rules: 原子写入 project_rules.md（使用 safe_write_text）
4. 所有写入操作去重（避免重复晋升同一条规则）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.atomic_io import safe_write_text
from core.utils.logger import get_logger
from .models import (
    CorrectionEntry,
    EntryStatus,
    LearningCategory,
    LearningEntry,
    MemorySection,
)

logger = get_logger("LearningPromoter")

# ── 晋升阈值 ──────────────────────────────────────────

_RECURRENCE_THRESHOLD = 3      # 重复出现次数阈值
_RECURRENCE_WINDOW_DAYS = 30   # 重复出现时间窗口（天）
_CORRECTION_SIMILAR_THRESHOLD = 2  # 相似纠正数量阈值

# ── 晋升目标 ──────────────────────────────────────────

PROMOTION_TARGET_RULES = "project_rules"     # → .trae/rules/project_rules.md
PROMOTION_TARGET_PROMPT = "prompt"           # → prompt 组件
PROMOTION_TARGET_CONFIG = "config"           # → 配置文件
PROMOTION_TARGET_MEMORY = "core_memory"      # → MEMORY.md 永久区


class LearningPromoter:
    """学习晋升与模式检测器

    P2-7: 实现真正的晋升逻辑
    - _promote_to_core_memory: 通过注入的 CoreMemory 实例写入 MEMORY.md
    - _promote_to_prompt: 写入 promoted_rules.md（prompt 系统可读取）
    - _promote_to_rules: 原子写入 project_rules.md
    """

    def __init__(
        self,
        base_dir: Path,
        project_root: Path,
        core_memory: Optional[Any] = None,
    ):
        """
        Args:
            base_dir: 数据目录（scope-specific，如 aveline_data/）
            project_root: 项目根目录
            core_memory: 可选的 CoreMemory 实例，由 service 层注入。
                         若未注入，_promote_to_core_memory 会延迟创建。
        """
        self._base_dir = base_dir
        self._project_root = project_root
        self._rules_file = project_root / ".trae" / "rules" / "project_rules.md"
        # P2-7: prompt 规则文件（prompt 系统可读取的晋升规则）
        self._prompt_rules_file = (
            project_root
            / "core"
            / "agents"
            / "chat_agent_components"
            / "persona_system"
            / "prompt"
            / "promoted_rules.md"
        )
        # 由 service 层注入的 CoreMemory 实例（避免重复创建、共享缓存）
        self._core_memory = core_memory
        self._core_memory_initialized = core_memory is not None

    # ── 晋升检测 ────────────────────────────────────────

    async def find_promotion_candidates(
        self,
        learnings: List[LearningEntry],
        corrections: List[CorrectionEntry],
    ) -> List[Dict[str, Any]]:
        """
        找出达到晋升阈值的候选条目。

        返回候选列表，每个候选包含：
        - entry: 原始条目
        - rule: 提炼后的规则
        - target: 晋升目标
        - reason: 晋升原因
        """
        candidates = []

        # 1. 重复模式检测
        for entry in learnings:
            if entry.status != EntryStatus.PENDING:
                continue
            if entry.recurrence_count < _RECURRENCE_THRESHOLD:
                continue
            # 检查时间窗口
            if entry.first_seen and entry.last_seen:
                try:
                    first = time.strptime(entry.first_seen, "%Y-%m-%d")
                    last = time.strptime(entry.last_seen, "%Y-%m-%d")
                    days = (time.mktime(last) - time.mktime(first)) / 86400
                    if days > _RECURRENCE_WINDOW_DAYS:
                        continue
                except ValueError:
                    pass

            rule = self._distill_learning_to_rule(entry)
            target = self._determine_target(entry)
            candidates.append({
                "entry": entry,
                "rule": rule,
                "target": target,
                "reason": f"重复出现 {entry.recurrence_count} 次",
            })

        # 2. 纠正晋升检测
        pending_corrections = [c for c in corrections if c.status == EntryStatus.PENDING]
        similar_groups = self._group_similar_corrections(pending_corrections)
        for group in similar_groups:
            if len(group) >= _CORRECTION_SIMILAR_THRESHOLD:
                rule = self._distill_corrections_to_rule(group)
                candidates.append({
                    "entry": group[0],
                    "rule": rule,
                    "target": PROMOTION_TARGET_RULES,
                    "reason": f"{len(group)}条相似纠正",
                })

        return candidates

    # ── 执行晋升 ────────────────────────────────────────

    async def promote(self, candidate: Dict[str, Any]) -> bool:
        """执行晋升：将规则写入目标文件"""
        rule = candidate.get("rule", "")
        target = candidate.get("target", "")
        entry = candidate.get("entry")

        if not rule or not target:
            return False

        try:
            if target == PROMOTION_TARGET_RULES:
                success = await self._promote_to_rules(rule)
            elif target == PROMOTION_TARGET_MEMORY:
                success = await self._promote_to_core_memory(rule)
            elif target == PROMOTION_TARGET_PROMPT:
                success = await self._promote_to_prompt(rule)
            else:
                logger.warning("未知晋升目标: %s", target)
                return False

            if success and entry:
                entry.status = EntryStatus.PROMOTED
                entry.promoted_to = target
                if hasattr(entry, "promoted_at"):
                    entry.promoted_at = time.time()

            return success
        except Exception as e:
            logger.error("晋升失败: %s", e)
            return False

    # ── 规则提炼 ────────────────────────────────────────

    @staticmethod
    def _distill_learning_to_rule(entry: LearningEntry) -> str:
        """将学习条目提炼为简洁规则"""
        # 优先使用 suggested_action
        if entry.suggested_action:
            return entry.suggested_action
        # 否则从 details 中提炼
        if entry.details:
            # 取第一句
            first_sentence = entry.details.split("。")[0].split("\n")[0]
            if len(first_sentence) > 100:
                first_sentence = first_sentence[:100]
            return first_sentence
        return entry.summary

    @staticmethod
    def _distill_corrections_to_rule(corrections: List[CorrectionEntry]) -> str:
        """将一组相似纠正提炼为规则"""
        # 合并所有教训
        lessons = []
        for c in corrections:
            if c.lesson:
                lessons.append(c.lesson)
        if lessons:
            # 取最通用的教训
            return lessons[0]
        # 回退到纠正内容
        corrections_text = [c.correction for c in corrections if c.correction]
        return corrections_text[0] if corrections_text else ""

    @staticmethod
    def _determine_target(entry: LearningEntry) -> str:
        """根据学习类型确定晋升目标"""
        if entry.category == LearningCategory.CORRECTION:
            return PROMOTION_TARGET_RULES
        if entry.category == LearningCategory.BEST_PRACTICE:
            return PROMOTION_TARGET_PROMPT
        if entry.category == LearningCategory.KNOWLEDGE_GAP:
            return PROMOTION_TARGET_MEMORY
        return PROMOTION_TARGET_RULES

    # ── 相似纠正分组 ────────────────────────────────────

    @staticmethod
    def _group_similar_corrections(
        corrections: List[CorrectionEntry],
    ) -> List[List[CorrectionEntry]]:
        """将相似纠正分组"""
        import re

        groups: List[List[CorrectionEntry]] = []
        assigned = set()

        for i, a in enumerate(corrections):
            if i in assigned:
                continue
            group = [a]
            assigned.add(i)

            a_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", a.title.lower()))
            a_tags = set(a.tags)

            for j, b in enumerate(corrections):
                if j in assigned:
                    continue
                # 标签重叠
                if a_tags and b.tags:
                    if set(b.tags) & a_tags:
                        group.append(b)
                        assigned.add(j)
                        continue
                # 标题关键词重叠
                b_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", b.title.lower()))
                if a_words and b_words:
                    overlap = a_words & b_words
                    if len(overlap) >= 2:
                        group.append(b)
                        assigned.add(j)

            if len(group) >= 2:
                groups.append(group)

        return groups

    # ── 晋升写入 ────────────────────────────────────────

    async def _promote_to_rules(self, rule: str) -> bool:
        """晋升到 project_rules.md（P2-7: 改用原子写入）"""
        try:
            rules_dir = self._rules_file.parent
            rules_dir.mkdir(parents=True, exist_ok=True)

            existing = ""
            if self._rules_file.exists():
                existing = self._rules_file.read_text(encoding="utf-8")

            # 检查是否已存在相同规则
            if rule in existing:
                logger.debug("规则已存在于 project_rules.md，跳过: %s", rule[:50])
                return True

            # 追加规则
            date_str = time.strftime("%Y-%m-%d")
            new_rule = f"\n- [{date_str} 自动晋升] {rule}\n"

            if existing and not existing.endswith("\n"):
                existing += "\n"
            existing += new_rule

            # P2-7: 使用原子写入，避免进程崩溃导致文件被截断
            safe_write_text(existing, self._rules_file, encoding="utf-8")
            logger.info("晋升规则到 project_rules.md: %s", rule[:50])
            return True
        except Exception as e:
            logger.error("晋升到 project_rules.md 失败: %s", e)
            return False

    async def _promote_to_core_memory(self, rule: str) -> bool:
        """晋升到 MEMORY.md 永久区（P2-7: 真正写入）

        通过注入的 CoreMemory 实例写入，避免重复创建实例和缓存不一致。
        若未注入 CoreMemory，则延迟创建一个。
        规则写入 EXPERIENCE 分区（业务经验，长期保留）。
        """
        try:
            core_memory = await self._get_or_create_core_memory()
            if core_memory is None:
                logger.error("CoreMemory 实例不可用，无法晋升到 MEMORY.md")
                return False

            # 写入 EXPERIENCE 分区（业务经验）
            # CoreMemory.add_item 内部会去重，无需在此处检查
            date_str = time.strftime("%Y-%m-%d")
            memory_item = f"[{date_str} 自动晋升] {rule}"
            success = await core_memory.add_item(MemorySection.EXPERIENCE, memory_item)

            if success:
                logger.info("晋升规则到 MEMORY.md: %s", rule[:50])
            else:
                # add_item 返回 False 可能是因为去重或 NOT-to-save 检查
                logger.debug(
                    "MEMORY.md add_item 返回 False（可能已存在或被 NOT-to-save 过滤）: %s",
                    rule[:50],
                )
                # 去重不算失败，返回 True 避免重复晋升
                return True
            return success
        except Exception as e:
            logger.error("晋升到 MEMORY.md 失败: %s", e)
            return False

    async def _promote_to_prompt(self, rule: str) -> bool:
        """晋升到 prompt 组件（P2-7: 真正写入 promoted_rules.md）

        写入 prompt 目录下的 promoted_rules.md 文件，
        prompt assembler 可读取该文件并将规则注入到系统 prompt 中。
        使用原子写入确保文件安全。
        """
        try:
            # 确保目录存在
            prompt_dir = self._prompt_rules_file.parent
            prompt_dir.mkdir(parents=True, exist_ok=True)

            existing = ""
            if self._prompt_rules_file.exists():
                existing = self._prompt_rules_file.read_text(encoding="utf-8")

            # 检查是否已存在相同规则
            if rule in existing:
                logger.debug("规则已存在于 promoted_rules.md，跳过: %s", rule[:50])
                return True

            # 追加规则
            date_str = time.strftime("%Y-%m-%d")
            new_rule = f"- [{date_str} 自动晋升] {rule}\n"

            if existing and not existing.endswith("\n"):
                existing += "\n"
            existing += new_rule

            # P2-7: 使用原子写入
            safe_write_text(existing, self._prompt_rules_file, encoding="utf-8")
            logger.info("晋升规则到 promoted_rules.md: %s", rule[:50])
            return True
        except Exception as e:
            logger.error("晋升到 promoted_rules.md 失败: %s", e)
            return False

    async def _get_or_create_core_memory(self):
        """获取或创建 CoreMemory 实例（延迟初始化）"""
        if self._core_memory is not None:
            return self._core_memory

        # 延迟创建 CoreMemory 实例
        # 注意：这种方式创建的实例不与 service 层共享缓存，
        # 优先由 service 层通过构造函数注入
        try:
            from .core_memory import CoreMemory
            self._core_memory = CoreMemory(self._base_dir, scope="user")
            self._core_memory.ensure_initialized()
            logger.debug("延迟创建 CoreMemory 实例: %s", self._base_dir)
            return self._core_memory
        except Exception as e:
            logger.error("创建 CoreMemory 实例失败: %s", e)
            return None
