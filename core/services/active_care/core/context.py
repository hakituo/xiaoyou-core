"""
Active Care 上下文模块

提供 ActiveCareContext 类，负责管理主动关怀的上下文信息，包括：
- 对话历史获取
- 最近用户消息缓存
- 设备上下文
- 会话 ID 解析（委托给 conversation_resolver）
- 调度配置加载（委托给 schedule_config_loader）
"""

import json
import time
import asyncio
from typing import Any, Dict, List, Tuple

import aiofiles
from config.debug_config import is_debug_enabled
from config.integrated_config import get_settings
from core.utils.common import get_project_root
from core.utils.data_paths import get_user_latest_device_context_file
from core.utils.logger import get_logger
from core.utils.timestamp_utils import safe_timestamp
from core.services.active_care.storage.storage import ActiveCareStorage
from core.services.active_care.core import conversation_resolver
from core.services.active_care.scheduling import schedule_config_loader

logger = get_logger("ACTIVE_CARE_CONTEXT")


class ActiveCareContext:
    def __init__(self, storage: ActiveCareStorage):
        self.settings = get_settings()
        self.storage = storage
        self._recent_user_message_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 项目根路径
    # ------------------------------------------------------------------

    def _get_project_root_path(self) -> str:
        return str(get_project_root())

    # ------------------------------------------------------------------
    # 对话历史
    # ------------------------------------------------------------------

    def _get_history_for_conversation(
        self, conversation_id: str, limit: int
    ) -> List[Dict[str, Any]]:
        from memory.weighted_memory_manager import get_weighted_memory_manager

        mm = get_weighted_memory_manager(conversation_id)
        if not mm:
            logger.warning("Active Care: No memory manager for cid=%s", conversation_id)
            return []

        # 排除 peer_chat（双角色互聊剧本），避免剧本台词污染主动关怀的上下文
        history = mm.get_history(limit=limit, exclude_categories=["peer_chat"])
        if is_debug_enabled("active_care"):
            logger.info(
                "Active Care _get_history_for_conversation: cid=%s, raw_count=%d, preview=%s",
                conversation_id,
                len(history),
                [str(m.get("content", ""))[:30] for m in (history[-3:] if history else [])],
            )
        result = []
        for m in history:
            if m.get("role") not in ["user", "assistant"]:
                continue
            item = dict(m)
            item.setdefault("conversation_id", conversation_id)
            result.append(item)
        return result

    async def get_latest_history_for_conversation(
        self, conversation_id: str, limit: int = 8
    ) -> List[Dict[str, Any]]:
        try:
            cid = str(conversation_id or "").strip() or "default"
            safe_limit = max(1, int(limit or 1))
            return await asyncio.to_thread(
                self._get_history_for_conversation, cid, safe_limit
            )
        except Exception as e:
            logger.warning(f"Failed to load history for conversation: {e}")
            return []

    # ------------------------------------------------------------------
    # 最近用户消息缓存
    # ------------------------------------------------------------------

    def update_recent_user_message(
        self, conversation_id: str, content: str, timestamp: float
    ) -> None:
        cid = str(conversation_id or "").strip()
        text = str(content or "").strip()
        if not cid or not text:
            return
        try:
            ts = float(timestamp or time.time())
        except (TypeError, ValueError):
            ts = time.time()
        self._recent_user_message_cache[cid] = {"content": text, "timestamp": ts}
        self.invalidate_primary_cid_cache()
        conversation_resolver.invalidate_candidate_cids_cache()

    def get_recent_user_message(self, conversation_id: str) -> Dict[str, Any]:
        cid = str(conversation_id or "").strip()
        if not cid:
            return {}
        data = self._recent_user_message_cache.get(cid)
        if not isinstance(data, dict):
            return {}
        return dict(data)

    # ------------------------------------------------------------------
    # 综合历史获取
    # ------------------------------------------------------------------

    async def get_latest_history(self, limit: int = 5, persona_filename: str = "") -> List[Dict[str, Any]]:
        """从记忆管理器获取最新对话历史"""
        try:
            candidates = await self.get_candidate_conversation_ids(persona_filename=persona_filename)
            merged: List[Dict[str, Any]] = []
            per_conversation_limit = max(int(limit or 1), 3)

            for cid in candidates:
                history = await asyncio.to_thread(
                    self._get_history_for_conversation, cid, per_conversation_limit
                )
                if history:
                    merged.extend(history)

            if not merged:
                return []

            merged.sort(key=lambda item: safe_timestamp(item.get("timestamp")))
            return merged[-limit:]
        except Exception as e:
            logger.warning(f"Failed to load history from memory manager: {e}")
            return []

    # ------------------------------------------------------------------
    # 设备上下文
    # ------------------------------------------------------------------

    async def get_latest_device_context(self) -> Dict[str, Any]:
        """获取最新的设备上下文信息"""
        try:
            from pathlib import Path

            root = get_project_root()
            if isinstance(root, str):
                root = Path(root)
            latest_file = get_user_latest_device_context_file()
            if latest_file.exists():
                async with aiofiles.open(latest_file, mode="r", encoding="utf-8") as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            logger.warning(f"Active Care: Failed to read latest device context: {e}")
        return {}

    # ------------------------------------------------------------------
    # 会话 ID 解析（委托给 conversation_resolver）
    # ------------------------------------------------------------------

    async def get_candidate_conversation_ids(self, persona_filename: str = "") -> List[str]:
        """收集所有候选会话 ID（委托给 conversation_resolver）"""
        return await conversation_resolver.get_candidate_conversation_ids(
            storage=self, persona_filename=persona_filename
        )

    async def resolve_primary_conversation_id(self, persona_filename: str = "") -> str:
        """解析主会话 ID（委托给 conversation_resolver）"""
        return await conversation_resolver.resolve_primary_conversation_id(
            storage=self, persona_filename=persona_filename
        )

    def invalidate_primary_cid_cache(self):
        """清除主会话 ID 缓存"""
        conversation_resolver.invalidate_primary_cid_cache()

    # ------------------------------------------------------------------
    # 调度配置加载（委托给 schedule_config_loader）
    # ------------------------------------------------------------------

    async def get_schedule_configs(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """获取调度配置（委托给 schedule_config_loader）"""
        return await schedule_config_loader.get_schedule_configs(settings=self.settings)
