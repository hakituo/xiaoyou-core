"""Active Care 触发上下文构建器

负责组装触发上下文（历史/睡眠/人设/明日基调等）并构建最终 Prompt。
从 executor.py 拆分而来，方法签名与原 _xxx 方法保持一致。

依赖注入策略：整体传入 executor 实例（参考 SleepSessionManager 模式），
新类方法内通过 executor.xxx 访问原 self 属性，降低搬迁出错风险。
"""
import time
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger
from core.services.active_care.prompt.prompt_builder import build_active_care_prompt
from core.services.active_care.postprocess.deduplicator import Deduplicator
from core.services.active_care.postprocess.postprocessor import LanguageHandler
from core.services.active_care.shared.constants import (
    StateKeys,
    LONG_SILENCE_THRESHOLD_SECONDS,
    format_duration_human,
    build_sleep_status_description,
)
from core.utils.timestamp_utils import safe_timestamp
from core.agents.chat_agent_components.persona_system.prompt.data import (
    get_persona_name_from_filename,
)

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class TriggerContextBuilder:
    """触发上下文与 Prompt 构建器

    通过整体注入 executor 实例访问 context/storage/persona_resolver/
    history_processor/input_builder 等依赖。
    """

    def __init__(self, executor):
        """构造器

        Args:
            executor: ActiveCareExecutor 实例（门面），用于访问：
                - executor.context: ActiveCareContext
                - executor.storage: ActiveCareStorage
                - executor.persona_resolver: PersonaResolver
                - executor._history_processor: HistoryProcessor
                - executor._input_builder: ModelInputBuilder
                - executor.settings: 全局配置
        """
        self._executor = executor

    # ==================== 历史记录获取 ====================

    async def get_history_with_cache(
        self,
        target_conversation_id: str,
        now: float,
    ) -> List[Dict[str, Any]]:
        """获取历史记录（含缓存）"""
        executor = self._executor
        history_msgs = await executor.context.get_latest_history_for_conversation(
            target_conversation_id, limit=10
        )
        logger.info(
            "Active Care _get_history_with_cache: cid=%s, history_count=%d, history_preview=%s",
            target_conversation_id,
            len(history_msgs),
            [str(m.get("content", ""))[:30] for m in (history_msgs[-3:] if history_msgs else [])],
        )
        cached_user_msg = executor.context.get_recent_user_message(target_conversation_id)
        cached_content = str(cached_user_msg.get("content") or "").strip()
        cached_ts = cached_user_msg.get("timestamp")
        logger.info(
            "Active Care _get_history_with_cache: cached_msg=%s, cached_ts=%s",
            cached_content[:50] if cached_content else "(empty)",
            cached_ts,
        )
        if cached_content:
            history_msgs = list(history_msgs)
            from core.services.active_care.shared.constants import normalize_content
            normalized_cached = normalize_content(cached_content)
            already_exists = False
            for msg in history_msgs:
                if str(msg.get("role") or "").lower() != "user":
                    continue
                msg_content = normalize_content(msg.get("content", ""))
                if msg_content == normalized_cached:
                    already_exists = True
                    break
            if not already_exists:
                effective_ts = cached_ts if cached_ts is not None and cached_ts > 0 else now
                history_msgs.append(
                    {
                        "role": "user",
                        "content": cached_content,
                        "timestamp": effective_ts,
                    }
                )
        return history_msgs

    # ==================== 上下文组装 ====================

    async def build_trigger_context(
        self,
        history_msgs: List[Dict[str, Any]],
        target_conversation_id: str,
        now: float,
        now_dt,
        tod: str,
    ) -> Dict[str, Any]:
        """构建触发上下文"""
        executor = self._executor
        hp = executor._history_processor

        recent_history_text, last_user_message = hp.build_recent_history_text(
            history_msgs, now
        )

        cached_user_msg = executor.context.get_recent_user_message(target_conversation_id)
        cached_ts = cached_user_msg.get("timestamp")
        last_user_ts_raw = hp.resolve_last_user_timestamp(
            history_msgs=history_msgs, cached_ts=cached_ts,
        )
        user_elapsed_seconds = (
            max(0.0, now - last_user_ts_raw)
            if last_user_ts_raw > 0
            else float(LONG_SILENCE_THRESHOLD_SECONDS)
        )
        elapsed_seconds = user_elapsed_seconds

        last_assistant_message, last_proactive_assistant_message, recent_assistant_messages = (
            hp.extract_last_assistant_messages(history_msgs)
        )

        last_assistant_ts = hp.resolve_last_assistant_timestamp(history_msgs)
        if last_assistant_ts > 0:
            assistant_elapsed = max(0.0, now - last_assistant_ts)
            if assistant_elapsed < elapsed_seconds:
                elapsed_seconds = assistant_elapsed

        # 判断主程序回复是否晚于用户最后一条消息：
        # True  → 主程序已经回复过用户那条消息，active care 不应再"回复主程序已回过的消息"
        # False → 用户最后一条消息尚未被主程序回复，active care 可跟进用户消息
        last_assistant_after_user = bool(
            last_assistant_ts > 0
            and last_user_ts_raw > 0
            and last_assistant_ts > last_user_ts_raw
        )

        try:
            proactive_state = await executor.storage.get_proactive_state()
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("获取主动状态失败，使用空字典", exc_info=True)
            proactive_state = {}

        # 解析睡眠状态
        sleep_info = self.parse_sleep_state(proactive_state)

        # 构建睡眠上下文
        sleep_context_text = self.build_sleep_context_text(proactive_state)
        mode_status_text = self.build_mode_status_text(proactive_state, sleep_info)
        goodnight_but_awake_context = self.build_goodnight_but_awake_context(proactive_state, now)

        if not last_proactive_assistant_message:
            last_proactive_assistant_message = str(
                proactive_state.get(StateKeys.LAST_SENT_CONTENT) or ""
            ).strip()

        repeat_anchors = Deduplicator.collect_repeat_anchors(
            last_proactive_assistant_message=last_proactive_assistant_message,
            last_assistant_message=last_assistant_message,
            proactive_state=proactive_state,
            recent_assistant_messages=recent_assistant_messages,
        )
        known_sleep_time = executor._input_builder.resolve_known_sleep_time()
        preferred_language = LanguageHandler.infer_preferred_language(history_msgs)

        # 解析人设
        persona_prompt = executor.persona_resolver.load_persona_prompt(target_conversation_id)
        active_care_persona_filename = executor.persona_resolver.resolve_persona_filename(target_conversation_id)
        active_care_persona_name = get_persona_name_from_filename(active_care_persona_filename)
        active_care_sensitive_mode = executor.persona_resolver.is_sensitive_mode(active_care_persona_filename)
        tone_reference_text = executor.persona_resolver.build_tone_reference(
            target_conversation_id,
            str(last_user_message or "").strip(),
            active_care_sensitive_mode,
        )

        # 解析时间戳
        last_sent_ts = safe_timestamp(proactive_state.get(StateKeys.LAST_SENT_TS))

        sleep_confirmed_by_silence = bool(
            sleep_info["sleep_session_active"]
            and sleep_info["last_goodnight_probe_ts"] > 0
            and (last_user_ts_raw <= 0 or last_user_ts_raw <= sleep_info["last_goodnight_probe_ts"])
        )

        # 获取明日基调
        tomorrow_tone_text = ""
        try:
            from core.services.journal.service import get_journal_service
            tomorrow_tone_text = await get_journal_service().get_tomorrow_tone() or ""
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("获取明日基调失败", exc_info=True)
            pass

        # 判断是否是晚安后的首次探针
        is_first_probe = bool(
            sleep_info["sleep_session_active"]
            and sleep_info["last_goodnight_probe_ts"] <= 0
            and sleep_info["last_goodnight_ts"] > 0
            and (now - sleep_info["last_goodnight_ts"]) >= 600  # 晚安后至少10分钟
        )

        return {
            "recent_history_text": recent_history_text,
            "last_user_message": last_user_message,
            "last_user_ts_raw": last_user_ts_raw,
            "elapsed_seconds": elapsed_seconds,
            "user_elapsed_seconds": user_elapsed_seconds,
            "last_assistant_message": last_assistant_message,
            "last_proactive_assistant_message": last_proactive_assistant_message,
            "last_assistant_after_user": last_assistant_after_user,
            "proactive_state": proactive_state,
            "sleep_info": sleep_info,
            "sleep_context_text": sleep_context_text,
            "mode_status_text": mode_status_text,
            "goodnight_but_awake_context": goodnight_but_awake_context,
            "repeat_anchors": repeat_anchors,
            "known_sleep_time": known_sleep_time,
            "preferred_language": preferred_language,
            "persona_prompt": persona_prompt,
            "persona_filename": active_care_persona_filename,
            "persona_name": active_care_persona_name,
            "tone_reference_text": tone_reference_text,
            "last_sent_ts": last_sent_ts,
            "sleep_session_active": sleep_info["sleep_session_active"],
            "sleep_confirmed_by_silence": sleep_confirmed_by_silence,
            "is_first_probe": is_first_probe,
            "tomorrow_tone_text": tomorrow_tone_text,
            "tod": tod,
            "now_dt": now_dt,
        }

    # ==================== 睡眠状态解析 ====================

    def parse_sleep_state(self, proactive_state: Dict) -> Dict[str, Any]:
        """解析睡眠状态"""
        from core.services.active_care.state.sleep_state import SleepStateManager
        last_goodnight_ts = safe_timestamp(proactive_state.get(StateKeys.LAST_GOODNIGHT_TS))
        last_goodmorning_ts = safe_timestamp(proactive_state.get(StateKeys.LAST_GOODMORNING_TS))
        last_goodnight_probe_ts = safe_timestamp(proactive_state.get(StateKeys.LAST_GOODNIGHT_PROBE_TS))

        sleep_session_active = SleepStateManager.is_sleep_session_active_from_state(
            last_goodnight_ts, last_goodmorning_ts
        )

        return {
            "last_goodnight_ts": last_goodnight_ts,
            "last_goodmorning_ts": last_goodmorning_ts,
            "last_goodnight_probe_ts": last_goodnight_probe_ts,
            "sleep_session_active": sleep_session_active,
        }

    def build_sleep_context_text(self, proactive_state: Dict) -> str:
        """构建睡眠上下文文本"""
        role_sleep_context = ""
        try:
            from core.services.active_care.prompt.prompt_context_builders import (
                build_role_sleep_context_text,
            )

            role_sleep_context = build_role_sleep_context_text(
                persona_name=self._executor.persona_name,
                persona_filename=self._executor.persona_filename,
            )
        except Exception:
            role_sleep_context = ""

        try:
            sleep_duration_seconds = int(
                float(proactive_state.get(StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS) or 0.0)
            )
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("解析睡眠时长(seconds)失败", exc_info=True)
            sleep_duration_seconds = 0

        if sleep_duration_seconds <= 0:
            try:
                start_ts = float(proactive_state.get(StateKeys.LAST_SLEEP_SESSION_START_TS) or 0.0)
                end_ts = float(proactive_state.get(StateKeys.LAST_SLEEP_SESSION_END_TS) or 0.0)
                if start_ts > 0 and end_ts > start_ts:
                    sleep_duration_seconds = int(end_ts - start_ts)
            except Exception:
                if is_debug_enabled("active_care_executor"):
                    logger.info("解析睡眠时长(start/end_ts)失败", exc_info=True)
                sleep_duration_seconds = 0

        sleep_source = str(
            proactive_state.get(StateKeys.LAST_SLEEP_SESSION_SOURCE) or ""
        ).strip()
        sleep_kind = str(
            proactive_state.get(StateKeys.LAST_SLEEP_SESSION_KIND) or ""
        ).strip()

        if 0 < sleep_duration_seconds <= (16 * 3600):
            from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import SLEEP_DURATION_CONTEXT_TEMPLATE
            span = format_duration_human(sleep_duration_seconds)
            user_sleep_context = SLEEP_DURATION_CONTEXT_TEMPLATE.format(
                span=span, sleep_duration_seconds=sleep_duration_seconds,
            )
            if sleep_source == "samsung_health":
                kind_label = "午睡/小憩" if sleep_kind == "nap" else "主睡眠"
                user_sleep_context += (
                    f"\n以上是 Samsung Health 实测的最近一次{kind_label}，"
                    "不要用聊天关键词改写其开始或结束时间。"
                )
            if role_sleep_context:
                return user_sleep_context + "\n" + role_sleep_context
            return user_sleep_context
        return role_sleep_context

    def build_mode_status_text(self, proactive_state: Dict, sleep_info: Dict) -> str:
        sleep_session_active = sleep_info["sleep_session_active"]
        last_goodnight_ts = sleep_info.get("last_goodnight_ts", 0.0)
        quiet_mode_active = last_goodnight_ts > 0 and not sleep_session_active
        reduced_mode_active = bool(proactive_state.get(StateKeys.REDUCED_MODE_ACTIVE))
        reduced_mode_reason = str(proactive_state.get(StateKeys.REDUCED_MODE_REASON) or "none")

        sleep_status = build_sleep_status_description(
            sleep_session_active=sleep_session_active,
            quiet_mode_active=quiet_mode_active,
            reduced_mode_active=reduced_mode_active,
            reduced_mode_reason=reduced_mode_reason,
        )

        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import MODE_STATUS_CONTEXT_TEMPLATE
        return MODE_STATUS_CONTEXT_TEMPLATE.format(
            sleep_status=sleep_status,
            sleep_session_active=str(bool(sleep_session_active)).lower(),
            reduced_mode_reason=str(proactive_state.get(StateKeys.REDUCED_MODE_REASON) or 'none'),
        )

    def build_goodnight_but_awake_context(self, proactive_state: Dict, now: float) -> str:
        """构建晚安但清醒的上下文"""
        try:
            goodnight_but_awake_ts = float(proactive_state.get(StateKeys.GOODNIGHT_BUT_AWAKE_TS) or 0.0)
            goodnight_but_awake_elapsed = int(proactive_state.get(StateKeys.GOODNIGHT_BUT_AWAKE_ELAPSED) or 0)
            if goodnight_but_awake_ts > 0 and (now - goodnight_but_awake_ts) < 1800:
                from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import GOODNIGHT_BUT_AWAKE_CONTEXT_TEMPLATE
                elapsed_text = format_duration_human(goodnight_but_awake_elapsed)
                return GOODNIGHT_BUT_AWAKE_CONTEXT_TEMPLATE.format(elapsed_text=elapsed_text)
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("构建晚安但清醒上下文失败", exc_info=True)
            pass
        return ""

    # ==================== Prompt 构建 ====================

    def build_prompt(
        self,
        context: Dict[str, Any],
        sys_prompt_type: str,
        user_input_mock: str,
        reminder_msg: Optional[str],
        thought: Optional[str],
        device_context: Optional[Dict[str, Any]],
        client_type: Optional[str],
        specific_instruction: Optional[str],
    ) -> Tuple[Any, str]:
        """构建提示，返回 (prompt_result, model_user_input)"""
        executor = self._executor
        user_display_name = str(executor.settings.user.display_name or "").strip() or "用户"

        if sys_prompt_type == "usage_limit_exceeded":
            # 硬事件不能被普通续聊输入改写为“接着旧话题聊”。
            model_user_input = str(user_input_mock or "").strip()
        else:
            model_user_input = executor._input_builder.build_model_user_input_for_active_care(
                user_input_mock=user_input_mock,
                last_user_message=context["last_user_message"],
                last_assistant_message=context["last_assistant_message"],
                last_proactive_assistant_message=context["last_proactive_assistant_message"],
                elapsed_seconds=context["user_elapsed_seconds"],
                preferred_language=context["preferred_language"],
                sleep_session_active=context.get("sleep_session_active", False),
                is_first_probe=context.get("is_first_probe", False),
                last_assistant_after_user=context.get("last_assistant_after_user", False),
            )

        sys_prompt_type_override = sys_prompt_type
        if "curious_question" in sys_prompt_type:
            sys_prompt_type_override += "_safe"

        # 查询当前 persona 对应角色的实时活动文本，作为"想你"消息的灵感锚点
        # 设计意图：让 LLM 在内容生成阶段知道"我现在正在做什么"，
        # 从而生成"我正在做 X，突然想到你"这种自然消息
        role_activity_text = self._resolve_role_activity_text(
            context.get("persona_filename", "")
        )

        prompt_result = build_active_care_prompt(
            user_id=context.get("target_conversation_id", ""),
            sys_prompt_type=sys_prompt_type_override,
            user_input_mock=user_input_mock,
            reminder_msg=reminder_msg,
            thought=thought,
            tod=context["tod"],
            now=time.time(),
            user_display_name=user_display_name,
            persona_prompt=context["persona_prompt"],
            tone_reference_text=str(context["tone_reference_text"] or ""),
            recent_history_text=context["recent_history_text"],
            sleep_context_text=context["sleep_context_text"],
            mode_status_text=context["mode_status_text"],
            goodnight_but_awake_context=context["goodnight_but_awake_context"],
            preferred_language=context["preferred_language"],
            device_context=device_context,
            client_type=client_type,
            elapsed_seconds=context["user_elapsed_seconds"],
            persona_filename=context["persona_filename"],
            persona_name=context["persona_name"],
            last_sent_ts=context["last_sent_ts"],
            last_user_ts=context["last_user_ts_raw"],
            last_proactive_assistant_message=context["last_proactive_assistant_message"],
            last_assistant_message=context["last_assistant_message"],
            proactive_state=context["proactive_state"],
            repeat_anchors=context["repeat_anchors"],
            tomorrow_tone=context["tomorrow_tone_text"],
            specific_instruction=specific_instruction,
            role_activity_text=role_activity_text,
        )
        # 推迟提醒的清除由调用方（trigger_message）在消息发送后执行
        # 这里只标记 flag，不直接操作存储
        return prompt_result, model_user_input

    def _resolve_role_activity_text(self, persona_filename: str) -> str:
        """根据 persona_filename 查询对应角色的实时活动描述文本

        把 character_daily engine 的"现在在做饭/看书/学习..."作为
        active care 内容生成阶段的"想你"消息灵感锚点。

        Returns:
            角色活动文本，形如 "七濑 澪现在在做饭"；
            若 engine 未启动或查询失败则返回空串（不注入 section）。
        """
        try:
            from core.services.character_daily.engine import get_character_daily_engine

            engine = get_character_daily_engine()
            if not engine or not getattr(engine, "_running", False):
                return ""

            # persona_filename 映射到 role_id（aveline / ling）
            scope = self._executor.storage.resolve_scope_from_persona_filename(
                persona_filename
            )
            role_id = scope if scope in ("aveline", "ling") else "aveline"

            return engine.get_activity_context_text(role_id)
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info(
                    "查询角色活动文本失败，跳过 role_activity_anchor 注入",
                    exc_info=True,
                )
            return ""
