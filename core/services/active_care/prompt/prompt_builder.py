import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config.integrated_config import get_settings
from core.agents.chat_agent_components.persona_system.prompt import (
    get_authoritative_calendar_prompt,
    get_special_day_prompt,
    get_upcoming_birthday_prompt,
)
from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    CORE_CONSTRAINTS,
    STYLE_ENFORCEMENT_TEMPLATE,
    VOICE_GUIDE,
    CONTEXT_GUARD_LONG_SILENCE,
    CONTEXT_GUARD_CONTINUATION,
    CONTINUATION_GUARD_EN,
    CONTINUATION_GUARD_ZH,
    TASK_REMINDER_TEMPLATE,
    TASK_PLANNED_TOPIC_TEMPLATE,
    TASK_WAKE_UP_GREETING,
    TASK_MORNING_REPORT,
    TASK_NOTIFICATION_ASSISTANT,
    TASK_USAGE_LIMIT_EXCEEDED_TEMPLATE,
    TASK_INSOMNIA,
    TASK_GOODNIGHT_PROACTIVE_TEMPLATE,
    TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE,
    TASK_ACTIVITY_RETURN_PROACTIVE_TEMPLATE,
    TASK_GOOD_MORNING_PROACTIVE_TEMPLATE,
    TASK_PROACTIVE_CHAT_TEMPLATE,
    TASK_FOCUS_NUDGE_TEMPLATE,
    TASK_SUPPRESSED_CHAT_TEMPLATE,
    ROLE_ACTIVITY_ANCHOR_TEMPLATE,
    TEMPORAL_ANCHOR_TEMPLATE,
    DEDUP_CONSTRAINT_TEMPLATE,
    DEDUP_MULTI_CONSTRAINT_TEMPLATE,
    TOMORROW_TONE_TEMPLATE,
    TODAY_PLAN_TEMPLATE,
    DEFERRED_REMINDERS_TEMPLATE,
)
from core.services.active_care.shared.constants import (
    LONG_SILENCE_THRESHOLD_SECONDS,
)

# ── 从拆分模块导入 ──────────────────────────────────────────
from core.services.active_care.prompt.prompt_context_builders import (
    _build_device_context_text,
    _build_bio_context_text,
    _build_health_reminder_prompt,
    _build_food_context_text,
    _build_study_context_text,
    _build_persona_active_care_style,
    _build_today_plan_text,
    build_deferred_reminders_text,
)
from core.services.active_care.prompt.topic_diversity import (
    build_topic_diversity_constraint,
)


def _get_auto_heal_brief() -> str:
    try:
        from core.services.auto_heal.heal_service import get_auto_heal_service
        svc = get_auto_heal_service()
        brief = svc.get_morning_brief()
        if brief:
            return f"\n\n{brief}\n如果提到了bug修复，可以简单提一下，不用太详细。"
        return ""
    except Exception:
        return ""


def _build_other_persona_reminders_text(persona_filename: str) -> str:
    """构建"另一角色今日已认领的提醒"提示文本

    同步读取 ReminderAssignmentRegistry 共享文件，过滤出对方已认领的提醒列表。
    让 LLM 知道对方今天已经发过什么提醒，自然避免重复。

    读取失败或无数据时返回空字符串（不注入 section）。
    """
    import json as _json
    from core.utils.data_paths import get_dual_role_reminder_assignment_path
    from core.utils.time_utils import get_current_time

    try:
        path = get_dual_role_reminder_assignment_path()
        if not path.exists():
            return ""
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            return ""
        # 日期检查
        today = get_current_time().strftime("%Y-%m-%d")
        if str(data.get("date", "")) != today:
            return ""
        assignments = data.get("assignments") or []
        if not assignments:
            return ""

        # 解析当前 persona
        fn = str(persona_filename or "").strip().lower()
        current_persona = "ling" if "ling" in fn else "aveline"
        other_name = "Ling" if current_persona == "aveline" else "七濑 澪"

        # 过滤对方已认领的提醒
        other_items = []
        for a in assignments:
            if not isinstance(a, dict):
                continue
            if str(a.get("assigned_to", "")) != current_persona:
                title = str(a.get("title") or "").strip()
                if title:
                    other_items.append(title)

        if not other_items:
            return ""

        # 构建提示文本
        items_text = "\n".join(f"- {t}" for t in other_items[:5])  # 最多 5 条
        return (
            f"\n\n========== 另一角色今日已发提醒 ==========\n"
            f"{other_name}今天已经发过以下提醒，请避免重复相同内容：\n"
            f"{items_text}\n"
            f"你可以从不同角度补充，或选择其他话题。\n"
            f"=================================================\n"
        )
    except Exception:
        return ""


