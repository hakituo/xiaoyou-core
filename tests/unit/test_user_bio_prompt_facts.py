from unittest.mock import MagicMock, patch

from core.agents.chat_agent_components.persona_system.prompt.components.user_bio import (
    _extract_known_sleep_time_fact,
    build_user_bio_context_for_chat,
)


def test_chat_sleep_anchor_is_fact_only():
    status_manager = MagicMock()
    status_manager.get_status_summary.return_value = "当前无特殊状态"

    daily_manager = MagicMock()
    daily_manager.get_today_summary.return_value = (
        "昨晚睡觉：01:23\n"
        "今天起床：08:10"
    )

    with patch(
        "core.services.workspace.status_manager.get_user_status_manager",
        return_value=status_manager,
    ), patch(
        "core.services.daily.manager.get_daily_manager",
        return_value=daily_manager,
    ):
        text = build_user_bio_context_for_chat("test-user")

    assert "【用户睡眠事实锚点】" in text
    assert "last_night_bedtime=01:23" in text
    for coaching in ("禁止追问", "禁止问", "现在困吗", "必须"):
        assert coaching not in text


def test_sleep_anchor_supports_current_portrait_wording():
    """锚点正则必须认当前文案，且不被规律值/设备实测行冒充。

    2026-09-18：日记录 sleep+wakeup 齐全时渲染成「用户睡眠: HH:MM → HH:MM」，
    旧正则只认「睡觉」，锚点长期抽不出来（等于这条护栏从不生效）。
    """
    assert _extract_known_sleep_time_fact("- 用户睡眠: 13:10 → 01:19 (12h9m)") == "13:10"
    assert _extract_known_sleep_time_fact("- 用户睡眠: 13:10") == "13:10"
    assert _extract_known_sleep_time_fact("- 用户昨晚睡觉: 23:30") == "23:30"
    # 作息中位数不能冒充当天就寝事实
    assert _extract_known_sleep_time_fact("用户通常入睡: 23:30（23:00~00:30）") == ""
    # 设备实测行可能带往期日期，也不能当「昨晚」锚点
    assert (
        _extract_known_sleep_time_fact(
            "- 用户睡眠（三星健康实测，优先于聊天推断）: 09-17 13:11 → 19:10（5h59m）"
        )
        == ""
    )
