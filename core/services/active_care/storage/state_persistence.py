"""
状态持久化模块
从 executor 中提取，负责主动关怀消息发送后的状态记录与持久化
"""
import time
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.services.active_care.shared.constants import StateKeys
from core.services.active_care.postprocess.deduplicator import Deduplicator

logger = get_logger("ACTIVE_CARE_STATE_PERSIST")


class StatePersistence:
    def __init__(self, storage):
        self.storage = storage

    def build_today_sent_event(
        self,
        *,
        content: str,
        message_type: str,
        thought: Optional[str],
        sys_prompt_type: str,
        now_ts: float,
        conversation_id: str,
    ) -> Dict[str, Any]:
        return {
            "ts": now_ts,
            "type": str(message_type or "text"),
            "content": str(content or "")[:300],
            "thought": str(thought or "")[:200] if thought else None,
            "sys_prompt_type": str(sys_prompt_type or ""),
            "conversation_id": str(conversation_id or ""),
        }

    def build_today_sent_events_updates(
        self,
        *,
        proactive_state: Dict[str, Any],
        new_event: Dict[str, Any],
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        existing = proactive_state.get(StateKeys.TODAY_SENT_EVENTS) or []
        if not isinstance(existing, list):
            existing = []
        today_date = proactive_state.get(StateKeys.TODAY_SENT_EVENTS_DATE)
        try:
            current_date = time.strftime("%Y-%m-%d", time.localtime(new_event.get("ts", time.time())))
        except Exception:
            current_date = ""
        if str(today_date or "").strip() != current_date:
            existing = []
        existing.append(new_event)
        return existing[-max(1, int(limit or 1)):]

    def build_persist_conversation_ids(
        self,
        *,
        proactive_state: Dict[str, Any],
        conversation_id: str,
        limit: int = 20,
    ) -> List[str]:
        existing = proactive_state.get("persist_conversation_ids") or []
        if not isinstance(existing, list):
            existing = []
        cid = str(conversation_id or "").strip()
        if cid and cid not in existing:
            existing.append(cid)
        return existing[-max(1, int(limit or 1)):]

    async def persist_proactive_message(
        self,
        *,
        user_id: str,
        final_text: str,
        full_raw_text: str,
        message_type: str,
        llm_thought: Optional[str],
        sys_prompt_type: str,
        now_ts: float,
        conversation_id: str,
        proactive_state: Dict[str, Any],
        planned_topic: str = "",
        self_activity: bool = False,
    ) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        updates[StateKeys.LAST_SENT_TS] = now_ts
        updates[StateKeys.LAST_SENT_TYPE] = str(sys_prompt_type or "")
        updates[StateKeys.LAST_SENT_CONTENT] = str(final_text or "")[:300]

        # 题材感知 MDP：记录本次发送消息的题材标签，供下次决策作为状态来源
        # 自发做事（角色日程切换告别）消息不记录题材，避免污染学习闭环
        if not self_activity and sys_prompt_type:
            from core.services.active_care.decision.topic_classifier import (
                classify_topic,
            )

            try:
                topic_label = classify_topic(
                    intent=sys_prompt_type,
                    planned_topic=planned_topic,
                    sent_content=final_text,
                )
                updates[StateKeys.LAST_SENT_TOPIC] = topic_label
                updates[StateKeys.LAST_SENT_TOPIC_TYPE] = str(
                    topic_label.split(":", 1)[-1] or "general"
                )
            except Exception as topic_e:
                logger.debug("Active Care: 题材分类失败: %s", topic_e)
        updates[StateKeys.LAST_SENT_SELF_ACTIVITY] = bool(self_activity)
        updates[StateKeys.LAST_THOUGHT] = str(llm_thought or "")[:200] if llm_thought else None
        updates[StateKeys.LAST_ATTEMPT_TS] = now_ts
        updates[StateKeys.LAST_ATTEMPT_TYPE] = str(sys_prompt_type or "")
        updates[StateKeys.RECENT_SENT_CONTENTS] = Deduplicator.build_recent_sent_contents(
            proactive_state=proactive_state, final_text=final_text,
        )
        new_event = self.build_today_sent_event(
            content=final_text,
            message_type=message_type,
            thought=llm_thought,
            sys_prompt_type=sys_prompt_type,
            now_ts=now_ts,
            conversation_id=conversation_id,
        )
        updates[StateKeys.TODAY_SENT_EVENTS] = self.build_today_sent_events_updates(
            proactive_state=proactive_state, new_event=new_event,
        )
        updates["persist_conversation_ids"] = self.build_persist_conversation_ids(
            proactive_state=proactive_state, conversation_id=conversation_id,
        )
        try:
            await self.storage.save_proactive_state(
                updates=updates,
                immediate=True,
            )
        except Exception as e:
            logger.warning(f"Active Care: 状态持久化失败: {e}")
        return updates
