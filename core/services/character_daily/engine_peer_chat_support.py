"""CharacterDailyEngine 的 peer chat 辅助实现。"""

from __future__ import annotations
from core.utils.logger import get_logger


import time
from datetime import datetime

from core.services.character_daily.activity_model import CHAT_ELIGIBLE_ACTIVITIES
from core.services.character_daily.peer_chat_gate import (
    build_situation_context,
    should_use_urgent_interrupt,
)
from core.utils.logger import get_module_logger
from core.utils.time_utils import now_str

logger = get_logger(__name__)

# 诊断专用 logger，写入 peer_chat.log（与 active_care 主流程分离）
_diag_logger = get_module_logger("PEER_CHAT", "peer_chat.log")


def is_user_recently_active(engine) -> bool:
    """检查用户是否最近活跃。"""
    try:
        scheduler = engine._peer_chat_scheduler
        if scheduler:
            from core.utils.config_accessor import get_active_care_config

            grace = float(
                get_active_care_config(
                    "peer_chat_user_activity_grace_seconds",
                    default=45.0,
                    settings=scheduler._settings,
                )
            )
            for _, ts in scheduler._last_user_activity_ts.items():
                if (time.time() - ts) < grace:
                    return True
    except Exception:
        return False
    return False


async def execute_peer_chat(engine, initiator: str, now: datetime) -> None:
    """执行一次 peer chat。"""
    from core.services.dual_role.personas import get_peer_role_id, get_persona
    plan_i = engine._state.get_plan(initiator)
    # N 角色系统:peer 取第一个 peer(向后兼容 N=2 时行为不变)
    peer_role_id = get_peer_role_id(initiator)
    if not peer_role_id:
        _diag_logger.warning("PeerChat 执行: initiator=%s 无 peer 角色", initiator)
        return
    plan_p = engine._state.get_plan(peer_role_id)
    if not plan_i or not plan_p:
        return

    peer_is_free = plan_p.current_activity in CHAT_ELIGIBLE_ACTIVITIES
    is_async = not peer_is_free
    interrupt_mode = should_use_urgent_interrupt(is_async, engine._config) if is_async else False
    situation = build_situation_context(initiator, plan_i, plan_p, interrupt_mode=interrupt_mode)

    mode_label = "urgent_interrupt" if interrupt_mode else ("async" if is_async else "normal")
    _diag_logger.info(
        "PeerChat 执行: 发起者=%s 模式=%s 情境=%s",
        initiator, mode_label, situation[:80],
    )

    scheduler = engine._peer_chat_scheduler
    if not scheduler:
        _diag_logger.warning("PeerChat 执行: PeerChatScheduler 未注入，无法执行")
        return

    try:
        scheduler.ensure_running()
        success = await trigger_via_scheduler(engine, initiator, situation)
        if success:
            record_peer_chat(engine, initiator, now)
            await sync_peer_chat_state(engine, initiator, now)
            _diag_logger.info("PeerChat 执行: 成功! 发起者=%s", initiator)
        else:
            _diag_logger.warning("PeerChat 执行: trigger_via_scheduler 返回 False, 发起者=%s", initiator)
    except Exception as exc:
        _diag_logger.error("PeerChat 执行: 异常: %s", exc, exc_info=True)


