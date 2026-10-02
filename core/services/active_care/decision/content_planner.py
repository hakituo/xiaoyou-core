"""主动关怀内容生成模块

从 decision.py 拆分而来，职责：根据已选动作生成主动消息内容。

对外暴露 ContentPlanner 类，供 ActiveCareDecision 门面委托调用。
内部按职责拆分 helper：
- _resolve_priority_focus    ：daily_push_priority 排序结果合并进 priority_focus
- _build_specific_instruction：构建行为指引（画像/任务/模式/时段约束）
- _build_sleep_metrics       ：解析睡眠相关指标（时长/状态/深夜活动）
- _build_dynamic_constraints ：睡眠保护 + 角色日常活动动态约束
- _build_llm_ctx             ：组装传给决策模型的上下文 JSON 与身份摘要
- _invoke_decision_llm       ：LLM 调用 + 空响应重试 + 解析（含工具调用）
"""

import json
import time
from typing import Any, Dict, List, Tuple

from config.integrated_config import get_settings
from core.llm import get_llm_module
from core.services.active_care.decision.decision_output_parser import (
    _parse_decision_output,
)
from core.services.active_care.decision.decision_instruction_builder import (
    _build_specific_instruction,
)
from core.services.active_care.prompt.decision_prompt_builder import (
    build_active_care_decision_prompt,
)
from core.services.active_care.storage.storage import ActiveCareStorage
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_logger
from core.utils.timestamp_utils import safe_timestamp

logger = get_logger("ACTIVE_CARE_DECISION")

# 睡眠保护：LLM 在睡眠期间可能返回过小的 next_check_seconds，
# 该值是其硬下限，减少睡眠期间的消息数
_SLEEP_NEXT_CHECK_FLOOR = 3600


