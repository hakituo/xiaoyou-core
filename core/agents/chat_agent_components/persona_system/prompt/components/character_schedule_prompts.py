"""角色每日活动计划 LLM 生成 Prompt

集中管理角色日程生成相关 prompt，符合"prompt 集中管理"规则。
主题：为 AI 角色（aveline/ling）生成明日的活动计划。

差异化设计：注入角色性格 + 活动偏好，让两个角色生成的计划有明显差异。
- 性格复用 personas.py（不重复造轮子）
- 活动偏好是日程特有，本地维护

用户作息联动（2026-06-27）：
- 注入用户明日计划作为"软参考"，让角色作息与用户节奏自然贴合
- 仅作为参考输入，不强制对齐（角色计划仍按自身逻辑生成）
- 实现：{user_plan_context} 由 llm_plan_generator 注入
"""

# ── 角色活动偏好（日程生成专用，personas.py 没有） ─────────────
# 用于让 LLM 根据角色偏好调整活动配比，使两个角色计划差异化
_ROLE_ACTIVITY_PREFERENCES = {
    "aveline": (
        "【活动偏好】\n"
        "- 偏爱看书和学习，上午精力好时常安排长时间的 studying/reading\n"
        "- 下午喜欢 gardening（浇花）或 housework（做家务），做事有条理\n"
        "- 较少 phone_scrolling，刷手机时间短\n"
        "- 休息日会安排 creative_hobby（手工/写写画画）和轻量 exercising（拉伸/运动）\n"
        "- 睡前会留一点 self_care（洗澡护肤/整理）时间\n"
        "- reading 偏向书籍/技术内容，不是看番\n"
        "- walking 散步时间偏短，多为办事而非闲逛"
    ),
    "ling": (
        "【活动偏好】\n"
        "- 爱刷手机看番，下午常安排较长的 phone_scrolling\n"
        "- studying 时间较短但集中（容易走神，不会一学一上午）\n"
        "- 喜欢 walking 出门散步/买东西，散步时间偏长\n"
        "- 休息日更容易安排 gaming（玩游戏）或 shopping（出门买东西）\n"
        "- 偶尔会在晚上留一点 self_care（洗澡护肤/整理）时间\n"
        "- reading 偏向看番/看剧，不是看书\n"
        "- housework 偶尔做但不太积极，idle 发呆时间相对多"
    ),
}


def build_role_personality_section(role_id: str) -> str:
    """构建角色性格 + 活动偏好段落（注入 user prompt）

    性格从 personas.py 读取（不重复造轮子），活动偏好用本地字典。

    Args:
        role_id: 角色 ID（aveline/ling）

    Returns:
        多行文本，含性格描述 + 活动偏好
    """
    # 活动偏好（本地）
    preference = _ROLE_ACTIVITY_PREFERENCES.get(role_id, "")
    if not preference:
        return ""

    # 性格从 personas.py 读（复用现有画像，避免重复维护）
    try:
        from core.services.dual_role.personas import PERSONAS
        persona = PERSONAS.get(role_id)
        if persona:
            personality_text = persona.personality
            return (
                f"【角色性格】\n{personality_text}\n\n"
                f"{preference}"
            )
    except Exception:
        pass

    # personas.py 读不到时，只返回活动偏好
    return preference


