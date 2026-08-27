"""日记服务门面（JournalService）

本模块是 journal 包对外的统一入口，采用门面模式（Facade）：
- JournalService 类作为薄壳，保留所有原有公共方法签名
- 每日/每月总结、记忆蒸馏职责委托给 JournalSummaryService
- 明日计划管理职责委托给 JournalPlanService
- 共享工具函数复用 journal_helpers 中的实现

外部导入路径保持不变：
    from core.services.journal.service import JournalService, get_journal_service
"""
import asyncio
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.singleton import singleton
from core.utils.time_utils import get_current_time
from core.services.journal.models import JournalEntry
from core.services.journal.storage import JournalStorage
from core.utils.data_paths import _resolve_scope_from_active_persona
from config.integrated_config import get_settings
from core.services.journal.journal_helpers import (
    append_weighted_memory,
    get_journal_model_hint,
    parse_date,
    should_skip_memory_append,
)

logger = get_logger("JournalService")


@singleton
class JournalService:
    """日记服务门面

    自身只保留日记 CRUD 与记忆联动相关方法（write_entry / get_entries /
    _append_journal_memory），其余职责通过委托转发到子服务：
    - 总结相关 → JournalSummaryService
    - 计划相关 → JournalPlanService
    """

    def __init__(self):
        self.storage = JournalStorage()
        self.settings = get_settings()
        # 子服务持有 service 引用，便于回写日记条目、调用记忆联动等
        from core.services.journal.plan_checkpoint_service import PlanCheckpointService
        from core.services.journal.summary_service import JournalSummaryService
        from core.services.journal.plan_service import JournalPlanService
        self._summary_service = JournalSummaryService(self)
        self._plan_service = JournalPlanService(self)
        self._plan_checkpoint_service = PlanCheckpointService(self)

    # ── 内部工具（供子服务通过 self.service.xxx 调用）─────────

    def _parse_date(self, date_str: Optional[str]):
        """解析日期字符串；未提供时走统一凌晨归属逻辑"""
        return parse_date(date_str)

    def _get_journal_model_hint(self) -> str:
        """获取日记专用模型 hint（保留以兼容外部调用）"""
        return get_journal_model_hint(self.settings)

    # ── 日记 CRUD + 记忆联动 ─────────────────────────────────

    async def write_entry(
        self,
        content: str,
        mood: str = "neutral",
        thought: str = None,
        type: str = "daily",
        tags: List[str] = None,
        source: str = None,
    ) -> str:
        # 日记是 AI 写的，source 默认为当前 persona 的 scope
        if source is None:
            source = _resolve_scope_from_active_persona()
        now = get_current_time()
        entry = JournalEntry(
            timestamp=now.timestamp(),
            time_str=now.strftime("%H:%M:%S"),
            type=type,
            content=content,
            mood=mood,
            thought=thought,
            tags=tags or [],
            source=source,
        )
        saved_path = await self.storage.save_entry(entry, now)
        try:
            from core.services.journal.persona_exports import (
                get_persona_journal_export_service,
            )
            await get_persona_journal_export_service().export_after_entry(entry, now)
        except Exception as e:
            logger.warning(f"更新 persona 日记导出失败: {e}")
        await self._append_journal_memory(entry)
        return saved_path

    async def _append_journal_memory(self, entry: JournalEntry) -> None:
        try:
            if should_skip_memory_append(entry, self.settings):
                return
            # 复用 journal_helpers 中的同步实现，在线程中执行避免阻塞事件循环
            await asyncio.to_thread(append_weighted_memory, entry, self.settings)
        except Exception as e:
            logger.warning(f"Journal 写入记忆失败: {e}")

    async def get_entries(self, date: Optional[str] = None) -> List[JournalEntry]:
        dt = self._parse_date(date)
        return await self.storage.get_entries(dt)

    # ── 总结相关：委托给 JournalSummaryService ───────────────

    async def get_daily_summary(self, date: Optional[str] = None, persona: str = "aveline"):
        """获取指定角色的每日总结。

        persona: aveline / ling / user（默认 aveline 保持兼容）。
        """
        return await self._summary_service.get_daily_summary(date, persona=persona)

    async def get_tomorrow_tone(self) -> Optional[str]:
        return await self._summary_service.get_tomorrow_tone()

    async def generate_daily_summary(
        self,
        date: Optional[str] = None,
        force: bool = False,
        persona: str = "aveline",
        temperature: float = 0.3,
        distinct_from: Optional[str] = None,
    ):
        return await self._summary_service.generate_daily_summary(
            date=date,
            force=force,
            persona=persona,
            temperature=temperature,
            distinct_from=distinct_from,
        )

    async def generate_study_daily_summary(
        self, date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        return await self._summary_service.generate_study_daily_summary(date=date)

    async def get_monthly_summary(self, date: Optional[str] = None):
        return await self._summary_service.get_monthly_summary(date)

    async def generate_monthly_summary(
        self, date: Optional[str] = None, force: bool = False
    ):
        return await self._summary_service.generate_monthly_summary(
            date=date, force=force
        )

    async def distill_memory(self, monthly_summary, date):
        return await self._summary_service.distill_memory(monthly_summary, date)

    # ── 计划相关：委托给 JournalPlanService ──────────────────

    async def generate_tomorrow_plan(self, force: bool = False):
        return await self._plan_service.generate_tomorrow_plan(force=force)

    async def generate_today_plan(self, force: bool = False):
        return await self._plan_service.generate_today_plan(force=force)

    async def generate_plan_for_date(self, date_str: str, force: bool = False):
        """为指定日期生成计划（供 nightly 等场景按精确日期调用）"""
        return await self._plan_service.generate_plan_for_date(date_str, force=force)

    async def get_plan(self, date: Optional[str] = None):
        return await self._plan_service.get_plan(date)

    async def get_tomorrow_plan(self):
        return await self._plan_service.get_tomorrow_plan()

    async def add_plan_item(
        self, date: Optional[str], item_dict: Dict[str, Any]
    ):
        return await self._plan_service.add_plan_item(date, item_dict)

    async def update_plan_item(
        self, date: Optional[str], item_id: str, updates: Dict[str, Any]
    ):
        return await self._plan_service.update_plan_item(date, item_id, updates)

    async def remove_plan_item(
        self, date: Optional[str], item_id: str
    ):
        return await self._plan_service.remove_plan_item(date, item_id)

    async def mark_plan_item_status(
        self, date: Optional[str], item_id: str, status: str
    ):
        return await self._plan_service.mark_plan_item_status(date, item_id, status)

    async def maybe_reassess_today_plan(self, now=None):
        return await self._plan_checkpoint_service.maybe_reassess_today_plan(now=now)

    def format_plan_for_injection(self, plan) -> str:
        return self._plan_service.format_plan_for_injection(plan)


def get_journal_service() -> JournalService:
    return JournalService()