@dataclass
class PromptSection:
    name: str
    content: str

    @property
    def chars(self) -> int:
        return len(self.content or "")


@dataclass
class ActiveCarePromptBuildResult:
    prompt: str
    sections: List[PromptSection]
    dynamic_prompt: str = ""  # 【缓存优化】动态内容，放 user message 前缀
    has_deferred_reminders: bool = False  # 是否包含推迟提醒（调用方应清除）

    @property
    def static_prompt(self) -> str:
        """【缓存优化】静态内容，放 system message，稳定命中缓存"""
        return self.prompt

    @property
    def static_chars(self) -> int:
        return len(self.prompt or "")

    @property
    def dynamic_chars(self) -> int:
        return len(self.dynamic_prompt or "")

    @property
    def total_chars(self) -> int:
        return self.static_chars + self.dynamic_chars

    @property
    def non_empty_sections(self) -> int:
        return sum(1 for s in self.sections if (s.content or "").strip())

    def format_breakdown(self) -> str:
        lines = [
            f"- static_chars={self.static_chars}, dynamic_chars={self.dynamic_chars}",
            f"- non_empty_sections={self.non_empty_sections}",
        ]
        for s in self.sections:
            content = str(s.content or "").strip()
            preview = content.replace("\n", " ")[:80]
            lines.append(f"- {s.name}: chars={s.chars}, preview={preview}")
        return "\n".join(lines)


def _build_context_guard(is_long_silence: bool) -> str:
    if is_long_silence:
        return CONTEXT_GUARD_LONG_SILENCE
    return CONTEXT_GUARD_CONTINUATION


def _build_continuation_guard(language: str, recent_history_text: str, is_long_silence: bool = False) -> str:
    """构建对话衔接约束。仅在非长沉默（延续模式）且有最近对话时注入。

    语言约束类反向提示（"不要切换成英文"）容易引出问题反而造成上下文混乱，已移除。
    """
    if not str(recent_history_text or "").strip() or is_long_silence:
        return ""
    if language == "en":
        # 长沉默（主动触发模式）下不注入，避免与 CONTEXT_GUARD_LONG_SILENCE 的"开启新话题"矛盾
        return CONTINUATION_GUARD_EN
    return CONTINUATION_GUARD_ZH


