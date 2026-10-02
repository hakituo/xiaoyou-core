# -*- coding: utf-8 -*-
"""互聊睡眠门禁（从 PeerChatScheduler 拆出）。"""

from __future__ import annotations

from typing import List

from core.utils.logger import get_module_logger

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")


class PeerChatSleepGateMixin:
    """角色睡眠门禁、用户睡眠判定、主人 QQ 号解析。"""

    async def _is_either_character_sleeping(
        self, role_a: str = "aveline", role_b: str = "ling"
    ) -> bool:
        """判断任一角色是否在睡眠中(peer_chat 角色睡眠门禁,双角色版本)

        只拦 SleepPhase.SLEEPING（夜间睡眠），不拦 NIGHT_AWAKE
        （被叫醒后的清醒状态，可参与互聊）。

        Returns:
            True 表示任一角色在睡眠中，应跳过 peer_chat
        """
        try:
            from core.services.life_simulation import get_sleep_manager
            from core.services.life_simulation.sleep_models import SleepPhase

            sleep_manager = get_sleep_manager()
            a_phase = sleep_manager.get_state(role_a).phase
            b_phase = sleep_manager.get_state(role_b).phase
            if a_phase == SleepPhase.SLEEPING or b_phase == SleepPhase.SLEEPING:
                logger.info(
                    "PeerChatScheduler: 角色睡眠门禁命中 (%s=%s, %s=%s)",
                    role_a, a_phase.value, role_b, b_phase.value,
                )
                return True
        except Exception as e:
            logger.warning("PeerChatScheduler: 角色睡眠门禁检查异常: %s", e)
        return False

    async def _is_any_character_sleeping(self, role_ids: List[str]) -> bool:
        """判断任一角色是否在睡眠中(N 角色通用版本)

        遍历所有角色,任一在 SLEEPING 即返回 True。
        用于协商类 peer chat(需要所有角色参与)。
        """
        try:
            from core.services.life_simulation import get_sleep_manager
            from core.services.life_simulation.sleep_models import SleepPhase

            sleep_manager = get_sleep_manager()
            for rid in role_ids:
                phase = sleep_manager.get_state(rid).phase
                if phase == SleepPhase.SLEEPING:
                    logger.info(
                        "PeerChatScheduler: 角色睡眠门禁命中 (%s=%s)",
                        rid, phase.value,
                    )
                    return True
        except Exception as e:
            logger.warning("PeerChatScheduler: 角色睡眠门禁检查异常: %s", e)
        return False

    async def is_user_sleeping(self) -> bool:
        """判断用户是否在睡觉（用于 peer_chat 等场景的睡眠门禁）

        判定标准（任一满足即视为睡觉）：
        1. reduced_mode_active=true 且 reason 属于睡眠相关（goodnight/sleep_hint）
        2. sleep_session_active=true（last_goodnight_ts > last_goodmorning_ts）

        注：probable_sleep 已于 2026-07-30 移除，不再基于长时间无响应推断入睡。

        Returns:
            True 表示用户在睡觉，应跳过 peer_chat
        """
        try:
            # 仅遍历可参与互聊的角色（aveline/ling），非常驻角色
            # （Frost/Coco）无真实客户端连接，不应被纳入睡眠门禁判定。
            connections = await self._get_multi_qq_connections()
            role_ids = [
                str(c.get("role_id", "")).strip().lower()
                for c in connections
                if str(c.get("role_id", "")).strip()
            ]
            for scope in role_ids:
                try:
                    self._storage.set_runtime_scope(scope)
                    state_data = await self._storage.get_proactive_state()
                except Exception:
                    continue

                # 条件1：reduced_mode_active + 睡眠相关 reason
                reduced_active = bool(state_data.get("reduced_mode_active", False))
                reduced_reason = str(state_data.get("reduced_mode_reason", "none") or "none")
                if reduced_active and reduced_reason in ("goodnight", "sleep_hint"):
                    return True

                # 条件2：sleep_session_active（基于 goodnight/goodmorning 时间戳）
                last_goodnight_ts = float(state_data.get("last_goodnight_ts", 0.0) or 0.0)
                last_goodmorning_ts = float(state_data.get("last_goodmorning_ts", 0.0) or 0.0)
                if last_goodnight_ts > 0 and last_goodmorning_ts < last_goodnight_ts:
                    return True
        except Exception as e:
            logger.warning("PeerChatScheduler: is_user_sleeping 检查异常: %s", e)
        return False

    def _resolve_master_qq_id(self) -> str:
        """获取主人QQ号"""
        try:
            from clients.bots.qq.main import QQAdapter
            for inst in QQAdapter.get_active_instances():
                qq_id = str(inst.get("adapter").cfg.qq_id if hasattr(inst.get("adapter"), "cfg") else "").strip()
                if qq_id:
                    return qq_id
        except Exception:
            pass
        return ""
