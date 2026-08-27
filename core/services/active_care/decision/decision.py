import random
import asyncio
import json
import re
import time
from typing import Any, Dict, List
from core.utils.logger import get_logger
from config.debug_config import is_debug_enabled
from core.utils.timestamp_utils import safe_timestamp
from config.integrated_config import get_settings
from core.utils.config_accessor import get_active_care_config
from core.llm import get_llm_module
from core.services.active_care.storage.storage import ActiveCareStorage
from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine
from core.services.active_care.decision.decision_output_parser import (
    _build_output_format_schema,
    _parse_decision_output,
    _parse_peer_chat_output,
)
from core.services.active_care.decision.decision_instruction_builder import (
    _build_specific_instruction,
)
from core.services.active_care.shared.constants import DEFAULT_BANDIT_EPSILON

logger = get_logger("ACTIVE_CARE_DECISION")

_UNINITIALIZED_SENTINEL = object()
_cached_scheduler_engine = _UNINITIALIZED_SENTINEL


def _get_scheduler_engine():
    global _cached_scheduler_engine
    if _cached_scheduler_engine is _UNINITIALIZED_SENTINEL:
        try:
            _cached_scheduler_engine = CPPSchedulerEngine()
        except Exception:
            _cached_scheduler_engine = None
    return _cached_scheduler_engine if _cached_scheduler_engine is not None else None