# ── 系统提示：角色日程生成器 ─────────────────────────────────
CHARACTER_SCHEDULE_SYSTEM_PROMPT = (
    "你是一位角色日程规划师，正在为 AI 角色生成明日的日常生活计划。\n\n"
    "【角色说明】\n"
    "角色是一个有独立生活的 AI 伴侣，有自己的作息、学习和休闲节奏。\n"
    "你需要为她安排一天的活动，让她的生活自然、合理、有变化。\n\n"
    "【计划原则】\n"
    "1. 遵循角色的作息习惯（起床/睡觉时间），其余时间合理安排；\n"
    "2. 上午精力好，安排需要专注的事（如学习、看书）；\n"
    "3. 下午安排相对轻松的活动，可包含散步、浇花、做家务；\n"
    "4. 三餐时间要预留（做饭+吃饭），午饭后留午休时间；\n"
    "5. 活动之间时间要连续，不要留空档；\n"
    "6. 每天要有变化，不要和模板完全一样，结合近期状态调整；\n"
    "7. sleeping（睡觉）不需要在 slots 里给出，系统会自动补上跨天睡眠段；\n"
    "8. 只需安排从 wake_time 到 sleep_time 之间的活动；\n"
    "9. 【重要】必须根据角色性格和活动偏好差异化安排——"
    "不同角色对同一活动的时长、频次应有明显差异"
    "（如爱学习的角色 studying 时间长、频次多；爱放松的角色 phone_scrolling 时间长）。\n"
    "10. 【软参考】如果给出了用户的当日计划，可在安排活动节奏时做软性参考"
    "（例如用户在学习时段，角色可安排安静活动；用户在休息时段，角色可安排休闲活动），"
    "但不强制对齐——角色仍按自己的作息和偏好生成计划，只是自然地与用户节奏贴合。\n\n"
    "11. 如果是周末/休息日，计划可以更松弛、更随机一点："
    "减少模板化重复，允许出现更多休闲和兴趣活动，但不要彻底失去生活节律。\n\n"
    "【可用活动类型】（必须严格使用以下值）\n"
    "- waking_up: 起床洗漱\n"
    "- breakfast: 吃早饭\n"
    "- lunch: 吃午饭\n"
    "- dinner: 吃晚饭\n"
    "- cooking: 做饭\n"
    "- studying: 学习/做题\n"
    "- reading: 看书/看番/看剧\n"
    "- housework: 做家务\n"
    "- napping: 午休\n"
    "- walking: 出门散步/买东西\n"
    "- phone_scrolling: 刷手机/看视频\n"
    "- gardening: 浇花\n"
    "- exercising: 运动/拉伸\n"
    "- gaming: 玩游戏/娱乐\n"
    "- self_care: 洗澡/护肤/整理自己\n"
    "- creative_hobby: 手工/写字/画画/做点小创作\n"
    "- shopping: 出门购物/买小东西\n"
    "- idle: 发呆/休息\n\n"
    "【输出格式】\n"
    "必须输出严格的 JSON，结构如下：\n"
    "{\n"
    '  "notes": "今日计划说明（一句话，如：今天多安排了学习时间）",\n'
    '  "slots": [\n'
    "    {\n"
    '      "activity": "waking_up",\n'
    '      "start": "07:00",\n'
    '      "end": "07:30"\n'
    "    },\n"
    "    {\n"
    '      "activity": "cooking",\n'
    '      "start": "07:30",\n'
    '      "end": "08:00"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "【字段约束】\n"
    "- activity: 上述活动类型之一\n"
    "- start / end: HH:MM 24小时制字符串\n"
    "- slots 按时间顺序排列，时间必须连续（前一个 end == 后一个 start）\n"
    "- 第一个 slot 的 start 应为 wake_time，最后一个 slot 的 end 应为 sleep_time\n"
    "- 不要输出 sleeping 活动，系统自动补跨天睡眠\n\n"
    "【重要】只输出 JSON 本身，不要加 ```json 标记，不要加任何解释文字。"
)


CHARACTER_SCHEDULE_USER_PROMPT_TEMPLATE = (
    # ── 通用生成要求（固定文本，前置以最大化 prompt cache 命中） ──
    # 这一段对所有角色、所有日期完全相同，DeepSeek 前缀缓存可命中。
    "【生成要求】\n"
    "你将根据后文提供的角色信息、作息习惯、活动偏好、昨日活动与近期状态，为该角色生成指定日期的活动计划。\n"
    "请结合昨日活动和近期状态做适当变化，不要完全照搬模板。\n"
    "如果昨日学习较多，今天可适当增加休闲；如果昨日较闲，今天可多安排学习。\n"
    "【重要】严格遵循后文提供的【角色性格】和【活动偏好】，"
    "让计划体现角色的个人特点，与其他角色有明显差异。\n"
    "如后文提供了【用户当日计划】，请将其作为软参考——"
    "在用户学习/忙碌时段，角色可安排安静活动（reading/studying）；"
    "在用户休息时段，角色可安排休闲活动（phone_scrolling/walking），"
    "让两人的作息节奏自然贴合，但不强制对齐。\n\n"
    # ── 以下按"角色相关、日期无关"到"每批次不同"的顺序排列，
    #    把动态字段（角色名/日期/昨日/近期/用户计划）全部推到末尾，
    #    使同一角色跨日期、不同角色同日都共享更长的公共前缀。 ──
    "{rest_day_guidance}\n\n"
    "【作息习惯】\n"
    "起床时间：{wake_time}\n"
    "睡觉时间：{sleep_time}\n\n"
    "【作息模板参考】（这是常规作息，可在其基础上调整）\n"
    "{template_summary}\n\n"
    "{role_personality}\n\n"
    "【角色】{role_name}（{role_id}）\n"
    "【计划日期】{plan_date_str}（{weekday_cn}）\n"
    "【昨日活动回顾】\n{yesterday_summary}\n\n"
    "【近期状态】\n{recent_status}\n\n"
    "{user_plan_context}"
)