def _build_task_block_dynamic(
    sys_prompt_type: str,
    tod: str,
    user_input_mock: str,
    reminder_msg: Optional[str],
    thought: Optional[str],
    specific_instruction: Optional[str] = None,
) -> str:
    if sys_prompt_type == "reminder" and reminder_msg:
        return TASK_REMINDER_TEMPLATE.format(tod=tod, reminder_msg=reminder_msg)
    if sys_prompt_type == "planned_topic":
        thought_ctx = f"你的思考：{thought}\n" if thought else ""
        topic_text = (
            user_input_mock if user_input_mock != "[PLANNED_TRIGGER]" else "（根据你的思考自发开始）"
        )
        return TASK_PLANNED_TOPIC_TEMPLATE.format(tod=tod, thought_ctx=thought_ctx, topic_text=topic_text)
    if sys_prompt_type == "wake_up_greeting":
        heal_brief = _get_auto_heal_brief()
        return TASK_WAKE_UP_GREETING.format(tod=tod) + heal_brief
    if sys_prompt_type == "morning_report":
        heal_brief = _get_auto_heal_brief()
        return TASK_MORNING_REPORT.format(tod=tod) + heal_brief
    if sys_prompt_type == "notification_assistant":
        notification_content = user_input_mock.replace('[NOTIFICATION_TRIGGER]:', '').strip()
        return TASK_NOTIFICATION_ASSISTANT.format(tod=tod, notification_content=notification_content)
    if sys_prompt_type == "usage_limit_exceeded":
        event_context = str(specific_instruction or user_input_mock or "").strip()
        return TASK_USAGE_LIMIT_EXCEEDED_TEMPLATE.format(
            tod=tod,
            event_context=event_context,
        )
    if sys_prompt_type == "insomnia":
        return TASK_INSOMNIA.format(tod=tod)
    if sys_prompt_type == "goodnight_proactive":
        # 角色按作息时间准备睡觉时主动给用户发晚安消息
        return TASK_GOODNIGHT_PROACTIVE_TEMPLATE.format(tod=tod)
    if sys_prompt_type == "sleep_again_proactive":
        # 角色半夜被叫醒后跟用户聊了一会儿，决定睡回去时主动给用户发告别消息
        return TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE.format(tod=tod)
    if sys_prompt_type == "activity_return_proactive":
        # /打断 后聊天窗口即将结束，角色要回去做原来的任务
        return TASK_ACTIVITY_RETURN_PROACTIVE_TEMPLATE.format(tod=tod)
    if sys_prompt_type == "good_morning_proactive":
        # 角色刚起床时主动给用户发起床消息（按作息正常起床 / 熬夜后白天恢复清醒）
        # specific_instruction 包含时间感知的问候语要求（早/中/下午/晚不同问候），
        # 必须拼接进来，否则 LLM 只看到模板里的"早安"硬约束，下午 13:47 醒来也会发"早安"
        specific_ctx = f"{specific_instruction}\n" if specific_instruction else ""
        return TASK_GOOD_MORNING_PROACTIVE_TEMPLATE.format(tod=tod) + specific_ctx
    if sys_prompt_type == "share_peer_chat":
        thought_ctx = f"你的思考：{thought}\n" if thought else ""
        specific_ctx = f"{specific_instruction}\n" if specific_instruction else ""
        return TASK_PROACTIVE_CHAT_TEMPLATE.format(
            tod=tod, thought_ctx=thought_ctx, specific_ctx=specific_ctx,
        )
    if sys_prompt_type == "focus_nudge" and reminder_msg:
        # 专注番茄钟探班：文案由专注监控策略生成，直接作为陪伴消息，
        # 不让 LLM 改写措辞（避免不可控的确定性断言/羞辱）。
        return TASK_FOCUS_NUDGE_TEMPLATE.format(tod=tod, nudge_msg=reminder_msg)
    thought_ctx = f"你的思考：{thought}\n" if thought else ""
    # [FIX] 如果 thought 表达"不该发/稍后再说"的意思，
    # 说明决策阶段本意是不发但被代码覆盖了，
    # 此时应该要求延续当前话题而非另开新话题
    thought_lower = str(thought or "").lower()
    suppress_new_topic = any(
        kw in thought_lower
        for kw in ["稍后", "不应该", "不该", "打扰", "skip", "don't", "not now", "wait"]
    )
    specific_ctx = f"{specific_instruction}\n" if specific_instruction else ""
    if suppress_new_topic:
        return TASK_SUPPRESSED_CHAT_TEMPLATE.format(
            tod=tod, thought_ctx=thought_ctx, specific_ctx=specific_ctx,
        )
    return TASK_PROACTIVE_CHAT_TEMPLATE.format(
        tod=tod, thought_ctx=thought_ctx, specific_ctx=specific_ctx,
    )


def _build_temporal_anchor(
    now: float,
    last_sent_ts: float,
    last_user_ts: float,
) -> str:
    from core.agents.chat_agent_components.persona_system.prompt.components import _format_elapsed_human

    now_text = ""
    try:
        now_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(now)))
    except Exception:
        pass
    parts = []
    if now_text:
        parts.append(f"当前本地时间：{now_text}")
        parts.append("若不确定钟点，不要编造具体时分，所有时间必须与此锚点一致")
    if last_sent_ts > 0:
        elapsed_sent = int(max(0.0, now - last_sent_ts))
        parts.append(f"距你上次主动发消息：{_format_elapsed_human(elapsed_sent) if elapsed_sent > 0 else '未知'}")
    if last_user_ts > 0:
        elapsed_user = int(max(0.0, now - last_user_ts))
        parts.append(f"距他最近一条消息：{_format_elapsed_human(elapsed_user) if elapsed_user > 0 else '未知'}")
    if last_user_ts > 0 and (now - last_user_ts) > 1800:
        parts.append("他很久没说话了，先确认他是否在忙，别急着抛话题")
    if not parts:
        return ""
    return TEMPORAL_ANCHOR_TEMPLATE.format(anchor_lines="\n".join(f"- {p}" for p in parts))


