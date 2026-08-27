"""角色起床时主动给用户发起床问候消息。

触发点：SleepManager._update_runtime_state 在以下场景进入 WAKING_UP 状态时
调用 _on_enter_waking_up：
1. 按作息时间正常起床（prev_phase=SLEEPING，is_stay_up_recovery=False，每日去重）
2. 熬夜后白天恢复清醒（prev_phase in {STAY_UP_LATE, NIGHT_AWAKE, SLEEP_LATER}，
   is_stay_up_recovery=True，可能睡眠不足，消息可以体现疲惫感）

发送链路：复用 active_care 的 executor.trigger_message 管线，
sys_prompt_type=good_morning_proactive 对应 prompt_builder 中的专属模板。
LLM 会自动通过 sleep_context_text 拿到睡眠摘要（睡眠时长、噩梦等级、惯性等），
根据上下文和当前时间生成自然的起床问候（早晨用早安，中午/下午用对应问候），
而非固定模板。

时间感知：_build_specific_instruction 会根据当前小时数动态指定问候语，
避免下午 13:47 醒来还发"早安"导致不真实。

去重保护：由本模块 _sent_today 按 role_id 维度做每日去重，同一角色一天最多发一次。
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

# 必须用 get_logger，否则日志只走 root logger（仅 console handler），不写入 xiaoyou_main.log
logger = get_logger(__name__)

# 角色 ID → QQ 人设文件名映射。
# 必须用 QQ 专属人设文件（qq/Aveline_QQ_Master.json），不能用 core_aveline.json，
# 因为 executor 会用 persona_filename 构建 conversation_id（__persona__aveline_qq_master），
# QQ 机器人客户端 receiver.py 会校验 conversation_id 的 persona 后缀是否匹配自己的 persona_filename，
# 如果传 core_aveline.json → 后缀 core_aveline ≠ aveline_qq_master → 客户端丢弃消息，
# 导致服务端日志显示"已实时送达"但用户实际收不到。
#
# 注意：未知 role_id 不再 fallback 到 aveline。
# 历史上这里 fallback 到 qq/Aveline_QQ_Master.json，导致 xiaolu/yeye/rushuang/mianmian
# 等未接入 active_care 的角色触发起床问候时，消息被误挂到"七濑澪"名义发出，
# 污染 aveline 的会话历史并让用户看到角色"精神分裂"。
# 现在改为未知角色返回 None，由调用方 trigger_character_good_morning 检查后跳过发送。
_ROLE_PERSONA_MAP: Dict[str, str] = {
    "aveline": "qq/Aveline_QQ_Master.json",
    "ling": "qq/Ling_QQ_Master.json",
    "yeye": "qq/Yeye.json",
    "rushuang": "sensitive/Frost.json",
}

# 每日去重缓存：{role_id: "YYYY-MM-DD"}
_sent_today: Dict[str, str] = {}
_lock = threading.Lock()

# P1-2: 跟踪角色早安触发任务，防止被 GC 后角色消息丢失
_pending_good_morning_tasks: set = set()


def _spawn_good_morning_task(coro) -> None:
    """P1-2: 提交早安消息触发任务并保存引用，完成后自动清理并记录异常。"""
    task = asyncio.create_task(coro)
    _pending_good_morning_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _pending_good_morning_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("角色早安触发任务异常: %r", exc, exc_info=exc)

    task.add_done_callback(_on_done)


def _get_today_str() -> str:
    """获取当前日期字符串（YYYY-MM-DD）。"""
    return time.strftime("%Y-%m-%d")


def _has_sent_today(role_id: str) -> bool:
    """检查今日是否已发送过早安消息。"""
    today = _get_today_str()
    with _lock:
        return _sent_today.get(role_id) == today


def _mark_sent(role_id: str) -> None:
    """标记今日已发送。"""
    today = _get_today_str()
    with _lock:
        _sent_today[role_id] = today


def reset_sent_cache(role_id: Optional[str] = None) -> None:
    """重置去重缓存（仅用于测试或强制重发）。

    Args:
        role_id: 指定角色则只重置该角色，None 则清空全部
    """
    with _lock:
        if role_id is None:
            _sent_today.clear()
        else:
            _sent_today.pop(role_id, None)


def _resolve_persona_filename(role_id: str) -> Optional[str]:
    """根据 role_id 解析 QQ 人设文件名。

    必须用 QQ 专属人设文件（qq/Aveline_QQ_Master.json），
    因为 executor 会用 persona_filename 构建 conversation_id，
    QQ 机器人客户端会校验 persona 后缀是否匹配，传错会导致消息被客户端丢弃。

    未知 role_id 返回 None：避免未接入 active_care 的角色（如 xiaolu/mianmian）
    被误挂到 aveline 名义发消息。
    """
    return _ROLE_PERSONA_MAP.get(str(role_id or "").strip().lower())


def _get_wake_greeting_context(hour: int) -> tuple[str, str]:
    """根据当前小时数返回 (时间段标签, 问候语要求)。

    时间分段与 core.utils.time_utils.get_time_period 保持一致：
    早晨（5-10）用早安；中午（11-12）用"刚醒/午安"；下午（13-17）
    用"下午好/睡过头"；傍晚及以后（18+）用"傍晚好/睡多了"。
    避免下午 13:47 还在发"早安"导致不真实。
    """
    if 5 <= hour < 11:
        return "早晨", "必须明确包含早安或起床的词（如『早』『起床了』『醒了』等）"
    if 11 <= hour < 13:
        return "中午", "可以用『刚醒』『起来了』，或简单的『午安』，不要用早安"
    if 13 <= hour < 18:
        return "下午", "用『下午好』或表达睡过头的感觉（如『这下睡多了』），不要用早安"
    return "傍晚以后", "用『傍晚好』或自嘲睡了一天（如『睡到这个点才醒』），不要用早安"


def _build_specific_instruction(role_id: str, is_stay_up_recovery: bool) -> str:
    """根据场景和当前时间构建 specific_instruction。

    时间感知：13:47 下午醒来不再发"早安"，会根据实际时间用"午安/下午好/傍晚好"等，
    让消息更真实自然。
    """
    now = get_current_time()
    period_label, greeting_req = _get_wake_greeting_context(now.hour)
    timing_hint = f"现在是{period_label}（{now.hour:02d}:{now.minute:02d}），"

    if is_stay_up_recovery:
        return (
            f"你（{role_id}）熬夜后刚醒过来，{timing_hint}"
            "可能睡眠不足、有点累。"
            "主动给用户发一句简短的起床消息，1-2 句话即可。"
            "可以自然地流露出疲惫或没睡好的感觉，但不要长篇抱怨。"
            f"{greeting_req}。"
        )
    return (
        f"你（{role_id}）按作息时间刚起床，{timing_hint}"
        "主动给用户发一句简短的起床消息。1-2 句话即可。"
        "可以结合当时的睡眠摘要（如睡眠时长、噩梦、睡眠惯性等）自然表达，"
        f"但不要机械汇报数据。{greeting_req}。"
    )


async def trigger_character_good_morning(
    role_id: str,
    is_stay_up_recovery: bool = False,
) -> bool:
    """角色刚进入 WAKING_UP 状态时主动给用户发一条早安消息。

    通过 active_care 的 executor.trigger_message 管线发送，
    sys_prompt_type=good_morning_proactive，LLM 会自动拿到 sleep_context_text
    中的睡眠摘要（时长/噩梦/惯性等），根据上下文生成自然消息。

    Args:
        role_id: 角色 ID（如 aveline/ling）
        is_stay_up_recovery: True 表示熬夜后白天恢复清醒（消息可体现疲惫）；
            False 表示按作息正常起床

    Returns:
        True: 消息已发送或在去重期内（视为成功）
        False: 发送失败（active_care 未就绪、被间隔保护拦住等）
    """
    role_id = str(role_id or "").strip().lower()
    if not role_id:
        logger.warning("trigger_character_good_morning: role_id 为空，跳过")
        return False

    # 连接门禁：非常驻角色必须有真实客户端接入才允许后台主动发消息。
    # 作息引擎仍会推进内部状态，只是不再对外推送。
    from core.services.active_care.core.qq_connection_resolver import (
        can_send_proactive_message,
    )

    if not can_send_proactive_message(role_id):
        logger.info(
            "角色 %s 无客户端接入，跳过起床问候消息（作息状态继续推进）",
            role_id,
        )
        return False

    # 每日去重：无论正常起床还是熬夜恢复，每人每天只发一次起床问候
    if _has_sent_today(role_id):
        logger.info("角色 %s 今日已发过起床问候消息，跳过", role_id)
        return True

    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if not ac or not getattr(ac, "executor", None):
            logger.warning(
                "Active Care 未就绪（service=%s），跳过角色 %s 的起床问候消息",
                "None" if ac is None else "no_executor",
                role_id,
            )
            return False

        persona_filename = _resolve_persona_filename(role_id)
        if not persona_filename:
            # 未知角色无 QQ 人设映射，跳过发送，避免误挂到 aveline 名义。
            logger.warning(
                "角色 %s 无 QQ 人设映射，跳过起床问候消息发送（避免误挂到其他角色）",
                role_id,
            )
            return False

        # 记录用户睡眠状态（每日去重已保证每角色每天最多1条，无需硬门禁）
        # 用于观察用户睡觉时角色醒来发早安的频率，便于后续调优
        try:
            from core.services.active_care.peer_chat.peer_chat_scheduler import (
                get_peer_chat_scheduler,
            )
            _pcs = get_peer_chat_scheduler()
            if _pcs is not None:
                _user_sleeping = await _pcs.is_user_sleeping()
                logger.info(
                    "角色 %s 触发起床问候（persona=%s, is_stay_up_recovery=%s），"
                    "用户睡眠状态=%s（每日去重已限流，正常发送）",
                    role_id, persona_filename, is_stay_up_recovery,
                    "睡觉中" if _user_sleeping else "清醒",
                )
        except Exception as _sleep_check_err:
            logger.debug(
                "角色 %s 起床问候：检查用户睡眠状态失败: %s",
                role_id, _sleep_check_err,
            )

        specific_instruction = _build_specific_instruction(role_id, is_stay_up_recovery)

        delivered = await ac.executor.trigger_message(
            sys_prompt_type="good_morning_proactive",
            user_input_mock="[CHARACTER_JUST_WOKE_UP]",
            thought=(
                f"character_{role_id}_waking_up_after_stay_up"
                if is_stay_up_recovery
                else f"character_{role_id}_waking_up_by_schedule"
            ),
            specific_instruction=specific_instruction,
            persona_filename=persona_filename,
            # 必须传 qq：否则 dispatch_proactive_message 不剥离 __persona__ 后缀，
            # ws_manager.broadcast 找不到连接 → 消息只能存离线队列，QQ 实时收不到；
            # 同时 resolve_target_conversation 也不会按 persona 路由，
            # 导致 ling 的早安被错发到 aveline 的会话。
            client_type="qq",
        )

        if delivered:
            _mark_sent(role_id)
            logger.info(
                "角色 %s 已主动发送起床问候消息（persona=%s, is_stay_up_recovery=%s）",
                role_id, persona_filename, is_stay_up_recovery,
            )
            return True

        logger.warning(
            "角色 %s 起床问候消息未发送（可能被间隔保护拦住或生成失败）",
            role_id,
        )
        return False
    except Exception as exc:
        logger.error(
            "角色 %s 主动起床问候失败: %s",
            role_id,
            exc,
            exc_info=True,
        )
        return False


def trigger_character_good_morning_async(
    role_id: str,
    is_stay_up_recovery: bool = False,
) -> None:
    """同步入口：通过 asyncio.ensure_future 异步触发早安消息。

    供 SleepManager._update_runtime_state（同步方法）调用，
    避免阻塞睡眠状态机更新。若无事件循环则记录 warning 并跳过。

    Args:
        role_id: 角色 ID
        is_stay_up_recovery: True 表示熬夜后白天恢复清醒
    """
    # P1-1: 使用 asyncio.get_running_loop() 替代 get_event_loop()
    # 避免在 Python 3.10+ 触发弃用警告
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "触发角色 %s 早安消息时无事件循环（is_stay_up_recovery=%s），跳过",
            role_id, is_stay_up_recovery,
        )
        return

    # P1-2: 保存任务引用，避免被 GC 后角色早安消息丢失
    # 不再使用已弃用的 ensure_future(..., loop=loop)
    _spawn_good_morning_task(
        trigger_character_good_morning(role_id, is_stay_up_recovery=is_stay_up_recovery)
    )
