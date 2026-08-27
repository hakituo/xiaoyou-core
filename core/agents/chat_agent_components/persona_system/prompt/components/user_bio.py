"""
用户生物/生活画像上下文组件
"""
from typing import Optional


def _build_user_status_and_daily(user_id: Optional[str] = None) -> str:
    """
    获取用户持续性状态 + 今日日程摘要（供多个场景复用）
    """
    txt = ""
    try:
        from core.services.workspace.status_manager import get_user_status_manager

        status_summary = get_user_status_manager().get_status_summary()
        if status_summary and "当前无特殊状态" not in status_summary:
            txt += f"\n【用户当前状态】\n{status_summary}\n"
    except Exception:
        pass
    try:
        from core.services.daily.manager import get_daily_manager

        daily_sum = get_daily_manager().get_today_summary(user_id)
        if daily_sum:
            known_sleep_time = _extract_known_sleep_time_fact(daily_sum)
            txt += f"\n【今日日程摘要】\n{daily_sum}\n"
            if known_sleep_time:
                txt += (
                    f"【睡眠事实锚点】已知昨晚睡觉时间：{known_sleep_time}\n"
                    "禁止编造睡眠时间/时长，禁止追问\"昨晚几点睡\"，禁止问\"现在困吗\"。\n"
                )
    except Exception:
        pass
    return txt


def build_bio_context_for_active_care(user_id: Optional[str] = None) -> str:
    """
    构建 Active Care 场景下的仿生体 + 用户状态上下文

    整合了原 active_care/prompt_builder.py 中 _build_bio_context_text 的全部逻辑，
    包括：仿生体硬件状态、用户生理数据、用户当前状态、今日日程摘要、睡眠事实锚点。

    Args:
        user_id: 用户 ID

    Returns:
        完整的仿生体+用户状态上下文字符串
    """
    txt = ""
    try:
        from core.services.life_simulation.service import get_life_simulation_service
        sim_service = get_life_simulation_service()
        st = sim_service.get_state() if sim_service else {}
        hardware_stats = st.get("hardware", {}) if isinstance(st, dict) else {}
        cpu_usage = hardware_stats.get("cpu_percent", 0)
        mem_usage = hardware_stats.get("memory_percent", 0)
        txt += (
            "【你的底层状态】\n"
            f"- CPU负载(心跳)：{cpu_usage}%，内存占用(脑压)：{mem_usage}%\n"
            "（如果数值异常，你可以抱怨身体不舒服。）\n"
        )
    except Exception:
        pass
    # 优先从 daily_record 读取睡眠数据（由晚安/早安自动提取，实时可靠）
    # user_physiology 只提供心率/血氧/压力等安卓端实时生理指标
    try:
        from core.services.active_care.decision.context_gatherer import _parse_sleep_duration_from_daily_record
        daily_sleep_h = _parse_sleep_duration_from_daily_record()
    except Exception:
        daily_sleep_h = None

    try:
        from core.services.user_physiology.service import get_user_physiology_service

        effective_user_id = str(user_id or "default_user").strip() or "default_user"
        rec = get_user_physiology_service().get_latest(effective_user_id)
        source = str((rec or {}).get("source") or "").strip().lower()
        is_test_source = source in {"tests", "test", "diagnostics", "debug"}
        if isinstance(rec, dict) and not rec.get("is_stale") and not is_test_source:
            metrics = rec.get("metrics") or {}
            parts = []
            if metrics.get("heart_rate_bpm") is not None:
                parts.append(f"心率={metrics.get('heart_rate_bpm')}")
            if metrics.get("spo2_percent") is not None:
                parts.append(f"血氧={metrics.get('spo2_percent')}")
            # 睡眠数据：优先用 daily_record（来源可靠），user_physiology 的仅作回退
            if daily_sleep_h is not None:
                parts.append(f"睡眠={daily_sleep_h:.1f}h(daily_record)")
            elif metrics.get("sleep_hours_last_night") is not None:
                parts.append(f"睡眠={metrics.get('sleep_hours_last_night')}h")
            if metrics.get("stress_level") is not None:
                parts.append(f"压力={metrics.get('stress_level')}")
            if parts:
                source = str(rec.get("source") or "未知设备")
                txt += (
                    f"\n【用户生理数据（{source}）】"
                    + " ".join(parts)
                    + "。★若心率过高/睡眠不足/压力大，必须立刻提醒休息。\n"
                )
    except Exception:
        pass
    # 若 user_physiology 无有效记录，但 daily_record 有睡眠数据，单独输出
    if daily_sleep_h is not None:
        has_physio_block = "【用户生理数据" in txt
        if not has_physio_block:
            txt += f"\n【用户生理数据（daily_record）】睡眠={daily_sleep_h:.1f}h。★若睡眠不足，必须提醒休息。\n"
    # 复用通用的用户状态 + 日程获取
    txt += _build_user_status_and_daily(user_id)
    return txt