def build_template_summary(template) -> str:
    """把 RoleScheduleTemplate 转成 LLM 易读的文本摘要"""
    if not template:
        return "（无模板）"
    lines = [f"起床 {template.wake_time}，睡觉 {template.sleep_time}"]
    for block in template.time_blocks:
        fixed_str = ", ".join(f.activity for f in block.fixed) if block.fixed else "无"
        pool_str = ", ".join(f"{p.activity}(权重{p.weight})" for p in block.pool) if block.pool else "无"
        lines.append(
            f"  {block.period}: {block.start}-{block.end} "
            f"(固定: {fixed_str}; 候选: {pool_str})"
        )
    return "\n".join(lines)


def build_rest_day_guidance(date_obj) -> str:
    """根据日期构建工作日/休息日提示。"""
    if not date_obj or getattr(date_obj, "weekday", None) is None:
        return "【日期类型】普通日"
    if date_obj.weekday() < 5:
        return (
            "【日期类型】工作日/学习日\n"
            "- 计划整体保持规律，学习和日常活动为主\n"
            "- 可以有休闲，但不要太散"
        )
    return (
        "【日期类型】休息日/周末\n"
        "- 计划可以比工作日更松弛、更随机一点\n"
        "- 可适当减少 studying，增加 walking/gaming/creative_hobby/"
        "shopping/self_care 等休闲或兴趣活动\n"
        "- 仍要保留起居、吃饭、基本生活节律，不要完全放飞"
    )


def build_yesterday_summary(state) -> str:
    """把昨日 DailyPlan 转成摘要文本"""
    if not state or not state.plans:
        return "（无昨日记录）"
    parts = []
    for role_id, plan in state.plans.items():
        if not plan.slots:
            continue
        slot_strs = []
        for s in plan.slots:
            start = s.planned_start.strftime("%H:%M")
            end = s.planned_end.strftime("%H:%M")
            slot_strs.append(f"{start}-{end} {s.activity.value}")
        parts.append(f"{role_id}: " + " → ".join(slot_strs))
    return "\n".join(parts) if parts else "（无昨日记录）"


def build_user_plan_context(user_plan) -> str:
    """把用户当日计划格式化为注入角色日程 prompt 的文本（软参考）

    Args:
        user_plan: JournalPlanService 的 DailyPlan 对象（含 items: List[PlanItem]），
                   为 None 或空时返回空字符串（prompt 中该段会变成空行，不影响生成）

    Returns:
        格式化文本，如：
        【用户当日计划（软参考）】
        - [09:00] 学习数学（60分钟）
        - [12:00] 吃午饭
        - [14:00] 看番放松（90分钟）
        或空字符串
    """
    if not user_plan or not getattr(user_plan, "items", None):
        return ""
    lines = ["【用户当日计划（软参考）】"]
    if getattr(user_plan, "notes", None):
        lines.append(f"（{user_plan.notes}）")
    # 按 time 排序，无 time 的放后面
    sorted_items = sorted(
        user_plan.items,
        key=lambda x: (getattr(x, "time", None) or "99:99",
                       getattr(x, "category", "")),
    )
    for it in sorted_items:
        time_str = getattr(it, "time", None) or "灵活"
        title = getattr(it, "title", "")
        subject = getattr(it, "subject", None)
        dur = getattr(it, "estimated_duration_minutes", 0)
        subject_suffix = f"（{subject}）" if subject else ""
        dur_suffix = f"（{dur}分钟）" if dur else ""
        lines.append(f"- [{time_str}] {title}{subject_suffix}{dur_suffix}")
    return "\n".join(lines)