class ContentPlanner:
    """主动消息内容规划器

    通过整体注入 storage 保持与 ActiveCareDecision 一致的构造方式；
    settings 懒加载避免导入期副作用。
    """

    def __init__(self, storage: ActiveCareStorage):
        self.storage = storage
        self.settings = get_settings()

    # ==================== 主流程 ====================

    async def decide(
        self,
        context: Dict[str, Any],
        chosen_action: str,
        device_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """基于所选动作生成主动内容"""
        llm = get_llm_module()

        bio = context.get("bio_state", {})
        urgent_needs = bio.get("urgent_needs", [])

        from core.services.active_care.shared.text_utils import (
            format_elapsed_human,
        )

        priority_focus = self._resolve_priority_focus(context)

        specific_instruction = self._build_specific_instruction(
            chosen_action, urgent_needs, priority_focus, context,
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

        now_iso = str(context.get("now") or "")
        now_hour = -1
        try:
            now_hour = int(now_iso[11:13])
        except Exception:
            now_hour = -1

        sleep_metrics = self._build_sleep_metrics(context, now_hour)

        user_display_name = str(context.get("user_display_name") or "用户").strip() or "用户"

        llm_ctx, persona_summary = self._build_llm_ctx(
            context=context,
            chosen_action=chosen_action,
            device_context=device_context,
            priority_focus=priority_focus,
            time_since_last_interaction=time_since_last_interaction,
            elapsed_seconds=elapsed_seconds,
            time_since_last_proactive_send=time_since_last_proactive_send,
            elapsed_since_last_proactive_seconds=elapsed_since_last_proactive_seconds,
            sleep_metrics=sleep_metrics,
            user_display_name=user_display_name,
        )

        # ── 决策 prompt 组装（2026-09-04 已解耦到 prompt/decision_prompt_builder）──
        # content_planner 只负责准备"决策输入数据"，文本组装一律在 prompt/ 目录完成。
        dynamic_constraints = self._build_dynamic_constraints(
            context, sleep_metrics, now_hour, elapsed_seconds,
        )

        ranked_items = (priority_focus.get("daily_push_ranked") or []) if isinstance(priority_focus, dict) else []
        daily_push_priority = context.get("daily_push_priority") or {}
        daily_push_text = ""
        if ranked_items:
            top_item = ranked_items[0] if isinstance(ranked_items[0], dict) else {}
            daily_push_text = (
                f"【今日推送优先级】摘要: {daily_push_priority.get('summary') or ''}"
                f"\n最高优先: {top_item.get('title') or ''} (intent={top_item.get('suggested_intent') or ''}, "
                f"reason={top_item.get('reason') or ''})"
            )

        bundle = build_active_care_decision_prompt(
            chosen_action=chosen_action,
            persona_summary=persona_summary,
            llm_ctx=llm_ctx,
            dynamic_constraints=dynamic_constraints,
            specific_instruction=specific_instruction,
            daily_push_text=daily_push_text,
        )
        messages = bundle.messages

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
            result = await self._invoke_decision_llm(
                messages=messages,
                model_path=model_path,
                temperature=decision_temperature,
                user_id=user_id,
                llm_ctx=llm_ctx,
                context=context,
                chosen_action=chosen_action,
            )
            result["specific_instruction"] = specific_instruction
            # intent 强制回填上游已选动作（决策模型不允许改写 intent）
            result["intent"] = str(result.get("intent") or chosen_action or "").strip() or chosen_action
            # 睡眠/低打扰期间的 defer 间隔硬下限（秒）：LLM 可能返回过小的
            # retry_after_seconds，导致睡眠期间频繁触发决策流程。
            if sleep_metrics["sleep_session_active"] or sleep_metrics["reduced_mode_active"]:
                retry_sec = int(result.get("retry_after_seconds") or 0)
                if retry_sec and retry_sec < _SLEEP_NEXT_CHECK_FLOOR:
                    logger.info(
                        "Active Care: 睡眠期间 retry_after_seconds 硬下限保护: %d -> %d",
                        retry_sec,
                        _SLEEP_NEXT_CHECK_FLOOR,
                    )
                    result["retry_after_seconds"] = _SLEEP_NEXT_CHECK_FLOOR
                    result["next_check_seconds"] = _SLEEP_NEXT_CHECK_FLOOR
            return result

        except Exception as e:
            logger.error(f"Content generation failed: {e}")
            return {
                "action": "defer_active_care",
                "intent": chosen_action,
                "reason_code": f"Error: {e}",
                "retry_after_seconds": 1800,
                "should_send": False,
                "next_check_seconds": 1800,
                "specific_instruction": specific_instruction,
            }

    # ==================== 子流程 ====================

    def _resolve_priority_focus(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """把 daily_push_priority 的 ranked 结果合并进 priority_focus"""
        priority_focus = dict(context.get("priority_focus") or {})
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
            priority_focus["portrait_priority"] = filtered_portrait
            priority_focus["daily_push_ranked"] = ranked_items
        return priority_focus

    def _build_specific_instruction(
        self,
        chosen_action: str,
        urgent_needs: List[str],
        priority_focus: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """构建行为指引文本（动作话术 + 画像/任务/模式/时段约束）"""
        from core.services.active_care.shared.prompt_helpers import (
            format_bio_complaint_prompt,
            get_action_prompt,
        )

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

        return _build_specific_instruction(
            specific_instruction, portrait_priority, task_probe, focus_stage,
            quiet_mode_active, reduced_mode_active, reduced_mode_reason,
            active_care_mode, elapsed_seconds, now_hour, context,
        )

    def _build_sleep_metrics(
        self,
        context: Dict[str, Any],
        now_hour: int,
    ) -> Dict[str, Any]:
        """解析睡眠相关指标，返回统一 dict 供后续使用"""
        from core.services.active_care.shared.prompt_helpers import (
            build_sleep_status_description,
        )
        from core.services.active_care.shared.text_utils import (
            format_duration_human,
        )

        quiet_mode_active = bool(context.get("quiet_mode_active", False))
        active_care_mode = str(context.get("active_care_mode") or "daily")
        reduced_mode_active = bool(context.get("reduced_mode_active", False))
        reduced_mode_reason = str(context.get("reduced_mode_reason") or "none")

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

        return {
            "quiet_mode_active": quiet_mode_active,
            "active_care_mode": active_care_mode,
            "reduced_mode_active": reduced_mode_active,
            "reduced_mode_reason": reduced_mode_reason,
            "sleep_session": sleep_session,
            "sleep_duration_text": sleep_duration_text,
            "sleep_session_active": sleep_session_active,
            "sleep_status_desc": sleep_status_desc,
            "has_late_night": has_late_night,
            "hours_since_late_night": hours_since_late_night,
            "latest_late_night_hour": latest_late_night_hour,
        }

    def _build_dynamic_constraints(
        self,
        context: Dict[str, Any],
        sleep_metrics: Dict[str, Any],
        now_hour: int,
        elapsed_seconds: int,
    ) -> List[str]:
        """构建动态约束：睡眠保护 + 角色日常活动话题源"""
        dynamic_constraints: List[str] = []

        sleep_session_active = sleep_metrics["sleep_session_active"]
        reduced_mode_active = sleep_metrics["reduced_mode_active"]
        reduced_mode_reason = sleep_metrics["reduced_mode_reason"]

        # 【P1 睡眠状态】只要系统判定用户在睡觉，无条件注入睡眠提示
        # 覆盖 goodnight / sleep_hint 两种模式，不依赖 elapsed 阈值
        # 注：probable_sleep（基于长时间无响应推断入睡）已于 2026-07-30 移除
        if sleep_session_active:
            dynamic_constraints.append(
                "【P1：用户在睡觉】sleep_session_active=true，用户已说晚安或被判定入睡。"
                "action 应为 defer_active_care；若确实需要轻量探针（probe_policy.allow_send=true），"
                "retry_after_seconds 至少 3600。禁止催促起床、禁止追问'醒了没'。"
            )
        elif reduced_mode_active and reduced_mode_reason in ("sleep_hint", "goodnight"):
            reason_text = {
                "sleep_hint": "用户暗示已入睡（如'不回就是睡了'）",
                "goodnight": "用户说了晚安，进入静默时段",
            }.get(reduced_mode_reason, "用户在低打扰模式")
            dynamic_constraints.append(
                f"【P1：用户在睡觉】{reason_text}。"
                "action 应为 defer_active_care；若确实需要轻量探针（probe_policy.allow_send=true），"
                "retry_after_seconds 至少 3600。禁止催促起床、禁止追问'醒了没'。"
            )

        # 添加基于时间间隔的睡眠状态推断
        if elapsed_seconds > 10800 and 0 <= now_hour < 11:
            hours_no_response = elapsed_seconds // 3600
            if reduced_mode_active and reduced_mode_reason == "sleep_hint":
                dynamic_constraints.append(
                    f"【长时间无响应（sleep_hint）】用户已{hours_no_response}小时无响应，当前早上{now_hour}点。"
                    f"用户之前暗示已入睡，若发送只能是轻量问候，"
                    f"禁止催促起床或询问'醒了没'，除非用户主动发消息。"
                )
            else:
                dynamic_constraints.append(
                    f"【长时间无响应】用户已{hours_no_response}小时无响应，当前早上{now_hour}点。"
                    f"如果用户之前说了晚安/睡了，推断用户还在睡觉，若发送只能是轻量问候，"
                    f"禁止催促起床或询问'醒了没'，除非用户主动发消息。"
                    f"如果不确定用户状态，defer 并设 retry_after_seconds 至少 3600。"
                )
        elif elapsed_seconds > 7200 and 0 <= now_hour < 6:
            if reduced_mode_active and reduced_mode_reason == "sleep_hint":
                dynamic_constraints.append(
                    f"【凌晨长时间无响应（sleep_hint）】用户已{elapsed_seconds // 3600}小时无响应，当前凌晨{now_hour}点。"
                    f"用户之前暗示已入睡，若发送只能是极轻的探针消息（如梦话、轻声自语）。"
                )
            else:
                dynamic_constraints.append(
                    f"【凌晨长时间无响应】用户已{elapsed_seconds // 3600}小时无响应，当前凌晨{now_hour}点。"
                    f"如果用户之前说了晚安/睡了，若发送只能是极轻的探针消息（如梦话、轻声自语），"
                    f"否则用户极可能已入睡，应 defer 并设 retry_after_seconds 至少 3600。"
                )
        elif reduced_mode_active and reduced_mode_reason == "sleep_hint" and elapsed_seconds > 3600:
            hours_no_response = elapsed_seconds // 3600
            dynamic_constraints.append(
                f"【用户暗示已入睡】用户之前明确表示'不回就是睡了'，已{hours_no_response}小时无响应。"
                f"系统已推断用户可能已入睡，只允许发极轻的探针消息或 defer。"
                f"禁止催促或反复追问，应优先 defer。"
            )

        if sleep_metrics["sleep_duration_text"]:
            dynamic_constraints.append(
                f"已知最近睡眠时长线索: {sleep_metrics['sleep_duration_text']}。若不确定，不要猜具体时间点。"
            )

        # 【角色日常活动】注入角色当前活动状态，作为"想你"消息的话题源
        # 设计意图：角色在做任何非睡眠的事时，都可能"突然想到用户"而发消息
        # 所以这里不再用"忙就拦截"，而是把活动当作正向话题锚点
        character_daily = context.get("character_daily") or {}
        if character_daily:
            role_states = [
                value for value in character_daily.values() if isinstance(value, dict)
            ]
            activity_parts = [
                str(item.get("activity_facts") or item.get("activity_text") or "").strip()
                for item in role_states
            ]
            activity_parts = [text for text in activity_parts if text]
            if activity_parts:
                activity_desc = "\n".join(activity_parts)
                sleeping = [
                    str(item.get("activity") or "").lower() in {"sleeping", "napping"}
                    for item in role_states
                ]
                if sleeping and all(sleeping):
                    activity_desc += "\n当前角色正在睡觉，应 defer。"
                else:
                    activity_desc += (
                        "\n只有存在有依据、值得分享的新内容时才 send，没有新内容就 defer。"
                        "可从已确定的活动中挑一个细节自然说起，不要逐项复述日程。"
                        "禁止『报备自己在做什么 → 想到他 → 反问他在做什么』三段式；"
                        "若当前活动本身就是值得分享的新内容，可以直接说。"
                        "不得补造这里没有的地点、同行者或已发生事件。"
                    )
                dynamic_constraints.append(f"【角色日常】{activity_desc}")

        return dynamic_constraints

    def _build_llm_ctx(
        self,
        *,
        context: Dict[str, Any],
        chosen_action: str,
        device_context: Dict[str, Any],
        priority_focus: Dict[str, Any],
        time_since_last_interaction: str,
        elapsed_seconds: int,
        time_since_last_proactive_send: str,
        elapsed_since_last_proactive_seconds: int,
        sleep_metrics: Dict[str, Any],
        user_display_name: str,
    ) -> Tuple[Dict[str, Any], str]:
        """组装决策上下文 JSON 与 persona 摘要"""
        llm_ctx = {
            "now": context.get("now"),
            "tod": context.get("tod"),
            "chosen_action": chosen_action,
            "time_since_last_interaction": time_since_last_interaction,
            "elapsed_seconds": elapsed_seconds,
            "time_since_last_proactive_send": time_since_last_proactive_send,
            "elapsed_since_last_proactive_seconds": elapsed_since_last_proactive_seconds,
            "quiet_mode_active": sleep_metrics["quiet_mode_active"],
            "active_care_mode": sleep_metrics["active_care_mode"],
            "reduced_mode_active": sleep_metrics["reduced_mode_active"],
            "reduced_mode_reason": sleep_metrics["reduced_mode_reason"],
            "sleep_session": sleep_metrics["sleep_session"],
            "sleep_status_desc": sleep_metrics["sleep_status_desc"],
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
        full_persona_prompt = str(context.get("persona_prompt") or "").strip()
        if full_persona_prompt:
            # 截取前500字符作为身份摘要（原来只有200，会丢失重要身份信息）
            persona_summary = full_persona_prompt[:500]
            if len(full_persona_prompt) > 500:
                persona_summary += "..."
        return llm_ctx, persona_summary

    async def _invoke_decision_llm(
        self,
        *,
        messages: List[Dict[str, str]],
        model_path: str,
        temperature: float,
        user_id: str,
        llm_ctx: Dict[str, Any],
        context: Dict[str, Any],
        chosen_action: str,
    ) -> Dict[str, Any]:
        """调用决策 LLM（含终止型工具出口），空响应时重试并兜底

        决策出口升级为 send_active_care / defer_active_care 二选一：
        - 模型命中终止型工具（function calling）→ 直接转成决策字典；
        - 模型走 JSON（不支持工具调用）→ 由 _parse_decision_output 解析；
        - 空响应/超时 → 默认 defer（宁可不发，也不错发）。
        """
        from core.services.active_care.decision.decision_tools import (
            chat_with_decision_tools,
        )

        tool_result = await chat_with_decision_tools(
            messages,
            model_path=model_path,
            temperature=temperature,
            max_new_tokens=600,
            user_id=user_id,
            max_tool_rounds=1,
        )

        # 终止型出口命中（send_active_care / defer_active_care）
        if tool_result.action is not None:
            from core.services.active_care.decision.action_protocol import (
                decision_action_to_dict,
            )

            action_dict = decision_action_to_dict(tool_result.action)
            action_dict["intent"] = chosen_action
            action_dict["specific_instruction"] = ""
            return action_dict

        raw = tool_result.raw_text

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
            # 模板含 JSON 字面量 `{`/`}`，禁止 .format()；intent 槽位用 replace 填充
            retry_system = DECISION_SYSTEM_PROMPT_TEMPLATE.replace(
                "{chosen_action}", chosen_action
            )
            retry_messages = [
                {
                    "role": "system",
                    "content": retry_system,
                },
                {"role": "user", "content": json.dumps(llm_ctx, ensure_ascii=False)},
            ]
            retry_raw = await get_llm_module().chat(
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
            # LLM 连续空响应 → 一律 defer（宁可不发，也不错发）。
            # 旧逻辑在 conversation_incomplete 时强制补发一条"保守消息"，
            # 与"不值得发就明确 defer"的原则冲突，已移除。
            logger.warning("Active Care: LLM empty response (retry also empty). Default to defer.")
            return {
                "action": "defer_active_care",
                "intent": chosen_action,
                "reason_code": "LLM 空响应（重试仍空），默认 defer",
                "retry_after_seconds": 900,
                "should_send": False,
                "next_check_seconds": 900,
                "specific_instruction": "",
            }
        return _parse_decision_output(raw, chosen_action)