def _extract_known_sleep_time_fact(summary_text: str) -> str:
    """
    从日程摘要文本中提取已知的睡觉时间
    """
    import re as _re
    raw = str(summary_text or "").strip()
    if not raw:
        return ""
    m = _re.search(r"(?:昨晚睡觉|睡觉)\s*[:：]\s*([01]?\d|2[0-3])[:：]([0-5]\d)", raw)
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def build_user_bio_context_for_chat(user_id: Optional[str] = None) -> str:
    """
    构建普通聊天场景下的用户生活画像上下文

    将 DailyActivityManager（每日生活画像：吃饭/睡觉/学习/心情）
    和 UserStatusManager（持续性状态：生病/考试周等跨天状态）
    注入到普通聊天的 prompt 中，让小优在日常对话时也能感知用户的作息和状态。

    之前这些数据只在 Active Care 中使用，普通聊天只有简陋的 PersistentStateTracker，
    导致小优在普通聊天时完全不知道用户今天吃了什么、几点起的、是不是还在生病。

    Args:
        user_id: 用户 ID

    Returns:
        用户生活画像上下文字符串
    """
    return _build_user_status_and_daily(user_id).strip()


def build_study_context_for_active_care() -> str:
    """
    构建 Active Care 场景下的学习状态上下文

    整合 TutorEngine（学生画像 + 薄弱点 + 间隔复习 + streak）和词汇管理器数据，
    以 Aveline 可自然融入对话的方式呈现，而非系统通知。

    Returns:
        学习状态上下文字符串（注入到 Active Care 决策 prompt）
    """
    parts: list[str] = []

    # ── 1. TutorEngine 结构化学习数据 ──
    try:
        from core.services.study.tutor_engine import get_tutor_engine
        engine = get_tutor_engine()
        briefing = engine.generate_daily_briefing()
        streak_info = briefing.get("streak_info") or {}
        current_streak = streak_info.get("current_streak", 0)
        longest_streak = streak_info.get("longest_streak", 0)
        encouragement = briefing.get("encouragement", "")

        # — streak —
        if current_streak > 0:
            parts.append(f"学习连续打卡：{current_streak}天（历史最长{longest_streak}天）")

        # — 昨日回顾 —
        yday = briefing.get("yesterday_review") or {}
        if yday.get("studied"):
            subjects_text = "、".join(yday.get("subjects", [])) or "未记录科目"
            mastered_n = yday.get("topics_mastered", 0)
            parts.append(f"昨天学了{yday.get('total_minutes', 0)}分钟（{subjects_text}）")
            if mastered_n > 0:
                parts.append(f"昨天掌握了{mastered_n}个知识点")
            struggles = yday.get("struggles") or []
            if struggles:
                s = struggles[0]
                parts.append(f"昨天在{s.get('subject', '')}的{s.get('topic', '')}上遇到了困难")
        elif current_streak == 0:
            parts.append("昨天没有学习")

        # — 间隔复习到期 —
        reviews = briefing.get("review_reminders") or []
        if reviews:
            due_lines = []
            for r in reviews[:5]:
                subj = r.get("subject", "")
                topic = r.get("topic", "")
                conf = r.get("confidence", 5)
                due_lines.append(f"{subj}·{topic}（掌握度{conf:.0f}/10）")
            parts.append(f"今天有{len(reviews)}个知识点该复习了：" + "；".join(due_lines))

        # — 今日计划 —
        plan = briefing.get("today_plan") or {}
        plan_items = plan.get("items") or []
        if plan_items:
            plan_lines = []
            for item in plan_items[:3]:
                title = item.get("title", "")
                mins = item.get("duration_minutes", 0)
                plan_lines.append(f"{title}（约{mins}分钟）")
            parts.append("今日建议计划：" + " → ".join(plan_lines))

        # — 鼓励语 —
        if encouragement:
            parts.append(f"鼓励方向：{encouragement}")

    except Exception:
        pass

    # ── 2. 英语词汇实时状态 ──
    try:
        from core.tools.study.english.vocabulary_manager import get_vocabulary_manager
        vm = get_vocabulary_manager()
        if vm:
            status = vm.get_today_review_status()
            reviewed_count = int(status.get("reviewed_words") or 0)
            remaining_count = int(status.get("remaining_words") or 0)
            unresolved_count = int(status.get("unresolved_words") or 0)
            new_learned = int(status.get("new_words") or 0)
            if status.get("completed"):
                completion_text = (
                    "英语单词今日任务已明确完成："
                    f"已复习{reviewed_count}个（新学{new_learned}）"
                )
                if remaining_count > 0:
                    completion_text += (
                        f"；会话结束后动态调度队列当前显示{remaining_count}个，"
                        "这不代表原任务没做完，禁止据此继续催促"
                    )
                else:
                    completion_text += "，当前待复习0个"
                completion_text += f"；最终有{unresolved_count}个未掌握词留到明天"
                parts.append(completion_text)
            elif reviewed_count > 0:
                parts.append(
                    f"英语单词今日已复习{reviewed_count}个（新学{new_learned}），"
                    f"当前还剩{remaining_count}个待复习"
                )
            elif remaining_count > 0:
                parts.append(f"英语单词今日尚未开始，当前待复习{remaining_count}个")
            else:
                parts.append("英语单词今天当前没有待复习任务")
    except Exception:
        pass

    if not parts:
        return ""

    text = "\n【你了解他的学习状态】（自然融入关心，不要照读数据）\n"
    for p in parts:
        text += f"- {p}\n"
    text += (
        "★ 以上是你作为陪伴者自然知道的信息。"
        "其中‘已完成/当前待复习/未掌握词’是实时权威事实，优先于昨日日记和聊天历史；"
        "如果显示已完成，禁止再追问背完没有、催促继续背或沿用旧数量。"
        "用你自己的语气和方式关心他，比如温和提起复习、鼓励坚持、或关心是不是太累了。"
        "绝对不要像系统通知一样列数据。\n"
    )
    return text