def _build_dedup_constraint(
    last_proactive_assistant_message: str,
    last_assistant_message: str,
    repeat_anchors: Optional[List[str]] = None,
) -> str:
    from core.utils.debug_markers import is_debug_context_message
    candidate_anchors: List[str] = []
    for item in repeat_anchors or []:
        text = str(item or "").strip()
        if not text or is_debug_context_message(text) or "[DEBUG_ERROR]" in text:
            continue
        candidate_anchors.append(text)
        if len(candidate_anchors) >= 3:
            break
    if candidate_anchors:
        lines = []
        for idx, anchor_text in enumerate(candidate_anchors, start=1):
            clipped = anchor_text[:120] + "..." if len(anchor_text) > 120 else anchor_text
            lines.append(f"- 参考锚点{idx}：{clipped}")
        return DEDUP_MULTI_CONSTRAINT_TEMPLATE.format(anchor_lines="\n".join(lines))
    anchor = str(last_proactive_assistant_message or "").strip()
    label = "上一条主动消息"
    if not anchor or is_debug_context_message(anchor) or "[DEBUG_ERROR]" in anchor:
        anchor = str(last_assistant_message or "").strip()
        label = "最近一条助手消息"
    if not anchor or is_debug_context_message(anchor) or "[DEBUG_ERROR]" in anchor:
        return ""
    if len(anchor) > 180:
        anchor = anchor[:180] + "..."
    return DEDUP_CONSTRAINT_TEMPLATE.format(label=label, anchor=anchor)


