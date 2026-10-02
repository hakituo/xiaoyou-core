# -*- coding: utf-8 -*-
"""互聊分工协商（从 PeerChatScheduler 拆出）。"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")


class PeerChatNegotiationMixin:
    """提醒分工协商、主动关怀时段分工协商、角色状态简述。"""

    async def _try_negotiation_peer_chat(self, connections: List[Dict[str, str]]) -> bool:
        """提醒分工协商检查（每日 1 次）

        条件：
        - ReminderAssignmentRegistry.needs_negotiation() == True（pending 状态）
        - 有待发提醒候选（planned_topic / user_health_reminder 类）
        - 双 QQ 模式
        - 任一角色不在 SLEEPING 状态（修复 QR-20260718-PEER-CHAT-SLEEP-GUARD）

        触发后：
        - 调用 generate_peer_script(negotiation_reminders=...)
        - 剧本分发成功后，由 PeerScriptGenerator 自动解析分工并写入 registry
        - 不占 daily_limit（系统调度需求）

        Returns:
            True 表示触发了协商 peer chat
        """
        try:
            from core.services.active_care.storage.reminder_assignment_registry import (
                get_reminder_assignment_registry,
            )
            registry = get_reminder_assignment_registry()

            # 1. 检查是否需要协商
            if not await registry.needs_negotiation():
                return False

            # 1.5 睡眠门禁：任一角色在 SLEEPING 时跳过协商，保持 pending 等起床后重试
            # （修复 QR-20260718-PEER-CHAT-SLEEP-GUARD：角色声明睡了不应被拉去商量提醒分工）
            # 说明：只拦 SLEEPING，不拦 NIGHT_AWAKE（被叫醒后的清醒状态，可参与协商）
            # 仅检查实际参与互聊的连接角色（aveline/ling），非常驻角色（Frost/Coco）
            # 无真实客户端连接，不应被纳入 peer chat 的睡眠门禁与协商范围。
            all_role_ids = [
                str(c.get("role_id", "")).strip().lower() for c in connections
            ]
            if await self._is_any_character_sleeping(all_role_ids):
                logger.info(
                    "PeerChatScheduler: 协商跳过，角色在睡眠中，保持 pending 等起床后重试"
                )
                return False

            # 注：peer_chat 是角色间互聊，不发消息给用户，不会吵醒用户，
            # 故不再设用户睡眠门禁；上方角色睡眠门禁已保证角色睡觉时不触发。
            # 2. 收集今日待发提醒
            reminders = await self._collect_today_reminders()
            if not reminders:
                logger.info("PeerChatScheduler: 无待发提醒，跳过协商")
                # 标记为 completed（无提醒可协商），避免后续重复检查
                await registry.mark_negotiation_status("completed", reason="无待发提醒")
                return False

            # 3. 写入 pending 列表到 registry（供 prompt 注入和调试）
            await registry.set_pending_reminders(reminders)

            # 4. 选第一个有互聊对象的角色作为发起者（协商 peer chat 是角色互聊，由谁发起都行）
            # 互聊对象以 ROOMMATE_RELATIONS 为准，未注册室友关系的角色（如 ye）不参与协商
            from core.services.dual_role.personas import get_peer_role_ids
            init_conn = None
            role_id = ""
            for conn in connections:
                rid = str(conn.get("role_id", "")).strip().lower()
                if rid and get_peer_role_ids(rid):
                    init_conn = conn
                    role_id = rid
                    break
            if not role_id:
                logger.info("PeerChatScheduler: 协商跳过，无互聊角色（仅室友关系角色参与）")
                return False
            peer_ids = get_peer_role_ids(role_id)
            peer_role_id = peer_ids[0] if peer_ids else ""
            if not peer_role_id:
                logger.warning("PeerChatScheduler: 协商跳过，无 peer 角色")
                return False
            peer_qq_id = self._resolve_peer_qq_id(peer_role_id)
            if not peer_qq_id:
                logger.warning("PeerChatScheduler: 协商跳过，peer_qq_id 为空")
                return False

            # 4.5 双方在线门禁：协商互聊同样需要对方 bot 真的在线
            from core.services.active_care.core.qq_connection_resolver import (
                check_peer_chat_participants_online,
            )

            allowed, reason = check_peer_chat_participants_online(role_id, peer_role_id)
            if not allowed:
                logger.info("PeerChatScheduler: 协商跳过，%s", reason)
                return False

            # 5. 用户活跃检查（协商 peer chat 也遵守用户活跃规则）
            base_cid = f"private_{master_qq_id}" if (master_qq_id := self._resolve_master_qq_id()) else "default"
            if self.is_user_recently_active(base_cid):
                logger.info("PeerChatScheduler: 协商跳过，用户最近活跃")
                return False

            logger.info(
                "PeerChatScheduler: 触发提醒分工协商 (role=%s, reminders=%d)",
                role_id, len(reminders),
            )

            # 6. 调用 generate_peer_script 进入协商模式
            sent = await self._executor.generate_peer_script(
                role_id=role_id,
                peer_qq_id=peer_qq_id,
                topic="提醒分工",
                situation="今天有几条提醒要发给主人，我们商量下谁发哪条",
                opening_idea="",
                persona_filename=init_conn.get("persona_filename", ""),
                negotiation_reminders=reminders,
            )

            if sent:
                logger.info("PeerChatScheduler: 提醒分工协商 peer chat 发送成功")
                # 协商 peer chat 也更新 last_peer_chat_ts，避免普通 peer chat 紧接着触发
                scope = role_id if role_id in all_role_ids else "aveline"
                self._storage.set_runtime_scope(scope)
                state_data = await self._storage.get_proactive_state()
                state_data["last_peer_chat_ts"] = time.time()
                date_key = get_current_time().strftime("%Y-%m-%d")
                global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
                state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
                await self._storage.save_proactive_state(state_data)
                return True
            else:
                logger.warning("PeerChatScheduler: 提醒分工协商 peer chat 发送失败")
                # 标记为 failed 避免重复触发
                try:
                    await registry.mark_negotiation_status("failed", reason="剧本发送失败")
                except Exception:
                    pass
                return False

        except Exception as e:
            logger.error(
                "PeerChatScheduler: 提醒分工协商异常: %s", e, exc_info=True
            )
            # 标记为 failed 避免每 2 分钟重复触发（needs_negotiation 只在 pending 时返回 True）
            try:
                from core.services.active_care.storage.reminder_assignment_registry import (
                    get_reminder_assignment_registry,
                )
                registry = get_reminder_assignment_registry()
                await registry.mark_negotiation_status(
                    "failed", reason=f"协商异常: {e}"
                )
                logger.info("PeerChatScheduler: 协商状态已标记为 failed，今日不再重试")
            except Exception:
                pass
            return False

    async def _collect_today_reminders(self) -> List[Dict[str, Any]]:
        """收集今日待发提醒候选列表

        从 daily_push_priority 候选中过滤出"提醒类"（planned_topic / user_health_reminder），
        返回简化的 [{reminder_id, title}, ...] 列表供协商 prompt 使用。
        """
        try:
            from core.services.active_care.decision.daily_push_priority import (
                build_daily_push_priority_candidates,
            )
            candidates = build_daily_push_priority_candidates(
                workspace_snapshot={},
                priority_focus={},
                urgent_needs=[],
            )
            # 过滤提醒类
            reminder_intents = {"planned_topic", "user_health_reminder"}
            reminders = []
            for c in candidates:
                if str(c.get("suggested_intent") or "") in reminder_intents:
                    reminders.append({
                        "reminder_id": str(c.get("id") or ""),
                        "title": str(c.get("title") or ""),
                    })
            return reminders
        except Exception as e:
            logger.warning("PeerChatScheduler: 收集待发提醒失败: %s", e)
            return []

    async def _try_proactive_assignment_negotiation(
        self, connections: List[Dict[str, str]]
    ) -> bool:
        """主动关怀时段分工协商检查（每日 1 次）

        条件：
        - ProactiveAssignmentRegistry.needs_negotiation() == True（pending 状态）
        - 双 QQ 模式
        - 用户不在活跃窗口内

        触发后：
        - 调用 generate_peer_script(proactive_assignment_mode=True)
        - 剧本分发成功后，由 PeerScriptGenerator 自动解析分工并写入 registry
        - 不占 daily_limit（系统调度需求）

        Returns:
            True 表示触发了协商 peer chat
        """
        try:
            from core.services.active_care.storage.proactive_assignment_registry import (
                get_proactive_assignment_registry,
            )
            registry = get_proactive_assignment_registry()

            # 1. 检查是否需要协商
            if not await registry.needs_negotiation():
                return False

            # 1.5 角色睡眠门禁：任一角色在 SLEEPING 时跳过，保持 pending 等起床后重试
            # （与提醒分工协商一致：角色睡觉时不应被拉去商量主动关怀分工）
            # 仅检查实际参与互聊的连接角色（aveline/ling），非常驻角色（Frost/Coco）
            # 无真实客户端连接，不应被纳入 peer chat 的睡眠门禁与协商范围。
            all_role_ids = [
                str(c.get("role_id", "")).strip().lower() for c in connections
            ]
            if await self._is_any_character_sleeping(all_role_ids):
                logger.info(
                    "PeerChatScheduler: 主动关怀分工协商跳过，角色在睡眠中，保持 pending 等起床后重试"
                )
                return False

            # 2. 用户活跃检查（协商 peer chat 也遵守用户活跃规则）
            base_cid = f"private_{master_qq_id}" if (master_qq_id := self._resolve_master_qq_id()) else "default"
            if self.is_user_recently_active(base_cid):
                logger.info("PeerChatScheduler: 主动关怀分工协商跳过，用户最近活跃")
                return False

            # 3. 收集所有角色的今日状态简述（供 prompt 注入,N 角色动态）
            role_states = {
                rid: self._get_persona_state_brief(rid)
                for rid in all_role_ids
            }
            # 向后兼容:aveline_state/ling_state 取前两个角色
            aveline_state = role_states.get("aveline", "")
            ling_state = role_states.get("ling", "")

            # 4. 选第一个有互聊对象的角色作为发起者
            # 互聊对象以 ROOMMATE_RELATIONS 为准，未注册室友关系的角色（如 ye）不参与协商
            from core.services.dual_role.personas import get_peer_role_ids
            init_conn = None
            role_id = ""
            for conn in connections:
                rid = str(conn.get("role_id", "")).strip().lower()
                if rid and get_peer_role_ids(rid):
                    init_conn = conn
                    role_id = rid
                    break
            if not role_id:
                logger.info("PeerChatScheduler: 主动关怀分工协商跳过，无互聊角色（仅室友关系角色参与）")
                return False
            peer_ids = get_peer_role_ids(role_id)
            peer_role_id = peer_ids[0] if peer_ids else ""
            if not peer_role_id:
                logger.warning("PeerChatScheduler: 主动关怀分工协商跳过，无 peer 角色")
                return False
            peer_qq_id = self._resolve_peer_qq_id(peer_role_id)
            if not peer_qq_id:
                logger.warning("PeerChatScheduler: 主动关怀分工协商跳过，peer_qq_id 为空")
                return False

            # 双方在线门禁：协商互聊同样需要对方 bot 真的在线
            from core.services.active_care.core.qq_connection_resolver import (
                check_peer_chat_participants_online,
            )

            allowed, reason = check_peer_chat_participants_online(role_id, peer_role_id)
            if not allowed:
                logger.info("PeerChatScheduler: 主动关怀分工协商跳过，%s", reason)
                return False

            logger.info(
                "PeerChatScheduler: 触发主动关怀时段分工协商 (role=%s)",
                role_id,
            )

            # 5. 调用 generate_peer_script 进入主动关怀分工协商模式
            sent = await self._executor.generate_peer_script(
                role_id=role_id,
                peer_qq_id=peer_qq_id,
                topic="主动关怀分工",
                situation="今天我们商量下谁在上午、下午、晚上去给主人发主动消息",
                opening_idea="",
                persona_filename=init_conn.get("persona_filename", ""),
                proactive_assignment_mode=True,
                aveline_state=aveline_state,
                ling_state=ling_state,
                role_states=role_states,
            )

            if sent:
                logger.info("PeerChatScheduler: 主动关怀时段分工协商 peer chat 发送成功")
                # 协商 peer chat 也更新 last_peer_chat_ts，避免普通 peer chat 紧接着触发
                scope = role_id if role_id in all_role_ids else "aveline"
                self._storage.set_runtime_scope(scope)
                state_data = await self._storage.get_proactive_state()
                state_data["last_peer_chat_ts"] = time.time()
                date_key = get_current_time().strftime("%Y-%m-%d")
                global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
                state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
                await self._storage.save_proactive_state(state_data)
                return True
            else:
                logger.warning("PeerChatScheduler: 主动关怀时段分工协商 peer chat 发送失败")
                # 标记为 failed 避免重复触发
                try:
                    await registry.mark_negotiation_status("failed", reason="剧本发送失败")
                except Exception:
                    pass
                return False

        except Exception as e:
            logger.error(
                "PeerChatScheduler: 主动关怀时段分工协商异常: %s", e, exc_info=True
            )
            # 标记为 failed 避免每 2 分钟重复触发
            try:
                from core.services.active_care.storage.proactive_assignment_registry import (
                    get_proactive_assignment_registry,
                )
                registry = get_proactive_assignment_registry()
                await registry.mark_negotiation_status(
                    "failed", reason=f"协商异常: {e}"
                )
                logger.info("PeerChatScheduler: 主动关怀分工协商状态已标记为 failed，今日不再重试")
            except Exception:
                pass
            return False

    def _get_persona_state_brief(self, role_id: str) -> str:
        """获取角色今日状态简述（供协商 prompt 注入）

        从生命模拟系统读取生理状态，生成简短描述。
        """
        try:
            from core.services.life_simulation import get_life_simulation_service
            life_sim = get_life_simulation_service()
            if not life_sim:
                return ""
            bio_state = life_sim.get_bio_state(role_id)
            if not isinstance(bio_state, dict):
                return ""
            parts = []
            energy = float(bio_state.get("energy", 0))
            if energy > 0:
                if energy > 70:
                    parts.append("精力充沛")
                elif energy > 40:
                    parts.append("精力尚可")
                else:
                    parts.append("有点累")
            mood = str(bio_state.get("mood") or "").strip()
            if mood:
                parts.append(f"心情{mood}")
            is_sick = bool(bio_state.get("is_sick", False))
            if is_sick:
                parts.append("身体不适")
            return "，".join(parts) if parts else ""
        except Exception:
            return ""