class ActiveCareDecision:
    def __init__(self, storage: ActiveCareStorage):
        self.settings = get_settings()
        self.storage = storage

    async def select_action_bandit(
        self, ctx: Dict[str, Any], actions: List[str]
    ) -> str:
        """
        Contextual Bandit for Action Selection.
        """
        # 0. 强制动作检查（长时间沉默打破器）
        elapsed = ctx.get("elapsed_seconds", 0)
        silence_threshold = int(
            get_active_care_config("active_care_silence_breaker_seconds", default=2700, settings=self.settings)
            or 2700
        )
        quiet_mode_active = bool(ctx.get("quiet_mode_active", False))

        if (
            not quiet_mode_active
            and elapsed > silence_threshold
            and "do_nothing" in actions
        ):
            logger.info(
                f"Active Care: Long silence detected ({elapsed}s > {silence_threshold}s). Forcing proactive action (removing do_nothing)."
            )
            actions = [a for a in actions if a != "do_nothing"]
            if not actions:
                actions = ["share_thought"]

        epsilon = get_active_care_config(
            "active_care_epsilon",
            default=DEFAULT_BANDIT_EPSILON,
            settings=self.settings,
        )
        scores = await self.storage.load_policy_scores()

        # 1. 探索（随机选择）
        if random.random() < epsilon:
            chosen = random.choice(actions)
            if is_debug_enabled("active_care_decision"):
                logger.info(f"Active Care: Bandit Exploration (Random) -> {chosen}")
            return chosen

        # 2. 启发式/基于规则的覆盖（JITAI）
        bio = ctx.get("bio_state", {})
        urgent_needs = ctx.get("urgent_needs", [])
        if urgent_needs:
            if is_debug_enabled("active_care_decision"):
                logger.info("Active Care: JITAI Heuristic -> bio_complaint (urgent)")
            return "bio_complaint"

        # 硬件启发式
        cpu_temp = float(bio.get("cpu_temp", 0))
        if cpu_temp > 80:  # 极度过热
            if is_debug_enabled("active_care_decision"):
                logger.info(
                    f"Active Care: JITAI Heuristic -> bio_complaint (CPU {cpu_temp}°C)"
                )
            return "bio_complaint"

        # 3. LLM驱动的利用（推理）
        # 不是直接选择最高分，而是让LLM在表现最好的候选中选择
        top_actions = sorted(
            actions,
            key=lambda a: scores.get(a, {}).get("avg_reward", 0.0),
            reverse=True,
        )[:3]

        try:
            llm = get_llm_module()

            # 优化：资源检查
            scheduler_busy = False
            try:
                scheduler = _get_scheduler_engine()
                if scheduler and scheduler.enabled and scheduler.is_busy():
                    scheduler_busy = True
            except Exception:
                pass

            if scheduler_busy:
                if is_debug_enabled("active_care_decision"):
                    logger.info("Active Care: Scheduler busy, skipping LLM decision")
                # 立即回退到基于评分的选择
                best_action = max(
                    actions, key=lambda a: scores.get(a, {}).get("avg_reward", 0.0)
                )
                return best_action

            from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import DECISION_REASONING_PROMPT_TEMPLATE
            reasoning_prompt = DECISION_REASONING_PROMPT_TEMPLATE.format(
                now=ctx.get('now'),
                user_state=json.dumps(ctx.get('user_bio_state'), ensure_ascii=False),
                candidates=', '.join(top_actions),
            )

            # 动态模型路由
            from config.model_config import resolve_active_care_model_path
            model_path = resolve_active_care_model_path(
                model_type="decision",
                settings=self.settings,
                llm_module=llm,
            )

            recommended = await asyncio.wait_for(
                llm.chat(
                    [{"role": "system", "content": reasoning_prompt}],
                    max_new_tokens=10,
                    temperature=0.1,
                    model_path=model_path,
                ),
                timeout=8.0,
            )

            if isinstance(recommended, dict):
                if recommended.get("status") == "success":
                    recommended = str(recommended.get("response") or "")
                else:
                    recommended = ""
            else:
                recommended = str(recommended or "")

            recommended = recommended.strip().lower()
            recommended = re.sub(r"[^\w\s]", "", recommended)

            for a in actions:
                if a in recommended:
                    if is_debug_enabled("active_care_decision"):
                        logger.info(f"Active Care: LLM Recommended Action -> {a}")
                    return a
        except asyncio.TimeoutError:
            logger.warning(
                "Active Care: LLM decision timed out, falling back to scores"
            )
        except Exception as e:
            if is_debug_enabled("active_care_decision"):
                logger.info(
                    f"Active Care: LLM reasoning skipped/failed ({e}), falling back to scores"
                )

        # 4. 回退：基于评分的利用
        best_action = max(
            actions, key=lambda a: scores.get(a, {}).get("avg_reward", 0.0)
        )
        if is_debug_enabled("active_care_decision"):
            logger.info(f"Active Care: Score-based Exploitation -> {best_action}")

        return best_action

    async def decide_proactive_content(
        self,
        context: Dict[str, Any],
        chosen_action: str,
        device_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate proactive content based on selected action.
        """
        llm = get_llm_module()

        bio = context.get("bio_state", {})
        urgent_needs = bio.get("urgent_needs", [])

        from core.services.active_care.shared.constants import (
            get_action_prompt, format_bio_complaint_prompt,
            format_duration_human, format_elapsed_human,
            build_sleep_status_description,
        )
        priority_focus = context.get("priority_focus") or {}
        if chosen_action == "bio_complaint":
            specific_instruction = format_bio_complaint_prompt(urgent_needs)
        elif chosen_action == "share_peer_chat":
            specific_instruction = get_action_prompt("share_peer_chat")
            peer_topics = priority_focus.get("recent_peer_chat_topics") or []
            if peer_topics:
                specific_instruction += f"\n今天和室友聊到的话题：{'、'.join(peer_topics[:3])}。从中选一个有趣的分享给主人。"
        else:
            specific_instruction = get_action_prompt(chosen_action)
        portrait_priority = priority_focus.get("portrait_priority") or []
        task_probe = priority_focus.get("task_probe") or {}
        focus_stage = str(priority_focus.get("stage") or "")
        quiet_mode_active = bool(context.get("quiet_mode_active", False))
        active_care_mode = str(context.get("active_care_mode") or "daily")
        reduced_mode_active = bool(context.get("reduced_mode_active", False))
        reduced_mode_reason = str(context.get("reduced_mode_reason") or "none")
        elapsed_seconds = context.get("elapsed_seconds", 0)
        now_iso = str(context.get("now") or "")
        now_hour = -1
        try:
            now_hour = int(now_iso[11:13])
        except Exception:
            now_hour = -1

        specific_instruction = _build_specific_instruction(
            specific_instruction, portrait_priority, task_probe, focus_stage,
            quiet_mode_active, reduced_mode_active, reduced_mode_reason,
            active_care_mode, elapsed_seconds, now_hour, context,
        )

        elapsed_seconds_raw = int(context.get("elapsed_seconds", 0) or 0)
        elapsed_seconds = max(0, min(elapsed_seconds_raw, 7 * 24 * 3600))
        time_since_last_interaction = format_elapsed_human(elapsed_seconds)

        last_proactive_sent_ts = 0.0
        try:
            last_proactive_sent_ts = safe_timestamp(context.get("last_proactive_sent_ts"))
        except Exception:
            last_proactive_sent_ts = 0.0
        decision_now_ts = safe_timestamp(context.get("now_ts")) or time.time()
        elapsed_since_last_proactive_seconds = (
            int(max(0.0, decision_now_ts - last_proactive_sent_ts))
            if last_proactive_sent_ts > 0
            else 0
        )
        time_since_last_proactive_send = (
            format_elapsed_human(elapsed_since_last_proactive_seconds)
            if elapsed_since_last_proactive_seconds > 0 else "未知"
        )

        sleep_session = context.get("sleep_session") or {}
        sleep_duration_seconds = max(0, min(
            int(sleep_session.get("last_sleep_session_duration_seconds") or 0),
            16 * 3600,
        ))
        sleep_duration_text = format_duration_human(sleep_duration_seconds) if sleep_duration_seconds > 0 else ""

        sleep_session_active = bool(sleep_session.get("active", False))
        late_night_info = sleep_session.get("inferred_late_night_activity") or {}
        has_late_night = bool(late_night_info.get("has_late_night_activity", False))
        hours_since_late_night = int(late_night_info.get("hours_since_late_night", -1))
        latest_late_night_hour = int(late_night_info.get("latest_late_night_hour", -1))

        sleep_status_desc = build_sleep_status_description(
            sleep_session_active=sleep_session_active,
            quiet_mode_active=quiet_mode_active,
            reduced_mode_active=reduced_mode_active,
            reduced_mode_reason=reduced_mode_reason,
            has_late_night_activity=has_late_night,
            hours_since_late_night=hours_since_late_night,
            latest_late_night_hour=latest_late_night_hour,
            now_hour=now_hour,
        )

        full_persona_prompt = str(context.get("persona_prompt") or "").strip()
        user_display_name = str(context.get("user_display_name") or "用户").strip() or "用户"
        # 使用 daily_push_priority 的 ranked 结果替代原始 portrait_priority
        daily_push_priority = context.get("daily_push_priority") or {}
        ranked_items = daily_push_priority.get("ranked") or []
        if ranked_items and isinstance(ranked_items, list):
            # 从 ranked 中提取真正需要关注的画像项（已过滤已覆盖话题）
            covered_topics = set((priority_focus.get("covered_topics") or []))
            filtered_portrait = [
                p for p in (priority_focus.get("portrait_priority") or [])
                if p not in covered_topics
            ]
            priority_focus = dict(priority_focus)
            priority_focus["portrait_priority"] = filtered_portrait
            priority_focus["daily_push_ranked"] = ranked_items

        llm_ctx = {
            "now": context.get("now"),
            "tod": context.get("tod"),
            "chosen_action": chosen_action,
            "time_since_last_interaction": time_since_last_interaction,
            "elapsed_seconds": elapsed_seconds,
            "time_since_last_proactive_send": time_since_last_proactive_send,
            "elapsed_since_last_proactive_seconds": elapsed_since_last_proactive_seconds,
            "quiet_mode_active": quiet_mode_active,
            "active_care_mode": active_care_mode,
            "reduced_mode_active": reduced_mode_active,
            "reduced_mode_reason": reduced_mode_reason,
            "sleep_session": sleep_session,
            "sleep_status_desc": sleep_status_desc,
            "priority_focus": priority_focus,
            "device": device_context,
            "user_bio": context.get("user_bio_state"),
            "aveline_bio": context.get("bio_state"),
            "recent_history_summary": [
                f"{m.get('role', 'unknown')}: {m.get('content', '')[:120]}"
                for m in context.get("recent_history", [])
            ][-8:],
            "daily_record_quality": context.get("daily_record_quality"),
            "user_display_name": user_display_name,
            "user_activity": context.get("user_activity"),
            "character_daily": context.get("character_daily") or {},
        }
        # 决策模型只需要短摘要，不需要完整人设（完整人设留给内容生成阶段）
        persona_summary = ""
        if full_persona_prompt:
            # 截取前500字符作为身份摘要（原来只有200，会丢失重要身份信息）
            persona_summary = full_persona_prompt[:500]
            if len(full_persona_prompt) > 500:
                persona_summary += "..."
        # 【缓存优化】静态约束 — 放在 system message 中，保持稳定前缀可命中缓存
        static_constraints = [
            f"你现在需要决定是否主动给{user_display_name}发一条消息。",
            f"intent 必须固定为 {chosen_action}。",
            "只做发送决策：should_send / next_check_seconds / thought。",
            "综合当前场景判断 should_send：角色正在做事时可以自然发起话题；"
            "但用户睡觉/深夜/明确忙碌时不要打扰。",
            "只输出 JSON，严禁输出解释、推理过程或多余的文字。",
            "必须直接输出有效的JSON对象格式，不要使用markdown包裹。",
            "时间与数字事实约束：拿不准就避免写具体时刻与精确数字。",
            "画像分数表达约束：不要输出具体分值，只能用缺失/待补充等表述。",
        ]

        # 【缓存优化】动态约束 — 放在 user message 中，不污染 system message 缓存前缀
        dynamic_constraints = []

        # 【睡眠保护 - 最高优先级】只要系统判定用户在睡觉，无条件注入睡眠提示
        # 覆盖 goodnight / sleep_hint 两种模式，不依赖 elapsed 阈值
        # 这是 sleep 保护的关键：必须在 LLM 看到"角色活动话题源"之前先看到睡眠提示
        # 注：probable_sleep（基于长时间无响应推断入睡）已于 2026-07-30 移除
        if sleep_session_active:
            dynamic_constraints.append(
                "【用户在睡觉 - 最高优先级】sleep_session_active=true，用户已说晚安或被判定入睡。"
                "should_send=false，除非是首次探针且 probe_policy.allow_send=true。"
                "next_check_seconds 至少 3600。禁止催促起床、禁止追问'醒了没'。"
            )
        elif reduced_mode_active and reduced_mode_reason in ("sleep_hint", "goodnight"):
            reason_text = {
                "sleep_hint": "用户暗示已入睡（如'不回就是睡了'）",
                "goodnight": "用户说了晚安，进入静默时段",
            }.get(reduced_mode_reason, "用户在低打扰模式")
            dynamic_constraints.append(
                f"【用户在睡觉 - 最高优先级】{reason_text}。"
                "should_send=false，除非是首次探针且 probe_policy.allow_send=true。"
                "next_check_seconds 至少 3600。禁止催促起床、禁止追问'醒了没'。"
            )

        # 添加基于时间间隔的睡眠状态推断
        if elapsed_seconds > 10800 and 0 <= now_hour < 11:
            hours_no_response = elapsed_seconds // 3600
            if reduced_mode_active and reduced_mode_reason == "sleep_hint":
                dynamic_constraints.append(
                    f"【长时间无响应（sleep_hint）】用户已{hours_no_response}小时无响应，当前早上{now_hour}点。"
                    f"用户之前暗示已入睡，可以发一条温柔的探针消息（如轻声问候），"
                    f"但禁止催促起床或询问'醒了没'，除非用户主动发消息。"
                )
            else:
                dynamic_constraints.append(
                    f"【长时间无响应】用户已{hours_no_response}小时无响应，当前早上{now_hour}点。"
                    f"如果用户之前说了晚安/睡了，推断用户还在睡觉，可以发一条温柔的探针消息（如轻声问候），"
                    f"但禁止催促起床或询问'醒了没'，除非用户主动发消息。"
                    f"如果不确定用户状态，should_send=false，next_check_seconds设为3600以上。"
                )
        elif elapsed_seconds > 7200 and 0 <= now_hour < 6:
            if reduced_mode_active and reduced_mode_reason == "sleep_hint":
                dynamic_constraints.append(
                    f"【凌晨长时间无响应（sleep_hint）】用户已{elapsed_seconds // 3600}小时无响应，当前凌晨{now_hour}点。"
                    f"用户之前暗示已入睡，可以发一条极轻的探针消息（如梦话、轻声自语）。"
                )
            else:
                dynamic_constraints.append(
                    f"【凌晨长时间无响应】用户已{elapsed_seconds // 3600}小时无响应，当前凌晨{now_hour}点。"
                    f"如果用户之前说了晚安/睡了，可以发一条极轻的探针消息（如梦话、轻声自语），"
                    f"否则用户极可能已入睡，应发送should_send=false，next_check_seconds至少3600。"
                )
        elif reduced_mode_active and reduced_mode_reason == "sleep_hint" and elapsed_seconds > 3600:
            hours_no_response = elapsed_seconds // 3600
            dynamic_constraints.append(
                f"【用户暗示已入睡】用户之前明确表示'不回就是睡了'，已{hours_no_response}小时无响应。"
                f"系统已推断用户可能已入睡，只允许发极轻的探针消息或do_nothing。"
                f"禁止催促或反复追问，should_send优先设为false。"
            )

        if sleep_duration_seconds > 0:
            dynamic_constraints.append(
                f"已知最近睡眠时长线索: {sleep_duration_text}。若不确定，不要猜具体时间点。"
            )

        # 【角色日常活动】注入角色当前活动状态，作为"想你"消息的话题源
        # 设计意图：角色在做任何非睡眠的事时，都可能"突然想到用户"而发消息
        # 所以这里不再用"忙就拦截"，而是把活动当作正向话题锚点
        character_daily = context.get("character_daily") or {}
        if character_daily:
            cd_aveline = character_daily.get("aveline", {})
            cd_ling = character_daily.get("ling", {})
            aveline_activity_text = cd_aveline.get("activity_text", "")
            ling_activity_text = cd_ling.get("activity_text", "")
            aveline_activity_val = str(cd_aveline.get("activity", "") or "").strip().lower()
            ling_activity_val = str(cd_ling.get("activity", "") or "").strip().lower()
            peer_chat_summary = character_daily.get("peer_chat_summary", "")

            # 仅 SLEEPING / NAPPING 视为"角色真的不能打扰"
            SLEEPY_ACTIVITIES = {"sleeping", "napping"}
            aveline_sleeping = aveline_activity_val in SLEEPY_ACTIVITIES
            ling_sleeping = ling_activity_val in SLEEPY_ACTIVITIES

            activity_parts = []
            if aveline_activity_text:
                activity_parts.append(aveline_activity_text)
            if ling_activity_text:
                activity_parts.append(ling_activity_text)

            if activity_parts:
                activity_desc = "，".join(activity_parts) + "。"
                if aveline_sleeping and ling_sleeping:
                    # 两角色都在睡：保持安静，由 sleep_policy 兜底
                    activity_desc += "两人都在睡觉，should_send=false。"
                elif aveline_sleeping or ling_sleeping:
                    # 一方在睡，另一方醒着：以醒着的那方为话题源
                    activity_desc += (
                        "有一个还在睡，另一个醒着——以醒着的那方视角自然发消息。"
                    )
                else:
                    # 两方都在做日常活动（学习/做饭/看书/家务等）：
                    # 这正是"突然想他了"最自然的时机，鼓励发送
                    activity_desc += (
                        "她正在做事时突然想到他，可以基于当前活动自然发起一条简短消息——"
                        "比如分享当下的感受、联想到他、或者顺口提一句自己正在做什么。"
                        "should_send=true。"
                    )
                if peer_chat_summary:
                    activity_desc += peer_chat_summary
                dynamic_constraints.append(f"【角色日常】{activity_desc}")

        # 【缓存优化】system message：persona摘要 + 静态指令 + schema（稳定不变）
        static_instruction = (
            "【Active Care 调度决策】\n"
            + "\n".join(f"- {x}" for x in static_constraints)
            + "\n\n"
            + _build_output_format_schema(chosen_action)
        )
        if persona_summary:
            system_prompt = persona_summary + "\n\n" + static_instruction
        else:
            system_prompt = static_instruction

        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import DECISION_USER_MESSAGE_TEMPLATE
        decision_user_message = DECISION_USER_MESSAGE_TEMPLATE.format(
            context_json=json.dumps(llm_ctx, ensure_ascii=False),
        )

        # 【缓存优化】动态约束追加到 user message 中，不影响 system 缓存
        if dynamic_constraints:
            decision_user_message += (
                "\n\n【当前时间/状态约束】\n"
                + "\n".join(f"- {x}" for x in dynamic_constraints)
            )

        # specific_instruction 和 daily_push_priority 也在 user message 尾部
        if specific_instruction:
            decision_user_message += f"\n\n【行为指引】\n{specific_instruction}"
        if ranked_items:
            top_item = ranked_items[0] if isinstance(ranked_items[0], dict) else {}
            decision_user_message += (
                f"\n\n【今日推送优先级】摘要: {daily_push_priority.get('summary') or ''}"
                f"\n最高优先: {top_item.get('title') or ''} (intent={top_item.get('suggested_intent') or ''}, "
                f"reason={top_item.get('reason') or ''})"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": decision_user_message},
        ]

        try:
            # Dynamic Model Routing - 使用统一模型路径解析
            from config.model_config import resolve_active_care_model_path
            model_path = resolve_active_care_model_path(
                model_type="decision",
                settings=self.settings,
                llm_module=llm,
            )

            decision_temperature = float(
                get_active_care_config("active_care_decision_temperature", default=0.45, settings=self.settings)
                or 0.45
            )

            # 【工具调用】决策模型可以主动查询记忆/状态来辅助决策
            user_id = str(context.get("primary_cid") or "")
            from core.services.active_care.decision.decision_tools import chat_with_tools
            raw, _ = await chat_with_tools(
                messages,
                model_path=model_path,
                temperature=decision_temperature,
                max_new_tokens=600,
                user_id=user_id,
                max_tool_rounds=1,
            )

            if isinstance(raw, dict):
                if raw.get("status") == "success":
                    raw = str(raw.get("response") or raw.get("text") or "")
                elif raw.get("response") or raw.get("text"):
                    raw = str(raw.get("response") or raw.get("text") or "")
                elif raw.get("error"):
                    raw = str(raw.get("error") or "")
                else:
                    raw = str(raw or "")

            logger.info(
                "Active Care LLM raw response (len=%d): %s",
                len(str(raw or "")),
                str(raw or "")[:1500],
            )
            if not raw or str(raw).strip() == "":
                logger.warning(
                    "Active Care: LLM returned empty response. Messages sent: %s",
                    json.dumps(messages, ensure_ascii=False)[:500],
                )
                from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import DECISION_SYSTEM_PROMPT_TEMPLATE
                retry_messages = [
                    {
                        "role": "system",
                        "content": DECISION_SYSTEM_PROMPT_TEMPLATE.format(chosen_action=chosen_action),
                    },
                    {"role": "user", "content": json.dumps(llm_ctx, ensure_ascii=False)},
                ]
                retry_raw = await llm.chat(
                    retry_messages,
                    temperature=0.2,
                    max_new_tokens=600,
                    model_path=model_path,
                    fallback_local=True,
                )
                if isinstance(retry_raw, dict):
                    if retry_raw.get("status") == "success":
                        retry_raw = str(retry_raw.get("response") or retry_raw.get("text") or "")
                    elif retry_raw.get("response") or retry_raw.get("text"):
                        retry_raw = str(retry_raw.get("response") or retry_raw.get("text") or "")
                    elif retry_raw.get("error"):
                        retry_raw = str(retry_raw.get("error") or "")
                    else:
                        retry_raw = ""
                logger.info(
                    "Active Care LLM retry response (len=%d): %s",
                    len(str(retry_raw or "")),
                    str(retry_raw or "")[:300],
                )
                if retry_raw and str(retry_raw).strip():
                    return _parse_decision_output(retry_raw, chosen_action)
                # 如果对话未完成且LLM返回空，强制兜底发送一次保守消息
                if context.get("conversation_incomplete"):
                    logger.warning(
                        "Active Care: LLM empty response but conversation_incomplete=True. Forcing conservative send."
                    )
                    return {
                        "thought": "LLM empty fallback: conversation incomplete, forcing conservative send",
                        "should_send": True,
                        "intent": "share_thought",
                        "next_check_seconds": 300,
                        "planned_topic": "",
                        "planned_delay_seconds": 0,
                        "reply_text": "",
                    }
                return {
                    "thought": "LLM returned empty response",
                    "should_send": False,
                    "intent": chosen_action,
                    "next_check_seconds": 600,
                    "planned_topic": "",
                    "planned_delay_seconds": 0,
                    "reply_text": "",
                }
            result = _parse_decision_output(raw, chosen_action)
            result["specific_instruction"] = specific_instruction
            # 【题材感知 MDP】确保 planned_topic 字段存在并透传给持久化链路，
            # 用于记录题材标签（_parse_decision_output 已带该字段，这里兜底）
            result["planned_topic"] = str(result.get("planned_topic") or "").strip()
            # 睡眠期间硬下限保护：LLM 可能返回过小的 next_check_seconds，
            # 导致睡眠期间频繁触发决策流程。sleep_session_active=true 时
            # 强制 next_check_seconds >= 3600（1小时），减少睡眠期间的消息数
            if sleep_session_active:
                _orig_next = int(result.get("next_check_seconds", 600) or 600)
                if _orig_next < 3600:
                    logger.info(
                        "Active Care: 睡眠期间 next_check_seconds 硬下限保护: %d -> 3600",
                        _orig_next,
                    )
                    result["next_check_seconds"] = 3600
            return result

        except Exception as e:
            logger.error(f"Content generation failed: {e}")
            return {"thought": f"Error: {e}", "should_send": False, "specific_instruction": specific_instruction}

    async def decide_peer_chat(
        self,
        context: Dict[str, Any],
        role_id: str,
        peer_name: str,
    ) -> Dict[str, Any]:
        """决策是否主动找对方角色聊天"""
        from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
            build_peer_chat_decision_prompt,
        )

        llm = get_llm_module()
        now_iso = str(context.get("now") or "")

        bio = context.get("bio_state", {})
        # 从 life 子字典获取 energy/mood
        life = bio.get("life", {}) if isinstance(bio, dict) else {}
        energy = float(life.get("energy", bio.get("energy", 50)))
        mood = str(life.get("mood", bio.get("mood", "neutral")))
        elapsed = int(context.get("elapsed_seconds", 0) or 0)

        role_name = "七濑 澪" if role_id == "aveline" else "Ling"
        recent_topics = list(context.get("recent_peer_chat_topics") or [])

        # 社交事件上下文
        social_events_hint = ""
        try:
            from core.services.dual_role.social_events import get_social_event_engine
            engine = get_social_event_engine()
            social_events_hint = engine.build_recent_events_context(
                "default",
                max_items=3,
                viewer_role_id=role_id,
            )
        except Exception:
            social_events_hint = ""

        # 【缓存优化】static/dynamic 分离：system message 跨请求稳定，命中 DeepSeek Prompt Caching
        prompt_result = build_peer_chat_decision_prompt(
            role_name=role_name,
            peer_name=peer_name,
            time_str=now_iso,
            energy=energy,
            mood=mood,
            elapsed_seconds=elapsed,
            recent_topics=recent_topics,
            social_events_hint=social_events_hint,
            bio_state=bio,
        )
        messages = [
            {"role": "system", "content": prompt_result.system_prompt},
            {"role": "user", "content": prompt_result.user_prompt},
        ]

        try:
            from config.model_config import resolve_active_care_model_path
            model_path = resolve_active_care_model_path(
                model_type="decision",
                settings=self.settings,
                llm_module=llm,
            )
            # 决策 LLM 调用加超时保护（避免卡死整个 scheduler 周期）
            try:
                from config.integrated_config import get_settings
                _decision_timeout = float(get_settings().dual_role.peer_chat_decision_timeout_seconds)
            except Exception:
                _decision_timeout = 20.0
            try:
                raw = await asyncio.wait_for(
                    llm.chat(
                        messages,
                        temperature=0.3,
                        max_new_tokens=300,
                        model_path=model_path,
                    ),
                    timeout=_decision_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Active Care: peer_chat决策LLM超时(%.0fs)，降级为不发送", _decision_timeout)
                try:
                    from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
                    get_peer_chat_metrics().incr("decision_timeout")
                except Exception:
                    pass
                return {
                    "thought": f"决策LLM超时({_decision_timeout}s)",
                    "should_send": False,
                    "intent": "peer_chat",
                    "topic": "",
                    "situation": "",
                    "opening_idea": "",
                }
            if isinstance(raw, dict):
                raw = str(raw.get("response") or raw.get("text") or "")
            # 使用 peer chat 专用 parser：一次解析提取全部字段
            # （thought/should_send/situation/opening_idea/topic），含正则兜底
            return _parse_peer_chat_output(str(raw or ""))
        except Exception as e:
            logger.warning(f"Active Care: peer_chat决策失败: {e}")
            return {
                "thought": f"决策异常: {e}",
                "should_send": False,
                "intent": "peer_chat",
                "topic": "",
                "situation": "",
                "opening_idea": "",
            }
