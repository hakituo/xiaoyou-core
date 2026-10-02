# -*- coding: utf-8 -*-
"""单角色互聊决策与连接解析（从 PeerChatScheduler 拆出）。"""

from __future__ import annotations

import os
import time
from typing import Dict, List

from config.debug_config import is_debug_enabled
from core.utils.config_accessor import get_dual_role_config
from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")


class PeerChatRoleCycleMixin:
    """单角色互聊触发判定、多 QQ 连接缓存、对方 QQ 号解析。"""

    async def _check_and_trigger_for_role(
        self,
        role_id: str,
        conn: Dict[str, str],
        all_connections: List[Dict[str, str]],
    ) -> bool:
        """为指定角色检查并触发互聊(N 角色系统:遍历所有 peer 选第一个可用的)"""
        now = time.time()
        from core.services.dual_role.personas import get_peer_role_ids, get_persona

        # N 角色系统:获取所有 peer,选第一个可用的(非睡眠、有 qq_id)
        peer_role_ids = get_peer_role_ids(role_id)
        if not peer_role_ids:
            logger.info("PeerChatScheduler: %s 跳过，无 peer 角色", role_id)
            return False

        # 频率限制（全局）- 提前检查避免不必要的睡眠/peer 查询
        daily_limit = int(get_dual_role_config(
            "peer_chat_daily_limit", default=6, settings=self._settings
        ))
        min_gap = float(get_dual_role_config(
            "peer_chat_min_gap_seconds", default=5400.0, settings=self._settings
        ))

        # 使用 role_id 来设置 scope(N 角色系统:所有角色用自己的 scope)
        self._storage.set_runtime_scope(role_id)
        state_data = await self._storage.get_proactive_state()

        date_key = get_current_time().strftime("%Y-%m-%d")

        # 全局计数检查：所有角色合计不超过 daily_limit
        global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
        if global_count >= daily_limit:
            if is_debug_enabled("peer_chat"):
                logger.info(
                    "PeerChatScheduler: 全局已达上限 (%d/%d)",
                    global_count, daily_limit
                )
            return False

        # per-role 计数仍保留，用于日志参考
        today_count = int(state_data.get(f"peer_chat_count_{date_key}", 0))

        last_peer_chat_ts = float(state_data.get("last_peer_chat_ts", 0.0))
        if last_peer_chat_ts > 0 and (now - last_peer_chat_ts) < min_gap:
            if is_debug_enabled("peer_chat"):
                logger.info(
                    "PeerChatScheduler: %s 间隔不足 (%.0fs < %.0fs)",
                    role_id, now - last_peer_chat_ts, min_gap
                )
            return False

        # 用户活跃检查（从 DualRoleCoordinator 合并）
        base_cid = f"private_{master_qq_id}" if (master_qq_id := self._resolve_master_qq_id()) else "default"
        if self.is_user_recently_active(base_cid):
            if is_debug_enabled("peer_chat"):
                logger.info("PeerChatScheduler: %s 跳过，用户最近活跃", role_id)
            return False
        if not self.is_within_idle_window(base_cid):
            if is_debug_enabled("peer_chat"):
                logger.info("PeerChatScheduler: %s 跳过，不在用户空闲窗口内", role_id)
            return False

        # N 角色系统:遍历所有 peer,选第一个可用的(非睡眠、有 qq_id)
        peer_role_id = ""
        peer_qq_id = ""
        peer_name = ""
        from core.services.active_care.core.qq_connection_resolver import (
            can_send_proactive_message,
            check_peer_chat_participants_online,
        )

        for candidate_peer_id in peer_role_ids:
            # 连接门禁：peer 侧角色来自全量注册表，未接入客户端的角色
            # （如未开前端的Frost/Coco）不应被拉进互聊并对外发消息
            if not can_send_proactive_message(candidate_peer_id):
                logger.info(
                    "PeerChatScheduler: %s->%s 跳过，peer 无客户端接入",
                    role_id, candidate_peer_id,
                )
                continue
            # 双方在线门禁：常驻角色（aveline/ling）会被 can_send_proactive_message
            # 无条件放行，但互聊需要对方真的在线，否则台词只会变成 QQ 离线消息
            allowed, reason = check_peer_chat_participants_online(
                role_id, candidate_peer_id
            )
            if not allowed:
                logger.info(
                    "PeerChatScheduler: %s->%s 跳过，%s",
                    role_id, candidate_peer_id, reason,
                )
                continue
            # 角色睡眠门禁：peer_chat 需要双方都参与，任一角色在 SLEEPING 就跳过
            if await self._is_either_character_sleeping(role_id, candidate_peer_id):
                if is_debug_enabled("peer_chat"):
                    logger.info(
                        "PeerChatScheduler: %s->%s 跳过，角色在睡眠中",
                        role_id, candidate_peer_id,
                    )
                continue
            # 解析 peer_qq_id
            candidate_qq_id = self._resolve_peer_qq_id(candidate_peer_id)
            if not candidate_qq_id:
                logger.info(
                    "PeerChatScheduler: %s->%s 跳过，peer_qq_id 为空",
                    role_id, candidate_peer_id,
                )
                continue
            # 获取 peer 中文名(从 personas 查)
            peer_persona = get_persona(candidate_peer_id)
            if peer_persona:
                peer_name = peer_persona.cn_name
            else:
                peer_name = candidate_peer_id
            peer_role_id = candidate_peer_id
            peer_qq_id = candidate_qq_id
            break

        if not peer_role_id:
            logger.info("PeerChatScheduler: %s 跳过，无可用 peer", role_id)
            return False

        # 获取生理状态
        bio_state = {}
        try:
            from core.services.life_simulation import get_life_simulation_service
            life_sim = get_life_simulation_service()
            if life_sim:
                bio_state = life_sim.get_bio_state(role_id)
        except Exception:
            pass

        # LLM 决策
        decision_context = {
            "now": get_current_time().strftime("%Y-%m-%d %H:%M:%S"),
            "now_ts": now,
            "bio_state": bio_state,
            "elapsed_seconds": int(now - last_peer_chat_ts) if last_peer_chat_ts > 0 else 9999,
            "recent_peer_chat_topics": list(state_data.get("recent_peer_chat_topics") or []),
        }

        decision_result = await self._decision.decide_peer_chat(
            decision_context, role_id, peer_name,
        )

        logger.info(
            "PeerChatScheduler: %s LLM决策 should_send=%s topic=%s reason_code=%s",
            role_id,
            decision_result.get("should_send"),
            str(decision_result.get("topic", ""))[:30],
            str(decision_result.get("reason_code", "")),
        )

        if not decision_result.get("should_send", False):
            logger.info(
                "PeerChatScheduler: %s 决策不发送: %s",
                role_id, str(decision_result.get("thought", ""))[:80]
            )
            return False

        topic = str(
            decision_result.get("topic", "")
            or decision_result.get("planned_topic", "")
        ).strip()
        situation = str(decision_result.get("situation", "")).strip()
        opening_idea = str(decision_result.get("opening_idea", "")).strip()

        # 生成剧本并发送
        sent = await self._executor.generate_peer_script(
            role_id=role_id,
            peer_qq_id=peer_qq_id,
            topic=topic,
            situation=situation,
            opening_idea=opening_idea,
            persona_filename=conn.get("persona_filename", ""),
            avoid=decision_result.get("avoid") or None,
        )

        if sent:
            # 更新状态（全局计数 + per-role 计数）
            state_data[f"peer_chat_count_{date_key}"] = today_count + 1
            state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
            state_data["last_peer_chat_ts"] = now
            if topic:
                recent_topics = list(state_data.get("recent_peer_chat_topics") or [])
                recent_topics.append(topic)
                state_data["recent_peer_chat_topics"] = recent_topics[-5:]
                logger.info(f"PeerChatScheduler: 保存 recent_peer_chat_topics={recent_topics[-5:]}")
            await self._storage.save_proactive_state(state_data)
            self._today_count = today_count + 1
            logger.info(
                "PeerChatScheduler: %s->%s 发送成功 (今日第%d次, topic=%s)",
                role_id, peer_name, today_count + 1, topic[:30],
            )
            return True

        return False

    async def _get_multi_qq_connections(self) -> List[Dict[str, str]]:
        """获取多QQ模式下的连接列表（带缓存）"""
        now = time.time()
        if (
            self._cached_connections
            and (now - self._connections_cache_ts) < self._connections_cache_ttl
        ):
            return self._cached_connections

        connections = self._executor._get_qq_connections()
        multi = [
            c for c in connections
            if c.get("persona_filename", "").strip()
        ]
        self._cached_connections = multi
        self._connections_cache_ts = now
        return multi

    def _resolve_peer_qq_id(self, peer_role_id: str) -> str:
        """从 multi_qq_config 或环境变量获取对方 QQ 号(N 角色通用)"""
        # 局部导入：避免 config 包循环导入
        # 通过统一入口 get_multi_qq_role_config() 读强类型配置,
        # settings_adapters 内部已应用 env var override
        from config.settings_adapters import get_multi_qq_role_config

        role_cfg = get_multi_qq_role_config(peer_role_id)
        if role_cfg is not None:
            peer_qq_id = str(getattr(role_cfg, "peer_qq_id", "") or "").strip()
            if peer_qq_id:
                return peer_qq_id

        # 兜底：读角色专属环境变量 XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}
        # 向后兼容:aveline/ling 用旧 env var 名
        env_key_legacy = None
        if peer_role_id == "aveline":
            env_key_legacy = "XIAOYOU_QQ_BOT_NUMBER"
        elif peer_role_id == "ling":
            env_key_legacy = "XIAOYOU_QQ_BOT_NUMBER_LING"
        if env_key_legacy:
            val = os.getenv(env_key_legacy, "").strip()
            if val:
                return val
        # N 角色通用:XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}
        env_key_generic = f"XIAOYOU_QQ_BOT_NUMBER_{peer_role_id.upper()}"
        return os.getenv(env_key_generic, "").strip()