def build_active_care_prompt(
    *,
    user_id: Optional[str] = None,
    sys_prompt_type: str,
    user_input_mock: str,
    reminder_msg: Optional[str],
    thought: Optional[str],
    tod: str,
    now: float,
    user_display_name: str,
    persona_prompt: str,
    recent_history_text: str,
    tone_reference_text: str = "",
    sleep_context_text: str = "",
    mode_status_text: str = "",
    goodnight_but_awake_context: str = "",
    preferred_language: str = "auto",
    device_context: Optional[Dict[str, Any]] = None,
    client_type: Optional[str] = None,
    elapsed_seconds: float = 0.0,
    persona_filename: str = "",
    persona_name: str = "",
    last_sent_ts: float = 0.0,
    last_user_ts: float = 0.0,
    last_proactive_assistant_message: str = "",
    last_assistant_message: str = "",
    proactive_state: Optional[Dict[str, Any]] = None,
    repeat_anchors: Optional[List[str]] = None,
    tomorrow_tone: str = "",
    specific_instruction: Optional[str] = None,
    role_activity_text: str = "",
) -> ActiveCarePromptBuildResult:
    _ = get_settings()
    device_context_text, is_mobile = _build_device_context_text(now, device_context, client_type)
    bio_context_text = _build_bio_context_text(user_id)
    food_context_text = _build_food_context_text()
    study_context_text = _build_study_context_text()
    language = str(preferred_language or "").strip().lower()

    is_long_silence = elapsed_seconds >= LONG_SILENCE_THRESHOLD_SECONDS
    context_guard = _build_context_guard(is_long_silence)
    continuation_guard = _build_continuation_guard(language, recent_history_text, is_long_silence)
    if sys_prompt_type == "usage_limit_exceeded":
        # 数字健康属于硬事件，不套普通聊天的“续聊/新话题”二选一约束。
        context_guard = ""
        continuation_guard = ""

    style_enforcement = STYLE_ENFORCEMENT_TEMPLATE

    voice_guide = VOICE_GUIDE

    active_care_guidelines = _build_persona_active_care_style(
        persona_prompt=persona_prompt,
        persona_filename=persona_filename,
        persona_name=persona_name,
    )
    if active_care_guidelines:
        style_enforcement += "\n" + active_care_guidelines + "\n"

    health_reminder_prompt = _build_health_reminder_prompt(sys_prompt_type)
    task_block_dynamic = _build_task_block_dynamic(
        sys_prompt_type, tod, user_input_mock, reminder_msg, thought,
        specific_instruction=specific_instruction,
    )

    include_bio_context = sys_prompt_type in {
        "bio_complaint", "user_health_reminder", "reminder", "morning_report",
    }
    include_study_context = sys_prompt_type in {
        "planned_topic", "curious_question", "share_peer_chat", "reminder", "morning_report",
    }

    combined_status_text = ""
    if str(mode_status_text or "").strip():
        combined_status_text = mode_status_text
    if str(sleep_context_text or "").strip():
        combined_status_text += sleep_context_text

    # 角色当前活动锚点：让 LLM 知道"我现在正在做什么"，
    # 从而生成"我正在做 X，突然想到你"这种自然消息
    role_activity_anchor = ""
    role_activity_text_str = str(role_activity_text or "").strip()
    if role_activity_text_str:
        # sleeping/napping 时由 sleep_policy 兜底，不注入活动锚点
        lowered = role_activity_text_str.lower()
        if not any(
            kw in lowered for kw in ("sleeping", "napping", "睡觉", "午休", "睡梦中")
        ):
            role_activity_anchor = ROLE_ACTIVITY_ANCHOR_TEMPLATE.format(
                role_activity_text=role_activity_text_str
            )

    temporal_anchor = _build_temporal_anchor(now, last_sent_ts, last_user_ts)
    dedup_constraint = _build_dedup_constraint(
        last_proactive_assistant_message,
        last_assistant_message,
        repeat_anchors=repeat_anchors,
    )
    topic_diversity = ""
    if proactive_state:
        candidate_text = str(last_proactive_assistant_message or last_assistant_message or "")
        topic_diversity = build_topic_diversity_constraint(proactive_state, candidate_text)

    # 【缓存优化】静态 sections —— 放 system message，跨请求稳定，可命中缓存
    static_sections = [
        PromptSection("persona_prompt", f"{persona_prompt}\n\n"),
        PromptSection("core_constraints", CORE_CONSTRAINTS),
        PromptSection("special_days", get_special_day_prompt()),
        PromptSection("upcoming_birthdays", get_upcoming_birthday_prompt()),
        PromptSection("style_enforcement", style_enforcement),
        PromptSection("tone_reference_text", tone_reference_text),
        PromptSection("voice_guide", voice_guide),
    ]

    # 【缓存优化】动态 sections —— 放 user message 前缀，每次请求都变
    dynamic_sections = [
        PromptSection("health_reminder_prompt", health_reminder_prompt),
        PromptSection("context_guard", context_guard),
        PromptSection("continuation_guard", continuation_guard),
        PromptSection("goodnight_but_awake_context", goodnight_but_awake_context),
        PromptSection("bio_context_text", bio_context_text if include_bio_context else ""),
        PromptSection("food_context_text", food_context_text if include_bio_context else ""),
        PromptSection("study_context_text", study_context_text if include_study_context else ""),
        PromptSection("combined_status_text", combined_status_text),
        PromptSection("device_context_text", device_context_text),
        PromptSection(
            "recent_history_text",
            "" if sys_prompt_type == "usage_limit_exceeded" else recent_history_text,
        ),
        PromptSection("task_block_dynamic", task_block_dynamic),
        PromptSection("role_activity_anchor", role_activity_anchor),
        PromptSection("temporal_anchor", temporal_anchor),
        PromptSection("dedup_constraint", dedup_constraint),
        PromptSection("topic_diversity", topic_diversity),
        PromptSection("authoritative_calendar", get_authoritative_calendar_prompt()),
    ]

    # 明日总基调注入（动态部分）
    tomorrow_tone_text = str(tomorrow_tone or "").strip()
    if tomorrow_tone_text:
        tone_section = TOMORROW_TONE_TEMPLATE.format(tomorrow_tone=tomorrow_tone_text)
        dynamic_sections.append(PromptSection("tomorrow_tone", tone_section))

    # 今日学习生活计划注入（动态部分）
    # 让 AI 在主动关怀时能参考今日计划，自然地提醒进度
    today_plan_text = _build_today_plan_text()
    if today_plan_text:
        plan_section = TODAY_PLAN_TEMPLATE.format(plan_text=today_plan_text)
        dynamic_sections.append(PromptSection("today_plan", plan_section))

    # 推迟提醒注入（用户睡觉期间跳过的计划提醒，醒来后统一汇报）
    if proactive_state:
        deferred_text = build_deferred_reminders_text(proactive_state)
        if deferred_text:
            deferred_section = DEFERRED_REMINDERS_TEMPLATE.format(deferred_text=deferred_text)
            dynamic_sections.append(PromptSection("deferred_reminders", deferred_section))

    # 跨 persona 提醒分工注入：让 LLM 知道另一角色今天已经发过什么提醒
    other_persona_reminders_text = _build_other_persona_reminders_text(persona_filename)
    if other_persona_reminders_text:
        dynamic_sections.append(PromptSection("other_persona_reminders", other_persona_reminders_text))

    all_sections = static_sections + dynamic_sections

    # 静态 prompt → system message
    static_prompt = "".join(s.content for s in static_sections if (s.content or "").strip()).strip()

    # 动态 prompt → user message 前缀
    dynamic_prompt = "".join(s.content for s in dynamic_sections if (s.content or "").strip()).strip()

    # 检查是否包含推迟提醒
    has_deferred = any(s.name == "deferred_reminders" for s in dynamic_sections if (s.content or "").strip())

    return ActiveCarePromptBuildResult(
        prompt=static_prompt,
        sections=all_sections,
        dynamic_prompt=dynamic_prompt,
        has_deferred_reminders=has_deferred,
    )
