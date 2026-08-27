#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Active Care 集成

- 把用户消息缓存进 Active Care 上下文
- 实时晚安/早安意图检测（BERT 语义 + 规则），驱动睡眠模式切换
"""

import time
import traceback

from core.utils.logger import get_logger

logger = get_logger(__name__)


def _make_debug_logger(debug_log_path):
    """返回一个把日志追加到 debug_log_path 的闭包（无路径时为空操作）。"""
    if not debug_log_path:

        def _noop(msg: str):
            return

        return _noop

    from core.utils.time_utils import get_current_time_str

    def _log_debug(msg: str):
        try:
            timestamp = get_current_time_str()
            with open(debug_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {msg}\n")
        except Exception:
            pass

    return _log_debug


async def run_active_care_update(content, conversation_id: str) -> None:
    """把用户消息缓存进 Active Care 上下文，并做实时晚安/早安意图检测。

    debug 日志仅在 active_care_ws 开关开启时落盘，避免长期堆积。
    """
    try:
        from config.debug_config import is_debug_enabled as _ac_is_debug_enabled
        from core.services.active_care.core.service import get_active_care_service

        # 专门的 Active Care 调试日志文件（仅当 active_care_ws 开关开启时才落盘）
        debug_log_path = None
        if _ac_is_debug_enabled("active_care_ws"):
            try:
                from core.utils.common import get_project_root

                debug_log_path = get_project_root() / "logs" / "active_care_debug.log"
            except Exception:
                debug_log_path = None

        _log_debug = _make_debug_logger(debug_log_path)

        content_str = str(content) if isinstance(content, list) else content
        content_preview = content_str[:50]

        _log_debug(f"用户消息: {content_preview}...")

        ac_service = get_active_care_service()
        if ac_service is None:
            _log_debug("错误: get_active_care_service() 返回 None")
        else:
            ac_service.context.update_recent_user_message(
                conversation_id=conversation_id,
                content=content_str,
                timestamp=time.time(),
            )
            _log_debug("消息缓存已更新")
            try:
                from core.services.dual_role.social_events import get_social_event_engine

                observer = ac_service.storage.resolve_scope_from_conversation_id(
                    conversation_id
                )
                await get_social_event_engine().record_user_life_event(
                    content_str,
                    learned_by=observer,
                )
            except Exception as social_e:
                logger.debug("记录共享生活事件失败: %s", social_e)

        # 实时模式检测：学习低打扰与晚安低打扰必须分别路由。
        try:
            mode_state = ac_service.state_manager.mode if ac_service else None
            if mode_state is None:
                _log_debug("跳过实时模式检测: Active Care 服务未初始化")
                return
            intent = await mode_state.detect_transition_intent(content_str)
            _log_debug(f"意图检测结果: {intent}")
            if intent and intent.get("action") == "enter_reduced":
                reason = intent.get("reason", "goodnight")
                label = intent.get("label", "")
                source = intent.get("source", "rule")
                bert_confidence = intent.get("bert_confidence", 0.0)
                _log_debug(
                    f"检测到低打扰意图: reason={reason}, label={label}, source={source}, "
                    f"bert_confidence={bert_confidence}"
                )

                is_sleep_transition = reason == "goodnight" and label == "sleep"
                if is_sleep_transition:
                    should_activate = source == "rule" or (
                        source == "bert" and bert_confidence >= 0.40
                    )
                    if should_activate:
                        _log_debug("确认晚安意图，激活睡眠低打扰")
                        success = await ac_service.set_sleep_mode(active=True, reason=reason)
                        _log_debug(f"set_sleep_mode 结果: {'成功' if success else '失败'}")

                        state = await ac_service.storage.get_proactive_state()
                        _log_debug(
                            f"状态验证: reduced_mode_active={state.get('reduced_mode_active')}, "
                            f"reduced_mode_label={state.get('reduced_mode_label')}, "
                            f"last_goodnight_ts={state.get('last_goodnight_ts')}"
                        )
                    else:
                        _log_debug(
                            f"晚安意图不满足激活条件: source={source}, "
                            f"bert_confidence={bert_confidence}"
                        )
                else:
                    result = await ac_service.state_manager.apply_transition_intent(intent)
                    _log_debug(
                        "非睡眠低打扰已按独立状态处理: "
                        f"focus_changed={result.get('focus_changed')}, "
                        f"mode_changed={result.get('mode_changed')}"
                    )
            elif intent and intent.get("action") == "exit_reduced":
                reason = intent.get("reason")
                label = intent.get("label")
                if reason == "morning" and label == "wake":
                    exit_sync_success = await ac_service.set_sleep_mode(
                        active=False, reason="morning"
                    )
                    _log_debug(
                        f"退出睡眠模式结果: {'成功' if exit_sync_success else '失败'}"
                    )
                else:
                    result = await ac_service.state_manager.apply_transition_intent(intent)
                    _log_debug(
                        "非睡眠退出意图已按独立状态处理: "
                        f"focus_changed={result.get('focus_changed')}, "
                        f"mode_changed={result.get('mode_changed')}"
                    )
            else:
                _log_debug("未检测到晚安意图")

        except Exception as intent_e:
            _log_debug(f"实时晚安检测异常: {intent_e}")
            _log_debug(traceback.format_exc())

    except Exception as ac_e:
        if debug_log_path:
            try:
                from core.utils.time_utils import get_current_time_str

                timestamp = get_current_time_str()
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] Active Care 消息更新异常: {ac_e}\n")
                    f.write(traceback.format_exc() + "\n")
            except Exception:
                pass
