"""角色进入睡眠状态时主动给用户发晚安消息。

触发点：SleepManager 在以下场景进入 SLEEPING 状态时调用 _on_enter_sleeping：
1. 按计划作息时间首次入睡（is_sleep_again=False，每日去重）
2. 半夜被叫醒后跟用户聊了一会儿，3 分钟静默窗口结束后决策睡回去
   （is_sleep_again=True，单独冷却去重，避免短时间重复发送）

发送链路：复用 active_care 的 executor.trigger_message 管线，
sys_prompt_type 对应 prompt_builder 中的专属模板：
- goodnight_proactive: 首次入睡的晚安告别
- sleep_again_proactive: 半夜睡回去的告别（不再发"晚安"）

角色睡眠降频兜底：角色入睡后，active_care 不再把"助手说晚安"当作用户入睡信号
（2026-08-16 起移除该自动闭环），避免 nightly_processor / peer_chat 误判用户入睡。
角色睡眠时的主动关怀降频由 checker_event_handler.role_sleeping 与 decision.py 兜底。
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, Optional

# 注意：未知 role_id 不再 fallback 到 aveline。
# 历史上这里 fallback 到 qq/Aveline_QQ_Master.json，导致 xiaolu/yeye/rushuang/mianmian
# 等未接入 active_care 的角色触发晚安时，消息被误挂到"七濑澪"名义发出，
# 污染 aveline 的会话历史并让用户看到角色"精神分裂"。
# 现在改为未知角色返回 None，由调用方 trigger_character_goodnight 检查后跳过发送。

from core.utils.logger import get_logger

# 必须用 get_logger，否则日志只走 root logger（仅 console handler），不写入 xiaoyou_main.log
logger = get_logger(__name__)

# 角色 ID → QQ 人设文件名映射。
# 必须用 QQ 专属人设文件（qq/Aveline_QQ_Master.json），不能用 core_aveline.json，
# 因为 executor 会用 persona_filename 构建 conversation_id（__persona__aveline_qq_master），
# QQ 机器人客户端 receiver.py 会校验 conversation_id 的 persona 后缀是否匹配自己的 persona_filename，
# 如果传 core_aveline.json → 后缀 core_aveline ≠ aveline_qq_master → 客户端丢弃消息，
# 导致服务端日志显示"已实时送达"但用户实际收不到。
_ROLE_PERSONA_MAP: Dict[str, str] = {
    "aveline": "qq/Aveline_QQ_Master.json",
    "ling": "qq/Ling_QQ_Master.json",
    "yeye": "qq/Yeye.json",
    "rushuang": "sensitive/Frost.json",
}

# 每日去重缓存：{role_id: "YYYY-MM-DD"}（仅针对首次入睡）
_sent_today: Dict[str, str] = {}
# 半夜睡回去冷却：{role_id: last_sent_timestamp}，避免短时间内多次睡回去发多次
_sleep_again_last_sent: Dict[str, float] = {}
_lock = threading.Lock()

# 半夜睡回去消息的最小冷却间隔（秒），避免短时间内多次发
_SLEEP_AGAIN_COOLDOWN_SECONDS = 300.0

# P1-2: 跟踪角色晚安触发任务，防止被 GC 后角色消息丢失
_pending_goodnight_tasks: set = set()


def _spawn_goodnight_task(coro) -> None:
    """P1-2: 提交晚安消息触发任务并保存引用，完成后自动清理并记录异常。"""
    task = asyncio.create_task(coro)
    _pending_goodnight_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _pending_goodnight_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("角色晚安触发任务异常: %r", exc, exc_info=exc)

    task.add_done_callback(_on_done)


def _get_today_str() -> str:
    """获取当前日期字符串（YYYY-MM-DD）。"""
    return time.strftime("%Y-%m-%d")


def _has_sent_today(role_id: str) -> bool:
    """检查今日是否已发送过晚安消息（仅首次入睡场景）。"""
    today = _get_today_str()
    with _lock:
        return _sent_today.get(role_id) == today


def _mark_sent(role_id: str) -> None:
    """标记今日已发送（首次入睡场景）。"""
    today = _get_today_str()
    with _lock:
        _sent_today[role_id] = today


def _has_sleep_again_in_cooldown(role_id: str) -> bool:
    """检查半夜睡回去消息是否在冷却期内（避免短时间内重复发送）。"""
    now = time.time()
    with _lock:
        last_sent = _sleep_again_last_sent.get(role_id, 0.0)
        return (now - last_sent) < _SLEEP_AGAIN_COOLDOWN_SECONDS


def _mark_sleep_again_sent(role_id: str) -> None:
    """标记半夜睡回去消息已发送。"""
    now = time.time()
    with _lock:
        _sleep_again_last_sent[role_id] = now


def reset_sent_cache(role_id: Optional[str] = None) -> None:
    """重置去重缓存（仅用于测试或强制重发）。

    Args:
        role_id: 指定角色则只重置该角色，None 则清空全部
    """
    with _lock:
        if role_id is None:
            _sent_today.clear()
            _sleep_again_last_sent.clear()
        else:
            _sent_today.pop(role_id, None)
            _sleep_again_last_sent.pop(role_id, None)


def _resolve_persona_filename(role_id: str) -> Optional[str]:
    """根据 role_id 解析 QQ 人设文件名。

    必须用 QQ 专属人设文件（qq/Aveline_QQ_Master.json），
    因为 executor 会用 persona_filename 构建 conversation_id，
    QQ 机器人客户端会校验 persona 后缀是否匹配，传错会导致消息被客户端丢弃。

    未知 role_id 返回 None：避免未接入 active_care 的角色（如 xiaolu/yeye）
    被误挂到 aveline 名义发消息。
    """
    return _ROLE_PERSONA_MAP.get(str(role_id or "").strip().lower())


def _resolve_sys_prompt_type(is_sleep_again: bool) -> str:
    """根据场景选择 sys_prompt_type。"""
    return "sleep_again_proactive" if is_sleep_again else "goodnight_proactive"


def _build_specific_instruction(role_id: str, is_sleep_again: bool) -> str:
    """根据场景构建 specific_instruction。"""
    if is_sleep_again:
        return (
            f"你（{role_id}）半夜被叫醒后跟用户聊了一会儿，"
            "现在决定睡回去继续睡觉。主动给用户发一句简短的告别消息，"
            "让他知道你睡去了。1-2 句话即可，"
            "必须明确包含睡回去的告别词（如『我先去睡了』『困了，继续睡啦』『再睡会儿』等），"
            "不要再发『晚安』，禁止提问。"
        )
    return (
        f"你（{role_id}）按作息时间准备睡觉了，"
        "主动给用户发一句简短温暖的晚安消息。"
        "1-2 句话即可，必须明确包含晚安告别词（如『晚安』『先去睡了』『睡啦』等），"
        "禁止提问（你要睡了不该期待回复）。"
    )


# 判断"用户正在聊天"的窗口（秒）：最近 N 秒内发过消息视为正在聊天
_USER_IN_CONVERSATION_WINDOW_SECONDS = 300.0


def _is_user_in_conversation() -> bool:
    """检查用户是否最近在聊天（最近 N 秒内发过消息）。

    用于首次入睡场景：如果用户正在聊天，用"聊天中入睡"instruction
    让 LLM 判断是顺延还是告别，而不是固定发晚安。
    """
    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if not ac:
            return False
        scheduler = getattr(ac, "peer_chat_scheduler", None)
        if not scheduler:
            return False
        now = time.time()
        threshold = _USER_IN_CONVERSATION_WINDOW_SECONDS
        for _, ts in scheduler._last_user_activity_ts.items():  # noqa: SLF001
            if ts > 0 and (now - float(ts)) < threshold:
                return True
        return False
    except Exception:
        return False


async def trigger_character_goodnight(
    role_id: str,
    is_sleep_again: bool = False,
) -> bool:
    """角色刚进入 SLEEPING 状态时主动给用户发一条晚安/睡回去消息。

    通过 active_care 的 executor.trigger_message 管线发送，
    根据 is_sleep_again 选择不同的 sys_prompt_type：
    - False: goodnight_proactive（首次入睡，每日去重）
    - True: sleep_again_proactive（半夜睡回去，冷却去重）

    Args:
        role_id: 角色 ID（如 aveline/ling）
        is_sleep_again: True 表示半夜被叫醒后睡回去；
            False 表示按作息时间首次入睡

    Returns:
        True: 消息已发送或在去重期内（视为成功）
        False: 发送失败（active_care 未就绪、被间隔保护拦住等）
    """
    role_id = str(role_id or "").strip().lower()
    if not role_id:
        logger.warning("trigger_character_goodnight: role_id 为空，跳过")
        return False

    # 连接门禁：非常驻角色必须有真实客户端接入才允许后台主动发消息。
    # 作息引擎仍会推进内部状态，只是不再对外推送。
    from core.services.active_care.core.qq_connection_resolver import (
        can_send_proactive_message,
    )

    if not can_send_proactive_message(role_id):
        logger.info(
            "角色 %s 无客户端接入，跳过晚安消息（作息状态继续推进）",
            role_id,
        )
        return False

    # 去重检查（按场景使用不同策略）
    if is_sleep_again:
        if _has_sleep_again_in_cooldown(role_id):
            logger.info(
                "角色 %s 半夜睡回去消息在冷却期内（%ds），跳过",
                role_id, int(_SLEEP_AGAIN_COOLDOWN_SECONDS),
            )
            return True
    else:
        if _has_sent_today(role_id):
            logger.info("角色 %s 今日已发过晚安消息，跳过", role_id)
            return True

    # 半夜睡回去复用统一的 activity_return 模块，使 interrupt / sleep 回归消息统一
    if is_sleep_again:
        try:
            from core.services.character_daily.activity_return import (
                send_activity_return_message,
            )

            result = await send_activity_return_message(
                conversation_id="",
                role_id=role_id,
                activity="sleeping",
                return_type="sleep",
                source="sleep_manager_sleep_again",
                sys_prompt_type="sleep_again_proactive",
                user_input_mock="[CHARACTER_SLEEP_AGAIN]",
                thought=f"character_{role_id}_sleep_again_by_recovery",
            )
            if result.get("delivered"):
                _mark_sleep_again_sent(role_id)
                logger.info(
                    "角色 %s 已主动发送睡回去消息（统一模块，persona=%s）",
                    role_id, _resolve_persona_filename(role_id),
                )
                return True
            logger.warning("角色 %s 睡回去消息未发送（可能被间隔保护拦住）", role_id)
            return False
        except Exception as exc:
            logger.error(
                "角色 %s 通过统一模块发送睡回去消息失败: %s",
                role_id, exc, exc_info=True,
            )
            return False

    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if not ac or not getattr(ac, "executor", None):
            logger.warning(
                "Active Care 未就绪（service=%s），跳过角色 %s 的晚安消息",
                "None" if ac is None else "no_executor",
                role_id,
            )
            return False

        persona_filename = _resolve_persona_filename(role_id)
        if not persona_filename:
            # 未知角色无 QQ 人设映射，跳过发送，避免误挂到 aveline 名义。
            logger.warning(
                "角色 %s 无 QQ 人设映射，跳过晚安消息发送（避免误挂到其他角色）",
                role_id,
            )
            return False
        sys_prompt_type = _resolve_sys_prompt_type(is_sleep_again)
        specific_instruction = _build_specific_instruction(role_id, is_sleep_again)

        # 首次入睡场景：如果用户正在聊天，用"聊天中入睡"instruction
        # 让 LLM 判断是顺延还是告别，而不是固定发晚安突然切断对话
        user_in_chat = _is_user_in_conversation()
        if user_in_chat and not is_sleep_again:
            try:
                from core.services.character_daily.activity_return.instruction import (
                    build_sleep_during_chat_farewell_instruction,
                )
                specific_instruction = build_sleep_during_chat_farewell_instruction(role_id)
                logger.info(
                    "角色 %s 首次入睡时用户正在聊天，使用聊天中入睡告别 instruction",
                    role_id,
                )
            except Exception as exc:
                logger.warning(
                    "角色 %s 构建聊天中入睡 instruction 失败，回退到默认晚安: %s",
                    role_id, exc,
                )

        delivered = await ac.executor.trigger_message(
            sys_prompt_type=sys_prompt_type,
            user_input_mock="[CHARACTER_GOING_TO_SLEEP]",
            thought=f"character_{role_id}_going_to_sleep_by_schedule",
            specific_instruction=specific_instruction,
            persona_filename=persona_filename,
            # 必须传 qq：否则 dispatch_proactive_message 不剥离 __persona__ 后缀，
            # ws_manager.broadcast 找不到连接 → 消息只能存离线队列，QQ 实时收不到；
            # 同时 resolve_target_conversation 也不会按 persona 路由，
            # 导致 ling 的晚安被错发到 aveline 的会话。
            client_type="qq",
        )

        if delivered:
            _mark_sent(role_id)
            logger.info(
                "角色 %s 已主动发送晚安消息（persona=%s）",
                role_id, persona_filename,
            )
            return True

        logger.warning(
            "角色 %s 晚安消息未发送（可能被间隔保护拦住或生成失败）",
            role_id,
        )
        return False
    except Exception as exc:
        logger.error(
            "角色 %s 主动晚安失败: %s",
            role_id, exc, exc_info=True,
        )
        return False


def trigger_character_goodnight_async(
    role_id: str,
    is_sleep_again: bool = False,
) -> None:
    """同步入口：通过 asyncio.ensure_future 异步触发晚安消息。

    供 SleepManager._update_runtime_state（同步方法）和
    finalize_sleep_recovery_check（异步方法但不应阻塞状态机）调用，
    避免阻塞睡眠状态机更新。若无事件循环则记录 warning 并跳过。

    Args:
        role_id: 角色 ID
        is_sleep_again: True 表示半夜睡回去场景
    """
    # P1-1: 使用 asyncio.get_running_loop() 替代 get_event_loop()
    # 避免在 Python 3.10+ 触发弃用警告
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "触发角色 %s 晚安消息时无事件循环（is_sleep_again=%s），跳过",
            role_id, is_sleep_again,
        )
        return

    # P1-2: 保存任务引用，避免被 GC 后角色晚安消息丢失
    # 不再使用已弃用的 ensure_future(..., loop=loop)
    _spawn_goodnight_task(
        trigger_character_goodnight(role_id, is_sleep_again=is_sleep_again)
    )
