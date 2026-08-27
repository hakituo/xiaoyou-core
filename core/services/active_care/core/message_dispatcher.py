"""Active Care 消息分发器

负责消息分发、状态保存、日记写入、非响应计数管理。
从 executor.py 拆分而来，方法签名与原 _xxx 方法保持一致。

依赖注入策略：整体传入 executor 实例（参考 SleepSessionManager 模式）。
"""
import asyncio
import json
from typing import Any, Dict, Optional

from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger
from core.utils.data_paths import get_role_daily_dir
from core.utils.time_utils import get_current_time
from core.services.active_care.shared.constants import StateKeys

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class MessageDispatcher:
    """消息分发与状态持久化

    通过整体注入 executor 实例访问 storage/state_persistence/
    hardware_intent_resolver/consecutive_non_responses 等依赖。
    """

    def __init__(self, executor):
        """构造器

        Args:
            executor: ActiveCareExecutor 实例（门面），用于访问：
                - executor.storage: ActiveCareStorage
                - executor.state_persistence: StatePersistence
                - executor.hardware_intent_resolver: ActiveCareHardwareIntentResolver
                - executor.consecutive_non_responses: Dict[str, int]
        """
        self._executor = executor

    # ==================== per-persona 非响应计数 ====================

    def get_non_response_count(self, persona_key: str = "") -> int:
        """获取指定 persona 的非响应计数

        Args:
            persona_key: persona scope 标识。空字符串表示单QQ兼容模式。
        """
        executor = self._executor
        if persona_key:
            return int(executor.consecutive_non_responses.get(persona_key, 0) or 0)
        # 单QQ模式：取所有 persona 中的最大值（保守策略）
        return max(executor.consecutive_non_responses.values()) if executor.consecutive_non_responses else 0

    def resolve_persona_key_from_filename(self, persona_filename: str) -> str:
        """根据 persona_filename 解析 persona scope key"""
        executor = self._executor
        fn = str(persona_filename or "").strip()
        if not fn:
            return ""
        try:
            return executor.storage.resolve_scope_from_persona_filename(fn)
        except Exception:
            return ""

    async def update_non_response_count(self, target_conversation_id: str, persona_filename: str = ""):
        """更新非响应计数（per-persona 独立追踪）

        Args:
            target_conversation_id: 目标会话ID
            persona_filename: 人设文件名，用于确定 persona scope
        """
        executor = self._executor
        persona_key = self.resolve_persona_key_from_filename(persona_filename)
        executor.consecutive_non_responses[persona_key] = (
            executor.consecutive_non_responses.get(persona_key, 0) + 1
        )
        current_count = executor.consecutive_non_responses[persona_key]

        try:
            save_data: Dict[str, Any] = {
                StateKeys.CONSECUTIVE_NON_RESPONSES: executor.consecutive_non_responses,
            }
            # per-persona 保存到对应 scope 的 state 文件
            scope = persona_key if persona_key else None
            await executor.storage.save_proactive_state(save_data, scope=scope)
        except Exception as e:
            logger.warning(f"Active Care: 保存非响应计数失败: {e}")

        if current_count >= 2:
            try:
                from core.emotion import get_emotion_manager
                get_emotion_manager().apply_influence(
                    target_conversation_id,
                    {"sad": 0.6, "angry": 0.4},
                    "active_care_ignored",
                    metadata={"consecutive": current_count, "persona": persona_key},
                )
                logger.info(
                    f"Active Care: Mood degraded due to {current_count} non-responses (persona={persona_key or 'default'})"
                )
            except Exception as emo_e:
                logger.warning(f"Active Care: Failed to degrade mood: {emo_e}")

        # 负奖励：首次无响应时给上次动作发 -1，避免连续无响应过度惩罚
        # 闭环：用户响应 → +1，用户首次忽略 → -1，后续忽略不再惩罚
        # 【题材感知 MDP】：
        # - 角色自发做事消息（self_activity=True）不进入学习闭环，不惩罚
        # - 非自发消息同时更新 bandit（兜底）与 MDP（按 (state, action) 学习）
        if current_count == 1:
            try:
                scope = persona_key if persona_key else None
                state = await executor.storage.get_proactive_state(scope=scope)
                # 自发做事（角色日程切换告别）不惩罚，避免把"不需要回复的行为"当失败
                if bool(state.get(StateKeys.LAST_SENT_SELF_ACTIVITY)):
                    logger.info(
                        "Active Care: 上次发送为自发做事(self_activity)，跳过负奖励"
                    )
                else:
                    last_action = str(state.get("last_sent_type") or "").strip()
                    if last_action:
                        await executor.storage.update_policy_reward(last_action, -1.0)
                    # MDP 负奖励：按 (state, action) 归因
                    try:
                        from core.services.active_care.decision.mdp import (
                            ActiveCareMDP,
                            build_reward_state_key,
                        )
                        from core.utils.time_utils import get_current_time
                        last_topic = str(state.get(StateKeys.LAST_SENT_TOPIC) or "").strip()
                        state_key = build_reward_state_key(
                            last_topic=last_topic,
                            now_dt=get_current_time(),
                            last_reply="ignored",
                        )
                        await ActiveCareMDP(executor.storage).update(
                            state_key=state_key,
                            action=last_action,
                            reward=-1.0,
                        )
                    except Exception as mdp_e:
                        logger.debug(f"Active Care: MDP 负奖励更新失败: {mdp_e}")
            except Exception as reward_e:
                logger.debug(f"Active Care: 负奖励更新失败: {reward_e}")

    # ==================== 消息分发 ====================

    async def dispatch_message(
        self,
        aveline_service,
        post_processed: Dict[str, Any],
        sys_prompt_type: str,
        device_context: Optional[Dict[str, Any]],
        target_conversation_id: str,
        original_conversation_id: str,
        effective_client_type: str,
        requested_client_type: str,
        thought: Optional[str],
        context: Dict[str, Any],
        now: float,
        now_dt,
        planned_topic: str = "",
        self_activity: bool = False,
    ) -> bool:
        """分发消息

        Args:
            planned_topic: 决策的计划话题（题材感知 MDP 记录用）
            self_activity: 是否为角色自发行为（True 时不记录题材、不进学习闭环）
        """
        executor = self._executor
        final_text = str(post_processed.get("content") or "").strip()
        full_raw_text = str(post_processed.get("tts_text") or final_text).strip()
        message_type = str(post_processed.get("message_type") or "text").strip().lower() or "text"
        llm_thought = post_processed.get("llm_thought")
        broadcast_thought = thought or llm_thought
        final_thought = thought
        if llm_thought:
            if final_thought:
                final_thought = f"{final_thought}\n[LLM Thought]: {llm_thought}"
            else:
                final_thought = llm_thought

        msg_logger.info(
            "Active Care: 准备分发消息，target=%s, content_len=%d, type=%s, client=%s",
            target_conversation_id, len(final_text), message_type, effective_client_type,
        )

        hw_intent = executor.hardware_intent_resolver.determine(sys_prompt_type, device_context or {})
        outbound_result = await aveline_service.dispatch_proactive_message(
            target_conversation_id=target_conversation_id,
            content=final_text,
            thought=str(broadcast_thought or final_thought or "").strip(),
            message_type=message_type,
            tts_text=full_raw_text,
            client_type=effective_client_type,
            requested_client_type=requested_client_type,
            hardware_payload=hw_intent.to_dict(),
            original_primary_conversation_id=original_conversation_id,
        )
        delivered = bool(outbound_result.get("delivered"))

        if delivered:
            msg_logger.info("Active Care: 消息分发完成（已实时送达或存入离线队列）")
        else:
            msg_logger.warning("Active Care: 消息分发失败（可能无活跃WebSocket连接），delivered=False")

        if delivered:
            await self.save_sent_state(
                context["proactive_state"], final_text, message_type,
                llm_thought, sys_prompt_type, now, now_dt, target_conversation_id,
                planned_topic=planned_topic, self_activity=self_activity,
            )
        else:
            await executor.storage.save_proactive_state(
                {
                    StateKeys.LAST_ATTEMPT_TS: now,
                    StateKeys.LAST_ATTEMPT_TYPE: sys_prompt_type,
                    StateKeys.LAST_THOUGHT: str(final_thought or "").strip(),
                }
            )

        return delivered

    async def save_sent_state(
        self,
        proactive_state: Dict,
        final_text: str,
        message_type: str,
        llm_thought: Optional[str],
        sys_prompt_type: str,
        now: float,
        now_dt,
        target_conversation_id: str,
        planned_topic: str = "",
        self_activity: bool = False,
    ):
        """保存发送状态（委托给 StatePersistence）"""
        executor = self._executor
        await executor.state_persistence.persist_proactive_message(
            user_id=target_conversation_id,
            final_text=str(final_text or "").strip(),
            full_raw_text=str(final_text or "").strip(),
            message_type=message_type,
            llm_thought=llm_thought,
            sys_prompt_type=sys_prompt_type,
            now_ts=now,
            conversation_id=target_conversation_id,
            proactive_state=proactive_state,
            planned_topic=planned_topic,
            self_activity=self_activity,
        )
        date_key = now_dt.strftime("%Y-%m-%d")
        await executor.storage.increment_proactive_count(date_key)

    # ==================== 主动消息持久化（后备方案） ====================

    async def persist_proactive_message_fallback(
        self, conversation_id: str, content: str, thought: str = ""
    ) -> None:
        """持久化主动消息（后备方案），委托给 AvelineService.append_proactive_message"""
        cid = str(conversation_id or "").strip()
        text = str(content or "").strip()
        if not cid or not text:
            return
        try:
            from core.core_engine.service_singletons import get_aveline_service
            aveline_service = get_aveline_service()
            if aveline_service:
                await aveline_service.append_proactive_message(
                    conversation_id=cid, content=text, thought=thought
                )
                return
        except Exception:
            logger.warning("持久化主动消息失败(aveline_service路径)", exc_info=True)
            pass
        from memory.weighted_memory_manager import get_weighted_memory_manager
        mm = get_weighted_memory_manager(cid)
        if not mm:
            return
        thought_text = str(thought or "").strip()
        await asyncio.to_thread(
            mm.add_memory,
            content=text,
            role="assistant",
            source="active_care",
            category="chat",
            scopes=["local", "cloud"],
            metadata={
                "conversation_id": cid,
                "is_proactive": True,
                "type": "proactive",
                "original_source": "active_care",
                "thought": thought_text,
            },
        )
        if thought_text:
            await asyncio.to_thread(
                mm.add_memory,
                content=thought_text,
                role="system",
                is_important=False,
                source="active_care",
                category="thinking",
                scopes=["local"],
                metadata={
                    "conversation_id": cid,
                    "hidden": True,
                    "is_proactive_thought": True,
                    "original_source": "active_care",
                },
            )

    # ==================== 日记写入 ====================

    async def write_diary_entry(
        self, event_type: str, content: str, thought: Optional[str] = None
    ):
        """写入日记条目"""
        executor = self._executor
        try:
            display_content = content
            mood = "happy"
            if "[EMO:" in content:
                try:
                    start_idx = content.find("[EMO:")
                    end_idx = content.find("]", start_idx)
                    if end_idx != -1:
                        emo_str = content[start_idx + 5 : end_idx]
                        emo_json = json.loads(emo_str)
                        mood = emo_json.get("mood", "happy")
                        display_content = (
                            content[:start_idx] + content[end_idx + 1 :]
                        ).strip()
                except Exception:
                    if is_debug_enabled("active_care_executor"):
                        logger.info("解析EMO情绪标记失败", exc_info=True)
                    pass
            now_dt = get_current_time()
            role_daily_dir = get_role_daily_dir(executor.storage.get_runtime_scope())
            daily_dir = (
                role_daily_dir
                / now_dt.strftime("%Y")
                / now_dt.strftime("%m")
                / now_dt.strftime("%d")
                / "events"
            )
            event_file = daily_dir / "active_care_actions.jsonl"
            payload = {
                "timestamp": now_dt.timestamp(),
                "time": now_dt.strftime("%H:%M:%S"),
                "event_type": event_type,
                "content": display_content,
                "mood": mood,
                "thought": thought,
                "source": "active_care",
            }

            from core.utils.debug_markers import is_debug_context_message
            if is_debug_context_message(display_content):
                logger.info(f"Active Care: Filtered out debug/error message from active_care_actions: {display_content[:100]}")
                return

            def _append_jsonl() -> None:
                daily_dir.mkdir(parents=True, exist_ok=True)
                with open(event_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")

            await asyncio.to_thread(_append_jsonl)
        except Exception as e:
            logger.warning(f"Active Care: Failed to write action event: {e}")
