"""每日总结上下文加载器

从 core/services/journal/summary_service.py 拆分而来，负责加载和聚合
每日总结生成所需的各类上下文数据（聊天历史、主动关怀事件、双角色互聊、
用户状态、学习统计、生活画像等）。

设计原则：
- 依赖注入：构造时接收 JournalStorage 实例
- 纯加载逻辑，不做格式化（格式化由 journal_helpers 中的函数负责）
"""
import asyncio
import json
import aiofiles
from datetime import datetime
from typing import Any, Dict, List

from core.utils.logger import get_logger
from core.services.journal.models import JournalEntry
from core.services.journal.storage import JournalStorage

logger = get_logger("SummaryContextLoader")


class SummaryContextLoader:
    """每日总结上下文加载器

    从磁盘各类数据源加载当日上下文，供 JournalSummaryService.generate_daily_summary 使用。
    """

    def __init__(self, storage: JournalStorage):
        self.storage = storage

    async def load_chat_history_for_date(
        self, dt: datetime, limit: int = 200, persona: str = "aveline"
    ) -> List[Dict[str, Any]]:
        """从磁盘 ChatHistoryStore 读取当天指定角色与主人的聊天记录

        persona="aveline" → 读 aveline_data/chat_history/
        persona="ling"   → 读 ling_data/chat_history/
        """
        try:
            from core.utils.data_paths import get_role_chat_history_dir

            day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            day_end = day_start + 86400

            result: List[Dict[str, Any]] = []
            seen_event_ids: set = set()

            # 只读指定角色的 chat_history 目录
            base_dir = get_role_chat_history_dir(persona).resolve()
            if not base_dir.exists():
                return []
            # 找到 YYYY/MM/DD 日期子目录
            day_path = base_dir / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d")
            if not day_path.exists():
                return []
            for jsonl_file in day_path.rglob("*.jsonl"):
                try:
                    async with aiofiles.open(jsonl_file, "r", encoding="utf-8") as f:
                        content = await f.read()
                    for line in content.splitlines():
                        text = str(line or "").strip()
                        if not text:
                            continue
                        try:
                            item = json.loads(text)
                        except Exception:
                            continue
                        if not isinstance(item, dict):
                            continue
                        storage_scope = str(item.get("storage_scope") or "").strip().lower()
                        if storage_scope and storage_scope != persona:
                            continue
                        metadata = item.get("metadata")
                        if not isinstance(metadata, dict):
                            metadata = {}
                        event_type = str(item.get("event_type") or "").strip().lower()
                        if event_type == "proactive_message" or metadata.get("is_proactive") is True:
                            # 主动关怀有独立、按 persona 隔离的数据源，避免在聊天历史里重复注入。
                            continue
                        role = str(item.get("role") or "").strip().lower()
                        if role not in {"user", "assistant"}:
                            continue
                        ts = float(item.get("timestamp") or 0.0)
                        if ts > 1e12:
                            ts = ts / 1000.0
                        if ts < day_start or ts >= day_end:
                            continue
                        event_id = str(item.get("event_id") or "")
                        if event_id and event_id in seen_event_ids:
                            continue
                        if event_id:
                            seen_event_ids.add(event_id)
                        content_text = str(item.get("content") or "").strip()
                        if not content_text or content_text == "[SYSTEM_GREETING]":
                            continue
                        result.append(
                            {
                                "timestamp": ts,
                                "role": role,
                                "content": content_text,
                            }
                        )
                except Exception:
                    continue

            result.sort(key=lambda x: float(x.get("timestamp") or 0.0))
            return result[-limit:]
        except Exception as e:
            logger.warning(f"Failed to fetch chat history for summary: {e}")
            return []

    async def load_user_status_summary(self) -> str:
        """加载用户状态摘要"""
        try:
            from core.services.workspace.status_manager import get_user_status_manager
            return await asyncio.to_thread(
                get_user_status_manager().get_status_summary
            )
        except Exception as e:
            logger.warning(f"Failed to fetch user status for summary: {e}")
            return "当前无特殊状态。"

    async def load_active_care_events(
        self, dt: datetime, limit: int = 200, persona: str = "aveline"
    ) -> List[Dict[str, Any]]:
        """加载指定角色的主动关怀行为事件"""
        try:
            rows = []
            # 只加载指定 persona 对应 scope 的事件
            scope = persona if persona in ("aveline", "ling") else "aveline"
            event_file = (
                self.storage.get_daily_dir(dt, scope=scope)
                / "events"
                / "active_care_actions.jsonl"
            )
            if event_file.exists():
                async with aiofiles.open(event_file, "r", encoding="utf-8") as f:
                    content = await f.read()
                for line in content.splitlines():
                    text = str(line or "").strip()
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(payload, dict):
                        rows.append(payload)
            rows.sort(key=lambda x: float(x.get("timestamp") or 0.0))
            return rows[-limit:]
        except Exception as e:
            logger.warning(f"Failed to load active care events for summary: {e}")
            return []

    async def load_peer_chat_history(
        self, dt: datetime, limit: int = 120
    ) -> List[Dict[str, Any]]:
        """从 dual_role目录加载双角色互聊记录（Ling ↔ 七濑澪/Aveline）"""
        try:
            from core.utils.data_paths import get_dual_role_data_dir

            dual_dir = get_dual_role_data_dir()
            if not dual_dir:
                return []
            date_str = dt.strftime("%Y-%m-%d")
            rows = []
            for persona_slug in ("qq_aveline", "qq_ling"):
                chat_dir = dual_dir / persona_slug / date_str
                if not chat_dir.exists():
                    continue
                for jsonl_file in chat_dir.glob("*.jsonl"):
                    try:
                        async with aiofiles.open(jsonl_file, "r", encoding="utf-8") as f:
                            content = await f.read()
                        for line in content.splitlines():
                            text = str(line or "").strip()
                            if not text:
                                continue
                            try:
                                payload = json.loads(text)
                            except Exception:
                                continue
                            if isinstance(payload, dict):
                                rows.append(payload)
                    except Exception:
                        continue
            rows.sort(key=lambda x: float(x.get("timestamp") or 0.0))
            return rows[-limit:]
        except Exception as e:
            logger.warning(f"Failed to load peer chat history for summary: {e}")
            return []

    async def load_character_daily_activities(self, dt: datetime) -> Dict[str, Any]:
        """加载角色日常活动计划（Aveline 和 Ling 今天的活动安排）
        
        Returns:
            Dict 包含两个角色的活动摘要：
            {
                "aveline": {"activities": [...], "peer_chat_count": N},
                "ling": {"activities": [...], "peer_chat_count": N}
            }
        """
        try:
            from core.services.character_daily.state import DailyStateStore
            from core.services.character_daily.activity_model import (
                ACTIVITY_VERBS,
                normalize_datetime_for_reference,
            )
            
            store = DailyStateStore()
            state = store.load()
            
            # 检查状态是否是今天的
            date_str = dt.strftime("%Y-%m-%d")
            if state.date != date_str:
                logger.debug(f"CharacterDaily: 状态日期 {state.date} 与目标 {date_str} 不匹配")
                return {}
            
            result = {}
            for role_id in ["aveline", "ling"]:
                plan = state.get_plan(role_id)
                if not plan:
                    continue
                
                # 提取已完成和进行中的活动
                activities = []
                now = dt.replace(hour=dt.hour, minute=dt.minute)
                
                for slot in plan.slots:
                    comparable_now = normalize_datetime_for_reference(
                        slot.planned_start,
                        now,
                    )
                    # 跳过睡觉
                    if slot.activity.value == "sleeping":
                        continue
                    
                    # 只记录已经结束或正在进行的活动
                    if slot.planned_end <= comparable_now:
                        # 已完成的活动
                        verb = ACTIVITY_VERBS.get(slot.activity, slot.activity.value)
                        activities.append({
                            "activity": slot.activity.value,
                            "verb": verb,
                            "time": slot.planned_start.strftime("%H:%M"),
                            "status": "completed"
                        })
                    elif slot.planned_start <= comparable_now < slot.planned_end:
                        # 正在进行的活动
                        verb = ACTIVITY_VERBS.get(slot.activity, slot.activity.value)
                        activities.append({
                            "activity": slot.activity.value,
                            "verb": verb,
                            "time": slot.planned_start.strftime("%H:%M"),
                            "status": "ongoing"
                        })
                
                result[role_id] = {
                    "activities": activities,
                    "peer_chat_count": plan.today_peer_chat_count,
                }
            
            return result
        except Exception as e:
            logger.warning(f"Failed to load character daily activities: {e}")
            return {}

    async def gather_daily_context(
        self, dt: datetime, entries: List[JournalEntry], persona: str = "aveline"
    ) -> Dict[str, Any]:
        """聚合当日所有上下文数据（学习统计、生活画像、聊天历史、主动关怀、双角色互聊、角色日常）"""
        study_stats = {}
        try:
            from core.services.study.service import get_study_service
            study_service = get_study_service()
            study_stats = study_service.get_daily_study_summary_data(
                dt.strftime("%Y-%m-%d")
            )
        except Exception as e:
            logger.warning(f"Failed to fetch study stats: {e}")

        daily_record = {}
        try:
            from core.services.daily.manager import get_daily_manager
            daily_record = get_daily_manager().get_record(dt.strftime("%Y-%m-%d"))
        except Exception as e:
            logger.warning(f"Failed to fetch daily record: {e}")

        user_status_summary = await self.load_user_status_summary()
        chat_history = await self.load_chat_history_for_date(dt, limit=240, persona=persona)
        active_care_events = await self.load_active_care_events(dt, limit=240, persona=persona)
        peer_chat_history = await self.load_peer_chat_history(dt, limit=120)
        character_daily = await self.load_character_daily_activities(dt)

        # auto_heal 不再注入日记，自愈日志由 auto_heal 模块自行管理

        return {
            "study_stats": study_stats,
            "daily_record": daily_record,
            "user_status_summary": user_status_summary,
            "chat_history": chat_history,
            "active_care_events": active_care_events,
            "peer_chat_history": peer_chat_history,
            "character_daily": character_daily,
        }
