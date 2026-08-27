"""验证角色日程生成的差异化：Aveline 和Ling的 prompt 应有明显差异

覆盖场景：
1. build_role_personality_section 返回非空，含性格 + 活动偏好
2. 两个角色的 personality section 内容不同
3. user prompt 模板 format 后，两个角色的 prompt 包含不同的活动偏好关键词
4. system prompt 包含"差异化"原则

运行方式（venv_core）：
    venv_core\\Scripts\\python.exe -m pytest tests/character_daily/test_schedule_differentiation.py -v
"""

from core.agents.chat_agent_components.persona_system.prompt.components.character_schedule_prompts import (
    CHARACTER_SCHEDULE_SYSTEM_PROMPT,
    CHARACTER_SCHEDULE_USER_PROMPT_TEMPLATE,
    build_role_personality_section,
    build_rest_day_guidance,
    build_template_summary,
    build_yesterday_summary,
)


# =====================================================================
# 1. build_role_personality_section 基本功能
# =====================================================================


def test_aveline_personality_section_contains_personality():
    """Aveline 的 personality section 应包含性格描述"""
    section = build_role_personality_section("aveline")
    assert section, "aveline 的 personality section 不应为空"
    # 性格关键词（来自 personas.py）
    assert "外冷内热" in section or "独立" in section or "有条理" in section


def test_ling_personality_section_contains_personality():
    """Ling的 personality section 应包含性格描述"""
    section = build_role_personality_section("ling")
    assert section, "ling 的 personality section 不应为空"
    # 性格关键词（来自 personas.py）
    assert "内向" in section or "小迷糊" in section


def test_aveline_personality_contains_activity_preference():
    """Aveline 的 section 应包含活动偏好（爱看书/学习）"""
    section = build_role_personality_section("aveline")
    assert "看书和学习" in section
    assert "gardening" in section  # 浇花
    assert "较少 phone_scrolling" in section  # 较少刷手机


def test_ling_personality_contains_activity_preference():
    """Ling的 section 应包含活动偏好（爱刷手机/看番）"""
    section = build_role_personality_section("ling")
    assert "刷手机看番" in section
    assert "walking" in section  # 散步
    assert "studying 时间较短" in section  # 学习时间短


def test_unknown_role_returns_empty():
    """未知角色应返回空字符串（不报错）"""
    section = build_role_personality_section("unknown_role")
    assert section == ""


# =====================================================================
# 2. 两个角色的差异化验证
# =====================================================================


def test_two_roles_personality_sections_are_different():
    """Aveline 和Ling的 personality section 必须不同"""
    aveline_section = build_role_personality_section("aveline")
    ling_section = build_role_personality_section("ling")
    assert aveline_section != ling_section, "两个角色的 personality section 不应完全相同"


def test_aveline_has_more_studying_ling_has_more_phone():
    """Aveline 偏学习，Ling偏刷手机——prompt 应体现这种差异"""
    aveline_section = build_role_personality_section("aveline")
    ling_section = build_role_personality_section("ling")
    # Aveline 强调学习，Ling强调刷手机
    assert "学习" in aveline_section
    assert "刷手机" in ling_section
    # 反向验证：Aveline 较少刷手机，Ling学习时间短
    assert "较少 phone_scrolling" in aveline_section
    assert "studying 时间较短" in ling_section


# =====================================================================
# 3. user prompt 模板 format 后的差异化
# =====================================================================


def _build_full_user_prompt(role_id: str, role_name: str) -> str:
    """构建完整 user prompt 用于对比（mock 模板和状态）"""
    # mock template_summary 和 yesterday_summary
    template_summary = "起床 07:00，睡觉 23:00\n  morning: 07:00-12:00"
    yesterday_summary = "（无昨日记录）"
    recent_status = "（无近期记录）"

    return CHARACTER_SCHEDULE_USER_PROMPT_TEMPLATE.format(
        role_name=role_name,
        role_id=role_id,
        plan_date_str="2026-06-27",
        weekday_cn="周六",
        wake_time="07:00",
        sleep_time="23:00",
        role_personality=build_role_personality_section(role_id),
        rest_day_guidance=build_rest_day_guidance(__import__("datetime").datetime(2026, 6, 27)),
        template_summary=template_summary,
        yesterday_summary=yesterday_summary,
        recent_status=recent_status,
        user_plan_context="",
    )


def test_aveline_user_prompt_contains_activity_preference():
    """Aveline 的完整 user prompt 应包含活动偏好关键词"""
    prompt = _build_full_user_prompt("aveline", "七濑澪")
    assert "看书和学习" in prompt
    assert "gardening" in prompt
    assert "较少 phone_scrolling" in prompt


def test_ling_user_prompt_contains_activity_preference():
    """Ling的完整 user prompt 应包含活动偏好关键词"""
    prompt = _build_full_user_prompt("ling", "Ling")
    assert "刷手机看番" in prompt
    assert "walking" in prompt
    assert "studying 时间较短" in prompt


def test_two_roles_full_prompts_are_different():
    """两个角色的完整 user prompt 必须不同"""
    aveline_prompt = _build_full_user_prompt("aveline", "七濑澪")
    ling_prompt = _build_full_user_prompt("ling", "Ling")
    assert aveline_prompt != ling_prompt


def test_aveline_prompt_has_studying_emphasis_ling_does_not():
    """Aveline 的 prompt 强调长时间学习，Ling的 prompt 强调短时间学习"""
    aveline_prompt = _build_full_user_prompt("aveline", "七濑澪")
    ling_prompt = _build_full_user_prompt("ling", "Ling")
    # Aveline: "长时间的 studying"
    assert "长时间的 studying" in aveline_prompt
    # Ling: "studying 时间较短"
    assert "studying 时间较短" in ling_prompt
    # 反向验证：Aveline 的 prompt 不应包含"studying 时间较短"
    assert "studying 时间较短" not in aveline_prompt
    # Ling的 prompt 不应包含"长时间的 studying"
    assert "长时间的 studying" not in ling_prompt


# =====================================================================
# 4. system prompt 包含差异化原则
# =====================================================================


def test_system_prompt_contains_differentiation_principle():
    """system prompt 应明确要求根据角色性格差异化安排"""
    assert "差异化" in CHARACTER_SCHEDULE_SYSTEM_PROMPT
    assert "角色性格" in CHARACTER_SCHEDULE_SYSTEM_PROMPT
    assert "活动偏好" in CHARACTER_SCHEDULE_SYSTEM_PROMPT


def test_system_prompt_mentions_activity_examples():
    """system prompt 应给出差异化示例"""
    # 提到"爱学习的角色"和"爱放松的角色"作为示例
    assert "爱学习" in CHARACTER_SCHEDULE_SYSTEM_PROMPT
    assert "爱放松" in CHARACTER_SCHEDULE_SYSTEM_PROMPT
    assert "phone_scrolling" in CHARACTER_SCHEDULE_SYSTEM_PROMPT


def test_user_prompt_template_has_role_personality_placeholder():
    """user prompt 模板应包含 {role_personality} 占位符"""
    assert "{role_personality}" in CHARACTER_SCHEDULE_USER_PROMPT_TEMPLATE