async def trigger_via_scheduler(engine, initiator: str, situation: str) -> bool:
    """通过 PeerChatScheduler 的管线触发 peer chat。"""
    scheduler = engine._peer_chat_scheduler
    if not scheduler:
        return False

    try:
        from core.services.dual_role.personas import get_peer_role_id, get_persona

        connections = await scheduler._get_multi_qq_connections()
        if len(connections) < 2:
            return False

        conn = None
        for item in connections:
            if item.get("role_id", "").strip().lower() == initiator:
                conn = item
                break
        if not conn:
            return False

        # N 角色系统:从 personas 获取 peer_role_id 和 peer_name
        peer_role_id = get_peer_role_id(initiator)
        if not peer_role_id:
            return False
        peer_qq_id = scheduler._resolve_peer_qq_id(peer_role_id)
        if not peer_qq_id:
            return False

        now_ts = time.time()
        bio_state = {}
        try:
            from core.services.life_simulation import get_life_simulation_service

            life_sim = get_life_simulation_service()
            if life_sim:
                bio_state = life_sim.get_bio_state(initiator)
        except Exception:
            pass

        peer_persona = get_persona(peer_role_id)
        peer_name = peer_persona.cn_name if peer_persona else peer_role_id
        decision_context = {
            "now": now_str("%Y-%m-%d %H:%M:%S"),
            "now_ts": now_ts,
            "bio_state": bio_state,
            "elapsed_seconds": int(now_ts - engine._state.global_last_peer_chat_ts)
            if engine._state.global_last_peer_chat_ts > 0
            else 9999,
            "recent_peer_chat_topics": [],
            "character_daily_situation": situation,
        }

        decision_result = await scheduler._decision.decide_peer_chat(
            decision_context,
            initiator,
            peer_name,
        )
        should_send = decision_result.get("should_send", False)
        thought = str(decision_result.get("thought", ""))[:100]
        _diag_logger.info(
            "PeerChat LLM决策: should_send=%s thought=%s initiator=%s",
            should_send, thought, initiator,
        )
        if not should_send:
            return False

        topic = str(
            decision_result.get("topic", "") or decision_result.get("planned_topic", "")
        ).strip()
        situation_from_llm = str(decision_result.get("situation", "")).strip()
        opening_idea = str(decision_result.get("opening_idea", "")).strip()
        if not situation_from_llm:
            situation_from_llm = situation

        _diag_logger.info(
            "PeerChat 生成剧本: initiator=%s topic=%s situation=%s",
            initiator, topic[:40], situation_from_llm[:40],
        )
        sent = await scheduler._executor.generate_peer_script(
            role_id=initiator,
            peer_qq_id=peer_qq_id,
            topic=topic,
            situation=situation_from_llm,
            opening_idea=opening_idea,
            persona_filename=conn.get("persona_filename", ""),
        )
        _diag_logger.info("PeerChat 剧本发送结果: sent=%s initiator=%s", sent, initiator)
        return bool(sent)
    except Exception as exc:
        _diag_logger.error("PeerChat trigger_via_scheduler 异常: %s", exc, exc_info=True)
        return False


def record_peer_chat(engine, initiator: str, now: datetime) -> None:
    """记录 peer chat 成功。"""
    from core.services.dual_role.personas import get_peer_role_id
    ts = now.timestamp()
    plan_i = engine._state.get_plan(initiator)
    if plan_i:
        plan_i.today_peer_chat_count += 1
        plan_i.last_peer_chat_ts = ts

    # N 角色系统:peer 取第一个 peer(向后兼容)
    peer_id = get_peer_role_id(initiator)
    if peer_id:
        plan_p = engine._state.get_plan(peer_id)
        if plan_p:
            plan_p.last_peer_chat_ts = ts

    engine._state.global_last_peer_chat_ts = ts
    engine._store.save(engine._state)
    logger.info(
        "CharacterDailyEngine: Peer chat 记录完成, 发起者=%s, 今日计数=%d",
        initiator,
        plan_i.today_peer_chat_count if plan_i else -1,
    )


async def sync_peer_chat_state(engine, initiator: str, now: datetime) -> None:
    """同步 peer chat 状态到 proactive_state。"""
    scheduler = engine._peer_chat_scheduler
    if not scheduler:
        return

    try:
        # N 角色系统:所有角色用自己的 scope
        from core.services.dual_role.personas import get_all_role_ids
        all_role_ids = set(get_all_role_ids())
        scope = initiator if initiator in all_role_ids else "aveline"
        scheduler._storage.set_runtime_scope(scope)
        state_data = await scheduler._storage.get_proactive_state()

        date_key = now.strftime("%Y-%m-%d")
        ts = now.timestamp()
        global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
        role_count = int(state_data.get(f"peer_chat_count_{date_key}", 0))
        state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
        state_data[f"peer_chat_count_{date_key}"] = role_count + 1
        state_data["last_peer_chat_ts"] = ts
        await scheduler._storage.save_proactive_state(state_data)
    except Exception as exc:
        logger.warning("CharacterDailyEngine: 同步 peer chat 状态失败: %s", exc)
