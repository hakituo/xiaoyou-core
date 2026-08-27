"""Active Care 用户响应处理器
负责用户响应处理、交互状态重置、睡眠推断同步
"""
import time
import hashlib
from typing import Optional

from core.utils.logger import get_module_logger
from core.utils.config_accessor import get_active_care_config
from core.utils.time_utils import from_timestamp

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")


class UserResponseHandler:
    """用户响应处理器，负责处理用户消息后的状态变更"""

    def __init__(self, service):
        """Args:
            service: ActiveCareService 实例，用于访问其属性和方法
        """
        self._service = service

    async def process_user_response(self):
        """处理用户响应：检测意图并重置交互状态

        双QQ模式下按 persona 分别处理，避免跨角色历史混淆
        """
        try:
            persona_filenames = self._get_active_persona_filenames()

            if len(persona_filenames) >= 2:
                for pf in persona_filenames:
                    try:
                        await self._process_user_response_for_persona(pf)
                    except Exception as e:
                        logger.warning(f"Active Care: process_user_response persona={pf} 失败: {e}")
            else:
                await self._process_user_response_for_persona("")
        except Exception as e:
            logger.warning(f"Failed to process user response: {e}")

    def _get_active_persona_filenames(self) -> list[str]:
        """获取当前活跃的 persona_filename 列表"""
        try:
            if self._service.executor and hasattr(self._service.executor, "_get_qq_connections"):
                connections = self._service.executor._get_qq_connections(emit_logs=False)
                persona_filenames = [
                    conn.get("persona_filename", "").strip()
                    for conn in connections
                    if conn.get("persona_filename", "").strip()
                ]
                if len(persona_filenames) >= 2:
                    return persona_filenames
        except Exception:
            pass
        return []

    async def _process_user_response_for_persona(self, persona_filename: str):
        """处理单个 persona 的用户响应"""
        try:
            history = await self._service.context.get_latest_history(
                limit=12, persona_filename=persona_filename
            )

            now = time.time()
            last_user_msg = None
            last_user_msg_ts = 0.0
            for msg in reversed(history) if history else []:
                if str(msg.get("role") or "").lower() == "user":
                    last_user_msg = msg
                    try:
                        last_user_msg_ts = float(msg.get("timestamp", 0) or 0)
                    except (TypeError, ValueError):
                        last_user_msg_ts = 0.0
                    break

            # 用 _recent_user_message_cache 补全尚未落盘的最新用户消息
            try:
                primary_cid = await self._service.context.resolve_primary_conversation_id(
                    persona_filename=persona_filename
                )
                if primary_cid:
                    cached = self._service.context.get_recent_user_message(primary_cid)
                    cached_content = str(cached.get("content") or "").strip()
                    cached_ts = float(cached.get("timestamp") or 0)
                    if cached_content and cached_ts > 0:
                        from core.services.active_care.shared.constants import normalize_content
                        already_in_history = False
                        if last_user_msg:
                            normalized_cached = normalize_content(cached_content)
                            normalized_history = normalize_content(str(last_user_msg.get("content", "")))
                            if normalized_cached == normalized_history:
                                already_in_history = True
                        # 如果缓存消息比历史中的消息更新，或历史中没有用户消息，则使用缓存
                        if not already_in_history and (cached_ts > last_user_msg_ts or not last_user_msg):
                            history_ts = last_user_msg_ts
                            last_user_msg = {
                                "role": "user",
                                "content": cached_content,
                                "timestamp": cached_ts,
                            }
                            last_user_msg_ts = cached_ts
                            logger.debug(
                                "Active Care: 使用缓存消息替代历史 (缓存ts=%.0f, 历史ts=%.0f, persona=%s)",
                                cached_ts, history_ts, persona_filename or "default"
                            )
            except Exception as cache_e:
                logger.debug(f"Active Care: 检查缓存消息失败: {cache_e}")

            if not last_user_msg:
                return

            content = str(last_user_msg.get("content", ""))
            if not content:
                return

            # 双QQ模式下按 persona 独立去重，避免不同角色互相覆盖签名导致旧消息反复刷日志。
            persona_dedup_key = persona_filename or "default"
            dedup_key = (
                f"{last_user_msg_ts}:"
                f"{hashlib.md5(content.encode('utf-8', errors='replace')).hexdigest()}"
            )
            last_signatures = getattr(self._service, "_last_processed_user_msg_signatures", None)
            if not isinstance(last_signatures, dict):
                last_signatures = {}
                self._service._last_processed_user_msg_signatures = last_signatures
            if dedup_key == last_signatures.get(persona_dedup_key, ""):
                return
            last_signatures[persona_dedup_key] = dedup_key

            from core.services.active_care.shared.constants import USER_MESSAGE_MAX_AGE_SECONDS
            max_message_age_seconds = USER_MESSAGE_MAX_AGE_SECONDS
            if last_user_msg_ts > 0 and (now - last_user_msg_ts) > max_message_age_seconds:
                logger.info(
                    "Active Care: 跳过旧消息处理 (消息时间: %.0fs前, 阈值: %ds, persona=%s)",
                    now - last_user_msg_ts, max_message_age_seconds, persona_filename or "default"
                )
                return

            result = await self._service.state_manager.process_user_message(content)

            if result.get("mode_changed"):
                logger.info(f"Active Care: 状态已更新 - {result} (persona={persona_filename or 'default'})")

            # Bandit 正奖励：用户响应了，给上次主动关怀选的动作发 +1
            # 闭环 select_action_bandit → update_policy_reward，bandit 才真正"学习"
            await self._reward_last_action(persona_filename, reward=1.0)

            await self.reset_interaction_state(
                interaction_ts=last_user_msg_ts,
                persona_filename=persona_filename,
                latest_user_content=content,
            )

        except Exception as e:
            logger.warning(f"Failed to process user response for persona={persona_filename}: {e}")

    async def _reward_last_action(self, persona_filename: str, reward: float) -> None:
        """给上次主动关怀动作发奖励（正/负）

        从 proactive_state 读取 last_sent_type，更新 bandit（兜底）与 MDP（题材感知）。
        角色自发做事消息（self_activity=True，如日程切换告别）不进入学习闭环。

        失败静默——奖励闭环不应阻塞主流程。
        """
        try:
            scope = None
            if persona_filename:
                try:
                    scope = self._service.storage.resolve_scope_from_persona_filename(persona_filename)
                except Exception:
                    scope = None
            state = await self._service.storage.get_proactive_state(scope=scope)
            if not isinstance(state, dict):
                return
            # 自发做事（角色日程切换告别）不学习，避免把"不需要回复的行为"当奖励样本
            if bool(state.get("last_sent_self_activity")):
                logger.info(
                    "Active Care: 上次发送为自发做事(self_activity)，跳过奖励闭环"
                )
                return
            last_action = str(state.get("last_sent_type") or "").strip()
            if not last_action:
                return
            # bandit 兜底（原有闭环保留）
            await self._service.storage.update_policy_reward(last_action, reward)
            # 【题材感知 MDP】按 (state, action) 归因：题材 = 上一条发的题材
            try:
                from core.services.active_care.decision.mdp import (
                    ActiveCareMDP,
                    build_reward_state_key,
                )
                from core.utils.time_utils import get_current_time

                last_topic = str(state.get("last_sent_topic") or "").strip()
                last_reply = "replied" if reward > 0 else "ignored"
                state_key = build_reward_state_key(
                    last_topic=last_topic,
                    now_dt=get_current_time(),
                    last_reply=last_reply,
                )
                await ActiveCareMDP(self._service.storage).update(
                    state_key=state_key,
                    action=last_action,
                    reward=float(reward),
                )
            except Exception as mdp_e:
                logger.debug(f"Active Care: MDP 正奖励更新失败: {mdp_e}")
        except Exception as e:
            logger.debug(f"Active Care: _reward_last_action 失败 (reward={reward}): {e}")

    async def reset_interaction_state(
        self,
        interaction_ts: float = 0.0,
        persona_filename: str = "",
        latest_user_content: str = "",
    ):
        """重置用户交互后的状态（non_responses 和下次检查时间）

        Args:
            interaction_ts: 交互时间戳
            persona_filename: 人设文件名，双QQ模式下只更新对应 persona 的调度时间

        修复说明（P0 #4）：
            此方法可能被 user_response_handler 在 proactive_checker 决策流程并发执行时调用。
            为避免实例级 _runtime_scope 被污染导致写到错误 persona 的目录，
            所有 storage 调用都显式传入 scope 参数，走并发安全的独立路径。
        """
        # 根据 persona_filename 解析 scope，双QQ模式下确保写到正确的 persona 目录
        resolved_scope: Optional[str] = None
        if persona_filename:
            try:
                resolved_scope = self._service.storage.resolve_scope_from_persona_filename(persona_filename)
            except Exception:
                resolved_scope = None

        # per-persona 重置非响应计数：只重置当前 persona，不影响其他角色
        executor = self._service.executor
        if resolved_scope and isinstance(executor.consecutive_non_responses, dict):
            old_val = executor.consecutive_non_responses.get(resolved_scope, 0)
            if old_val > 0:
                executor.consecutive_non_responses[resolved_scope] = 0
                logger.info(f"Active Care: 重置 persona={resolved_scope} non_responses (was {old_val})")
                await self._service.storage.save_proactive_state(
                    {"consecutive_non_responses": executor.consecutive_non_responses},
                    scope=resolved_scope,
                )
        elif self._service.consecutive_non_responses > 0:
            logger.info(f"Active Care: 重置 non_responses (was {self._service.consecutive_non_responses})")
            self._service.consecutive_non_responses = 0
            await self._service.storage.save_proactive_state({"consecutive_non_responses": 0}, scope=resolved_scope)

        try:
            state_data = await self._service.storage.get_proactive_state(scope=resolved_scope)
            reduced_mode_active = bool(state_data.get("reduced_mode_active"))
            reduced_mode_reason = str(state_data.get("reduced_mode_reason") or "none")
            if reduced_mode_active and reduced_mode_reason == "sleep_hint":
                # probable_sleep 已于 2026-07-30 移除。
                # sleep_hint 退出时不再同步推断作息到 daily_record：
                # 推断的睡眠时间（用户暗示时间≠实际睡觉时间）不可靠，
                # 作息数据应由 UIE 从"早安/晚安"消息抽取，或由 AI 调用 update_sleep_record 修正。
                from core.services.active_care.shared.constants import build_reduced_mode_clear_updates
                await self._service.storage.save_user_sleep_state(
                    build_reduced_mode_clear_updates(),
                    immediate=True,
                    scope=resolved_scope,
                )
                logger.info("Active Care: 用户发消息，退出 %s 模式", reduced_mode_reason)
            elif reduced_mode_active and reduced_mode_reason == "goodnight":
                should_exit_goodnight = False
                try:
                    from core.services.active_care.state.mode_state import is_direct_awake_statement
                    latest_msg = {}
                    if self._service.checker and hasattr(self._service.checker, 'context'):
                        try:
                            primary_cid = await self._service.checker.context.resolve_primary_conversation_id()
                            latest_msg = self._service.checker.context.get_recent_user_message(primary_cid) or {}
                        except Exception:
                            pass
                    msg_content = str(latest_user_content or "").strip().lower()
                    if not msg_content:
                        msg_content = str(latest_msg.get("content") or "").strip().lower()
                    if msg_content and is_direct_awake_statement(msg_content):
                        should_exit_goodnight = True
                        logger.info("Active Care: 用户发消息含早安关键词('%s')，退出 goodnight 模式", msg_content[:40])
                    now_hour = from_timestamp(time.time()).hour
                    if 10 <= now_hour < 18:
                        should_exit_goodnight = True
                        logger.info("Active Care: 当前为白天(%d点)，用户发消息退出 goodnight 模式", now_hour)
                except Exception as e:
                    logger.debug(f"Active Care: goodnight 模式退出检测失败: {e}")

                if should_exit_goodnight:
                    now_val = time.time()
                    effective_wakeup = interaction_ts if interaction_ts > 0 else now_val
                    await self._service.state_manager.sleep.exit_low_disturbance_mode(
                        exit_ts=effective_wakeup,
                        source="user_activity",
                    )
                    logger.info(
                        "Active Care: 已退出 goodnight 低打扰 "
                        "(signal_ts=%.0f，不写正式起床时间)",
                        effective_wakeup,
                    )
        except Exception as e:
            logger.debug(f"Active Care: 清除 reduced_mode 状态失败: {e}")

        now = time.time()
        effective_ts = interaction_ts if interaction_ts > 0 else now
        quiet_seconds = get_active_care_config(
            "active_care_user_quiet_seconds", default=300, settings=self._service.settings
        )
        next_allowed_ts = now + max(quiet_seconds, 300)

        if self._service.checker:
            await self._service.checker.set_next_decision_ts(
                next_allowed_ts, persona_filename=persona_filename
            )

        await self._service.storage.save_proactive_state({"last_user_interaction_ts": effective_ts}, scope=resolved_scope)

        # 双QQ模式下，同时更新 per-persona 的交互时间戳
        if persona_filename:
            persona_key = resolved_scope if resolved_scope else "default"
            per_persona_ts = {}
            try:
                state_data = await self._service.storage.get_proactive_state(scope=resolved_scope)
                per_persona_ts = dict(state_data.get("last_user_interaction_ts_by_persona") or {})
            except Exception:
                pass
            per_persona_ts[persona_key] = effective_ts
            await self._service.storage.save_proactive_state(
                {"last_user_interaction_ts_by_persona": per_persona_ts},
                scope=resolved_scope,
            )
